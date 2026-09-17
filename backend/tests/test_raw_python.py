"""Standalone compiler tests that do not need the Studio API dependencies."""
import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / 'app' / 'raw_python.py'
spec = importlib.util.spec_from_file_location('raw_python_compiler', MODULE)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


class RawPythonTests(unittest.TestCase):
    def project(self):
        return {
            'id': 'example', 'name': 'Example', 'schemas': [],
            'resources': [{'id': 'k1', 'type': 'kafka', 'name': 'Memory Kafka', 'config': {'mode': 'memory'}}],
            'tasks': [
                {'id': 'main', 'name': 'Main', 'kind': 'starter', 'groups': [], 'activities': [
                    {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                    {'id': 'c', 'type': 'call_task', 'name': 'Call', 'config': {'taskId': 'child', 'inputMappings': {'value': '${input.value}'}}},
                    {'id': 'p', 'type': 'kafka', 'name': 'Publish', 'config': {'operation': 'publish', 'resourceId': 'k1', 'topic': 'orders', 'message': '${last}'}},
                    {'id': 'r', 'type': 'kafka', 'name': 'Receive', 'config': {'operation': 'receive', 'resourceId': 'k1', 'topic': 'orders'}},
                    {'id': 'e', 'type': 'end', 'name': 'End', 'config': {}}],
                 'transitions': [{'source': a, 'target': b} for a, b in zip('scpr', 'cpre')]},
                {'id': 'child', 'name': 'Child', 'kind': 'subtask', 'groups': [], 'activities': [
                    {'id': 'cs', 'type': 'start', 'name': 'Start', 'config': {}},
                    {'id': 'ce', 'type': 'end', 'name': 'End', 'config': {'inputMappings': {'result.answer.value': '${input.value}'}}}],
                 'transitions': [{'source': 'cs', 'target': 'ce'}]},
            ],
        }

    def test_generated_python_runs_without_fabric_runtime_or_json_descriptors(self):
        files = compiler.raw_python_files(self.project(), {'dev': [{'key': 'x', 'value': 1, 'data_type': 'integer'}]})
        self.assertTrue(all(name.endswith('.py') for name in files))
        self.assertNotIn('fabric_dsl.py', '\n'.join(files))
        with tempfile.TemporaryDirectory() as folder:
            for name, body in files.items():
                path = Path(folder) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application.main import run_task
                result = asyncio.run(run_task('main', {'value': 42}, 'dev'))
                self.assertEqual(result['count'], 1)
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'):
                        sys.modules.pop(name)

    def test_unsupported_semantics_are_rejected(self):
        project = self.project()
        project['tasks'][0]['groups'] = [{'id': 'g', 'type': 'transaction_jdbc'}]
        with self.assertRaisesRegex(ValueError, 'groups are not yet supported'):
            compiler.raw_python_files(project, {'dev': []})


if __name__ == '__main__':
    unittest.main()
