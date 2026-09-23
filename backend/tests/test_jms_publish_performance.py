import asyncio
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app.java_bridge import JavaBridgeError
from app.runtime import WorkflowRuntime
from app.debugger import DebugManager
from app.models import Project


class JmsPublishSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_debug_step_uses_send_executor_and_logs_timing(self):
        runtime = WorkflowRuntime()
        project = Project(id='ems-perf', name='EMS test', resources=[{
            'id': 'ems', 'name': 'EMS', 'type': 'ems', 'config': {
                'mode': 'external', 'serverUrl': 'tcp://example:7222', 'username': 'test', 'password': 'test'}}],
            tasks=[{'id': 'main', 'name': 'Main', 'kind': 'starter', 'activities': [
                {'id': 'start', 'name': 'Start', 'type': 'start'},
                {'id': 'send', 'name': 'Send', 'type': 'ems', 'config': {
                    'operation': 'send', 'resourceId': 'ems', 'destination': 'test', 'message': 'hello'}},
                {'id': 'end', 'name': 'End', 'type': 'end'}],
                'transitions': [{'id': 'a', 'source': 'start', 'target': 'send'}, {'id': 'b', 'source': 'send', 'target': 'end'}]}])
        manager = DebugManager(runtime)
        session = manager.start(project, 'main', {}, {'ems': project.resources[0]}, {}, [])['sessionId']
        try:
            await manager.action(session, 'step_over')
            with patch('app.runtime.execute_jms', return_value={'published': True, 'messageId': 'id'}) as send:
                result = await manager.action(session, 'step_over')
                send.assert_called_once()
            self.assertEqual(result['currentActivityId'], 'end')
            self.assertIn('publishTiming', result['variables']['last'])
            self.assertTrue(any('Java bridge' in entry.get('message', '') for entry in result['logs']))
        finally:
            runtime.close_publishers()

    async def test_send_does_not_wait_for_saturated_receiver_executor(self):
        runtime = WorkflowRuntime()
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        occupied, release = threading.Event(), threading.Event()
        def receiver():
            occupied.set()
            release.wait(5)
        blocked = loop.run_in_executor(None, receiver)
        try:
            while not occupied.is_set():
                await asyncio.sleep(0)
            with patch('app.runtime.execute_jms', return_value={'published': True, 'messageId': 'id'}) as send:
                result = await asyncio.wait_for(runtime._publish_jms_isolated(
                    {'serverUrl': 'test'}, 'queue', 'payload', {'deliveryMode': 'Persistent'}), 1)
                self.assertFalse(blocked.done())
                self.assertEqual(result['messageId'], 'id')
                self.assertEqual(set(result['publishTiming']), {'queueMs', 'bridgeMs', 'totalMs'})
                send.assert_called_once_with({'serverUrl': 'test'}, 'send', 'queue', 'payload', {'deliveryMode': 'Persistent'})
        finally:
            release.set()
            await blocked
            runtime.close_publishers()
        self.assertIsNone(runtime._jms_executor)

    async def test_send_failure_is_not_retried(self):
        runtime = WorkflowRuntime()
        try:
            with patch('app.runtime.execute_jms', side_effect=JavaBridgeError('broker failure')) as send:
                with self.assertRaisesRegex(JavaBridgeError, 'broker failure'):
                    await runtime._publish_jms_isolated({}, 'queue', 'payload', {})
                send.assert_called_once()
        finally:
            runtime.close_publishers()

    async def test_worker_pool_is_reused(self):
        runtime = WorkflowRuntime()
        try:
            with patch('app.runtime.execute_jms', return_value={'published': True}):
                await runtime._publish_jms_isolated({}, 'one', 'payload', {})
                pool = runtime._jms_executor
                await runtime._publish_jms_isolated({}, 'two', 'payload', {})
                self.assertIs(runtime._jms_executor, pool)
        finally:
            runtime.close_publishers()
