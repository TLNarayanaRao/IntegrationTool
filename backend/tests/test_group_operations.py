import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.debugger import DebugManager
from app.models import Project
from app.runtime import WorkflowRuntime
from app.raw_python import engine_python_files, raw_python_files


def project_for(kind, config=None, parallel_routes=False):
    body = ['first', 'second'] if parallel_routes else ['first']
    paths = [('start', entry) for entry in body] + [(entry, 'end') for entry in body]
    return Project(id='group-test', name='Group Test', tasks=[dict(
        id='main', name='Main', kind='subtask',
        activities=[dict(id='start', name='Start', type='start'),
                    *[dict(id=name, name=name, type='basic', config={'operation': 'empty'}) for name in body],
                    dict(id='end', name='End', type='end')],
        transitions=[dict(id=str(index), source=source, target=target) for index, (source, target) in enumerate(paths)],
        groups=[dict(id='group', name='Operations', type=kind, member_activity_ids=body, config=config or {})],
    )])


class GroupOperationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_items_are_batched_and_ordered_in_run_and_debug(self):
        class Observed(WorkflowRuntime):
            active = 0
            maximum = 0

            async def execute(self, activity, ctx):
                if activity.id != 'first':
                    return await super().execute(activity, ctx)
                self.active += 1
                self.maximum = max(self.active, self.maximum)
                try:
                    await asyncio.sleep(.02 if ctx['vars']['currentIndex'] == 1 else .002)
                    return {'batch': ctx['vars']['currentElement']}
                finally:
                    self.active -= 1

        project = project_for('parallel_for_each', {'source': '${input.items}', 'batchSize': 2, 'maxConcurrency': 2})
        payload = {'items': [1, 2, 3, 4, 5]}
        expected = [{'batch': [1, 2]}, {'batch': [3, 4]}, {'batch': [5]}]
        runtime = Observed()
        result = await runtime.run(project.tasks[0], payload, project=project)
        self.assertEqual(result.status, 'completed', result.logs)
        self.assertEqual(result.output, {'result': expected})
        self.assertEqual(runtime.maximum, 2)
        manager = DebugManager(runtime)
        session = manager.start(project, 'main', payload, {}, {}, [])['sessionId']
        for _ in range(8):
            view = await manager.action(session, 'step', {})
            if view['status'] == 'completed':
                break
        self.assertEqual(view['status'], 'completed', view.get('logs'))
        self.assertEqual(view['output'], expected)

    async def test_route_failures_wait_for_the_other_route_and_fallback_is_sequential(self):
        class Observed(WorkflowRuntime):
            def __init__(self):
                super().__init__()
                self.visits = []

            async def execute(self, activity, ctx):
                if activity.id == 'first':
                    ctx['vars']['failed_route'] = True
                    self.visits.append('first')
                    raise RuntimeError('unavailable')
                if activity.id == 'second':
                    await asyncio.sleep(.005)
                    self.visits.append('second')
                    return {'isolated': 'failed_route' not in ctx['vars']}
                return await super().execute(activity, ctx)

        for kind in ('scatter_gather', 'first_successful'):
            project = project_for(kind, parallel_routes=True)
            runtime = Observed()
            result = await runtime.run(project.tasks[0], {})
            self.assertEqual(runtime.visits, ['first', 'second'])
            if kind == 'scatter_gather':
                self.assertEqual(result.status, 'failed')
                self.assertNotIn('end', result.activity_outputs)
            else:
                self.assertEqual(result.status, 'completed', result.logs)
                self.assertEqual(result.output, {'isolated': True})

    async def test_scope_matches_faults_and_restores_local_variables(self):
        class Observed(WorkflowRuntime):
            async def execute(self, activity, ctx):
                if activity.id == 'first':
                    self.assert_local = ctx['vars']['local']
                    raise ValueError('pick up here')
                if activity.id == 'end':
                    return {'resume': ctx['last'], 'leaked': 'local' in ctx['vars']}
                return await super().execute(activity, ctx)

        project = project_for('scope', {
            'localVariables': [{'name': 'local', 'value': '${input.seed}'}],
            'faultHandlers': [{'action': 'propagate', 'types': ['OtherFault']},
                              {'action': 'continue', 'types': ['ValueError'], 'value': '${vars.local}'}],
        })
        runtime = Observed()
        result = await runtime.run(project.tasks[0], {'seed': 5})
        self.assertEqual(runtime.assert_local, 5)
        self.assertEqual(result.output, {'resume': 5, 'leaked': False})

    async def test_background_continues_without_waiting_and_keeps_payload(self):
        release = asyncio.Event()

        class Observed(WorkflowRuntime):
            async def execute(self, activity, ctx):
                if activity.id == 'first':
                    await release.wait()
                    return {'background': True}
                return await super().execute(activity, ctx)

        runtime = Observed()
        project = project_for('async')
        result = await asyncio.wait_for(runtime.run(project.tasks[0], {'original': True}), timeout=1)
        self.assertEqual(result.output, {'original': True})
        self.assertNotIn('first', result.activity_outputs)
        pending = tuple(runtime._detached_runs)
        self.assertEqual(len(pending), 1)
        release.set()
        await asyncio.wait_for(asyncio.gather(*pending), timeout=1)
        self.assertFalse(runtime._detached_runs)

    async def test_isolated_retry_restores_variables_and_payload_before_retry(self):
        class Observed(WorkflowRuntime):
            attempts = 0

            async def execute(self, activity, ctx):
                if activity.id == 'first':
                    self.attempts += 1
                    if self.attempts == 1:
                        ctx['vars']['temporary'] = True
                        raise ValueError('retry me')
                    return {'payload': ctx['last'], 'temporary': ctx['vars'].get('temporary'), 'attempt': ctx['vars']['index']}
                return await super().execute(activity, ctx)

        project = project_for('repeat_on_error', {'resetOnRetry': True, 'retryCount': 1})
        result = await Observed().run(project.tasks[0], {'original': True})
        self.assertEqual(result.output, {'payload': {'original': True}, 'temporary': None, 'attempt': 2})


class GroupExportTests(unittest.TestCase):
    def execute_archive(self, files, payload, entry=('run.py',)):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            process = subprocess.run([sys.executable, *entry, '--task', 'main', '--input', json.dumps(payload)],
                                     cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            return json.loads(process.stdout)

    def test_direct_batching_and_engine_parallel_export(self):
        parallel = project_for('parallel_for_each', {'source': '${input.items}', 'batchSize': 2}).model_dump()
        output = self.execute_archive(engine_python_files(parallel, {'local': []}), {'items': [1, 2, 3]},
                                      entry=('-m', 'application.main'))
        self.assertEqual(output, {'result': [[1, 2], [3]]})
        with self.assertRaisesRegex(ValueError, 'engine-backed Python export'):
            raw_python_files(parallel, {'local': []})

        sequential = project_for('iterate', {'source': '${input.items}', 'batchSize': 2,
                                             'accumulateOutput': True, 'accumulatorVariable': 'batches'}).model_dump()
        task = sequential['tasks'][0]
        task['activities'][1]['config'] = {'operation': 'assign', 'variable': 'batch', 'value': '${vars.currentElement}'}
        task['activities'][2]['config'] = {'inputMappings': {'result': '${vars.batches}'}}
        output = self.execute_archive(raw_python_files(sequential, {'local': []}), {'items': [1, 2, 3]})
        self.assertEqual(output, [{'name': 'batch', 'value': [1, 2]}, {'name': 'batch', 'value': [3]}])
