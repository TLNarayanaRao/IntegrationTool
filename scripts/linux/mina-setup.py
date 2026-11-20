#!/usr/bin/env python3
"""Single INI-driven Linux setup entry; bundle preparation also runs on Windows."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from linux_config import read_config, environment

SOFTWARE = Path(__file__).resolve().parent.parent.parent
BUNDLE_ROOT = 'software/'
LAUNCHER = 'scripts/linux/start-control-plane.sh'
CHECK_PYTHON_SHARED_LIBRARY = '''
import ctypes
from pathlib import Path
import sys
import sysconfig

name = sysconfig.get_config_var('INSTSONAME')
if not name or '.so' not in name:
    name = f'libpython{sys.version_info.major}.{sys.version_info.minor}.so.1.0'
directory = sysconfig.get_config_var('LIBDIR') or str(Path(sys.base_prefix) / 'lib')
for candidate in (name, str(Path(directory) / name)):
    try:
        ctypes.CDLL(candidate)
    except OSError:
        continue
    raise SystemExit(0)
raise SystemExit(1)
'''

def get(config, section, key, default=''):
    return config.get(section, key, fallback=default).strip()

def required(config, section, key):
    value = get(config, section, key)
    if not value or value.startswith('CHANGE_ME') or value == 'replace-me':
        raise ValueError(f'Set [{section}] {key} in the INI')
    return value

def absolute(value, label):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f'{label} must be an absolute Linux path')
    return path.resolve()

def normalize_scripts(source):
    """Also handles an existing tree copied by a Windows editor/file transfer."""
    files = list((source / 'scripts').rglob('*.sh')) + [source / 'administrator/bin/minaadmin']
    for path in files:
        if path.is_file():
            original = path.read_bytes()
            fixed = original.removeprefix(b'\xef\xbb\xbf').replace(b'\r\n', b'\n')
            if original != fixed:
                path.write_bytes(fixed)

def bundle(output):
    output = Path(output).resolve()
    excluded = {'node_modules', '__pycache__', 'dist', 'build', 'release', 'data', 'logs', 'agent-state'}
    source_suffixes = {'.py', '.sh', '.ps1', '.cmd', '.cjs', '.ini', '.txt', '.md',
                       '.java', '.nsi', '.html', '.js', '.css'}
    files = []
    for folder in ('administrator', 'backend', 'scripts', 'java-bridge', 'drivers'):
        base = SOFTWARE / folder
        for directory, subdirectories, names in os.walk(base):
            subdirectories[:] = sorted(name for name in subdirectories
                                       if name not in excluded and not name.startswith('.'))
            for name in sorted(names):
                path = Path(directory) / name
                if name.startswith('.') or path.is_symlink() or path == output:
                    continue
                if path.suffix in source_suffixes or path == SOFTWARE / 'administrator/bin/minaadmin':
                    files.append(path)
    files.extend(SOFTWARE / 'docs' / name for name in
                 ('LINUX_SETUP.md', 'SAP_INTEGRATION.md', 'sap-soak-config.example.json'))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(Path(__file__), '__main__.py')
        archive.write(Path(__file__).with_name('linux_config.py'), 'linux_config.py')
        for path in files:
            relative = path.relative_to(SOFTWARE)
            data = path.read_bytes()
            if path.suffix in {'.sh', '.py', '.ini'} or relative.as_posix() == 'administrator/bin/minaadmin':
                data = data.removeprefix(b'\xef\xbb\xbf').replace(b'\r\n', b'\n')
            info = zipfile.ZipInfo('software/' + relative.as_posix())
            info.external_attr = (0o100755 if path.suffix == '.sh' else 0o100644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    print(f'Linux transfer bundle: {output}')


def install_bundled_source(bundle_path, source, *, check=False):
    """Publish a complete software tree at once and let setup retry the same bundle."""
    with bundle_path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    receipt = source / '.mina-transfer-sha256'
    if source.exists() and (not source.is_dir() or any(source.iterdir())):
        if receipt.is_file() and receipt.read_text(encoding='ascii').strip() == digest and (source / LAUNCHER).is_file():
            return
        raise ValueError(f'Software path {source} already contains another source tree. Use a new [setup] source_root for this bundle.')
    with zipfile.ZipFile(bundle_path) as archive:
        members = [entry for entry in archive.infolist() if entry.filename.startswith(BUNDLE_ROOT)]
        if BUNDLE_ROOT + LAUNCHER not in {entry.filename for entry in members}:
            raise ValueError('Transfer bundle has no Control Plane launcher')
        seen = set()
        for entry in members:
            name = entry.filename.removeprefix(BUNDLE_ROOT)
            path = PurePosixPath(name)
            if not name or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts or path in seen:
                raise ValueError(f'Invalid source entry in transfer bundle: {entry.filename}')
            seen.add(path)
        if check:
            if damaged := archive.testzip():
                raise ValueError(f'Damaged transfer bundle entry: {damaged}')
            return
        source.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.mina-transfer-', dir=source.parent) as temp:
            tree = Path(temp) / 'source'
            for entry in members:
                target = tree / entry.filename.removeprefix(BUNDLE_ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as supplied, target.open('xb') as output:
                    shutil.copyfileobj(supplied, output)
            (tree / receipt.name).write_text(digest + '\n', encoding='ascii')
            if source.exists():
                source.rmdir()  # Succeeds only while the agreed destination is still empty.
            tree.rename(source)


def settings(config, role, config_file, *, from_bundle=False):
    root = absolute(required(config, 'setup', 'install_root'), 'install_root')
    source = absolute(get(config, 'setup', 'source_root') or str(root / 'software' if from_bundle else SOFTWARE), 'source_root')
    if from_bundle and source == root:
        raise ValueError('[setup] source_root must be separate from install_root when installing a transfer bundle')
    python = get(config, 'setup', 'python', sys.executable)
    if not shutil.which(python):
        raise ValueError(f'Python interpreter not found: {python}')
    interpreter = subprocess.run([python, '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'], check=True, capture_output=True, text=True)
    if tuple(map(int, interpreter.stdout.strip().split('.'))) < (3, 12):
        raise ValueError('[setup] python must be Python 3.12 or newer')
    config.getboolean('setup', 'start', fallback=True)
    if not from_bundle and not (source / LAUNCHER).is_file():
        raise ValueError(f'Missing software tree: {source}')
    env = os.environ.copy()
    env.update(environment(config))
    env.update(MINA_CONFIG_FILE=str(config_file), MINA_INSTALL_ROOT=str(root), MINA_SOURCE_ROOT=str(source), MINA_PYTHON=python)
    bridge = root / 'java-bridge/build'
    previous_bridge = source / 'java-bridge/build'
    if not (bridge / 'classes').is_dir() and (previous_bridge / 'classes').is_dir():
        bridge = previous_bridge
    env.update(MINA_DRIVER_HOME=get(config, 'runtime', 'driver_home', str(root / 'drivers')),
               MINA_JAVA_BRIDGE_HOME=get(config, 'runtime', 'java_bridge_home') or str(bridge),
               MINA_PYPI_INDEX_URL=get(config, 'setup', 'pip_index_url'), MINA_WHEELHOUSE=get(config, 'setup', 'wheelhouse'),
               MINA_INSTALL_DB2=str(config.getboolean('runtime', 'install_db2', fallback=False)).lower())
    env['MINA_BUILD_JAVA_BRIDGE'] = str(config.getboolean('runtime', 'build_java_bridge', fallback=False)).lower()
    if get(config, 'runtime', 'java'):
        env['MINA_JAVA'] = get(config, 'runtime', 'java')
    if role == 'control-plane':
        required(config, 'control-plane', 'api_key'); required(config, 'control-plane', 'secret_key')
        required(config, 'control-plane', 'host')
        if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?', required(config, 'setup', 'version')):
            raise ValueError('[setup] version must be a semantic version such as 1.0.5')
        config.getboolean('setup', 'build_administrator', fallback=True)
        config.getboolean('control-plane', 'install_local_runtime', fallback=False)
        port = int(required(config, 'control-plane', 'port'))
        if not 1 <= port <= 65535:
            raise ValueError('Control Plane port must be 1..65535')
    else:
        identifier = required(config, 'data-plane', 'id')
        namespace = required(config, 'data-plane', 'namespace')
        required(config, 'data-plane', 'name'); required(config, 'data-plane', 'host')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', identifier) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', namespace):
            raise ValueError('Data Plane id and namespace must contain letters, digits, underscores or hyphens')
        required(config, 'control-plane', 'admin_key')
        url = urllib.parse.urlsplit(required(config, 'control-plane', 'control_plane_url'))
        if url.scheme not in ('http', 'https') or not url.hostname or url.query or url.fragment or url.username or url.password:
            raise ValueError('control_plane_url must be an HTTP(S) base URL without query or fragment')
        if int(get(config, 'data-plane', 'heartbeat_seconds', '30')) < 1 or not 1 <= int(get(config, 'data-plane', 'available_capacity', '20')) <= 10000:
            raise ValueError('Heartbeat seconds must be positive; capacity must be 1..10000')
        if get(config, 'control-plane', 'ca_bundle') and not Path(get(config, 'control-plane', 'ca_bundle')).is_file():
            raise ValueError('The configured HTTPS ca_bundle does not exist')
        env['MINA_AGENT_ROOT'] = str(absolute(get(config, 'data-plane', 'state_dir') or str(root / 'agent' / identifier), 'state_dir'))
        existing = Path(env['MINA_AGENT_ROOT']) / 'data-plane.ini'
        if existing.is_file() and get(read_config(existing), 'data-plane', 'id') != identifier:
            raise ValueError('state_dir already belongs to another Data Plane; use a separate directory')
        env['MINA_PYTHON_EXECUTABLE'] = str(root / 'runtime/.venv/bin/python')
        env['CONTROL_PLANE_URL'] = required(config, 'control-plane', 'control_plane_url').rstrip('/')
        env['ADMIN_KEY'] = required(config, 'control-plane', 'admin_key')
        if get(config, 'delivery-team', 'id'):
            required(config, 'delivery-team', 'name')
            if get(config, 'delivery-team', 'scopes_json'):
                if not isinstance(json.loads(get(config, 'delivery-team', 'scopes_json')), list):
                    raise ValueError('delivery-team.scopes_json must be a JSON array')
        if get(config, 'user', 'id'):
            required(config, 'user', 'team_id')
    return root, source, env

def bash(path, env, *args):
    subprocess.run(['bash', str(path), *args], env=env, check=True)

class Api:
    def __init__(self, url, key, ca_bundle='', *, timeout=30):
        self.url, self.key = url.rstrip('/'), key
        self.context = ssl.create_default_context(cafile=ca_bundle or None)
        self.timeout = timeout

    def request(self, method, path, body=None):
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.url + path, data=payload, method=method, headers={'X-Admin-Key': self.key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, context=self.context, timeout=self.timeout) as response:
            data = response.read()
            return json.loads(data) if data else {}

    def upsert(self, collection, identifier, body):
        try:
            return self.request('PUT', f'{collection}/{urllib.parse.quote(identifier, safe="")}', body)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                error.close()
                raise
            error.close()
            return self.request('POST', collection, body)

def register_plane(config, api):
    identifier, namespace = required(config, 'data-plane', 'id'), required(config, 'data-plane', 'namespace')
    existing_plane = next((plane for plane in api.request('GET', '/api/data-planes') if plane.get('id') == identifier), {})
    namespaces = list(dict.fromkeys([*existing_plane.get('namespaces', []), namespace]))
    api.upsert('/api/data-planes', identifier, {'id': identifier, 'name': required(config, 'data-plane', 'name'), 'type': get(config, 'data-plane', 'type', 'on-premises'), 'host': required(config, 'data-plane', 'host'), 'region': get(config, 'data-plane', 'region', 'local'), 'namespaces': namespaces, 'capacity': int(get(config, 'data-plane', 'available_capacity', '20')), 'driver': 'agent', 'tags': []})
    capability = f'integration-runtime-{identifier}-{namespace}'
    api.upsert('/api/capabilities', capability, {'name': get(config, 'data-plane', 'capability_name', 'Integration Runtime'), 'type': 'integration-runtime', 'version': get(config, 'setup', 'version', '1.0.0'), 'dataPlaneId': identifier, 'namespace': namespace, 'tags': []})
    if config.has_section('delivery-team') and get(config, 'delivery-team', 'id'):
        team = required(config, 'delivery-team', 'id')
        scopes = [{'dataPlaneId': identifier, 'namespace': namespace}]
        if get(config, 'delivery-team', 'scopes_json'):
            scopes = json.loads(get(config, 'delivery-team', 'scopes_json'))
        else:
            previous = next((item for item in api.request('GET', '/api/teams') if item.get('id') == team), {})
            scopes = previous.get('namespaceScopes', []) + [scope for scope in scopes if scope not in previous.get('namespaceScopes', [])]
        api.upsert('/api/teams', team, {'id': team, 'name': required(config, 'delivery-team', 'name'), 'kind': 'delivery', 'description': get(config, 'delivery-team', 'description'), 'namespaceScopes': scopes})
    if config.has_section('user') and get(config, 'user', 'id'):
        user = required(config, 'user', 'id')
        api.upsert('/api/access/principals', user, {'id': user, 'name': get(config, 'user', 'name') or user, 'type': 'user', 'teamId': required(config, 'user', 'team_id'), 'permissions': [{'role': get(config, 'user', 'role', 'Application Manager'), 'scope': get(config, 'user', 'scope', 'namespace'), 'resourceId': get(config, 'user', 'resource_id') or namespace}]})
    print(f'Registered Data Plane {identifier}; capability {capability}')


def administrator_archive(config, source):
    version = required(config, 'setup', 'version')
    supplied = get(config, 'setup', 'administrator_archive')
    archive = Path(supplied or source / f'administrator/release/MinaAdministrator-{version}-Linux-x64.tar.gz')
    build = not archive.is_file() and not supplied and config.getboolean('setup', 'build_administrator', fallback=True)
    return archive, build


def check_linux_prerequisites(config, role, source, env):
    build_administrator = False
    if role == 'control-plane':
        archive, build_administrator = administrator_archive(config, source)
        if not build_administrator and not archive.is_file():
            raise ValueError(f'Linux Administrator archive not found: {archive}')
    tools = ('bash', 'ldd', 'objdump', 'objcopy', 'tar') if build_administrator else ('bash',)
    absent = [name for name in tools if not shutil.which(name)]
    if absent:
        raise ValueError('Missing Linux setup tools: ' + ', '.join(absent) + '. Administrator source builds require binutils, libc and tar.')
    if build_administrator or role == 'data-plane' or config.getboolean('control-plane', 'install_local_runtime', fallback=False):
        result = subprocess.run([env['MINA_PYTHON'], '-c', 'import venv, ensurepip'], capture_output=True)
        if result.returncode:
            raise ValueError('The configured Python lacks venv or ensurepip. Install its venv package (python3.12-venv on Ubuntu 24.04).')
    if build_administrator:
        result = subprocess.run([env['MINA_PYTHON'], '-c', CHECK_PYTHON_SHARED_LIBRARY], capture_output=True)
        if result.returncode:
            raise ValueError('Administrator source builds require the configured Python shared library (libpython3.12 on Ubuntu 24.04).')


def control_plane(config, config_file, action, root, source, env):
    cp = absolute(get(config, 'control-plane', 'home', str(root / 'control-plane')), 'control-plane.home')
    launcher = source / LAUNCHER
    installed_ini = cp / 'mina-control-plane.ini'
    env['MINA_ADMIN_INI'] = str(config_file if action != 'setup' else installed_ini)
    if action != 'setup':
        bash(launcher, env, action); return
    pid_file = Path(get(config, 'control-plane', 'pid_dir', str(root / 'run'))) / 'control-plane.pid'
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        except (OSError, ValueError):
            pass
        else:
            if any(str(cp / name).encode() in command for name in ('MinaAdministrator', 'mina-control-plane')):
                raise ValueError('Stop the existing Control Plane before setup/upgrade; its data is retained')
    archive, build_administrator = administrator_archive(config, source)
    if build_administrator:
        bash(source / 'scripts/build-administrator-linux.sh', env, required(config, 'setup', 'version'))
    if not archive.is_file():
        raise ValueError(f'Linux Administrator archive not found: {archive}')
    cp.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as stage:
        with tarfile.open(archive) as package:
            package.extractall(stage, filter='data')
        executable = next((path for path in Path(stage).rglob('MinaAdministrator') if path.is_file()), None)
        if executable is None or not executable.is_file():
            raise ValueError('Archive must contain the Linux MinaAdministrator executable')
        config_bytes = config_file.read_bytes()
        shutil.copytree(executable.parent, cp, dirs_exist_ok=True)
    shutil.copy2(cp / 'MinaAdministrator', cp / 'mina-control-plane')
    for name in ('MinaAdministrator', 'mina-control-plane'):
        (cp / name).chmod(0o755)
    shutil.copy2(launcher, cp / launcher.name)
    installed_ini.touch(mode=0o600, exist_ok=True)
    installed_ini.chmod(0o600)
    installed_ini.write_bytes(config_bytes)
    for path in (root / 'control-plane-data', root / 'logs/control-plane', root / 'run'):
        path.mkdir(parents=True, exist_ok=True)
    local_runtime = config.getboolean('control-plane', 'install_local_runtime', fallback=False)
    if local_runtime:
        bash(source / 'scripts/linux/install-runtime.sh', env)
    if config.getboolean('setup', 'start', fallback=True):
        bash(launcher, env, 'start')
        host = get(config, 'control-plane', 'host', '0.0.0.0')
        host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(host, host)
        host = f'[{host}]' if ':' in host else host
        api = Api(f'http://{host}:{get(config,"control-plane","port")}', required(config, 'control-plane', 'api_key'), timeout=2)
        log_dir = get(config, 'control-plane', 'log_dir') or str(root / 'logs/control-plane')
        verify_control_plane(api, local_runtime, Path(log_dir) / 'administrator.log')
        print(f'Control Plane verified at {api.url}')
        if local_runtime:
            print('Deployment target verified: localhost / default / integration-runtime-local')
    print(f'Control Plane and local runtime installed at {root}' if local_runtime else f'Control Plane installed at {cp}')


def verify_control_plane(api, local_runtime, log):
    deadline = time.monotonic() + 45
    while True:
        try:
            health = api.request('GET', '/api/health')
            break
        except (urllib.error.URLError, TimeoutError) as error:
            if time.monotonic() >= deadline:
                raise ValueError(f'Control Plane did not become healthy; inspect {log}') from error
            time.sleep(1)
    if health.get('status') != 'ok' or health.get('component') != 'mina-control-plane':
        raise ValueError(f'Expected MINA Control Plane health at {api.url}')
    api.request('GET', '/api/session')
    if local_runtime:
        capabilities = api.request('GET', '/api/capabilities')
        if not health.get('runtimeAdapterConfigured') or not any(
            item.get('id') == 'integration-runtime-local' and item.get('dataPlaneId') == 'localhost'
            and item.get('namespace') == 'default' and item.get('state') == 'PROVISIONED'
            for item in capabilities
        ):
            raise ValueError('Control Plane is online but its local Integration Runtime target is unavailable')

def plane_alive(pid_file, agent, config_file):
    try:
        pid = int(pid_file.read_text().strip())
        command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return pid if str(agent).encode() in command and str(config_file).encode() in command else None
    except (OSError, ValueError):
        return None

def data_plane(config, config_file, action, root, source, env):
    state = Path(env['MINA_AGENT_ROOT'])
    state.mkdir(parents=True, exist_ok=True)
    installed_ini = state / 'data-plane.ini'
    agent = source / 'scripts/linux/remote-data-plane-agent.py'
    pid_file = state / 'agent.pid'
    pid = plane_alive(pid_file, agent, installed_ini)
    if action == 'status':
        print(f'RUNNING PID {pid}' if pid else 'STOPPED'); return
    if action in ('stop', 'restart'):
        if pid:
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                if not plane_alive(pid_file, agent, installed_ini):
                    break
                time.sleep(1)
            else:
                raise ValueError('Agent did not stop gracefully; inspect agent.log')
        pid_file.unlink(missing_ok=True)
        if action == 'stop':
            print('Data Plane agent stopped'); return
        pid = None
    if pid:
        if action == 'setup':
            raise ValueError('Stop this Data Plane before changing its INI/setup')
        print(f'Already running (PID {pid})'); return
    if action == 'setup':
        api = Api(required(config, 'control-plane', 'control_plane_url'), required(config, 'control-plane', 'admin_key'), get(config, 'control-plane', 'ca_bundle'))
        api.request('GET', '/api/health')
        bash(source / 'scripts/linux/install-runtime.sh', env)
        register_plane(config, api)
    if config_file.resolve() != installed_ini.resolve():
        shutil.copyfile(config_file, installed_ini)
    installed_ini.chmod(0o600)
    env['MINA_CONFIG_FILE'] = str(installed_ini)
    if action != 'setup' or config.getboolean('setup', 'start', fallback=True):
        if not Path(env['MINA_PYTHON_EXECUTABLE']).is_file():
            raise ValueError('Runtime is not installed; run the Data Plane setup action first')
        with (state / 'agent.log').open('ab') as output:
            process = subprocess.Popen([env['MINA_PYTHON_EXECUTABLE'], '-u', str(agent), '--config', str(installed_ini)], env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        pid_file.write_text(str(process.pid), encoding='ascii')
        time.sleep(1)
        if process.poll() is not None:
            pid_file.unlink(missing_ok=True)
            raise ValueError(f'Agent exited; inspect {state}/agent.log')
        print(f'Data Plane agent started (PID {process.pid}); log: {state}/agent.log')

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('bundle', 'control-plane', 'data-plane'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path, default=Path('MinaLinuxSetup.zip'))
    parser.add_argument('--action', choices=('setup', 'start', 'stop', 'restart', 'status'), default='setup')
    parser.add_argument('--check', action='store_true', help='Validate INI and copied inputs without installing or starting anything')
    args = parser.parse_args(argv)
    entry = Path(sys.argv[0]).resolve()
    from_bundle = zipfile.is_zipfile(entry)
    if args.role == 'bundle':
        if from_bundle:
            parser.error('Build a new bundle from the repository setup script')
        bundle(args.output); return
    if args.config is None:
        parser.error('--config is required for setup and lifecycle commands')
    config_file = args.config.resolve()
    config = read_config(config_file)
    bundled_setup = from_bundle and args.action == 'setup'
    root, source, env = settings(config, args.role, config_file, from_bundle=from_bundle)
    if not bundled_setup and not (source / LAUNCHER).is_file():
        raise ValueError(f'Missing software tree: {source}; run setup first')
    if args.action == 'setup' and sys.platform == 'linux':
        check_linux_prerequisites(config, args.role, source, env)
    if args.check:
        if bundled_setup:
            install_bundled_source(entry, source, check=True)
        print(f'INI validated: {args.role}; software={source}; install_root={root}'); return
    if sys.platform != 'linux' or sys.version_info < (3, 12):
        raise ValueError('Setup requires Linux and Python 3.12 or newer; bundle preparation runs on Windows')
    if not shutil.which('bash'):
        raise ValueError('Bash is required')
    import fcntl
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True)
    lock_name = 'control-plane' if args.role == 'control-plane' else required(config, 'data-plane', 'id')
    with (root / f'.setup-{lock_name}.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if bundled_setup:
            install_bundled_source(entry, source)
        normalize_scripts(source)
        (control_plane if args.role == 'control-plane' else data_plane)(config, config_file, args.action, root, source, env)

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, tarfile.TarError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
