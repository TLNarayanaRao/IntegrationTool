import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.file_operations import file_poll_events
from app.main import app
from app.models import Project
from app.raw_python import engine_python_files, raw_python_files


def starter(kind, config, receipt, expression, resources=()):
    return {
        'id': 'continuous-connectors', 'name': 'Continuous Connectors',
        'resources': list(resources),
        'tasks': [{
            'id': 'main', 'name': 'Receive', 'kind': 'starter', 'groups': [],
            'activities': [
                {'id': 'receive', 'type': kind, 'name': 'Receive', 'config': config},
                {'id': 'record', 'type': 'file', 'name': 'Record', 'config': {
                    'operation': 'write', 'path': str(receipt), 'textContent': expression,
                    'append': True, 'addLineSeparator': True,
                }},
            ],
            'transitions': [{'id': 'success', 'source': 'receive', 'target': 'record'}],
        }],
    }


def file_starter(inbox, receipt):
    return starter('file', {'operation': 'poll', 'path': str(inbox), 'pattern': '*.txt',
                            'eventType': 'All', 'pollInterval': .1, 'includeExisting': True},
                   receipt, '${last.files.0.fileName}')


FILE_ARCHIVE_CHECK = '''
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from application.main import run_application

inbox, receipt = map(Path, sys.argv[2:])

async def wait_for(expected):
    for _ in range(150):
        if receipt.exists() and receipt.read_text().splitlines() == expected:
            return
        await asyncio.sleep(.02)
    raise AssertionError(receipt.read_text() if receipt.exists() else 'No flow executions')

async def check():
    runner = asyncio.create_task(run_application('local'))
    try:
        await wait_for(['existing.txt'])
        await asyncio.sleep(.35)
        assert receipt.read_text().splitlines() == ['existing.txt']
        created = inbox / 'new.txt'
        created.write_text('new')
        await wait_for(['existing.txt', 'new.txt'])
        created.write_text('modified file')
        await wait_for(['existing.txt', 'new.txt', 'new.txt'])
        created.unlink()
        expected = ['existing.txt', 'new.txt', 'new.txt', 'new.txt']
        await wait_for(expected)
        await asyncio.sleep(.35)
        assert receipt.read_text().splitlines() == expected
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

asyncio.run(check())
'''


AMQP_ARCHIVE_CHECK = '''
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from application.main import run_application, run_task

receipt = Path(sys.argv[2])

async def wait_for(expected):
    for _ in range(150):
        if receipt.exists() and receipt.read_text().splitlines() == expected:
            return
        await asyncio.sleep(.02)
    raise AssertionError(receipt.read_text() if receipt.exists() else 'No AMQP deliveries')

async def check():
    runner = asyncio.create_task(run_application('local'))
    try:
        await asyncio.sleep(.15)
        assert not runner.done() and not receipt.exists()
        for body, expected in [('first', ['first']), ('second', ['first', 'second'])]:
            await run_task('publish', {'body': body}, 'local')
            await wait_for(expected)
        await asyncio.sleep(.2)
        assert not runner.done() and receipt.read_text().splitlines() == ['first', 'second']
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

asyncio.run(check())
'''


class ContinuousConnectorTests(unittest.TestCase):
    def check_archive(self, root, files, script, *args):
        archive = root / 'application.zip'
        with ZipFile(archive, 'w') as package:
            for name, body in files.items():
                package.writestr(name, body)
        completed = subprocess.run([sys.executable, '-c', script, str(archive), *map(str, args)],
                                   cwd=root, text=True, capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_file_poller_in_both_archives(self):
        for export in (raw_python_files, engine_python_files):
            with self.subTest(export=export.__name__), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                inbox, receipt = root / 'inbox', root / 'receipt.txt'
                inbox.mkdir()
                (inbox / 'existing.txt').write_text('existing')
                self.check_archive(root, export(file_starter(inbox, receipt), {'local': []}),
                                   FILE_ARCHIVE_CHECK, inbox, receipt)

    def test_amqp_starter_waits_for_successive_messages_in_both_archives(self):
        for export in (raw_python_files, engine_python_files):
            with self.subTest(export=export.__name__), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                receipt = root / 'receipt.txt'
                project = starter('amqp', {'operation': 'receive', 'resourceId': 'amqp',
                                           'queueName': 'orders', 'receiveTimeout': 50},
                                  receipt, '${last.body}',
                                  [{'id': 'amqp', 'type': 'amqp', 'name': 'AMQP', 'config': {'mode': 'memory'}}])
                project['tasks'].append({'id': 'publish', 'name': 'Publish', 'kind': 'subtask', 'groups': [],
                    'activities': [{'id': 'send', 'type': 'amqp', 'name': 'Send', 'config': {
                        'operation': 'send', 'resourceId': 'amqp', 'queueName': 'orders', 'body': '${input.body}',
                    }}], 'transitions': []})
                self.check_archive(root, export(project, {'local': []}), AMQP_ARCHIVE_CHECK, receipt)

    def test_file_poller_in_studio_run_and_debug(self):
        for mode in ('run', 'debug'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                inbox, receipt = root / 'inbox', root / 'receipt.txt'
                inbox.mkdir()
                (inbox / 'existing.txt').write_text('existing')
                project = Project.model_validate(file_starter(inbox, receipt))
                location = f'/api/projects/{project.id}'
                with patch('app.main.get_project', return_value=project), TestClient(app) as client:
                    started = client.post(f'{location}/{mode}', json={'environment': 'local', 'breakpoints': []})
                    self.assertEqual(started.status_code, 200, started.text)
                    state = started.json()
                    self.assertEqual(state['status'], 'listening', state)
                    try:
                        for expected in (['existing.txt'], ['existing.txt', 'new.txt']):
                            if len(expected) == 2:
                                (inbox / 'new.txt').write_text('new file')
                            deadline = time.monotonic() + 3
                            while time.monotonic() < deadline:
                                if receipt.exists() and receipt.read_text().splitlines() == expected:
                                    break
                                time.sleep(.02)
                            time.sleep(.25)
                            self.assertEqual(receipt.read_text().splitlines() if receipt.exists() else [], expected)
                    finally:
                        if mode == 'debug':
                            client.post(f"/api/debug/{state['sessionId']}/action", json={'action': 'stop'})
                        else:
                            client.post(f'{location}/stop')

    def test_file_event_modes_and_first_snapshot(self):
        original = [{'fullName': name, 'lastModified': 'same', 'size': 1}
                    for name in ('modified.txt', 'deleted.txt', 'unchanged.txt')]
        updated = [{**original[0], 'size': 2}, {'fullName': 'created.txt'}, original[2]]
        baseline, seen = file_poll_events({'files': original}, {'includeExisting': 'false'}, None)
        self.assertEqual(baseline['count'], 0)
        for mode, names in (('Created', ['created.txt']), ('Modified', ['modified.txt']),
                            ('Deleted', ['deleted.txt']), ('All', ['created.txt', 'modified.txt', 'deleted.txt'])):
            with self.subTest(mode=mode):
                result, snapshot = file_poll_events({'files': updated}, {'eventType': mode}, seen)
                self.assertEqual(result['count'], len(names))
                self.assertEqual([file['fullName'] for file in result['files']], names)
                unchanged, _ = file_poll_events({'files': updated}, {'eventType': mode}, snapshot)
                self.assertEqual(unchanged['count'], 0)
