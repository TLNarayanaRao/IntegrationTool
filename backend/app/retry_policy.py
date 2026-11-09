"""Bounded activity retries shared by Studio and both Python exporters."""
import math
import random


class RetryConfigurationError(ValueError):
    fault_type = 'RetryConfigurationError'


def retry_boolean(value):
    return value if isinstance(value, bool) else str(value).strip().lower() in ('true', '1', 'yes', 'on')


def outbound_activity(kind, operation=''):
    if kind in ('http', 'jdbc', 'snowflake', 'ftp', 'sftp'): return True
    operations = {
        'amqp': {'send', 'get', 'dead_letter'},
        'ems': {'send', 'publish', 'request_reply', 'reply'},
        'jms': {'send_message', 'get_queue_message', 'request_reply', 'reply_message'},
        'kafka': {'publish', 'send', 'get'}, 'pubsub': {'publish'},
        'rest': {'invoke'}, 'soap': {'request_reply'},
        'sap': {'idoc_acknowledgment', 'idoc_confirmation', 'post_idoc', 'invoke_rfc_bapi', 'reply_rfc_bapi', 'read_table'},
    }
    return operation in operations.get(kind, ())


class RetryPlan:
    def __init__(self, outbound, advanced, policy):
        self.count = 0
        self.interval = 0
        self.maximum = 300
        self.elapsed_limit = 0
        self.backoff = 'fixed'
        self.jitter = False
        self.faults = set()
        enabled = outbound and retry_boolean(advanced.get('retryEnabled', False))
        if policy.get('action') == 'retry':
            settings = policy
            self.count = self.number(settings, 'retryCount', 0, 0, 100, integer=True)
            self.interval = self.number(settings, 'retryDelay', 0, 0, 86400000) / 1000
        elif enabled:
            settings = advanced
            self.count = self.number(settings, 'retryCount', 3, 0, 100, integer=True)
            self.interval = self.number(settings, 'retryIntervalSeconds', 60, 0, 86400)
        else:
            return
        self.backoff = str(settings.get('retryBackoff') or 'fixed')
        if self.backoff not in ('fixed', 'exponential'):
            raise RetryConfigurationError('Retry backoff must be fixed or exponential')
        # Existing fixed-interval configurations retain their original interval.
        self.maximum = self.number(settings, 'retryMaxIntervalSeconds', max(300, self.interval), 0, 86400)
        self.elapsed_limit = self.number(settings, 'retryMaxElapsedSeconds', 0, 0, 604800)
        self.jitter = retry_boolean(settings.get('retryJitter', False))
        names = settings.get('retryFaultTypes') or []
        if isinstance(names, str): names = names.replace(',', ' ').split()
        if not isinstance(names, (list, tuple)) or len(names) > 100 or any(not isinstance(name, str) or len(name) > 200 for name in names):
            raise RetryConfigurationError('Retry fault types must be a list or comma-separated names')
        self.faults = {name.strip() for name in names if name.strip()}

    @staticmethod
    def number(settings, key, default, minimum, maximum, integer=False):
        raw = settings.get(key)
        if raw is None or raw == '': raw = default
        try:
            value = float(raw)
            if isinstance(raw, bool) or not math.isfinite(value) or not minimum <= value <= maximum or integer and value != int(value): raise ValueError()
        except (ValueError, TypeError, OverflowError):
            raise RetryConfigurationError(f'{key} must be {"an integer" if integer else "a number"} between {minimum} and {maximum}') from None
        return int(value) if integer else value

    def delay(self, attempt, error, elapsed):
        """None stops retries; zero is a valid immediate retry. Never swallows cancellation."""
        if attempt >= self.count: return None
        if self.faults and not self.faults.intersection({type(error).__name__, str(getattr(error, 'fault_type', '')), str(getattr(error, 'code', ''))}): return None
        wait = min(self.maximum, self.interval * (2 ** attempt if self.backoff == 'exponential' else 1))
        if self.jitter: wait = random.uniform(wait / 2, wait)
        if self.elapsed_limit and elapsed + wait >= self.elapsed_limit: return None
        return wait
