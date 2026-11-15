"""Shared SFTP authentication and host-key policy for Studio and Python archives."""

import os
import queue
import threading
from functools import lru_cache


class _TransportJob:
    def __init__(self, target):
        self.target = target
        self.done = threading.Event()
        self.thread = None


class _TransportWorkers:
    """Bound native crypto thread state without retaining connections between jobs.

    Workers are lazy, daemon threads, fixed for the lifetime of this module. A
    fresh SSH transport still owns every socket, key exchange and authentication.
    Do not recycle workers per connection: that recreates Windows native growth.
    """
    def __init__(self, maximum):
        self.maximum = maximum
        self.slots = threading.BoundedSemaphore(maximum)
        self.jobs = queue.Queue(maxsize=maximum)
        self.lock = threading.Lock()
        self.workers = []
        self.active = 0

    def submit(self, target, timeout):
        if not self.slots.acquire(timeout=timeout):
            raise TimeoutError('SFTP transport capacity wait timed out')
        job = _TransportJob(target)
        try:
            with self.lock:
                self.active += 1
                if self.active > len(self.workers):
                    worker = threading.Thread(target=self._work, name='mina-sftp-transport', daemon=True)
                    worker.start()
                    self.workers.append(worker)
            self.jobs.put_nowait(job)
        except BaseException:
            with self.lock:
                self.active -= 1
            self.slots.release()
            raise
        return job

    def _work(self):
        while True:
            job = self.jobs.get()
            try:
                job.thread = threading.current_thread()
                job.target()
            except BaseException:
                # Transport.run reports SSH failures itself. An unexpected fatal
                # exception must not kill a persistent worker or retain traceback.
                import logging
                logging.getLogger(__name__).error('SFTP transport worker terminated its current connection')
            finally:
                job.target = None
                job.thread = None
                with self.lock:
                    self.active -= 1
                self.slots.release()
                job.done.set()
                self.jobs.task_done()
                del job


_transport_type_lock = threading.Lock()


def _windows_transport_type():
    # functools caches results, but concurrent misses can execute the builder
    # more than once. There must be only one worker bound per module/process.
    with _transport_type_lock:
        return _build_windows_transport_type()


@lru_cache(maxsize=1)
def _build_windows_transport_type():
    import paramiko
    try:
        maximum = int(os.environ.get('MINA_SFTP_TRANSPORT_WORKERS', '32'))
    except ValueError as error:
        raise ValueError('MINA_SFTP_TRANSPORT_WORKERS must be an integer from 1 to 128') from error
    if not 1 <= maximum <= 128:
        raise ValueError('MINA_SFTP_TRANSPORT_WORKERS must be an integer from 1 to 128')
    workers = _TransportWorkers(maximum)

    class Transport(paramiko.Transport):
        """Paramiko transport_factory using bounded persistent execution threads."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._mina_job = None

        def start(self):
            if self._mina_job is not None:
                raise RuntimeError('SFTP transport can only be started once')
            self._mina_job = workers.submit(self.run, self.channel_timeout)

        def is_alive(self):
            return self._mina_job is not None and not self._mina_job.done.is_set()

        def join(self, timeout=None):
            if self._mina_job is None:
                raise RuntimeError('Cannot join SFTP transport before it is started')
            if self._mina_job.thread is threading.current_thread():
                raise RuntimeError('Cannot join the current SFTP transport thread')
            self._mina_job.done.wait(timeout)

    return Transport


def _boolean(value, default=False):
    if value is None: return default
    if isinstance(value, bool): return value
    text = str(value).strip().lower()
    if text in ('true', '1', 'yes', 'on'): return True
    if text in ('false', '0', 'no', 'off', ''): return False
    raise ValueError(f'Invalid SFTP boolean value: {value!r}')


def open_connection(config):
    try: import paramiko
    except ImportError as error: raise RuntimeError('SFTP requires the optional paramiko package') from error
    client = paramiko.SSHClient()
    try:
        client.load_system_host_keys()
        if config.get('knownHostsFile'): client.load_host_keys(config['knownHostsFile'])
        strict = _boolean(config.get('verifyHostKey', config.get('strictHostKeyChecking')), True)
        if 'allowUnknownHostKey' in config and 'verifyHostKey' not in config and 'strictHostKeyChecking' not in config:
            strict = not _boolean(config['allowUnknownHostKey'])
        client.set_missing_host_key_policy(paramiko.RejectPolicy() if strict else paramiko.AutoAddPolicy())
        timeout = float(config.get('timeout') or config.get('timeoutSeconds') or 30)
        import math
        if not math.isfinite(timeout) or timeout <= 0: raise ValueError('SFTP timeout must be positive and finite')
        client.connect(str(config.get('host') or ''), port=int(config.get('port') or 22),
                       username=config.get('username'), password=config.get('password') or None,
                       key_filename=config.get('privateKeyFile') or config.get('privateKeyPath') or None,
                       passphrase=config.get('privateKeyPassphrase') or None,
                       timeout=timeout, banner_timeout=timeout, auth_timeout=timeout, channel_timeout=timeout,
                       allow_agent=_boolean(config.get('useSshAgent')), look_for_keys=_boolean(config.get('useSshAgent')),
                       **({'transport_factory': _windows_transport_type()} if os.name == 'nt' else {}))
        # Channel-open timeout does not bound the subsequent subsystem/version handshake.
        import threading
        from contextlib import suppress
        timed_out=threading.Event();negotiating=threading.Event();negotiating.set();guard=threading.Lock()
        def expire():
            with guard:
                if not negotiating.is_set():return
                timed_out.set()
            with suppress(Exception):client.close()
        timer=threading.Timer(timeout,expire);timer.daemon=True;timer.start()
        try:
            sftp=client.open_sftp()
            with guard:negotiating.clear()
            if timed_out.is_set():
                with suppress(Exception):sftp.close()
                raise TimeoutError('SFTP subsystem negotiation timed out')
        except Exception as error:
            if timed_out.is_set():raise TimeoutError('SFTP subsystem negotiation timed out') from error
            raise
        finally:
            with guard:negotiating.clear()
            timer.cancel()
        try:
            sftp.get_channel().settimeout(timeout)
        except BaseException:
            sftp.close()
            raise
        return client, sftp
    except BaseException:
        client.close()
        raise
