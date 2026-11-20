import asyncio
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.debug_trace import DebugTrace
from app.debugger import DebugManager
from app.execution_analytics import activity_timings
from app.main import app
from app.models import Project
from app.runtime import WorkflowRuntime


def activity(identity, kind='log', **config):
    return {'id': identity, 'type': kind, 'name': identity, 'config': config}


def link(source, target, kind='success', condition='', identity=None):
    return {'id': identity or f'{source}-{target}', 'source': source, 'target': target, 'type': kind, 'condition': condition}


def task(identity, activities, transitions, kind='starter'):
    return {'id': identity, 'name': identity, 'kind': kind, 'activities': activities, 'transitions': transitions}


class DebugTraceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = WorkflowRuntime()
        self.manager = DebugManager(self.runtime)

    def start(self, *tasks, breakpoints=(), payload=None, capture=True):
        project = Project(id='trace-project', name='Trace project', tasks=list(tasks))
        session = self.manager.start(project, tasks[0]['id'], payload or {}, {}, {}, list(breakpoints), capture_trace=capture)
        return session['sessionId']

    def report(self, session, **options):
        return self.manager.sessions[session]['trace'].report(**options)

    async def test_branch_paths_keep_actual_edge_ids_and_join_after_both_branches(self):
        session = self.start(task('main', [
            activity('start', 'start'), activity('left'), activity('right'), activity('unused'), activity('join'), activity('end', 'end'),
        ], [link('start', 'left'), link('start', 'right'), link('start', 'unused', 'success_condition', 'false'),
            link('left', 'join'), link('right', 'join'), link('unused', 'join'), link('join', 'end')]),
            breakpoints=['left'])
        paused = await self.manager.action(session, 'continue')
        self.assertEqual(paused['currentActivityId'], 'left')
        trace = self.report(session)
        self.assertEqual({row['status'] for row in trace['threads']}, {'active', 'waiting', 'queued'})
        self.assertEqual([event['transitionId'] for event in trace['events'] if event['kind'] == 'transition'], ['start-left'])
        for _ in range(3):
            self.assertEqual(self.manager.view(self.manager.sessions[session])['activeThreadId'], paused['activeThreadId'])
        done = await self.manager.action(session, 'continue')
        self.assertEqual(done['status'], 'completed')
        trace = self.report(session)
        self.assertEqual([event['transitionId'] for event in trace['events'] if event['kind'] == 'transition'],
                         ['start-left', 'left-join', 'start-right', 'right-join', 'join-end'])
        self.assertEqual([event['activityId'] for event in trace['events'] if event['kind'] == 'join'], ['join'])
        self.assertEqual([row['status'] for row in trace['threads']], ['completed'] * 3, trace['threads'])
        right = next(row for row in trace['threads'] if row['entryActivityId'] == 'right')
        page = self.report(session, thread=right['id'], limit=2)
        older = self.report(session, before=page['olderBefore'], thread=right['id'], limit=2)
        self.assertEqual([row['threadId'] for row in page['events'] + older['events']], [right['id']] * 4)
        self.assertLess(older['events'][-1]['sequence'], page['events'][0]['sequence'])

    async def test_partial_join_continues_in_the_parent_branch_group(self):
        session = self.start(task('main', [
            activity('fork', 'start'), activity('a'), activity('b'), activity('c'),
            activity('inner'), activity('outer'), activity('end', 'end'),
        ], [link('fork', 'a'), link('fork', 'b'), link('fork', 'c'),
            link('a', 'inner'), link('b', 'inner'), link('inner', 'outer'), link('c', 'outer'), link('outer', 'end')]))
        self.assertEqual((await self.manager.action(session, 'continue'))['status'], 'completed')
        report = self.report(session)
        inner, outer = [event for event in report['events'] if event['kind'] == 'join']
        self.assertEqual((inner['activityId'], outer['activityId']), ('inner', 'outer'))
        threads = {row['id']: row for row in report['threads']}
        self.assertEqual(threads[inner['threadId']]['kind'], 'branch group')
        self.assertEqual(threads[inner['threadId']]['parentId'], outer['threadId'])
        self.assertEqual(sum(event.get('transitionId') == 'inner-outer' for event in report['events']), 1)

    async def test_group_iteration_records_only_the_actual_path(self):
        process = task('main', [activity('start', 'start'), activity('work'), activity('end', 'end')],
                       [link('start', 'work'), link('work', 'end')])
        process['groups'] = [{'id': 'repeat', 'type': 'repeat', 'name': 'Repeat',
                              'member_activity_ids': ['work'], 'config': {'condition': '${vars.index} >= 3'}}]
        session = self.start(process)
        self.assertEqual((await self.manager.action(session, 'continue'))['status'], 'completed')
        events = self.report(session)['events']
        visits = [row for row in events if row['kind'] == 'activity' and row['activityId'] == 'work']
        self.assertEqual([row['groups'][0]['iteration'] for row in visits], [1, 2, 3])
        self.assertEqual(sum(row.get('transitionId') == 'work-end' for row in events), 1)
        self.assertEqual([row['targetActivityId'] for row in events if row['kind'] == 'redirect'], ['work', 'work'])

    def call_tasks(self):
        return (
            task('main', [activity('start', 'start'), activity('call', 'call_task', taskId='child'),
                          activity('shared'), activity('end', 'end')],
                 [link('start', 'call'), link('call', 'shared'), link('shared', 'end')]),
            task('child', [activity('start', 'start'), activity('shared'), activity('end', 'end')],
                 [link('start', 'shared'), link('shared', 'end')], 'subtask'),
        )

    async def test_step_over_steps_out_to_caller_and_records_child_thread(self):
        session = self.start(*self.call_tasks())
        await self.manager.action(session, 'step_over')
        paused = await self.manager.action(session, 'step_over')
        self.assertEqual((paused['currentTaskId'], paused['currentActivityId']), ('main', 'shared'))
        trace = self.report(session)
        calls = [event for event in trace['events'] if event['kind'] in ('call', 'return')]
        self.assertEqual([event['kind'] for event in calls], ['call', 'return'])
        self.assertEqual(calls[0]['targetThreadId'], calls[1]['targetThreadId'])
        self.assertEqual(self.report(session)['metrics']['activities']['completed'], 5)
        rows = activity_timings(paused['logs'])
        self.assertEqual([(row['taskId'], row['timingScope']) for row in rows if row['activityId'] == 'call'],
                         [('main', 'call_setup')])
        self.assertTrue(any(row['taskId'] == 'child' and row['activityId'] == 'shared' for row in rows))

    async def test_step_out_can_honor_breakpoint_and_run_to_is_task_scoped(self):
        session = self.start(*self.call_tasks(), breakpoints=['shared'])
        await self.manager.action(session, 'step_over')
        entered = await self.manager.action(session, 'step_in')
        self.assertEqual((entered['currentTaskId'], entered['currentActivityId']), ('child', 'start'))
        paused = await self.manager.action(session, 'step_out')
        self.assertEqual((paused['currentTaskId'], paused['currentActivityId']), ('child', 'shared'))
        outer = await self.manager.action(session, 'run_to', {'task_id': 'main', 'activity_id': 'shared'})
        self.assertEqual((outer['currentTaskId'], outer['pauseReason']), ('main', 'run-to:shared'))

        session = self.start(*self.call_tasks())
        outer = await self.manager.action(session, 'run_to', {'task_id': 'main', 'activity_id': 'shared'})
        self.assertEqual((outer['currentTaskId'], outer['pauseReason']), ('main', 'run-to:shared'))

    async def test_pause_waits_until_inflight_activity_finishes_and_prevents_second_driver(self):
        session = self.start(*self.call_tasks(), breakpoints=['shared'])
        entered, release = asyncio.Event(), asyncio.Event()
        execute = self.runtime.execute_with_policy

        async def blocked(activity, ctx):
            if activity.id == 'start':
                entered.set()
                await release.wait()
            return await execute(activity, ctx)

        with patch.object(self.runtime, 'execute_with_policy', side_effect=blocked):
            driver = asyncio.create_task(self.manager.action(session, 'continue'))
            await asyncio.wait_for(entered.wait(), 2)
            requested = await self.manager.action(session, 'pause')
            self.assertEqual(requested['status'], 'running')
            self.assertTrue(requested['pauseRequested'])
            with self.assertRaisesRegex(ValueError, 'already executing'):
                await self.manager.action(session, 'step_over')
            release.set()
            paused = await driver
        self.assertEqual((paused['pauseReason'], paused['currentActivityId']), ('user', 'call'))
        done = await self.manager.action(session, 'continue_without_breakpoints')
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(done['breakpoints'], ['shared'])

    async def test_listener_break_and_two_jobs_have_separate_thread_paths(self):
        session = self.start(task('main', [activity('timer', 'timer', operation='schedule'), activity('end', 'end')],
                                  [link('timer', 'end')]))
        await self.manager.action(session, 'break_next_event')
        paused = await self.manager.trigger_event(session, {'batch': 1})
        self.assertEqual((paused['status'], paused['pauseReason']), ('paused', 'next-event'))
        self.assertFalse(paused['breakOnNextEvent'])
        await self.manager.action(session, 'continue')
        idle = await self.manager.trigger_event(session, {'batch': 2})
        self.assertEqual(idle['status'], 'listening')
        summary = self.report(session)
        self.assertEqual(summary['metrics']['jobs']['completed'], 2)
        self.assertEqual(summary['metrics']['activities']['received'], 2)
        self.assertEqual({thread['job'] for thread in summary['threads']}, {1, 2})
        timings = [row for row in activity_timings(idle['logs']) if row['activityId'] == 'timer']
        self.assertEqual([row['timingScope'] for row in timings], ['event_handoff', 'event_handoff'])

    async def test_event_starters_use_the_same_debug_analytics_path(self):
        from app.main import CONTINUOUS_EVENT_OPERATIONS

        starters = {**CONTINUOUS_EVENT_OPERATIONS, 'http_listener': {'listen'}, 'rest': {'receiver'}}
        for kind, operations in starters.items():
            for operation in sorted(operations):
                with self.subTest(kind=kind, operation=operation):
                    session = self.start(task('main', [activity('receive', kind, operation=operation),
                                                       activity('end', 'end')], [link('receive', 'end')]))
                    if kind in ('http_listener', 'rest'):
                        # Hosted Debug activates event mode before handing off the request.
                        self.manager.sessions[session].update(listenerMode=True, status='listening')
                    view = await self.manager.trigger_event(session, {'body': 'fixture'})
                    rows = [row for row in activity_timings(view['logs']) if row['activityId'] == 'receive']
                    self.assertEqual(len(rows), 1)
                    self.assertEqual((rows[0]['type'], rows[0]['operation']), (kind, operation))
                    self.assertEqual(rows[0]['timingScope'], 'idoc_intake' if operation == 'idoc_listener' else 'event_handoff')

    async def test_call_input_failure_has_a_timing_record(self):
        session = self.start(*self.call_tasks())
        await self.manager.action(session, 'step_over')
        with patch.object(self.runtime, 'map_input_values', side_effect=ValueError('Invalid call mapping')):
            failed = await self.manager.action(session, 'continue')
        self.assertEqual(failed['status'], 'failed')
        calls = [row for row in activity_timings(failed['logs']) if row['activityId'] == 'call']
        self.assertEqual([(row['status'], row['timingScope']) for row in calls], [('failed', 'call_setup')])

    async def test_child_fault_follows_parent_error_edge(self):
        parent, child = self.call_tasks()
        parent['transitions'].append(link('call', 'end', 'error', identity='handler'))
        child['activities'].append(activity('sibling'))
        child['transitions'] += [link('start', 'sibling'), link('sibling', 'end')]
        session = self.start(parent, child)
        execute = self.runtime.execute_with_policy

        async def fault(activity, ctx):
            if activity.id == 'shared' and ctx['context']['taskId'] == 'child':
                raise ValueError('test child fault')
            return await execute(activity, ctx)

        with patch.object(self.runtime, 'execute_with_policy', side_effect=fault):
            paused = await self.manager.action(session, 'continue')
        self.assertEqual((paused['currentTaskId'], paused['currentActivityId'], paused['pauseReason']),
                         ('main', 'end', 'exception'))
        report = self.report(session)
        self.assertEqual(report['events'][-1]['transitionId'], 'handler')
        calls = [row for row in activity_timings(paused['logs']) if row['activityId'] == 'call']
        self.assertEqual([(row['status'], row['timingScope']) for row in calls], [('failed', 'call_setup')])
        self.assertEqual(report['metrics']['activities']['failed'], 2)
        self.assertEqual((await self.manager.action(session, 'continue'))['status'], 'completed')
        threads = self.report(session)['threads']
        self.assertEqual(next(row for row in threads if row['entryActivityId'] == 'sibling')['status'], 'skipped')

    async def test_metrics_are_available_when_capture_is_disabled(self):
        session = self.start(*self.call_tasks(), capture=False)
        await self.manager.action(session, 'continue')
        metrics = self.report(session)
        self.assertEqual(metrics['events'], [])
        self.assertEqual(metrics['threads'], [])
        self.assertEqual(metrics['metrics']['jobs']['completed'], 1)
        self.assertEqual(len(metrics['metrics']['byActivity']), 7)


class DebugTraceReportTests(unittest.TestCase):
    def test_metrics_keep_all_visits_when_trace_is_truncated_and_exclude_pauses(self):
        clock = [0.0]
        with patch('app.debug_trace.perf_counter', side_effect=lambda: clock[0]):
            trace = DebugTrace(2, True)
            project = Project(id='test', name='Test', tasks=[task('main', [activity('start', 'start')], [])])
            process = project.tasks[0]
            frame = {'taskId': 'main', 'activityId': 'start'}
            trace.open_job(frame, process)
            trace.resume()
            trace.activity(frame, process.activities[0], 'completed', 500)
            clock[0] = 1
            trace.suspend()
            clock[0] = 11
            trace.resume()
            trace.activity(frame, process.activities[0], 'failed', 250)
            trace.activity(frame, process.activities[0], 'mocked')
            clock[0] = 12
            trace.finish_job('completed')
            report = trace.report()
        self.assertEqual(report['metrics']['activeMs'], 2000)
        self.assertEqual(report['metrics']['wallWindowMs'], 12000)
        self.assertEqual(report['metrics']['droppedEvents'], 1)
        self.assertEqual(report['metrics']['byActivity'][0]['totalMs'], 750)
        self.assertEqual(report['metrics']['byActivity'][0]['count'], 3)
        self.assertEqual([event['sequence'] for event in report['events']], [2, 3])

    def test_api_launch_read_and_download_metadata_without_input(self):
        project_id = f'debug-trace-{uuid4()}'
        project = {'id': project_id, 'name': 'Trace API', 'tasks': [
            task('main', [activity('start', 'start'), activity('end', 'end')], [link('start', 'end')]),
        ]}
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/projects', json=project).status_code, 200)
            try:
                started = client.post(f'/api/projects/{project_id}/debug', json={
                    'task_id': 'main', 'pause_at_entry': True, 'input': {'example': 'private-fixture-payload'},
                })
                self.assertEqual(started.status_code, 200, started.text)
                self.assertEqual(started.json()['status'], 'paused')
                session = f"/api/debug/{started.json()['sessionId']}"
                terminal = client.post(session + '/action', json={'action': 'continue'})
                self.assertEqual(terminal.json()['output'], {'example': 'private-fixture-payload'})
                report = client.get(session + '/trace?limit=1')
                self.assertEqual(len(report.json()['events']), 1)
                self.assertIsNotNone(report.json()['olderBefore'])
                export = client.get(session + '/trace?download=true')
                self.assertIn('attachment', export.headers['content-disposition'])
                self.assertNotIn('private-fixture-payload', export.text)
                self.assertEqual(export.json()['metrics']['jobs']['completed'], 1)
                self.assertEqual(client.get(session + '/trace?limit=501').status_code, 422)
            finally:
                client.delete(f'/api/projects/{project_id}')
