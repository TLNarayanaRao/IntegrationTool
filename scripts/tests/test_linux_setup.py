import configparser
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

LINUX = Path(__file__).resolve().parents[1] / 'linux'
sys.path.insert(0, str(LINUX))
spec = importlib.util.spec_from_file_location('mina_setup', LINUX / 'mina-setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
from linux_config import read_config, environment

class LinuxSetupTests(unittest.TestCase):
    @unittest.skipIf(sys.version_info < (3, 12), 'Executable setup bundle requires Python 3.12 or newer')
    def test_executable_bundle_check_and_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'transfer.zip'
            setup.bundle(archive)
            cfg = root / 'control.ini'
            cfg.write_text(f'[setup]\ninstall_root={root / "install with spaces"}\npython={sys.executable}\nversion=1.0.5\n'
                           '[control-plane]\nhost=127.0.0.1\nport=19080\napi_key=qa-key\nsecret_key=qa-secret\n', encoding='utf-8')
            result = subprocess.run([sys.executable, str(archive), 'control-plane', '--config', str(cfg), '--check'],
                                    check=True, text=True, capture_output=True, cwd=root)
            self.assertIn('INI validated: control-plane', result.stdout)
            destination = root / 'install with spaces' / 'software'
            self.assertFalse(destination.parent.exists())
            setup.install_bundled_source(archive, destination)
            setup.install_bundled_source(archive, destination)
            self.assertTrue((destination / setup.LAUNCHER).is_file())
            with zipfile.ZipFile(archive, 'a') as changed:
                changed.writestr('software/new-file', 'new')
            with self.assertRaisesRegex(ValueError, 'another source tree'):
                setup.install_bundled_source(archive, destination)
            self.assertFalse((destination / 'new-file').exists())

    def test_zip_bootstrap_rejects_unsafe_members_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'transfer.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('software/' + setup.LAUNCHER, '')
                bundle.writestr('software/../escaped', 'unsafe')
            with self.assertRaisesRegex(ValueError, 'Invalid source entry'):
                setup.install_bundled_source(archive, root / 'software')
            self.assertFalse((root / 'escaped').exists())
            self.assertFalse((root / 'software').exists())

    def test_registration_against_control_plane_api_is_repeatable_and_preserves_scopes(self):
        from fastapi.testclient import TestClient
        from administrator.app import main
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = {'DATA_DIR': root, 'PACKAGES_DIR': root/'packages', 'STAGING_DIR': root/'staging', 'LOGS_DIR': root/'logs'}
            for name, filename in {'DEPLOYMENTS_FILE':'deployments.json','PACKAGES_FILE':'packages.json','MACHINES_FILE':'machines.json','SECRETS_FILE':'secrets.json','AUDIT_FILE':'audit.json','KEY_FILE':'.key','CAPABILITIES_FILE':'capabilities.json','RESOURCES_FILE':'resources.json','PRINCIPALS_FILE':'principals.json','TEAMS_FILE':'teams.json','TOKENS_FILE':'tokens.json','REVISIONS_FILE':'revisions.json','TELEMETRY_FILE':'telemetry.json'}.items():
                paths[name] = root / filename
            with patch.multiple(main, **paths, API_KEY='', RUNTIME_COMMAND=''), TestClient(main.app, base_url='http://localhost', client=('127.0.0.1',50000)) as client:
                class TestApi(setup.Api):
                    def request(self, method, path, body=None):
                        response = client.request(method, path, json=body)
                        if response.status_code >= 400:
                            raise urllib.error.HTTPError(path, response.status_code, response.text, {}, None)
                        return response.json()
                api = TestApi('http://localhost', '')
                config = configparser.ConfigParser()
                config.read_string('[data-plane]\nid=first\nnamespace=orders\nname=First\nhost=host\n[delivery-team]\nid=team\nname=Team\n[user]\nid=user-first\nteam_id=team\n')
                setup.register_plane(config, api)
                setup.register_plane(config, api)
                config['data-plane']['id'] = 'second'
                config['user']['id'] = 'user-second'
                setup.register_plane(config, api)
                teams = client.get('/api/teams').json()
                team = next(item for item in teams if item['id'] == 'team')
                self.assertEqual(len(team['namespaceScopes']), 2)
                capabilities = client.get('/api/capabilities').json()
                self.assertEqual(len([item for item in capabilities if item['dataPlaneId'] in ('first','second')]), 2)

    def test_crlf_bom_and_literal_secrets_have_identical_meaning(self):
        with tempfile.TemporaryDirectory() as folder:
            ini = Path(folder) / 'settings.ini'
            ini.write_bytes(b'\xef\xbb\xbf[control-plane]\r\nadmin_key=a#b%$;$(echo not-executed)\r\n[setup]\r\ninstall_root=/opt/mina\r\n')
            values = environment(read_config(ini))
        self.assertEqual(values['ADMIN_KEY'], 'a#b%$;$(echo not-executed)')
        self.assertEqual(values['MINA_INSTALL_ROOT'], '/opt/mina')

    def test_config_rejects_multiline_values_and_shell_variable_names(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read_string('[setup]\npython=one\n two\n')
        with self.assertRaises(ValueError): environment(config)
        config.read_string('[runtime]\ninvalid.key=one\n')
        with self.assertRaises(ValueError): environment(config)

    def test_only_not_found_allows_resource_creation(self):
        api = setup.Api('http://localhost', 'test-key')
        missing = urllib.error.HTTPError('http://localhost', 404, 'missing', {}, None)
        with patch.object(api, 'request', side_effect=[missing, {'id': 'plane'}]) as request:
            self.assertEqual(api.upsert('/api/data-planes', 'plane', {}), {'id': 'plane'})
            self.assertEqual(request.call_args.args[0], 'POST')
        denied = urllib.error.HTTPError('http://localhost', 401, 'denied', {}, None)
        with patch.object(api, 'request', side_effect=denied) as request:
            with self.assertRaises(urllib.error.HTTPError): api.upsert('/api/data-planes', 'plane', {})
            self.assertEqual(request.call_count, 1)

    def test_transfer_bundle_has_lf_shells_and_excludes_machine_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for filename, payload in [('scripts/linux/example.sh', b'\xef\xbb\xbf#!/bin/bash\r\necho ok\r\n'), ('administrator/data/secret.json', b'secret'), ('backend/.venv/config', b'local'), ('docs/LINUX_SETUP.md', b'guide'), ('docs/SAP_INTEGRATION.md', b'guide'), ('docs/sap-soak-config.example.json', b'{}')]:
                path = root / filename; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
            output = root / 'transfer.zip'
            with patch.object(setup, 'SOFTWARE', root): setup.bundle(output)
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertEqual(archive.read('software/scripts/linux/example.sh'), b'#!/bin/bash\necho ok\n')
                self.assertFalse(any('/data/' in name or '/.venv/' in name for name in names))
                self.assertIn('software/docs/LINUX_SETUP.md', names)

    def test_script_normalization_needs_no_manual_linux_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); script = root / 'scripts/linux/run.sh'; script.parent.mkdir(parents=True)
            script.write_bytes(b'\xef\xbb\xbf#!/bin/bash\r\nset -eu\r\n')
            setup.normalize_scripts(root)
            self.assertEqual(script.read_bytes(), b'#!/bin/bash\nset -eu\n')

    def test_another_plane_cannot_reuse_existing_state_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); software = root/'software'; launcher = software/'scripts/linux/start-control-plane.sh'
            launcher.parent.mkdir(parents=True); launcher.write_text('#!/bin/bash\n')
            state = root/'agent/shared'; state.mkdir(parents=True)
            (state/'data-plane.ini').write_text('[data-plane]\nid=first\n')
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(f'[setup]\ninstall_root={root}\nsource_root={software}\npython={sys.executable}\n[control-plane]\nadmin_key=test\ncontrol_plane_url=http://localhost:19080\n[data-plane]\nid=second\nname=Second\nhost=host\nnamespace=orders\nstate_dir={state}\n')
            with patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '3.12\n')), \
                    self.assertRaisesRegex(ValueError, 'another Data Plane'):
                setup.settings(config, 'data-plane', root/'second.ini')

    def test_data_plane_setup_keeps_control_plane_installation_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'software'; config_file = root/'operator.ini'
            config = configparser.ConfigParser(interpolation=None)
            config.read_string('[setup]\nstart=false\n[control-plane]\ncontrol_plane_url=http://localhost:19080\nadmin_key=test\n[data-plane]\nid=plane\nname=Plane\nhost=host\nnamespace=orders\n')
            with config_file.open('w') as handle: config.write(handle)
            env = {'MINA_AGENT_ROOT': str(root/'agent/plane')}
            with patch.object(setup, 'Api'), patch.object(setup, 'bash') as bash, patch.object(setup, 'register_plane') as register:
                setup.data_plane(config, config_file, 'setup', root, source, env)
            self.assertEqual(bash.call_args.args[0], source/'scripts/linux/install-runtime.sh')
            register.assert_called_once()
            self.assertTrue((root/'agent/plane/data-plane.ini').exists())
            self.assertFalse((root/'control-plane').exists())

    def test_control_plane_install_preserves_data_and_does_not_install_data_plane(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); software = root / 'software'; launcher = software / 'scripts/linux/start-control-plane.sh'
            launcher.parent.mkdir(parents=True); launcher.write_text('#!/bin/bash\n')
            archive = root / 'admin.tar.gz'
            with tarfile.open(archive, 'w:gz') as output:
                data = b'Linux executable'; info = tarfile.TarInfo('MinaAdministrator/MinaAdministrator'); info.size = len(data); output.addfile(info, io.BytesIO(data))
                data = b'internal'; info = tarfile.TarInfo('MinaAdministrator/_internal/library'); info.size = len(data); output.addfile(info, io.BytesIO(data))
                data = b'shipped defaults'; info = tarfile.TarInfo('MinaAdministrator/mina-control-plane.ini'); info.size = len(data); output.addfile(info, io.BytesIO(data))
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(f'[setup]\nversion=1.0.5\nadministrator_archive={archive}\nstart=false\n[control-plane]\napi_key=test\nsecret_key=stable\n')
            ini = root / 'control-plane/mina-control-plane.ini'
            ini.parent.mkdir()
            with ini.open('w') as handle: config.write(handle)
            state = root / 'control-plane-data/keep.json'; state.parent.mkdir(); state.write_text('existing')
            config['control-plane']['install_local_runtime'] = 'true'
            with ini.open('w') as handle: config.write(handle)
            with patch.object(setup, 'bash') as bash: setup.control_plane(config, ini, 'setup', root, software, {})
            self.assertEqual(bash.call_args.args[0], software / 'scripts/linux/install-runtime.sh')
            self.assertEqual(state.read_text(), 'existing')
            self.assertTrue((root / 'control-plane/_internal/library').is_file())
            self.assertIn('secret_key = stable', ini.read_text())
            self.assertFalse((root / 'agent').exists())

    def test_readiness_requires_authenticated_local_capability(self):
        from unittest.mock import Mock
        api = Mock()
        api.request.side_effect = [{'status':'ok', 'component':'mina-control-plane', 'runtimeAdapterConfigured':True}, {},
                                   [{'id':'integration-runtime-local', 'dataPlaneId':'localhost', 'namespace':'default', 'state':'PROVISIONED'}]]
        setup.verify_control_plane(api, True, Path('administrator.log'))
        self.assertEqual([call.args[1] for call in api.request.call_args_list], ['/api/health', '/api/session', '/api/capabilities'])
        api.request.side_effect = [{'status':'ok', 'component':'mina-control-plane', 'runtimeAdapterConfigured':True}, {}, []]
        with self.assertRaisesRegex(ValueError, 'target is unavailable'):
            setup.verify_control_plane(api, True, Path('administrator.log'))

    def test_minimal_linux_missing_build_tools_and_venv_are_reported(self):
        config = configparser.ConfigParser()
        config.read_string('[setup]\nversion=1.0.5\n[control-plane]\ninstall_local_runtime=true\n')
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            with patch.object(setup.shutil, 'which', side_effect=lambda name: None if name in ('objdump','objcopy') else name), \
                    self.assertRaisesRegex(ValueError, 'objdump, objcopy.*binutils'):
                setup.check_linux_prerequisites(config, 'control-plane', source, {'MINA_PYTHON':'python3.12'})
            with patch.object(setup.shutil, 'which', side_effect=lambda name: name), \
                    patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), \
                    self.assertRaisesRegex(ValueError, 'python3.12-venv'):
                setup.check_linux_prerequisites(config, 'control-plane', source, {'MINA_PYTHON':'python3.12'})
            with patch.object(setup.shutil, 'which', side_effect=lambda name: name), \
                    patch.object(setup.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1)]), \
                    self.assertRaisesRegex(ValueError, 'libpython3.12'):
                setup.check_linux_prerequisites(config, 'control-plane', source, {'MINA_PYTHON':'python3.12'})

    def test_archive_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root / 'bad.tar.gz'
            with tarfile.open(archive, 'w:gz') as output:
                info = tarfile.TarInfo('../escaped'); info.size = 1; output.addfile(info, io.BytesIO(b'x'))
            config = configparser.ConfigParser(); config.read_string(f'[setup]\nversion=1.0.5\nadministrator_archive={archive}\nstart=false\n')
            with self.assertRaises(tarfile.TarError): setup.control_plane(config, root / 'settings.ini', 'setup', root, root, {})
            self.assertFalse((root.parent / 'escaped').exists())

    def test_existing_team_scopes_are_preserved_for_additional_plane(self):
        config = configparser.ConfigParser(); config.read_string('[control-plane]\n[data-plane]\nid=second\nnamespace=orders\nname=Second\nhost=host\n[delivery-team]\nid=team\nname=Team\n')
        old = {'dataPlaneId': 'first', 'namespace': 'orders'}
        api = setup.Api('http://localhost', 'test')
        with patch.object(api, 'request', return_value=[{'id': 'team', 'namespaceScopes': [old]}]), patch.object(api, 'upsert') as upsert:
            setup.register_plane(config, api)
            scopes = upsert.call_args.args[2]['namespaceScopes']
        self.assertEqual(scopes, [old, {'dataPlaneId': 'second', 'namespace': 'orders'}])

    def test_all_shipped_shell_scripts_are_lf_without_bom(self):
        root = LINUX.parent
        for path in root.rglob('*.sh'):
            data = path.read_bytes()
            self.assertNotIn(b'\r\n', data, str(path))
            self.assertFalse(data.startswith(b'\xef\xbb\xbf'), str(path))

if __name__ == '__main__': unittest.main()
