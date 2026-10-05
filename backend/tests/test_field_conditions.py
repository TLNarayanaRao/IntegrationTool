import unittest
from backend.app.runtime import WorkflowRuntime


class FieldConditionTests(unittest.TestCase):
    def test_choose_first_match_and_fallback(self):
        runtime = WorkflowRuntime()
        ctx = {'input': {'status': 'B'}, 'last': {}, 'properties': {}, 'vars': {}, 'activities': {}}
        rule = {'$rule': 'choose', 'whens': [
            {'condition': "${input.status} = 'A'", 'source': "'alpha'"},
            {'condition': "${input.status} = 'B'", 'source': "'beta'"},
            {'condition': 'true', 'source': "'later'"}], 'otherwise': "'fallback'"}
        self.assertEqual(runtime.evaluate_mapping(rule, ctx), (True, 'beta'))
        rule['whens'] = rule['whens'][:1]
        self.assertEqual(runtime.evaluate_mapping(rule, ctx), (True, 'fallback'))

    def test_unselected_values_are_not_resolved(self):
        runtime = WorkflowRuntime()
        def resolve(value, ctx):
            if value == 'bad': raise AssertionError('Inactive branch evaluated')
            return value
        runtime.resolve = resolve
        self.assertEqual(runtime.evaluate_mapping({'$rule': 'choose', 'source': 'bad', 'whens': [{'condition': 'true', 'source': 'good'}], 'otherwise': 'bad'}, {}), (True, 'good'))
        self.assertEqual(runtime.evaluate_mapping({'$rule': 'when-otherwise', 'condition': 'false', 'source': 'bad', 'otherwise': 'good'}, {}), (True, 'good'))
        self.assertEqual(runtime.evaluate_mapping({'$rule': 'if', 'condition': 'false', 'source': 'bad'}, {}), (False, None))
