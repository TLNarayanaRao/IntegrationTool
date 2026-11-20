import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.execution_analytics import activity_timings


class ExecutionAnalyticsTests(unittest.TestCase):
    def test_completed_run_history_captures_its_own_timing_logs(self):
        from app.main import _publish_runtime_state
        result = SimpleNamespace(run_id='run', correlation_id='correlation', status='completed', started_at='start', ended_at='end', duration_ms=15, activity_outputs={}, task_outputs={}, logs=[{'kind': 'activity', 'activityId': 'a', 'durationMs': 10}])
        with patch('app.main.runtime_states', {}):
            state = _publish_runtime_state('analytics-test', status='completed', logs=[{'kind': 'activity', 'activityId': 'unrelated', 'durationMs': 90}], result=result)
        self.assertEqual(state['lastExecution']['activityTimings'][0]['activityId'], 'a')

    def test_timings_preserve_iterations_failures_and_exclude_payloads(self):
        events = [
            {'kind': 'activity', 'runtimeActivityId': 'a', 'taskId': 'main', 'activityName': 'Mapper', 'durationMs': 0, 'level': 'INFO', 'payload': {'secret': 'credential'}},
            {'kind': 'activity', 'activityId': 'a', 'taskId': 'main', 'durationMs': 12.5, 'level': 'ERROR'},
            {'kind': 'activity', 'activityId': 'a', 'message': 'started'},
            {'kind': 'lifecycle', 'durationMs': 50},
        ]
        rows = activity_timings(events)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['name'], 'Mapper')
        self.assertEqual(rows[1]['status'], 'failed')
        self.assertNotIn('secret', str(rows))

    def test_invalid_durations_are_not_reported(self):
        rows = activity_timings([{'kind': 'activity', 'activityId': 'a', 'durationMs': value} for value in [-1, float('nan'), float('inf'), True, '10', None]])
        self.assertEqual(rows, [])

    def test_publisher_phases_exclude_payloads_and_invalid_values(self):
        rows = activity_timings([{'kind': 'activity', 'activityId': 'sender', 'durationMs': 5,
            'publishTiming': {'bridgeMs': 4, 'providerSendMs': 2, 'queueMs': 0,
                              'sessionWaitMs': float('nan'), 'enqueueMs': True, 'password': 'secret'}}])
        self.assertEqual(rows[0]['publishTiming'], {'bridgeMs': 4, 'providerSendMs': 2, 'queueMs': 0})


class DetachedExecutionAnalyticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_spawned_child_records_its_own_history_without_blocking_parent(self):
        from app import main
        from app.models import Project
        from app.runtime import WorkflowRuntime

        project = Project.model_validate({'id': 'detached-history', 'name': 'Detached history', 'tasks': [
            {'id': 'main', 'name': 'Parent', 'kind': 'starter', 'activities': [
                {'id': 'start', 'name': 'Start', 'type': 'start'},
                {'id': 'call', 'name': 'Launch', 'type': 'call_task', 'config': {'taskId': 'child', 'spawn': True}},
                {'id': 'end', 'name': 'End', 'type': 'end'},
            ], 'transitions': [{'id': 'enter', 'source': 'start', 'target': 'call'},
                               {'id': 'finish', 'source': 'call', 'target': 'end'}]},
            {'id': 'child', 'name': 'Background', 'kind': 'subtask', 'activities': [
                {'id': 'work', 'name': 'Work', 'type': 'log'},
            ], 'transitions': []},
        ]})
        runtime = WorkflowRuntime()
        runtime.on_detached_result = main._record_detached_execution
        real_execute = runtime.execute_with_policy
        release = asyncio.Event()

        async def execute(activity, context):
            if activity.id == 'work':
                await release.wait()
            return await real_execute(activity, context)

        with patch.object(main, 'runtime_states', {}), patch.object(main, '_write_runtime_logs', new_callable=AsyncMock), patch.object(runtime, 'execute_with_policy', execute):
            parent = await asyncio.wait_for(runtime.run(project.tasks[0], {}, project=project), timeout=2)
            self.assertEqual(parent.status, 'completed')
            main._publish_runtime_state(project.id, status=parent.status, logs=parent.logs, result=parent)
            release.set()
            await asyncio.wait_for(asyncio.gather(*runtime._detached_runs), timeout=2)
            state = main.runtime_states[project.id]

        self.assertEqual(state['lastExecution']['runId'], parent.run_id)
        self.assertEqual(state['status'], 'completed')
        detached = state['executions'][0]
        self.assertEqual(detached['detachedTask'], 'Background')
        self.assertEqual([(row['activityId'], row['taskId']) for row in detached['activityTimings']], [('work', 'child')])
