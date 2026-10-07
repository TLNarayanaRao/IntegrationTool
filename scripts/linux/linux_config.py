"""Read INI files without interpolation, shell evaluation or inline comments."""
import configparser
import re
import sys

ALIASES = {
    'control-plane:control_plane_url': 'CONTROL_PLANE_URL', 'control-plane:admin_key': 'ADMIN_KEY',
    'control-plane:secret_key': 'ADMIN_SECRET_KEY',
    'data-plane:id': 'DATA_PLANE_ID', 'data-plane:name': 'DATA_PLANE_NAME',
    'data-plane:namespace': 'DATA_PLANE_NAMESPACE', 'data-plane:agent_version': 'AGENT_VERSION',
    'data-plane:heartbeat_seconds': 'HEARTBEAT_SECONDS', 'data-plane:available_capacity': 'AVAILABLE_CAPACITY',
    'delivery-team:id': 'DELIVERY_TEAM_ID', 'delivery-team:name': 'DELIVERY_TEAM_NAME',
    'delivery-team:description': 'DELIVERY_TEAM_DESCRIPTION', 'delivery-team:scopes_json': 'DELIVERY_TEAM_SCOPES_JSON',
    'user:id': 'USER_ID', 'user:name': 'USER_NAME', 'user:team_id': 'USER_TEAM_ID',
    'user:role': 'USER_ROLE', 'user:scope': 'USER_SCOPE', 'user:resource_id': 'USER_RESOURCE_ID',
    'setup:version': 'MINA_VERSION', 'setup:install_root': 'MINA_INSTALL_ROOT', 'setup:python': 'MINA_PYTHON',
}

def read_config(path):
    config = configparser.ConfigParser(interpolation=None)
    with open(path, encoding='utf-8-sig') as handle:
        config.read_file(handle)
    return config

def environment(config):
    values = {}
    for section in ('control-plane', 'runtime', 'data-plane', 'delivery-team', 'user', 'setup'):
        if section not in config:
            continue
        for key, value in config[section].items():
            name = ALIASES.get(f'{section}:{key}', f'MINA_{section.upper()}_{key.upper()}'.replace('-', '_'))
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*', name) or '\x00' in value or '\n' in value:
                raise ValueError(f'Invalid configuration key or multiline value: [{section}] {key}')
            values[name] = value
    return values

if __name__ == '__main__':
    for name, value in environment(read_config(sys.argv[1])).items():
        sys.stdout.buffer.write(name.encode() + b'\0' + value.encode() + b'\0')
