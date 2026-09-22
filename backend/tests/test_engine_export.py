"""Exercise selective engine exports in an isolated Python process."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'app' / 'raw_python.py'
SPEC = importlib.util.spec_from_file_location('engine_export_compiler', SOURCE)
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


class EngineExportTests(unittest.TestCase):
    def project(self, kind='log'):
        return dict(id='sample', name='Sample', resources=[], tasks=[dict(
            id='main', name='Main', kind='starter', groups=[],
            activities=[dict(id='a', type=kind, name='Activity', config={})], transitions=[])])

    def modules(self, project):
        return {Path(name).stem for name in compiler.engine_python_files(project, {'local': []})
                if name.startswith('application/engine/') and not name.endswith('__init__.py')}

    def test_unused_resources_do_not_pull_in_connectors(self):
        project = self.project()
        project['resources'] = [dict(id='sap', type='sap', name='Unused SAP', config={})]
        self.assertEqual(self.modules(project), {'runtime', 'models', 'mapper', 'time_utils'})

    def test_connector_dependency_closure(self):
        base = {'runtime', 'models', 'mapper', 'time_utils'}
        for kind, extra in [
            ('sap', {'sap', 'java_bridge'}), ('jdbc', {'jdbc', 'java_bridge', 'snowflake'}),
            ('ems', {'java_bridge'}), ('jms', {'java_bridge'}),
            ('pubsub', {'google_pubsub'}), ('amqp', {'amqp'}),
            ('snowflake', {'snowflake'}), ('dataweave', {'dataweave'}), ('kafka', set()),
        ]:
            with self.subTest(kind=kind):
                self.assertEqual(self.modules(self.project(kind)), base | extra)

    def test_subtasks_and_nested_transaction_groups_are_included(self):
        project = self.project()
        child = self.project('pubsub')['tasks'][0]
        child.update(id='child', kind='subtask', groups=[dict(
            id='tx', type='transaction_jdbc', name='Transaction', member_activity_ids=['a'],
            parent_group_id='outer', config={})])
        project['tasks'].append(child)
        self.assertTrue({'jdbc', 'java_bridge', 'google_pubsub'} <= self.modules(project))

    def test_reduced_package_imports_and_executes_without_optional_modules(self):
        project = self.project('start')
        files = compiler.engine_python_files(project, {'local': []})
        with tempfile.TemporaryDirectory() as directory:
            for name, body in files.items():
                path = Path(directory) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            result = subprocess.run([sys.executable, '-c',
                'import asyncio, sys; from application.main import run_task; '
                'asyncio.run(run_task("main", {"value": 42})); '
                'assert not any("application.engine." + m in sys.modules for m in '
                '["sap", "jdbc", "amqp", "snowflake", "java_bridge", "google_pubsub", "dataweave"])'],
                cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_selected_adapter_executes_after_lazy_import(self):
        project = self.project('jdbc')
        project['resources'] = [dict(id='db', type='jdbc', name='SQLite', config={'driver': 'sqlite', 'database': ':memory:'})]
        project['tasks'][0]['activities'][0]['config'] = dict(resourceId='db', operation='query', sql='SELECT 42 AS answer')
        files = compiler.engine_python_files(project, {'local': []})
        with tempfile.TemporaryDirectory() as directory:
            for name, body in files.items():
                path = Path(directory) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            result = subprocess.run([sys.executable, '-c',
                'import asyncio; from application.main import run_task; '
                'asyncio.run(run_task("main"))'], cwd=directory,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
