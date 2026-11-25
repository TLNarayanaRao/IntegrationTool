"""Exercise reviewed transform outputs in preview, Run, Debug and real archives."""
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.models import Activity, Project
from app.runtime import WorkflowRuntime


CASES = [
    ('lazy', '{ok: if (payload.value == null) "missing" else (1 / payload.value), keep: "ready" default (1 / 0)}',
     {'value': None}, {'ok': 'missing', 'keep': 'ready'}, {}),
    ('object', 'payload mapObject (value, key, index) -> {(key): {value: value, ordinal: index}}',
     {'a': 4, 'b': 5}, {'a': {'value': 4, 'ordinal': 0}, 'b': {'value': 5, 'ordinal': 1}}, {}),
    ('empty', '{empty: [] map (item) -> 1 / item, absent: null filterObject (value) -> value != null}',
     {}, {'empty': [], 'absent': None}, {}),
    ('filter', 'payload filterObject (value, key, index) -> value != null and index < 2',
     {'a': 4, 'b': None, 'c': 6}, {'a': 4}, {}),
    ('unicode', "{name: 'München', other: 'こんにちは', difference: 1-2}",
     {}, {'name': 'München', 'other': 'こんにちは', 'difference': -1}, {}),
    ('xml', 'payload', '<root><entry id="A">value</entry></root>',
     {'root': {'entry': {'@id': 'A', '#text': 'value'}}}, {'inputMimeType': 'application/xml; charset=UTF-8'}),
    ('best', 'payload maxBy (item) -> item.score', [{'score': 1}, {'score': 9}], {'score': 9}, {}),
    ('csv', 'payload', 'id,name\n1,Ada\n', [{'id': '1', 'name': 'Ada'}], {'inputMimeType': 'text/csv'}),
]


class TransformExecutionParityTests(unittest.TestCase):
    def test_both_archives_declare_the_transform_xml_reader(self):
        from app.raw_python import raw_python_files, engine_python_files
        project = {'id': 'xml-reader', 'name': 'XML-reader', 'resources': [], 'tasks': [
            {'id': 'main', 'name': 'Main', 'kind': 'subtask', 'activities': [
                {'id': 'transform', 'name': 'Transform', 'type': 'script_transform', 'config': {}}
            ], 'transitions': []}]}
        for compiler in (raw_python_files, engine_python_files):
            with self.subTest(archive=compiler.__name__):
                files = compiler(project, {'local': []})
                requirements = json.loads(files['legal/DEPENDENCIES.json'])['requirements']
                self.assertTrue(any(item['name'] == 'lxml.etree' for item in requirements))

    def test_preview_run_debug_and_both_generated_archives(self):
        from app.main import script_transform_test
        spec = importlib.util.spec_from_file_location('flow_transform_parity', Path(__file__).parents[2] / 'scripts/flow-throughput.py')
        flow = importlib.util.module_from_spec(spec); spec.loader.exec_module(flow)
        tasks = []
        for name, body, payload, expected, options in CASES:
            script = '%mina 2.0\noutput application/json\n---\n' + body
            result = script_transform_test({'script': script, 'input': payload, **options})
            self.assertEqual(result['output'], expected, ('preview', name))
            nodes = [{'id': name + '-start', 'type': 'start', 'name': 'Start'},
                     {'id': name + '-transform', 'type': 'script_transform', 'name': 'Transform',
                      'config': {'script': script, 'payload': '${input}', **options}},
                     {'id': name + '-end', 'type': 'end', 'name': 'End'}]
            tasks.append({'id': name, 'name': name, 'kind': 'subtask', 'activities': nodes,
                          'transitions': [{'id': name + str(i), 'source': a['id'], 'target': b['id']}
                                          for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]})
        project = Project.model_validate({'id': 'transform-parity', 'name': 'Transform-parity', 'tasks': tasks})
        async def exercise(folder):
            for mode in ('run', 'debug', 'python-direct', 'python-engine'):
                executor = flow.Executor(mode, project, str(Path(folder) / (mode + '.log')))
                try:
                    await executor.start()
                    for name, _, payload, expected, _ in CASES:
                        output = await executor.execute(name, payload)
                        # Task End wraps a non-object return in the public result envelope.
                        if isinstance(expected, list) and isinstance(output, dict) and set(output) == {'result'}:
                            output = output['result']
                        self.assertEqual(output, expected, (mode, name))
                finally:
                    await executor.close()
        with tempfile.TemporaryDirectory() as folder:
            asyncio.run(exercise(folder))

    def test_runtime_transform_does_not_block_the_event_loop(self):
        async def exercise():
            started = threading.Event(); release = threading.Event()
            def blocking(*args, **kwargs):
                started.set()
                if not release.wait(3): raise AssertionError('Event loop was blocked by the transform')
                return {'output': {'done': True}, 'mimeType': 'application/json', 'version': '2.0'}
            runtime = WorkflowRuntime()
            activity = Activity(id='work', name='Work', type='script_transform', config={})
            ctx = {'last': {}, 'input': {}, 'vars': {}, 'properties': {}, 'resources': {}}
            with patch('app.transform_engine.execute_details', side_effect=blocking):
                task = asyncio.create_task(runtime.execute(activity, ctx))
                try:
                    for _ in range(100):
                        if started.is_set(): break
                        await asyncio.sleep(.01)
                    self.assertTrue(started.is_set())
                    release.set()
                    self.assertEqual(await task, {'done': True})
                finally:
                    release.set()
                    await asyncio.gather(task, return_exceptions=True)
        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
