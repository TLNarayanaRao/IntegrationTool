"""Shared SFTP authentication and host-key policy for Studio and Python archives."""


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
        client.connect(str(config.get('host') or ''), port=int(config.get('port') or 22),
                       username=config.get('username'), password=config.get('password') or None,
                       key_filename=config.get('privateKeyFile') or config.get('privateKeyPath') or None,
                       passphrase=config.get('privateKeyPassphrase') or None,
                       timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
                       allow_agent=_boolean(config.get('useSshAgent')), look_for_keys=_boolean(config.get('useSshAgent')))
        return client, client.open_sftp()
    except BaseException:
        client.close()
        raise
