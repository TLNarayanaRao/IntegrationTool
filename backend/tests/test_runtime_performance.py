import asyncio
import unittest

from app.models import Activity, ProcessDefinition, Transition
from app.runtime import WorkflowRuntime


class CountingTransitions(list):
    visits = 0

    def __iter__(self):
        for transition in super().__iter__():
            self.visits += 1
            yield transition


class RuntimePerformanceTests(unittest.TestCase):
    def test_long_process_indexes_transitions_once_instead_of_scanning_each_step(self):
        count = 250
        process = ProcessDefinition(
            id='large', name='Large',
            activities=[Activity(id=str(i), name=str(i), type='start' if i == 0 else 'end' if i == count - 1 else 'basic', config={'operation': 'empty'}) for i in range(count)],
            transitions=[Transition(id=str(i), source=str(i), target=str(i + 1)) for i in range(count - 1)],
        )
        transitions = CountingTransitions(process.transitions)
        process.transitions = transitions
        result = asyncio.run(WorkflowRuntime().run(process, {}))
        self.assertEqual(result.status, 'completed')
        self.assertIn(str(count - 1), result.activity_outputs)
        self.assertLessEqual(transitions.visits, len(transitions) * 10)


if __name__ == '__main__':
    unittest.main()
