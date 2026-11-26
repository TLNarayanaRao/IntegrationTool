import asyncio
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
import sqlite3

from app.file_operations import file_activity, file_poll_events
from app.jdbc import JdbcAdapterError, execute
from app.models import Project


class FileJdbcActivityTests(unittest.TestCase):
    def test_timestamp_opt_out_preserves_listing_order_and_poller_change_detection(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new.txt'
            path.write_text('new')
            other = Path(folder) / 'old.txt'
            other.write_text('old')
            os.utime(other, (1000000000, 1000000000))
            options = {'path': folder, 'omitTimestamp': True, 'sortBy': 'Last Modified', 'eventType': 'Modified'}
            result = file_activity('list', options, None)
            self.assertEqual([item['fileName'] for item in result['files']], ['old.txt', 'new.txt'])
            self.assertTrue(all('lastModified' not in item for item in result['files']))
            _, snapshot = file_poll_events(file_activity('poll', options, None), options, None)
            os.utime(path, (1100000000, 1100000000))
            changed, _ = file_poll_events(file_activity('poll', options, None), options, snapshot)
            self.assertEqual([(item['fileName'], item['eventType']) for item in changed['files']], [('new.txt', 'Modified')])
            self.assertNotIn('lastModified', changed['files'][0])
            legacy = file_activity('read', {'path': str(path), 'includeTimestamp': False}, None)
            self.assertIn('lastModified', legacy)

    def test_sqlite_execution_timeout_is_classified_and_cleared_before_reuse(self):
        from contextlib import closing
        with closing(sqlite3.connect(':memory:')) as conn:
            timeout_before = conn.execute('PRAGMA busy_timeout').fetchone()[0]
            with self.assertRaises(JdbcAdapterError) as error:
                execute({'driver': 'sqlite'}, {'timeout': 1, 'sql': (
                    'WITH RECURSIVE counter(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM counter WHERE n<1000000000)'
                    ' SELECT sum(n) FROM counter'
                )}, conn)
            self.assertEqual(error.exception.fault_type, 'ActivityTimedOutException')
            self.assertEqual(conn.execute('PRAGMA busy_timeout').fetchone()[0], timeout_before)
            self.assertEqual(execute({'driver': 'sqlite'}, {'sql': 'SELECT 1 AS ok'}, conn)['rows'], [{'ok': 1}])

    def test_exists_returns_metadata_or_an_absent_result_and_propagates_io_errors(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.txt'
            config = {'path': str(path)}
            self.assertEqual(file_activity('exists', config, None),
                             {'path': str(path), 'exists': False, 'fileInfo': None})
            path.write_bytes(b'source')
            existing = file_activity('exists', config, None)
            self.assertTrue(existing['exists'])
            self.assertEqual((existing['fileInfo']['type'], existing['fileInfo']['size']), ('file', 6))
            self.assertEqual(file_activity('exists', {'path': folder}, None)['fileInfo']['type'], 'directory')
            with patch.object(Path, 'stat', side_effect=PermissionError('denied')):
                with self.assertRaises(PermissionError):
                    file_activity('exists', config, None)

    def test_binary_write_uses_incoming_bytes_and_rejects_invalid_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'payload.bin'
            config = {'path': str(path), 'writeAs': 'Binary'}
            file_activity('write', config, b'\x00\xff')
            self.assertEqual(path.read_bytes(), b'\x00\xff')
            with self.assertRaisesRegex(ValueError, 'bytes or base64 text'):
                file_activity('write', {**config, 'overwrite': True, 'binaryContent': 4096}, None)
            self.assertEqual(path.read_bytes(), b'\x00\xff')

    def test_create_directory_can_reuse_a_directory_but_not_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'parent' / 'target'
            config = {'path': str(path), 'createDirectories': True}
            self.assertTrue(file_activity('mkdir', config, None)['created'])
            with self.assertRaises(FileExistsError):
                file_activity('mkdir', config, None)
            self.assertFalse(file_activity('mkdir', {**config, 'allowExisting': True}, None)['created'])
            file = Path(folder) / 'existing-file'
            file.write_bytes(b'preserved')
            with self.assertRaises(FileExistsError):
                file_activity('mkdir', {**config, 'path': str(file), 'allowExisting': True}, None)
            self.assertEqual(file.read_bytes(), b'preserved')

    def test_checksum_uses_stored_bytes_and_enforces_limit(self):
        data = bytes(range(256)) * 513
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'payload.bin'
            path.write_bytes(data)
            result = file_activity('checksum', {'path': str(path), 'maxReadBytes': len(data), 'checksumAlgorithm': 'SHA-512'}, None)
            self.assertEqual(result, {'path': str(path), 'algorithm': 'SHA-512',
                                      'checksum': hashlib.sha512(data).hexdigest(), 'bytesRead': len(data)})
            with self.assertRaisesRegex(ValueError, 'maximum read bytes'):
                file_activity('checksum', {'path': str(path), 'maxReadBytes': len(data) - 1}, None)
            with self.assertRaisesRegex(ValueError, 'regular file'):
                file_activity('checksum', {'path': folder}, None)

    def test_sqlite_duplicate_result_labels_and_quoted_truncate(self):
        with tempfile.TemporaryDirectory() as folder:
            connection = {'driver': 'sqlite', 'url': str(Path(folder) / 'tables.db')}
            execute(connection, {'operation': 'dynamic', 'sql': 'CREATE TABLE "Sales Order" (id INTEGER)'})
            execute(connection, {'operation': 'insert', 'sql': 'INSERT INTO "Sales Order" VALUES (7)'})
            with self.assertRaises(JdbcAdapterError) as duplicate:
                execute(connection, {'sql': 'SELECT id AS item, id + 1 AS item FROM "Sales Order"'})
            self.assertEqual(duplicate.exception.fault_type, 'DuplicatedFieldNameException')
            with self.assertRaisesRegex(JdbcAdapterError, 'one table identifier'):
                execute(connection, {'operation': 'truncate', 'sql': 'TRUNCATE TABLE other Order'})
            self.assertEqual(execute(connection, {'sql': 'SELECT id FROM "Sales Order"'})['rows'], [{'id': 7}])
            self.assertEqual(execute(connection, {'operation':'truncate',
                                                 'sql':'TRUNCATE TABLE main."Sales Order";'})['noOfUpdates'], 1)

    def test_file_and_jdbc_operations_in_all_execution_formats(self):
        module_path = Path(__file__).parents[2] / 'scripts' / 'flow-throughput.py'
        spec = importlib.util.spec_from_file_location('file_jdbc_flows', module_path)
        flows = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(flows)

        def task(activity_type, operation, config):
            return {'id': operation, 'name': operation, 'kind': 'subtask',
                    'activities': [{'id': 'Start', 'name': 'Start', 'type': 'start'},
                                   {'id': 'Activity', 'name': 'Activity', 'type': activity_type, 'config': {'operation': operation, **config}},
                                   {'id': 'End', 'name': 'End', 'type': 'end'}],
                    'transitions': [{'id': 'one', 'source': 'Start', 'target': 'Activity'},
                                    {'id': 'two', 'source': 'Activity', 'target': 'End'}]}

        async def verify(folder):
            path = Path(folder) / 'sample.bin'
            path.write_bytes(b'MINA sample')
            connection = {'driver': 'sqlite', 'url': str(Path(folder) / 'metadata.db')}
            execute(connection, {'operation': 'dynamic', 'sql': 'CREATE TABLE sqliteX_orders (id INTEGER)'})
            paths = {'path': '${input.path}'}
            destination = {**paths, 'destination': '${input.destination}'}
            project = Project.model_validate({
                'id': 'file-jdbc-qa', 'name': 'File JDBC QA',
                'resources': [{'id': 'db', 'type': 'jdbc', 'name': 'Database', 'config': connection}],
                'tasks': [task('file', 'checksum', {'inputMappings': {'path': '${input.path}'}}),
                          task('file', 'exists', {'inputMappings': {'path': '${input.path}'}}),
                          task('file', 'mkdir', {'createDirectories': True, 'allowExisting': True,
                                                 'inputMappings': {'path': '${input.path}'}}),
                          task('file', 'write', {'inputMappings': {**paths, 'textContent': '${input.text}'}}),
                          task('file', 'read', {'omitTimestamp': True, 'inputMappings': paths}),
                          task('file', 'list', {'omitTimestamp': True, 'inputMappings': paths}),
                          task('file', 'copy', {'inputMappings': destination}),
                          task('file', 'rename', {'inputMappings': destination}),
                          task('file', 'delete', {'inputMappings': paths}),
                          task('jdbc', 'health_check', {'resourceId': 'db'}),
                          task('jdbc', 'metadata', {'resourceId': 'db', 'inputMappings': {'schema': '${input.schema}'}}),
                          task('jdbc', 'dynamic', {'resourceId': 'db', 'sql': 'CREATE TABLE activity_qa (id INTEGER, name TEXT)'}),
                          task('jdbc', 'insert', {'resourceId': 'db', 'sql': 'INSERT INTO activity_qa VALUES (:id,:name)',
                                                 'inputMappings': {'parameters': '${input}'}}),
                          task('jdbc', 'update', {'resourceId': 'db', 'sql': 'UPDATE activity_qa SET name=:name WHERE id=:id',
                                                 'inputMappings': {'parameters': '${input}'}}),
                          task('jdbc', 'query', {'resourceId': 'db', 'sql': 'SELECT * FROM activity_qa ORDER BY id'}),
                          task('jdbc', 'truncate', {'resourceId': 'db', 'sql': 'TRUNCATE TABLE activity_qa'}),
                          {**task('jdbc', 'delete', {'resourceId': 'db', 'sql': 'DELETE FROM activity_qa WHERE id=:id',
                                                    'inputMappings': {'parameters': '${input}'}}), 'id': 'db_delete', 'name': 'Database-Delete'}],
            })
            for mode in ('run', 'debug', 'python-direct', 'python-engine'):
                with self.subTest(mode=mode):
                    executor = flows.Executor(mode, project, str(Path(folder) / (mode + '.log')))
                    try:
                        await executor.start()
                        result = await executor.execute('checksum', {'path': str(path)})
                        self.assertEqual(result['checksum'], hashlib.sha256(b'MINA sample').hexdigest())
                        self.assertTrue((await executor.execute('exists', {'path': str(path)}))['exists'])
                        self.assertFalse((await executor.execute('exists', {'path': str(path.with_suffix('.missing'))}))['exists'])
                        target = str(Path(folder) / mode / 'output')
                        self.assertTrue((await executor.execute('mkdir', {'path': target}))['created'])
                        self.assertFalse((await executor.execute('mkdir', {'path': target}))['created'])
                        source = str(Path(target) / 'source.txt')
                        copied = str(Path(target) / 'copy.txt')
                        renamed = str(Path(target) / 'renamed.txt')
                        self.assertTrue((await executor.execute('write', {'path': source, 'text': 'hello'}))['written'])
                        read = await executor.execute('read', {'path': source})
                        self.assertEqual(read['textContent'], 'hello')
                        self.assertNotIn('lastModified', read['fileInfo'])
                        listed = await executor.execute('list', {'path': target})
                        self.assertEqual([entry['fileName'] for entry in listed['files']], ['source.txt'])
                        self.assertTrue((await executor.execute('copy', {'path': source, 'destination': copied}))['success'])
                        self.assertTrue((await executor.execute('rename', {'path': copied, 'destination': renamed}))['success'])
                        self.assertTrue((await executor.execute('delete', {'path': renamed}))['deleted'])
                        self.assertTrue((await executor.execute('health_check', {}))['ok'])
                        result = await executor.execute('metadata', {'schema': 'main'})
                        self.assertEqual([(row['name'], row['columns'][0]['name']) for row in result['tables']],
                                         [('sqliteX_orders', 'id')])
                        await executor.execute('dynamic', {})
                        await executor.execute('insert', {'id': 1, 'name': 'Ada'})
                        await executor.execute('insert', {'id': 2, 'name': 'Jo'})
                        self.assertEqual((await executor.execute('update', {'id': 1, 'name': 'Grace'}))['rowCount'], 1)
                        self.assertEqual((await executor.execute('db_delete', {'id': 2}))['rowCount'], 1)
                        self.assertEqual((await executor.execute('query', {}))['rows'], [{'id': 1, 'name': 'Grace'}])
                        self.assertEqual((await executor.execute('truncate', {}))['rowCount'], 1)
                        self.assertEqual((await executor.execute('query', {}))['rows'], [])
                    finally:
                        await executor.close()
                        execute(connection, {'sql': 'DROP TABLE IF EXISTS activity_qa'})

        with tempfile.TemporaryDirectory() as folder:
            asyncio.run(verify(folder))
