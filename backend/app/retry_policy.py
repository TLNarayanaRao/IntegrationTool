"""Outbound activity resilience shared by Studio and both Python exporters."""
import math
import random
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from time import monotonic


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


def circuit_activity(kind, operation=''):
    # HTTP has its own transport breaker. Keep settlement and reply operations
    # outside this policy so a tripped circuit cannot withhold acknowledgements.
    return (kind not in ('http', 'rest', 'soap') and outbound_activity(kind, operation)
            and operation not in ('dead_letter', 'idoc_acknowledgment', 'idoc_confirmation', 'reply_rfc_bapi',
                                  'reply', 'reply_message'))


def fault_names(value, label):
    names = value or []
    if isinstance(names, str):
        names = names.replace(',', ' ').split()
    if not isinstance(names, (list, tuple)) or len(names) > 100 or any(
            not isinstance(name, str) or len(name) > 200 for name in names):
        raise RetryConfigurationError(f'{label} must be a list or comma-separated names')
    return {name.strip() for name in names if name.strip()}


def matches_fault(names, error):
    return not names or bool(names.intersection({
        type(error).__name__, str(getattr(error, 'fault_type', '')), str(getattr(error, 'code', '')),
    }))


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
        self.faults = fault_names(settings.get('retryFaultTypes'), 'Retry fault types')

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
        if attempt >= self.count or isinstance(error, CircuitOpenError) or not matches_fault(self.faults, error):
            return None
        wait = min(self.maximum, self.interval * (2 ** attempt if self.backoff == 'exponential' else 1))
        if self.jitter: wait = random.uniform(wait / 2, wait)
        if self.elapsed_limit and elapsed + wait >= self.elapsed_limit: return None
        return wait


class CircuitOpenError(RuntimeError):
    fault_type = 'CircuitOpen'

    def __init__(self, retry_after, *, probing=False):
        message = ('Activity circuit is waiting for its recovery probe' if probing else
                   f'Activity circuit is open for another {retry_after:.3f} seconds')
        super().__init__(message)
        self.details = {'retryAfterSeconds': retry_after}


class CircuitCapacityError(CircuitOpenError):
    fault_type = 'CircuitBreakerCapacity'

    def __init__(self):
        RuntimeError.__init__(self, 'Activity circuit registry is full')


class CircuitPlan:
    def __init__(self, kind, operation, advanced):
        enabled = advanced.get('circuitEnabled')
        self.enabled = bool(enabled) and retry_boolean(enabled) and circuit_activity(kind, operation)
        if self.enabled:
            self.threshold = RetryPlan.number(advanced, 'circuitFailureThreshold', 5, 1, 1000, integer=True)
            self.cooldown = RetryPlan.number(advanced, 'circuitCooldownSeconds', 30, 1, 86400)
            self.faults = fault_names(advanced.get('circuitFaultTypes'), 'Circuit breaker fault types')


@dataclass
class _Circuit:
    failures: int = 0
    until: float = 0
    probe: bool = False
    generation: int = 0
    active: int = 0
    updated: float = 0


@dataclass
class _CircuitAttempt:
    state: _Circuit
    generation: int
    probe: bool
    stops_retry: bool = False


class ActivityCircuits:
    def __init__(self, capacity=4096, clock=monotonic):
        self._records = {}
        self._lock = Lock()
        self._capacity = capacity
        self._clock = clock

    def _enter(self, key):
        with self._lock:
            now = self._clock()
            state = self._records.get(key)
            if state is None:
                if len(self._records) >= self._capacity:
                    for candidate, record in list(self._records.items()):
                        if not record.active and now >= max(record.until, record.updated + 3600):
                            del self._records[candidate]
                    if len(self._records) >= self._capacity:
                        raise CircuitCapacityError()
                state = self._records[key] = _Circuit()
            if state.until > now or state.probe:
                raise CircuitOpenError(max(0, state.until - now), probing=state.probe)
            state.probe = bool(state.until)
            state.active += 1
            return _CircuitAttempt(state, state.generation, state.probe, stops_retry=state.probe)

    def _finish(self, key, ticket, plan, failed):
        with self._lock:
            state = ticket.state
            state.active -= 1
            target = None
            if state.generation == ticket.generation:
                now = self._clock()
                state.updated = now
                state.probe = False
                if failed is False:
                    state.failures = 0
                    if state.until:
                        target = 'closed'
                    state.until = 0
                elif failed is True:
                    state.failures += 1
                    if ticket.probe or state.failures >= plan.threshold:
                        state.until = now + plan.cooldown
                        state.generation += 1
                        ticket.stops_retry = True
                        target = 'open'
            else:
                # An already running attempt from the old generation must not
                # change the circuit or schedule another connector attempt.
                ticket.stops_retry = True
            if not state.active and not state.failures and not state.until:
                del self._records[key]
            return target

    @contextmanager
    def attempt(self, key, plan, report):
        try:
            ticket = self._enter(key)
        except CircuitOpenError:
            report('blocked')
            raise
        failed = None
        try:
            yield ticket
            failed = False
        except Exception as error:
            if not isinstance(error, (CircuitOpenError, RetryConfigurationError)) and matches_fault(plan.faults, error):
                failed = True
            raise
        finally:
            target = self._finish(key, ticket, plan, failed)
            if target:
                report(target)
