import json
import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
import types
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from administrator.app.compat import env_value, application_environment
from administrator.agent.main import Settings, PythonAgent


class UpgradeCompatibilityTests(unittest.TestCase):
    def test_environment_precedence_and_empty_new_key_cannot_disable_old_auth(self):
        with patch.dict(os.environ, {'FABRIC_ADMIN_API_KEY': 'old', 'MINA_ADMIN_API_KEY': ''}, clear=True):
            self.assertEqual(env_value('MINA_ADMIN_API_KEY'), 'old')
            os.environ['MINA_ADMIN_API_KEY'] = 'new'
            self.assertEqual(env_value('MINA_ADMIN_API_KEY'), 'new')

    def test_old_control_plane_configuration_still_requires_authentication(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {k:v for k,v in os.environ.items() if not k.startswith(('MINA_', 'FABRIC_'))}
            env.update(FABRIC_ADMIN_API_KEY='upgrade-test-key', FABRIC_ADMIN_DATA_DIR=folder,
                       FABRIC_ADMIN_SECRET_KEY='encryption-test-key')
            code = '''
from administrator.app import main
from fastapi.testclient import TestClient
import os, json
with TestClient(main.app) as client:
    assert client.get('/api/session').status_code == 401
    assert client.get('/api/session', headers={'X-Admin-Key':'upgrade-test-key'}).status_code == 200
    assert str(main.DATA_DIR) == os.environ['FABRIC_ADMIN_DATA_DIR']
    assert main.env_value('MINA_ADMIN_SECRET_KEY') == 'encryption-test-key'
print('upgrade-auth-ok')
'''
            result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('upgrade-auth-ok', result.stdout)

    def test_agent_accepts_old_service_configuration(self):
        with patch.dict(os.environ, {'FABRIC_CONTROL_PLANE_URL':'https://example.test/', 'FABRIC_AGENT_KEY':'test', 'FABRIC_DATA_PLANE_ID':'plane'}, clear=True):
            settings = Settings.from_environment()
            self.assertEqual(settings.control_plane_url, 'https://example.test')
            self.assertEqual(settings.key, 'test')
            self.assertEqual(settings.plane_id, 'plane')

    def test_managed_launch_contract_sets_identical_aliases(self):
        values = {'MINA_SECRET_FILE':'/run/mina/secrets.json', 'MINA_ENABLED_STARTERS':'[]', 'MINA_ENVIRONMENT':'qa'}
        result = application_environment(values)
        for key, value in values.items():
            self.assertEqual(result[key], value)
            self.assertEqual(result[key.replace('MINA_', 'FABRIC_', 1)], value)

    def test_kubernetes_runtime_receives_legacy_secret_and_starter_contract(self):
        exceptions = types.ModuleType('kubernetes.client.exceptions')
        exceptions.ApiException = type('ApiException', (Exception,), {})
        with tempfile.TemporaryDirectory() as folder:
            agent = PythonAgent(Settings('https://example.test', 'test', 'plane', state_dir=Path(folder)))
            core, apps = MagicMock(), MagicMock()
            apps.read_namespaced_deployment.return_value = types.SimpleNamespace(status=types.SimpleNamespace(ready_replicas=1))
            agent._kubernetes = lambda: (core, apps)
            agent._report = AsyncMock()
            item = {'id':'upgrade', 'namespace':'default', 'state':'RUNNING', 'pythonSource':{'entrypoint':'application/main.py'},
                    'packageId':'app:1.0', 'environment':'qa', 'starterStates':{'listener':'STOPPED'}, 'desiredInstances':1}
            with patch.dict(sys.modules, {'kubernetes.client.exceptions':exceptions}):
                asyncio.run(agent._reconcile_kubernetes(item))
            body = apps.create_namespaced_deployment.call_args.args[1]
            entries = body['spec']['template']['spec']['containers'][0]['env']
            values = {entry['name']:entry['value'] for entry in entries}
            self.assertEqual(len(entries), len(values))
            self.assertEqual(values['FABRIC_SECRET_FILE'], values['MINA_SECRET_FILE'])
            self.assertEqual(values['FABRIC_ENABLED_STARTERS'], '[]')
            self.assertEqual(values['FABRIC_ENVIRONMENT'], 'qa')
            asyncio.run(agent.close())
