import asyncio
import unittest

from app.models import Activity, ProcessDefinition, Project, Transition
from app.runtime import WorkflowRuntime


class CountingTransitions(list):
    visits = 0

    def __iter__(self):
        for transition in super().__iter__():
            self.visits += 1
            yield transition


class RuntimePerformanceTests(unittest.TestCase):
    def test_live_activity_snapshot_is_project_scoped_and_cleared_on_stop(self):
        async def test():
            entered = asyncio.Event()
            class WaitingRuntime(WorkflowRuntime):
                async def execute_with_policy(self, activity, context):
                    entered.set()
                    await asyncio.Future()

            runtime = WaitingRuntime()
            process = ProcessDefinition(id='process',name='My-Task',activities=[Activity(id='start',name='Start',type='start')])
            task = asyncio.create_task(runtime.run(process, {'secret':'not published'}, project=Project(id='workspace',name='Workspace')))
            await asyncio.wait_for(entered.wait(), 1)
            activity, = runtime.active_activities('workspace')
            self.assertEqual((activity['taskName'],activity['activityName']),('My-Task','Start'))
            self.assertNotIn('secret', str(activity))
            self.assertEqual(runtime.active_activities('other'), [])
            snapshot = runtime.execution_snapshot('workspace')
            self.assertEqual(snapshot['status'], 'running')
            self.assertTrue(any('Activity started' in entry['message'] for entry in snapshot['logs']))
            self.assertIsNone(runtime.execution_snapshot('other'))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertEqual(runtime.active_activities('workspace'), [])
            self.assertIsNone(runtime.execution_snapshot('workspace'))
        asyncio.run(test())

    def test_long_process_indexes_transitions_once_instead_of_scanning_each_step(self):
        count = 250
        process = ProcessDefinition(
            id='large', name='Large',
            activities=[Activity(id=str(i), name=str(i), type='start' if i == 0 else 'end' if i == count - 1 else 'basic', config={'operation': 'empty'}) for i in range(count)],
            transitions=[Transition(id=str(i), source=str(i), target=str(i + 1)) for i in range(count - 1)],
        )
        transitions = CountingTransitions(process.transitions)
        process.transitions = transitions
        runtime = WorkflowRuntime()
        result = asyncio.run(runtime.run(process, {}, project=Project(id='long-process',name='Long-Process')))
        self.assertEqual(result.status, 'completed')
        self.assertIsNone(runtime.execution_snapshot('long-process'))
        self.assertIn(str(count - 1), result.activity_outputs)
        self.assertLessEqual(transitions.visits, len(transitions) * 10)


if __name__ == '__main__':
    unittest.main()
