"""Upgrade compatibility for configuration and previously exported applications.

MINA names take precedence when nonempty. Legacy names remain wire/configuration
contracts, not product branding. Never log the values (they may be credentials).
"""
import os


def env_value(name, default=None):
    value = os.environ.get(name)
    if value is not None and value.strip():
        return value
    legacy = 'FABRIC_' + name.removeprefix('MINA_')
    return os.environ.get(legacy, default) if name.startswith('MINA_') else default


def required_env(name):
    value = env_value(name)
    if not value:
        raise ValueError(f'{name} is required')
    return value


def application_environment(values):
    """Emit identical managed settings for both new and existing archives."""
    result = dict(values)
    for name, value in values.items():
        if name.startswith('MINA_'):
            result['FABRIC_' + name.removeprefix('MINA_')] = value
    return result
