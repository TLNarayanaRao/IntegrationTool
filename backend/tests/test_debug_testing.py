import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.debugger import DebugManager
from app.models import DebugAction, Project
from app.runtime import WorkflowRuntime


class DebugTestingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = WorkflowRuntime()
        self.manager = DebugManager(self.runtime)
        self.project = Project(id='debug-test', name='Debug Test', tasks=[{
            'id': 'main', 'name': 'Main', 'kind': 'starter', 'activities': [
                {'id': 'start', 'name': 'Start', 'type': 'start'},
                {'id': 'log', 'name': 'Log', 'type': 'log', 'config': {
                    'message': '${input.message}', 'inputMappings': {'payload': '${last.payload}'}}},
                {'id': 'end', 'name': 'End', 'type': 'end'}],
            'transitions': [{'id': 'a', 'source': 'start', 'target': 'log'},
                            {'id': 'b', 'source': 'log', 'target': 'end'}]}])
        self.session = self.manager.start(self.project, 'main', {'message': 'original'}, {}, {}, [])['sessionId']

    async def test_whole_payload_replacement_and_null(self):
        for value in ([1, 2], 'text', None, {'id': 3}):
            options = DebugAction(action='set_value', path='input', value=value).model_dump(exclude={'action'}, exclude_unset=True)
            view = await self.manager.action(self.session, 'set_value', options)
            self.assertEqual(view['variables']['input'], value)
            self.assertEqual(view['variables']['last'], {'message': 'original'})

    async def test_nested_edit_does_not_mutate_aliased_last(self):
        view = await self.manager.action(self.session, 'set_value', {'path': 'input.message', 'value': 'changed'})
        self.assertEqual(view['variables']['input']['message'], 'changed')
        self.assertEqual(view['variables']['last']['message'], 'original')

    async def test_preview_resolves_mappings_then_literal_field_overrides(self):
        with patch.object(self.runtime, 'execute_with_policy', new_callable=AsyncMock) as execute:
            view = await self.manager.action(self.session, 'preview_activity', {
                'activity_id': 'log', 'value': {'message': 'test', 'payload': [1, 2]},
                'fields': {'message': 'literal ${not.resolved}'}})
            execute.assert_not_awaited()
        result = view['lastActivityTest']
        self.assertEqual(result['resolvedInputs']['payload'], [1, 2])
        self.assertEqual(result['resolvedInputs']['message'], 'literal ${not.resolved}')
        self.assertEqual(view['currentActivityId'], 'start')

    async def test_single_activity_assertions_and_history(self):
        view = await self.manager.action(self.session, 'test_activity', {
            'activity_id': 'start', 'value': {'count': 3}, 'assertion': '${last.count} > 0'})
        self.assertEqual(view['lastActivityTest']['status'], 'passed')
        self.assertEqual(view['lastActivityTest']['output'], {'count': 3})
        self.assertEqual(view['currentActivityId'], 'start')
        self.assertEqual(view['variables']['input'], {'message': 'original'})
        view = await self.manager.action(self.session, 'test_activity', {
            'activity_id': 'start', 'value': {'count': 0}, 'assertion': '${last.count} > 0'})
        self.assertEqual(view['lastActivityTest']['status'], 'assertion_failed')
        self.assertEqual(len(view['testHistory']), 2)

    async def test_mock_steps_without_executing_activity(self):
        with patch.object(self.runtime, 'execute_with_policy', new_callable=AsyncMock) as execute:
            view = await self.manager.action(self.session, 'mock_step', {'activity_id': 'start', 'value': None})
            execute.assert_not_awaited()
        self.assertEqual(view['currentActivityId'], 'log')
        self.assertIsNone(view['variables']['last'])

    async def test_failed_test_does_not_fail_paused_workflow(self):
        with patch.object(self.runtime, 'execute_with_policy', new_callable=AsyncMock, side_effect=RuntimeError('test failure')):
            view = await self.manager.action(self.session, 'test_activity', {'activity_id': 'log', 'value': {}})
        self.assertEqual(view['lastActivityTest']['error'], 'test failure')
        self.assertEqual(view['status'], 'paused')
        self.assertEqual(view['currentActivityId'], 'start')

    async def test_timeout_leaves_session_available(self):
        async def slow_activity(*args):
            await asyncio.sleep(10)
        with patch.object(self.runtime, 'execute_with_policy', side_effect=slow_activity):
            view = await self.manager.action(self.session, 'test_activity', {
                'activity_id': 'log', 'value': {}, 'timeout_seconds': 0.1})
        self.assertEqual(view['lastActivityTest']['status'], 'failed')
        self.assertEqual(view['lastActivityTest']['error'], 'TimeoutError')
        self.assertEqual(view['status'], 'paused')
        self.assertFalse(self.manager.sessions[self.session]['_testing'])

    async def test_activity_selection_is_scoped_to_selected_process(self):
        self.project.tasks.append(type(self.project.tasks[0])(id='child', name='Child', kind='subtask', activities=[
            {'id': 'start', 'type': 'start', 'name': 'Child Start'},
            {'id': 'log', 'type': 'log', 'name': 'Child Log', 'config': {'message': '${context.taskId}'}}]))
        view = await self.manager.action(self.session, 'preview_activity', {
            'task_id': 'child', 'activity_id': 'log', 'value': {'child': True}})
        self.assertEqual(view['lastActivityTest']['taskId'], 'child')
        self.assertEqual(view['lastActivityTest']['resolvedInputs']['message'], 'child')
        self.assertEqual(view['currentTaskId'], 'main')
        view = await self.manager.action(self.session, 'test_activity', {
            'task_id': 'child', 'activity_id': 'start', 'value': [1, 2]})
        self.assertEqual(view['lastActivityTest']['output'], [1, 2])
        self.assertEqual(view['currentTaskId'], 'main')
        with self.assertRaisesRegex(ValueError, 'currently paused'):
            await self.manager.action(self.session, 'mock_step', {
                'task_id': 'child', 'activity_id': 'start', 'value': {}})
        with self.assertRaisesRegex(ValueError, 'process was not found'):
            await self.manager.action(self.session, 'preview_activity', {
                'task_id': 'missing', 'activity_id': 'start'})


if __name__ == '__main__':
    unittest.main()
