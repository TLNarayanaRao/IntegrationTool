"""Standalone compiler tests that do not need the Studio API dependencies."""
import asyncio
import importlib.util
import json
import sqlite3
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / 'app' / 'raw_python.py'
spec = importlib.util.spec_from_file_location('raw_python_compiler', MODULE)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


class RawPythonTests(unittest.TestCase):
    def project(self):
        return {
            'id': 'example', 'name': 'Example', 'schemas': [],
            'resources': [{'id': 'k1', 'type': 'kafka', 'name': 'Memory Kafka', 'config': {'mode': 'memory', 'bootstrapServers': '${properties.kafka.servers}'}}],
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
        files = compiler.raw_python_files(self.project(), {'dev': [{'key': 'x', 'value': 1, 'data_type': 'integer'}, {'key': 'kafka.servers', 'value': 'localhost:9092', 'data_type': 'string'}]})
        self.assertTrue(all(name.endswith('.py') for name in files))
        self.assertNotIn('fabric_dsl.py', '\n'.join(files))
        self.assertNotIn(b'${', files['application/config.py'])
        self.assertNotIn(b'${', files['application/tasks/task_0_main.py'])
        self.assertNotIn(b'TRANSITIONS =', files['application/tasks/task_0_main.py'])
        self.assertNotIn('application/inbound_http.py', files)
        self.assertNotIn(b"reasons = {200:'OK'", files['application/main.py'])
        self.assertNotIn(b'http_listener', files['application/main.py'])
        self.assertNotIn('application/activities.py', files)
        self.assertFalse(any(name.startswith('application/native/') for name in files))
        connector_source = files['application/connectors.py']
        self.assertIn(b'async def kafka', connector_source)
        self.assertIn(b'async def close_kafka', connector_source)
        self.assertIn(b'await connectors.close_kafka()', files['application/main.py'])
        self.assertNotIn(b'async def jms', connector_source)
        self.assertNotIn(b'async def pubsub', connector_source)
        self.assertNotIn(b'async def sap', connector_source)
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

    def test_minimal_project_links_only_structural_runtime(self):
        project = self.project()
        project['resources'] = [{'id': 'unused-snowflake', 'type': 'snowflake', 'name': 'Unused', 'config': {'account': 'unused'}}]
        project['schemas'] = [{'id': 'unused-schema', 'name': 'unused.xsd', 'content': '<schema/>'}]
        project['tasks'] = [{'id': 'main', 'name': 'Minimal', 'kind': 'starter', 'groups': [],
            'activities': [{'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                           {'id': 'e', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 's', 'target': 'e'}]}]
        files = compiler.raw_python_files(project, {'dev': [{'key': 'unused.value', 'value': 'discard-me', 'data_type': 'string'}]})
        self.assertNotIn('application/activities.py', files)
        self.assertNotIn('application/connectors.py', files)
        self.assertNotIn('application/inbound_http.py', files)
        self.assertFalse(any(name.startswith('application/native/') for name in files))
        self.assertIn(b"CAPABILITIES = ('structural',)", files['application/capabilities.py'])
        self.assertNotIn(b'unused-snowflake', files['application/config.py'])
        self.assertNotIn(b'unused.xsd', files['application/config.py'])
        self.assertNotIn(b'discard-me', files['application/config.py'])
        core = files['application/core.py']
        for unused in (b"kind == 'timer'", b"kind == 'kafka'", b"kind == 'sap'", b"kind == 'file'", b"kind == 'mapper'"):
            self.assertNotIn(unused, core)
        self.assertNotIn(b'def group_lock', core)
        self.assertNotIn(b'group_lock', files['application/tasks/task_0_main.py'])

    def test_artifact_linker_follows_resource_and_schema_dependencies(self):
        project = self.project()
        project['resources'] = [
            {'id': 'logical-db', 'type': 'jdbc', 'name': 'Logical DB', 'config': {'connectionId': 'physical-db'}},
            {'id': 'physical-db', 'type': 'jdbc', 'name': 'Physical DB', 'config': {'url': '${properties.db.url}'}},
            {'id': 'unused-db', 'type': 'jdbc', 'name': 'Unused DB', 'config': {'url': 'discard'}},
        ]
        project['schemas'] = [
            {'id': 'order', 'name': 'order.xsd', 'content': '<xs:include schemaLocation="common/types.xsd"/>'},
            {'id': 'types', 'name': 'types.xsd', 'content': '<xs:schema/>'},
            {'id': 'unused', 'name': 'unused.xsd', 'content': '<xs:schema/>'},
        ]
        project['tasks'] = [{'id': 'main', 'name': 'Linked', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'q', 'type': 'jdbc', 'name': 'Query', 'config': {'operation': 'query', 'resourceId': 'logical-db', 'schemaId': 'order'}},
                {'id': 'e', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 's', 'target': 'q'}, {'source': 'q', 'target': 'e'}]}]
        resources, schemas = compiler._project_artifact_closure(project)
        self.assertEqual([item['id'] for item in resources], ['logical-db', 'physical-db'])
        self.assertEqual([item['id'] for item in schemas], ['order', 'types'])

    def test_dynamic_schema_reference_conservatively_keeps_schema_options(self):
        project = self.project()
        project['resources'] = []
        project['schemas'] = [
            {'id': 'one', 'name': 'one.xsd', 'content': '<schema/>'},
            {'id': 'two', 'name': 'two.xsd', 'content': '<schema/>'},
        ]
        project['tasks'] = [{'id': 'main', 'name': 'Dynamic schema', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'p', 'type': 'xml', 'name': 'Parse', 'config': {'operation': 'parse', 'schemaId': '${properties.schema.id}'}},
                {'id': 'e', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 's', 'target': 'p'}, {'source': 'p', 'target': 'e'}]}]
        _, schemas = compiler._project_artifact_closure(project)
        self.assertEqual([item['id'] for item in schemas], ['one', 'two'])

    def test_linker_registry_covers_every_supported_studio_operation(self):
        compiler._validate_capability_registry()
        missing = [(kind, operation) for kind, operation in compiler.SUPPORTED
                   if compiler._activity_capabilities(kind, operation) is None]
        self.assertEqual(missing, [])
        self.assertEqual(compiler.SUPPORTED_GROUP_TYPES, {
            'if', 'for_each', 'iterate', 'while', 'repeat', 'repeat_on_error',
            'critical_section', 'transaction_jdbc',
        })

    def test_future_supported_operation_cannot_be_silently_omitted(self):
        future = ('future_connector', 'future_operation')
        compiler.SUPPORTED.add(future)
        try:
            with self.assertRaisesRegex(RuntimeError, 'future_connector/future_operation'):
                compiler._validate_capability_registry()
        finally:
            compiler.SUPPORTED.remove(future)

    def test_capability_linking_does_not_depend_on_project_or_task_identity(self):
        first = self.project()
        second = self.project()
        second['id'] = 'customer-created-project-947'
        second['name'] = 'Unseen customer application'
        for index, task in enumerate(second['tasks']):
            task['name'] = f'Arbitrary task {index}'
        self.assertEqual(compiler._project_capabilities(first), compiler._project_capabilities(second))

    def test_unsupported_semantics_are_rejected(self):
        project = self.project()
        project['tasks'][0]['groups'] = [{'id': 'g', 'type': 'transaction_jdbc'}]
        with self.assertRaisesRegex(ValueError, 'group is empty'):
            compiler.raw_python_files(project, {'dev': []})

    def test_direct_archive_runs_as_zip_and_as_script_without_source_edits(self):
        files = compiler.raw_python_files(self.project(), {'dev': [
            {'key': 'kafka.servers', 'value': 'localhost:9092', 'data_type': 'string'},
        ]})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive_path = root / 'example.pyifpkg'
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, body in files.items():
                    archive.writestr(name, body)
            args = ['--task', 'main', '--input', '{"value":42}']
            result = subprocess.run([sys.executable, str(archive_path), *args], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['count'], 1)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(root / 'unpacked')
            script = subprocess.run([sys.executable, str(root / 'unpacked' / 'run.py'), *args], capture_output=True, text=True, timeout=20)
            self.assertEqual(script.returncode, 0, script.stderr)
            self.assertEqual(json.loads(script.stdout)['count'], 1)
            qualified = subprocess.run([sys.executable, str(root / 'unpacked' / 'run.py'), '--qualify-task', 'main', '--input', '{"value":42}', '--iterations', '5', '--concurrency', '2'], capture_output=True, text=True, timeout=20)
            self.assertEqual(qualified.returncode, 0, qualified.stderr)
            report = json.loads(qualified.stdout); self.assertTrue(report['passed']); self.assertEqual(report['iterations'], 5)

    def test_direct_connector_adapters_execute_ems_and_sap_parser(self):
        project = self.project()
        project['resources'] = [
            {'id': 'ems', 'type': 'ems', 'name': 'Memory EMS', 'config': {'mode': 'memory'}},
            {'id': 'sap', 'type': 'sap', 'name': 'Mock SAP', 'config': {'mode': 'mock'}},
        ]
        project['tasks'] = [{'id': 'main', 'name': 'Main', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'send', 'type': 'ems', 'name': 'Send', 'config': {'operation': 'send', 'resourceId': 'ems', 'destination': 'orders', 'message': '${input.value}'}},
                {'id': 'recv', 'type': 'ems', 'name': 'Receive', 'config': {'operation': 'queue_receiver', 'resourceId': 'ems', 'destination': 'orders', 'receiveTimeout': 100}},
                {'id': 'parse', 'type': 'sap', 'name': 'Parse', 'config': {'operation': 'idoc_parser', 'resourceId': 'sap', 'payload': '<IDOC><EDI_DC40><IDOCTYP>ORDERS05</IDOCTYP></EDI_DC40></IDOC>'}},
                {'id': 'e', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': a, 'target': b} for a, b in [('s', 'send'), ('send', 'recv'), ('recv', 'parse'), ('parse', 'e')]]}]
        files = compiler.raw_python_files(project, {'dev': []})
        self.assertIn('application/native/sap.py', files)
        self.assertIn('application/native/java_bridge.py', files)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            result = subprocess.run([sys.executable, str(root / 'run.py'), '--task', 'main', '--input', '{"value":"hello"}'], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('SAPIDoc', json.loads(result.stdout))

    def test_ems_starter_receives_events_without_manual_run(self):
        project = self.project()
        project['resources'] = [{'id': 'ems', 'type': 'ems', 'name': 'Memory EMS', 'config': {'mode': 'memory'}}]
        project['tasks'] = [{'id': 'main', 'name': 'Receiver', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 'start', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'recv', 'type': 'ems', 'name': 'Receive', 'config': {'operation': 'queue_receiver', 'resourceId': 'ems', 'destination': 'orders', 'receiveTimeout': 50}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 'start', 'target': 'recv'}, {'source': 'recv', 'target': 'end'}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application import connectors
                from application.main import run_application
                from application.registry import TASKS
                seen = []
                original = TASKS['main']
                async def record(ctx, **kwargs):
                    seen.append(kwargs['event_output']['body'])
                    return await original(ctx, **kwargs)
                TASKS['main'] = record
                async def exercise():
                    runner = asyncio.create_task(run_application('dev'))
                    await connectors._MEMORY_JMS.setdefault(('ems', 'orders'), asyncio.Queue()).put('first')
                    await connectors._MEMORY_JMS[('ems', 'orders')].put('second')
                    for _ in range(100):
                        if len(seen) == 2: break
                        await asyncio.sleep(.01)
                    runner.cancel()
                    try: await runner
                    except asyncio.CancelledError: pass
                asyncio.run(exercise())
                self.assertEqual(seen, ['first', 'second'])
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'):
                        sys.modules.pop(name)

    def test_if_group_compiles_to_direct_python_condition(self):
        project = self.project()
        project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Conditional', 'kind': 'starter',
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'assign', 'type': 'basic', 'name': 'Assign', 'config': {'operation': 'assign', 'variable': 'flag', 'value': 'yes'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 's', 'target': 'assign'}, {'source': 'assign', 'target': 'end'}],
            'groups': [{'id': 'if1', 'name': 'If', 'type': 'if', 'member_activity_ids': ['assign'], 'config': {'condition': '${input.enabled} == true'}}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        source = files['application/tasks/task_0_main.py']
        self.assertIn(b"if current == 'assign' and not ((resolve(Reference('input.enabled'), ctx) == True)):", source)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            for enabled, expected in [(True, {'name': 'flag', 'value': 'yes'}), (False, {'enabled': False})]:
                result = subprocess.run([sys.executable, str(root / 'run.py'), '--task', 'main', '--input', json.dumps({'enabled': enabled})], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)

    def test_parallel_success_branches_compile_to_asyncio_gather(self):
        project = self.project()
        project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Fan Out', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'a', 'type': 'basic', 'name': 'A', 'config': {'operation': 'assign', 'variable': 'branch', 'value': 'A'}},
                {'id': 'b', 'type': 'basic', 'name': 'B', 'config': {'operation': 'assign', 'variable': 'branch', 'value': 'B'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 's', 'target': 'a'}, {'source': 's', 'target': 'b'},
                            {'source': 'a', 'target': 'end'}, {'source': 'b', 'target': 'end'}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        self.assertIn(b'await asyncio.gather(run(ctx.fork(), start_at=\'a\'), run(ctx.fork(), start_at=\'b\'))',
                      files['application/tasks/task_0_main.py'])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            result = subprocess.run([sys.executable, str(root / 'run.py'), '--task', 'main'], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'name': 'branch', 'value': 'B'})

    def test_iterate_group_uses_current_element_and_accumulates(self):
        project = self.project()
        project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Iterate', 'kind': 'starter',
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'work', 'type': 'basic', 'name': 'Work', 'config': {'operation': 'assign', 'variable': 'item', 'value': '${vars.currentElement}'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {'inputMappings': {'result': '${vars.processed}'}}}],
            'transitions': [{'source': 's', 'target': 'work'}, {'source': 'work', 'target': 'end'}],
            'groups': [{'id': 'items', 'name': 'Items', 'type': 'iterate', 'member_activity_ids': ['work'],
                        'config': {'source': '${input.orders}', 'accumulateOutput': True, 'accumulatorVariable': 'processed'}}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            result = subprocess.run([sys.executable, str(root / 'run.py'), '--task', 'main', '--input', '{"orders":["A","B"]}'], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [{'name': 'item', 'value': 'A'}, {'name': 'item', 'value': 'B'}])

    def test_repeat_group_emits_bounded_python_loop(self):
        project = self.project()
        project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Repeat', 'kind': 'starter',
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'work', 'type': 'basic', 'name': 'Work', 'config': {'operation': 'assign', 'variable': 'seen', 'value': '${vars.index}'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {'inputMappings': {'result': '${vars.seen}'}}}],
            'transitions': [{'source': 's', 'target': 'work'}, {'source': 'work', 'target': 'end'}],
            'groups': [{'id': 'repeat', 'name': 'Repeat', 'type': 'repeat', 'member_activity_ids': ['work'],
                        'config': {'condition': '${vars.index} >= 3', 'maxIterations': 5}}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            result = subprocess.run([sys.executable, str(root / 'run.py'), '--task', 'main'], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), 3)

    def test_jdbc_transaction_group_commits_and_rolls_back_same_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / 'orders.db'
            conn = sqlite3.connect(database)
            try:
                conn.execute('CREATE TABLE orders (value TEXT)')
                conn.commit()
            finally:
                conn.close()
            for failing in (False, True):
                project = self.project()
                project['resources'] = [{'id': 'db', 'type': 'jdbc', 'name': 'DB', 'config': {'driver': 'sqlite', 'url': str(database)}}]
                project['tasks'] = [{'id': 'main', 'name': 'Transaction', 'kind': 'starter',
                    'activities': [
                        {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                        {'id': 'insert', 'type': 'jdbc', 'name': 'Insert', 'config': {'operation': 'insert', 'resourceId': 'db', 'SqlStatement': "INSERT INTO orders(value) VALUES ('rollback')" if failing else "INSERT INTO orders(value) VALUES ('commit')"}},
                        {'id': 'next', 'type': 'throw' if failing else 'log', 'name': 'Next', 'config': {'message': 'failed' if failing else 'ok'}},
                        {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
                    'transitions': [{'source': 's', 'target': 'insert'}, {'source': 'insert', 'target': 'next'}, {'source': 'next', 'target': 'end'}],
                    'groups': [{'id': 'tx', 'type': 'transaction_jdbc', 'name': 'Transaction', 'member_activity_ids': ['insert', 'next'], 'config': {'resourceId': 'db'}}]}]
                files = compiler.raw_python_files(project, {'dev': []})
                export_root = root / ('failure' if failing else 'success')
                for name, body in files.items():
                    path = export_root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                result = subprocess.run([sys.executable, str(export_root / 'run.py'), '--task', 'main'], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode != 0, failing, result.stderr)
            conn = sqlite3.connect(database)
            try:
                values = [row[0] for row in conn.execute('SELECT value FROM orders')]
            finally:
                conn.close()
            self.assertEqual(values, ['commit'])

    def test_critical_section_serializes_concurrent_generated_tasks(self):
        project = self.project()
        project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Critical', 'kind': 'starter',
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'work', 'type': 'basic', 'name': 'Work', 'config': {'operation': 'sleep', 'duration': 100, 'unit': 'milliseconds'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 's', 'target': 'work'}, {'source': 'work', 'target': 'end'}],
            'groups': [{'id': 'lock', 'type': 'critical_section', 'name': 'Locked', 'member_activity_ids': ['work'], 'config': {'lockName': 'orders'}}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application.main import run_task
                started = time.monotonic()
                async def concurrent_runs():
                    return await asyncio.gather(run_task('main', {}, 'dev'), run_task('main', {}, 'dev'))
                asyncio.run(concurrent_runs())
                self.assertGreaterEqual(time.monotonic() - started, .18)
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'):
                        sys.modules.pop(name)

    def test_repeat_on_error_retries_generated_body_from_property(self):
        project = self.project()
        project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Retry', 'kind': 'starter',
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'work', 'type': 'basic', 'name': 'Work', 'config': {'operation': 'assign', 'variable': 'done', 'value': True}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 's', 'target': 'work'}, {'source': 'work', 'target': 'end'}],
            'groups': [{'id': 'retry', 'type': 'repeat_on_error', 'name': 'Retry', 'member_activity_ids': ['work'],
                        'config': {'stopCondition': '${vars.index} >= 5', 'retryCount': '${properties.retryCount}', 'retryIntervalSeconds': 0}}]}]
        files = compiler.raw_python_files(project, {'dev': [{'key': 'retryCount', 'value': 3, 'data_type': 'integer'}]})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application.main import run_task
                from application.tasks import task_0_main
                original = task_0_main.execute_with_policy
                attempts = []
                async def flaky(kind, cfg, ctx, activity_id, name):
                    if activity_id == 'work':
                        attempts.append(ctx.variables.get('index'))
                        if len(attempts) < 3: raise RuntimeError('temporary')
                    return await original(kind, cfg, ctx, activity_id, name)
                task_0_main.execute_with_policy = flaky
                result = asyncio.run(run_task('main', {}, 'dev'))
                self.assertEqual(result, {'name': 'done', 'value': True})
                self.assertEqual(attempts, [1, 2, 3])
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'):
                        sys.modules.pop(name)

    def test_nested_if_groups_compile_without_runtime_descriptors(self):
        project = self.project()
        project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Nested', 'kind': 'starter',
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'outer_a', 'type': 'basic', 'name': 'Outer A', 'config': {'operation': 'assign', 'variable': 'a', 'value': 1}},
                {'id': 'inner_work', 'type': 'basic', 'name': 'Inner', 'config': {'operation': 'assign', 'variable': 'inner', 'value': 2}},
                {'id': 'outer_b', 'type': 'basic', 'name': 'Outer B', 'config': {'operation': 'assign', 'variable': 'b', 'value': 3}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 's', 'target': 'outer_a'}, {'source': 'outer_a', 'target': 'inner_work'},
                            {'source': 'inner_work', 'target': 'outer_b'}, {'source': 'outer_b', 'target': 'end'}],
            'groups': [
                {'id': 'outer', 'type': 'if', 'name': 'Outer', 'member_activity_ids': ['outer_a', 'inner', 'outer_b'], 'config': {'condition': '${input.outer}'}},
                {'id': 'inner', 'type': 'if', 'name': 'Inner', 'parent_group_id': 'outer', 'member_activity_ids': ['inner_work'], 'config': {'condition': '${input.inner}'}}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application.core import Context
                from application.tasks.task_0_main import run
                for values, expected in [({'outer': False, 'inner': True}, set()),
                                         ({'outer': True, 'inner': False}, {'outer_a', 'outer_b'}),
                                         ({'outer': True, 'inner': True}, {'outer_a', 'inner_work', 'outer_b'})]:
                    context = Context(values, {}, {})
                    asyncio.run(run(context))
                    self.assertEqual(set(context.outputs) - {'s', 'end'}, expected)
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'):
                        sys.modules.pop(name)

    def test_client_acknowledge_requeues_failed_delivery_and_confirms_success(self):
        project = self.project()
        project['resources'] = [{'id': 'ems', 'type': 'ems', 'name': 'Memory EMS', 'config': {'mode': 'memory'}}]
        project['tasks'] = [{'id': 'main', 'name': 'Receiver', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 'recv', 'type': 'ems', 'name': 'Receive', 'config': {'operation': 'queue_receiver', 'resourceId': 'ems', 'destination': 'orders', 'acknowledgeMode': 'Client', 'receiveTimeout': 50}},
                {'id': 'confirm', 'type': 'confirm', 'name': 'Confirm', 'config': {'operation': 'acknowledge', 'inputMappings': {'ackId': '${activities.recv.output.ackId}'}}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 'recv', 'target': 'confirm'}, {'source': 'confirm', 'target': 'end'}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application import connectors
                from application.main import run_application
                from application.registry import TASKS
                attempts = []
                original = TASKS['main']
                async def flaky(ctx, **kwargs):
                    attempts.append(kwargs['event_output']['body'])
                    if len(attempts) == 1: raise RuntimeError('temporary')
                    return await original(ctx, **kwargs)
                TASKS['main'] = flaky
                async def exercise():
                    await connectors._MEMORY_JMS.setdefault(('ems', 'orders'), asyncio.Queue()).put('order-1')
                    runner = asyncio.create_task(run_application('dev'))
                    for _ in range(250):
                        if len(attempts) == 2 and not connectors._MEMORY_ACKS: break
                        await asyncio.sleep(.01)
                    runner.cancel()
                    try: await runner
                    except asyncio.CancelledError: pass
                asyncio.run(exercise())
                self.assertEqual(attempts, ['order-1', 'order-1'])
                self.assertFalse(connectors._MEMORY_ACKS)
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'):
                        sys.modules.pop(name)

    def test_sap_inbound_delivery_is_acknowledged_after_generated_flow(self):
        project = self.project()
        project['resources'] = [{'id': 'sap', 'type': 'sap', 'name': 'SAP', 'config': {'mode': 'mock'}}]
        project['tasks'] = [{'id': 'main', 'name': 'Inbound', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 'recv', 'type': 'sap', 'name': 'IDoc Listener', 'config': {'operation': 'idoc_listener', 'resourceId': 'sap', 'messagingSource': 'NoMessaging'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 'recv', 'target': 'end'}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application import connectors
                from application.main import run_application
                from application.registry import TASKS
                class FakeSap:
                    def __init__(self): self.received = 0; self.decisions = []
                    async def receive_idoc(self, cfg):
                        self.received += 1
                        if self.received > 2: await asyncio.Event().wait()
                        return {'received': True, 'payload': '<IDOC/>', '_sapDeliveryId': f'd{self.received}', '_sapListenerKey': 'listener'}
                    def acknowledge_idoc(self, listener_key, delivery_id, success):
                        self.decisions.append((delivery_id, success))
                    def close_all(self): pass
                fake = FakeSap()
                connectors._SAP_ADAPTER = fake
                original = TASKS['main']
                async def flaky(ctx, **kwargs):
                    if kwargs['event_output']['payload'] == '<IDOC/>' and fake.received == 1:
                        raise RuntimeError('temporary')
                    return await original(ctx, **kwargs)
                TASKS['main'] = flaky
                async def exercise():
                    runner = asyncio.create_task(run_application('dev'))
                    for _ in range(250):
                        if len(fake.decisions) == 2: break
                        await asyncio.sleep(.01)
                    runner.cancel()
                    try: await runner
                    except asyncio.CancelledError: pass
                asyncio.run(exercise())
                self.assertEqual(fake.decisions, [('d1', False), ('d2', True)])
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'):
                        sys.modules.pop(name)

    def test_scheduler_starter_runs_once_from_generated_python(self):
        project = self.project()
        project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Scheduled', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 'schedule', 'type': 'timer', 'name': 'Scheduler', 'config': {'operation': 'schedule', 'runOnceOnLocalStart': True, 'scheduleMode': 'dateTime'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 'schedule', 'target': 'end'}]}]
        files = compiler.raw_python_files(project, {'local': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application.main import run_application
                result = asyncio.run(run_application('local'))
                self.assertEqual(result, [None])
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'):
                        sys.modules.pop(name)

    def test_global_catch_routes_fault_into_direct_python_task(self):
        project = self.project()
        project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Catches', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'throw', 'type': 'throw', 'name': 'Throw', 'config': {'message': 'boom'}},
                {'id': 'catch', 'type': 'catch', 'name': 'Catch', 'config': {'catchAll': True}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {'inputMappings': {'result': '${catch.message}'}}}],
            'transitions': [{'source': 's', 'target': 'throw'}, {'source': 'catch', 'target': 'end'}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            result = subprocess.run([sys.executable, str(root / 'run.py'), '--task', 'main'], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), 'boom')

    def test_direct_general_data_activities_and_runtime_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            output_file = Path(folder) / 'payload.json'
            project = self.project()
            project['resources'] = []
            project['tasks'] = [{'id': 'main', 'name': 'Portable Data', 'kind': 'starter', 'groups': [],
                'activities': [
                    {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                    {'id': 'write', 'type': 'file', 'name': 'Write', 'config': {'operation': 'write', 'path': str(output_file), 'textContent': '{"name":"fabric"}', 'overwrite': True}},
                    {'id': 'read', 'type': 'file', 'name': 'Read', 'config': {'operation': 'read', 'path': str(output_file)}},
                    {'id': 'parse', 'type': 'json', 'name': 'Parse', 'config': {'operation': 'parse', 'inputMappings': {'jsonString': '${activities.read.output.textContent}'}}},
                    {'id': 'map', 'type': 'mapper', 'name': 'Map', 'config': {'mappings': [{'target': 'upperName', 'source': 'upper(activities.parse.output.value.name)'}]}},
                    {'id': 'end', 'type': 'end', 'name': 'End', 'config': {'inputMappings': {'result': '${activities.map.output.upperName}'}}}],
                'transitions': [{'source': 's', 'target': 'write'}, {'source': 'write', 'target': 'read'},
                                {'source': 'read', 'target': 'parse'}, {'source': 'parse', 'target': 'map'}, {'source': 'map', 'target': 'end'}]}]
            files = compiler.raw_python_files(project, {'dev': []})
            root = Path(folder) / 'export'
            for name, body in files.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            run = subprocess.run([sys.executable, str(root / 'run.py'), '--task', 'main'], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout), 'FABRIC')
            check = subprocess.run([sys.executable, str(root / 'run.py'), '--check'], capture_output=True, text=True, timeout=20)
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertTrue(json.loads(check.stdout)['ready'])

    def test_direct_export_declares_optional_connector_dependencies(self):
        project = self.project()
        project['tasks'][0]['activities'].insert(1, {'id': 'excel', 'type': 'excel', 'name': 'Excel', 'config': {'operation': 'read', 'filePath': 'orders.xlsx'}})
        project['tasks'][0]['transitions'] = [{'source': 's', 'target': 'excel'}, {'source': 'excel', 'target': 'c'},
                                              {'source': 'c', 'target': 'p'}, {'source': 'p', 'target': 'r'}, {'source': 'r', 'target': 'e'}]
        files = compiler.raw_python_files(project, {'dev': []})
        requirements = files['application/requirements.py'].decode()
        self.assertIn('openpyxl', requirements)
        self.assertNotIn('aiokafka', requirements)  # in-memory connectors need no third-party client
        self.assertIn('python -m pip install', requirements)

    def test_inbound_rest_starter_hosts_generated_application(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        project = self.project()
        project['resources'] = [{'id': 'http', 'type': 'http', 'name': 'Inbound', 'config': {'host': '127.0.0.1', 'port': port}}]
        project['tasks'] = [{'id': 'main', 'name': 'Inbound REST', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 'listen', 'type': 'rest', 'name': 'Receive', 'config': {'operation': 'receiver', 'resourceId': 'http', 'path': '/orders/{orderId}', 'methods': 'POST'}},
                {'id': 'respond', 'type': 'http_response', 'name': 'Respond', 'config': {'operation': 'response', 'statusCode': 201, 'inputMappings': {'body': '${activities.listen.output.body}'}}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 'listen', 'target': 'respond'}, {'source': 'respond', 'target': 'end'}]}]
        files = compiler.raw_python_files(project, {'local': []})
        self.assertIn('application/inbound_http.py', files)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            process = subprocess.Popen([sys.executable, str(root / 'run.py'), '--environment', 'local'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                response = None
                for _ in range(100):
                    try:
                        request = urllib.request.Request(f'http://127.0.0.1:{port}/orders/42', data=b'{"name":"Ada"}', headers={'Content-Type': 'application/json'}, method='POST')
                        response = urllib.request.urlopen(request, timeout=1); break
                    except Exception: time.sleep(.05)
                self.assertIsNotNone(response, process.stderr.read() if process.poll() is not None else 'listener did not become ready')
                self.assertEqual(response.status, 201)
                self.assertEqual(json.loads(response.read()), {'name': 'Ada'})
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
                if process.stdout: process.stdout.close()
                if process.stderr: process.stderr.close()

    def test_mixed_nested_foreach_and_critical_group_executes(self):
        project = self.project(); project['resources'] = []
        project['tasks'] = [{'id': 'main', 'name': 'Nested Mixed', 'kind': 'starter',
            'activities': [
                {'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                {'id': 'work', 'type': 'basic', 'name': 'Work', 'config': {'operation': 'assign', 'variable': 'seen', 'value': '${vars.currentElement}'}},
                {'id': 'after', 'type': 'log', 'name': 'After', 'config': {'message': 'iteration'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {'inputMappings': {'result': '${vars.seen}'}}}],
            'transitions': [{'source': 's', 'target': 'work'}, {'source': 'work', 'target': 'after'}, {'source': 'after', 'target': 'end'}],
            'groups': [
                {'id': 'outer', 'type': 'for_each', 'name': 'Every order', 'member_activity_ids': ['inner', 'after'], 'config': {'collection': '${input.orders}'}},
                {'id': 'inner', 'type': 'critical_section', 'name': 'Locked order', 'parent_group_id': 'outer', 'member_activity_ids': ['work'], 'config': {'lockName': 'orders'}}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            result = subprocess.run([sys.executable, str(root / 'run.py'), '--task', 'main', '--input', '{"orders":["A","B"]}'], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), 'B')

    def test_sap_listener_reads_memory_kafka_in_direct_runtime(self):
        project = self.project()
        project['resources'] = [{'id': 'sap', 'type': 'sap', 'name': 'SAP', 'config': {'mode': 'mock'}},
                                {'id': 'kafka', 'type': 'kafka', 'name': 'Kafka', 'config': {'mode': 'memory'}}]
        project['tasks'] = [{'id': 'main', 'name': 'SAP Kafka', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 'listen', 'type': 'sap', 'name': 'IDoc Listener', 'config': {'operation': 'idoc_listener', 'resourceId': 'sap', 'messagingSource': 'Kafka', 'messagingResourceId': 'kafka', 'messagingDestination': 'sap.idoc'}},
                {'id': 'seed', 'type': 'kafka', 'name': 'Test Publisher', 'config': {'operation': 'publish', 'resourceId': 'kafka', 'topic': 'sap.idoc'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 'listen', 'target': 'seed'}, {'source': 'seed', 'target': 'end'}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application import connectors
                from application.config import environment
                from application.core import Context, execute_with_policy
                properties, resources = environment('dev'); context = Context({}, properties, resources, environment_name='dev')
                async def exercise():
                    await connectors.kafka('publish', {'mode': 'memory'}, {'topic': 'sap.idoc', 'message': 'IDOC-FLAT'}, None)
                    return await execute_with_policy('sap', project['tasks'][0]['activities'][0]['config'], context, 'listen', 'IDoc Listener')
                result = asyncio.run(exercise())
                self.assertEqual(result['payload'], 'IDOC-FLAT')
                self.assertEqual(result['messagingSource'], 'KAFKA')
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'): sys.modules.pop(name)

    def test_event_starter_accepts_legacy_null_success_transition(self):
        project = self.project()
        project['resources'] = [{'id': 'sap', 'type': 'sap', 'name': 'SAP', 'config': {'mode': 'mock'}}]
        project['tasks'] = [{'id': 'main', 'name': 'Legacy SAP Starter', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 'listen', 'type': 'sap', 'name': 'IDoc Listener', 'config': {'operation': 'idoc_listener', 'resourceId': 'sap', 'messagingSource': 'Kafka'}},
                {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 'listen', 'target': 'end', 'type': None}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application.config import environment
                from application.core import Context
                from application.registry import TASKS
                properties, resources = environment('dev')
                payload = {'IDocXML': '<IDOC/>', 'documentNumber': '1'}
                result = asyncio.run(TASKS['main'](Context({}, properties, resources), start_after='listen', event_output=payload))
                self.assertEqual(result, payload)
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'): sys.modules.pop(name)

    def test_event_starter_routes_injected_payload_through_conditions(self):
        project = self.project()
        project['resources'] = [{'id': 'sap', 'type': 'sap', 'name': 'SAP', 'config': {'mode': 'mock'}}]
        project['tasks'] = [{'id': 'main', 'name': 'Conditional SAP Starter', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 'listen', 'type': 'sap', 'name': 'IDoc Listener', 'config': {'operation': 'idoc_listener', 'resourceId': 'sap', 'messagingSource': 'Kafka'}},
                {'id': 'accepted', 'type': 'end', 'name': 'Accepted', 'config': {}},
                {'id': 'rejected', 'type': 'end', 'name': 'Rejected', 'config': {}}],
            'transitions': [
                {'source': 'listen', 'target': 'accepted', 'type': 'success_condition', 'condition': '${last.accepted}'},
                {'source': 'listen', 'target': 'rejected', 'type': 'success_no_match'}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application.config import environment
                from application.core import Context
                from application.registry import TASKS
                properties, resources = environment('dev')
                context = Context({}, properties, resources)
                asyncio.run(TASKS['main'](context, start_after='listen', event_output={'accepted': True}))
                self.assertIn('accepted', context.outputs)
                self.assertNotIn('rejected', context.outputs)
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'): sys.modules.pop(name)

    def test_jms_request_reply_round_trip_uses_reply_destination_and_correlation(self):
        project = self.project()
        project['resources'] = [{'id': 'jms', 'type': 'jms', 'name': 'JMS', 'config': {'mode': 'memory'}}]
        project['tasks'] = [{'id': 'main', 'name': 'Request', 'kind': 'starter', 'groups': [],
            'activities': [{'id': 's', 'type': 'start', 'name': 'Start', 'config': {}},
                           {'id': 'send', 'type': 'jms', 'name': 'Send', 'config': {'operation': 'send_message', 'resourceId': 'jms', 'destination': 'orders'}},
                           {'id': 'request', 'type': 'jms', 'name': 'Request Reply', 'config': {'operation': 'request_reply', 'resourceId': 'jms', 'destination': 'orders'}},
                           {'id': 'wait', 'type': 'jms', 'name': 'Wait Request', 'config': {'operation': 'wait_request', 'resourceId': 'jms', 'destination': 'orders'}},
                           {'id': 'reply', 'type': 'jms', 'name': 'Reply', 'config': {'operation': 'reply_message', 'resourceId': 'jms'}},
                           {'id': 'end', 'type': 'end', 'name': 'End', 'config': {}}],
            'transitions': [{'source': 's', 'target': 'send'}, {'source': 'send', 'target': 'end'}]}]
        files = compiler.raw_python_files(project, {'dev': []})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in files.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            sys.path.insert(0, folder)
            try:
                from application import connectors
                from application.core import Context
                async def exercise():
                    request_context, responder_context = Context({}, {}, {}), Context({}, {}, {})
                    request = asyncio.create_task(connectors.jms('jms', 'request_reply', {'mode': 'memory'},
                        {'destination': 'orders', 'receiveTimeout': 2000}, {'orderId': 42}, request_context))
                    await asyncio.sleep(.01)
                    incoming = await connectors.jms('jms', 'wait_request', {'mode': 'memory'},
                        {'destination': 'orders', 'receiveTimeout': 2000}, None, responder_context)
                    responder_context.transport.update({'replyTo': incoming['replyTo'], 'correlationId': incoming['correlationId']})
                    await connectors.jms('jms', 'reply_message', {'mode': 'memory'}, {}, {'accepted': True}, responder_context)
                    return incoming, await request
                incoming, response = asyncio.run(exercise())
                self.assertEqual(incoming['body'], {'orderId': 42})
                self.assertEqual(response['body'], {'accepted': True})
                self.assertEqual(response['headers']['JMSCorrelationID'], incoming['correlationId'])
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'): sys.modules.pop(name)


if __name__ == '__main__':
    unittest.main()
