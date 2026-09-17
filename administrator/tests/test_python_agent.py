import asyncio
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from administrator.agent.bootstrap import extract_python_package
from administrator.agent.main import PythonAgent, Settings
from administrator.app import main as control_plane


def package_bytes(*, unsafe=False):
    body = io.BytesIO()
    with zipfile.ZipFile(body, 'w') as archive:
        archive.writestr('manifest.json', json.dumps({
            'applicationId': 'orders', 'pythonSource': {'entrypoint': 'application/main.py', 'formatVersion': 2}}))
        archive.writestr('../outside.txt' if unsafe else 'application/main.py', 'print("ready")\n')
    return body.getvalue()


class PythonAgentTests(unittest.TestCase):
    def test_agent_heartbeat_reports_real_host_capacity(self):
        with tempfile.TemporaryDirectory() as folder:
            agent = PythonAgent(Settings('https://control.example', 'agent-key', 'remote-host', state_dir=Path(folder)))
            sent = []
            async def request(_method, _path, **kwargs): sent.append(kwargs['json'])
            agent._request = request
            asyncio.run(agent._heartbeat())
            self.assertIn('diskFreeBytes', sent[0]['telemetry']['system'])
            self.assertEqual(sent[0]['processCount'], 0)
            asyncio.run(agent.close())

    def test_local_agent_log_tail_is_bounded(self):
        deployment_id = '11111111-2222-3333-4444-555555555555'
        with tempfile.TemporaryDirectory() as folder:
            agent = PythonAgent(Settings('https://control.example', 'agent-key', 'remote-host', state_dir=Path(folder)))
            directory = agent._deployment_dir(deployment_id)
            directory.mkdir()
            (directory / 'instance-1.log').write_text(''.join(f'line {index}\n' for index in range(400)), encoding='utf-8')
            logs = agent._local_logs(deployment_id, 1)
            self.assertEqual(len(logs[0]['lines']), 200)
            self.assertEqual(logs[0]['lines'][-1], 'line 399')
            asyncio.run(agent.close())

    def test_control_plane_exposes_undeploy_tombstone_to_agent(self):
        record = {'id': '11111111-2222-3333-4444-555555555555', 'dataPlaneId': 'remote-host',
                  'state': 'UNDEPLOYED'}
        with patch.object(control_plane, 'deployment_inventory', return_value=[record]), \
             patch.object(control_plane, 'deployment_secret_values', return_value={}):
            self.assertEqual(control_plane.agent_deployment_record('remote-host')[0]['state'], 'UNDEPLOYED')

    def test_bootstrap_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'Unsafe Python package path'):
                extract_python_package(package_bytes(unsafe=True), Path(folder) / 'work')

    def test_local_agent_launches_python_entry_and_keeps_secrets_out_of_arguments(self):
        class Process:
            pid = 12345
            returncode = None
            def poll(self): return None
            def terminate(self): self.returncode = 0
            def wait(self, timeout=None): return 0
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings('https://control.example', 'agent-key', 'remote-host', state_dir=Path(folder))
            agent = PythonAgent(settings)
            captured, reported = [], []
            async def package(_item): return package_bytes(), ''
            async def report(_item, **values): reported.append(values)
            agent._package, agent._report = package, report
            item = {'id': '11111111-2222-3333-4444-555555555555', 'applicationId': 'orders',
                    'packageId': 'orders:1.0.0', 'state': 'RUNNING', 'environment': 'dev',
                    'starterStates': {'main': 'STARTED'}, 'desiredInstances': 1,
                    'secrets': {'database.password': 'redacted-in-test'}}
            with patch('administrator.agent.main.subprocess.Popen', side_effect=lambda *args, **kwargs: (captured.append((args, kwargs)) or Process())):
                asyncio.run(agent._reconcile_local(item))
            args, options = captured[0]
            self.assertEqual(args[0][1:3], ['-m', 'application.main'])
            self.assertNotIn('redacted-in-test', str(args))
            self.assertEqual(options['env']['FABRIC_ENABLED_STARTERS'], '["main"]')
            self.assertEqual(reported[0]['state'], 'RUNNING')
            async def reconcile_changed():
                await agent._reconcile_local(item)
                item['starterStates']['main'] = 'STOPPED'
                await agent._reconcile_local(item)
            with patch('administrator.agent.main.subprocess.Popen', side_effect=lambda *args, **kwargs: (captured.append((args, kwargs)) or Process())):
                asyncio.run(reconcile_changed())
            self.assertEqual(len(captured), 2, 'unchanged configuration should reuse the process; a starter change should restart it')
            self.assertEqual(captured[-1][1]['env']['FABRIC_ENABLED_STARTERS'], '[]')
            asyncio.run(agent.close())


if __name__ == '__main__':
    unittest.main()
