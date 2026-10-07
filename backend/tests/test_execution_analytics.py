import unittest
from types import SimpleNamespace
from unittest.mock import patch
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
