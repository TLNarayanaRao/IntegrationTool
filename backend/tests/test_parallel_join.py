import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.debugger import DebugManager
from app.flow_graph import parallel_join, parallel_plan
from app.models import ProcessDefinition, Project
from app.runtime import WorkflowRuntime
from tests.test_engine_export import compiler


def graph(nested=False):
    paths = [('Start', 'Fork'), ('Fork', 'A'), ('Fork', 'B'), ('A', 'Join'), ('B', 'Join'), ('Join', 'End')]
    if nested:
        paths.remove(('A', 'Join'))
        paths += [('A', 'C'), ('A', 'D'), ('C', 'Inner'), ('D', 'Inner'), ('Inner', 'Join')]
    names = list(dict.fromkeys(node for edge in paths for node in edge))
    return ProcessDefinition(id='main', name='Parallel', activities=[
        {'id': name, 'name': name, 'type': 'start' if name == 'Start' else 'end' if name == 'End' else 'basic',
         'config': {'operation': 'empty'}} for name in names],
        transitions=[{'id': str(i), 'source': source, 'target': target} for i, (source, target) in enumerate(paths)])


def partial_graph():
    process = graph()
    value = process.model_dump()
    value['activities'] += [{'id': 'C', 'name': 'C', 'type': 'basic', 'config': {'operation': 'empty'}},
                            {'id': 'Inner', 'name': 'Inner', 'type': 'basic', 'config': {'operation': 'empty'}}]
    for edge in value['transitions']:
        if edge['source'] in ('A', 'B'): edge['target'] = 'Inner'
    value['transitions'] += [{'id': 'to-c', 'source': 'Fork', 'target': 'C'},
                             {'id': 'inner-join', 'source': 'Inner', 'target': 'Join'},
                             {'id': 'c-join', 'source': 'C', 'target': 'Join'}]
    return ProcessDefinition.model_validate(value)


class RecordingRuntime(WorkflowRuntime):
    def __init__(self, fail=None):
        super().__init__()
        self.events = []
        self.fail = fail

    async def execute(self, activity, ctx):
        self.events.append(('start', activity.id))
        if activity.id in ('A', 'B', 'C', 'D'):
            await asyncio.sleep(.02 if activity.id in ('B', 'D') else .001)
            self.assert_input(ctx)
            ctx['vars']['local'] = activity.id
        if activity.id == self.fail: raise RuntimeError('branch failure')
        self.events.append(('done', activity.id))
        return {'activity': activity.id}

    @staticmethod
    def assert_input(ctx):
        assert ctx['input'] == {'original': True}, ctx['input']
        assert 'local' not in ctx['vars'] or ctx['vars']['local'] == 'A'


class ParallelJoinTests(unittest.IsolatedAsyncioTestCase):
    async def test_join_runs_once_after_slowest_branch(self):
        runtime = RecordingRuntime()
        result = await runtime.run(graph(), {'original': True})
        self.assertEqual(result.status, 'completed', result.logs)
        events = runtime.events
        self.assertLess(events.index(('start', 'B')), events.index(('done', 'A')))
        self.assertLess(events.index(('done', 'B')), events.index(('start', 'Join')))
        self.assertEqual(events.count(('start', 'Join')), 1)
        self.assertEqual(events.count(('start', 'End')), 1)

    async def test_one_hundred_branches_complete_before_shared_continuation(self):
        branches = [f'branch-{index}' for index in range(100)]
        activities = [{'id': 'Start', 'name': 'Start', 'type': 'start'},
                      {'id': 'Join', 'name': 'Join', 'type': 'basic', 'config': {'operation': 'empty'}},
                      {'id': 'End', 'name': 'End', 'type': 'end'}]
        edges = [{'id': 'finish', 'source': 'Join', 'target': 'End'}]
        for branch in branches:
            activities.append({'id': branch, 'name': branch, 'type': 'basic', 'config': {'operation': 'empty'}})
            edges += [{'id': f'start-{branch}', 'source': 'Start', 'target': branch},
                      {'id': f'join-{branch}', 'source': branch, 'target': 'Join'}]
        runtime = RecordingRuntime()
        result = await runtime.run(ProcessDefinition(id='main', name='Wide', activities=activities, transitions=edges), {'original': True})
        self.assertEqual(result.status, 'completed', result.logs)
        join_start = runtime.events.index(('start', 'Join'))
        for branch in branches:
            self.assertLess(runtime.events.index(('done', branch)), join_start)
        self.assertEqual(runtime.events.count(('start', 'Join')), 1)
        self.assertEqual(runtime.events.count(('start', 'End')), 1)

    async def test_nested_forks_join_in_order(self):
        runtime = RecordingRuntime()
        result = await runtime.run(graph(True), {'original': True})
        self.assertEqual(result.status, 'completed', result.logs)
        events = runtime.events
        for name in ('C', 'D'):
            self.assertLess(events.index(('done', name)), events.index(('start', 'Inner')))
        for name in ('Inner', 'B'):
            self.assertLess(events.index(('done', name)), events.index(('start', 'Join')))
        for name in ('Inner', 'Join', 'End'):
            self.assertEqual(events.count(('start', name)), 1)

    async def test_two_of_three_branches_join_before_final_barrier(self):
        runtime = RecordingRuntime()
        result = await runtime.run(partial_graph(), {'original': True})
        self.assertEqual(result.status, 'completed', result.logs)
        events = runtime.events
        for name in ('A', 'B'):
            self.assertLess(events.index(('done', name)), events.index(('start', 'Inner')))
        for name in ('Inner', 'C'):
            self.assertLess(events.index(('done', name)), events.index(('start', 'Join')))
        self.assertEqual(events.count(('start', 'Inner')), 1)
        self.assertEqual(events.count(('start', 'Join')), 1)

    async def test_failure_waits_for_sibling_and_blocks_join(self):
        runtime = RecordingRuntime(fail='A')
        result = await runtime.run(graph(), {'original': True})
        self.assertEqual(result.status, 'failed')
        self.assertIn(('done', 'B'), runtime.events)
        self.assertNotIn(('start', 'Join'), runtime.events)

    async def test_join_preserves_scalar_last_and_original_input(self):
        class ScalarRuntime(WorkflowRuntime):
            async def execute(self, activity, ctx):
                if activity.id in ('A', 'B'): return 42
                if activity.id == 'Join':
                    self_test.assertEqual(ctx['last'], 42)
                    self_test.assertEqual(ctx['input'], {'original': True})
                    return {'ok': True}
                return await super().execute(activity, ctx)
        self_test = self
        result = await ScalarRuntime().run(graph(), {'original': True})
        self.assertEqual(result.status, 'completed', result.logs)

    async def test_debug_join_runs_once_after_all_branches(self):
        runtime = RecordingRuntime()
        manager = DebugManager(runtime)
        process = graph(True)
        project = Project(id='test', name='Test', tasks=[process.model_dump()])
        view = manager.start(project, 'main', {'original': True}, {}, {}, [])
        state = manager.sessions[view['sessionId']]
        for _ in range(30):
            if state['status'] == 'completed': break
            await manager.step(state)
        self.assertEqual(state['status'], 'completed')
        events = runtime.events
        for name in ('Inner', 'B'):
            self.assertLess(events.index(('done', name)), events.index(('start', 'Join')))
        self.assertEqual(events.count(('start', 'Join')), 1)
        self.assertEqual(events.count(('start', 'End')), 1)

    async def test_debug_partial_join_runs_once(self):
        runtime = RecordingRuntime()
        manager = DebugManager(runtime)
        project = Project(id='test', name='Test', tasks=[partial_graph().model_dump()])
        state = manager.sessions[manager.start(project, 'main', {'original': True}, {}, {}, [])['sessionId']]
        for _ in range(30):
            if state['status'] == 'completed': break
            await manager.step(state)
        self.assertEqual(state['status'], 'completed')
        for name in ('A', 'B'):
            self.assertLess(runtime.events.index(('done', name)), runtime.events.index(('start', 'Inner')))
        self.assertEqual(runtime.events.count(('start', 'Inner')), 1)

    def test_conditional_bypass_is_not_an_unconditional_join(self):
        edges = [('fork', 'a', 'success'), ('fork', 'b', 'success'),
                 ('a', 'join', 'success_condition'), ('a', 'end', 'success_no_match'),
                 ('b', 'join', 'success'), ('join', 'end', 'success')]
        self.assertEqual(parallel_join(edges, ['a', 'b'], ['end']), 'end')

    def test_wide_fanout_does_not_rescan_edges_for_every_branch_pair(self):
        class CountingEdges(list):
            visits = 0
            def __iter__(self):
                for edge in super().__iter__():
                    self.visits += 1
                    yield edge
        targets = [f'branch-{index}' for index in range(100)]
        edges = CountingEdges([(target, 'join', 'success') for target in targets] + [('join', 'end', 'success')])
        plan = parallel_plan(edges, targets, ['end'])
        self.assertEqual(plan['join'], 'join')
        self.assertEqual(plan['branches'], targets)
        self.assertLessEqual(edges.visits, len(edges) * 3)

    def test_exported_direct_and_engine_join_once(self):
        project = {'id': 'join', 'name': 'Join', 'resources': [], 'schemas': [],
                   'tasks': [{**partial_graph().model_dump(), 'kind': 'starter'}]}
        for export in (compiler.raw_python_files, compiler.engine_python_files):
            with self.subTest(export=export.__name__), tempfile.TemporaryDirectory() as directory:
                for name, body in export(project, {'local': []}).items():
                    path = Path(directory) / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                # Count execution of shared Join/End with the packaged runtime.
                if export == compiler.raw_python_files:
                    script = ('import asyncio, importlib; from application.core import Context; '
                              'from application.main import TASKS; task=importlib.import_module(TASKS["main"].__module__); '
                              'seen=[]; original=task.execute_with_policy; '
                              'exec("async def execute(*args, **kwargs):\\n seen.append(args[3]); return await original(*args, **kwargs)"); '
                              'task.execute_with_policy=execute; '
                              'asyncio.run(task.run(Context({}, {}, {}))); '
                              'assert all(seen.count(name)==1 for name in ("Inner", "Join", "End")), seen')
                else:
                    script = ('import asyncio; from application.engine.runtime import WorkflowRuntime; '
                              'from application.engine.models import ProcessDefinition; '
                              f'p=ProcessDefinition.model_validate({partial_graph().model_dump()!r}); '
                              'r=WorkflowRuntime(); result=asyncio.run(r.run(p, {})); '
                              'assert result.status=="completed", result.logs; '
                              'starts=[x.get("runtimeActivityId") for x in result.logs if x.get("message", "").startswith("Activity started:")]; '
                              'assert all(starts.count(name)==1 for name in ("Inner", "Join", "End")), starts')
                result = subprocess.run([sys.executable, '-c', script], cwd=directory, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
