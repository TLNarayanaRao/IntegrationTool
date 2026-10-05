import unittest

from app.mapper import execute, rewrite_references
from app.models import Project
from app.runtime import WorkflowRuntime


class ConditionParityTests(unittest.TestCase):
    def test_literals_grouping_negation_precedence_and_functions(self):
        ctx = {'input': {'text': 'A and B > C', 'n': 5, 'empty': []}, 'last': {},
               'vars': {}, 'properties': {}, 'activities': {}}
        cases = [
            ('${input.text} = "A and B > C"', True),
            ('contains(${input.text}, "and B >")', True),
            ('false or true and false', False),
            ('(false or true) and true', True),
            ('not (${input.n} < 3 or ${input.n} >= 9)', True),
            ('not(contains(${input.text}, "or"))', True),
            ('greaterThan(add(${input.n}, 1), 5) and empty(${input.empty})', True),
            ('"a or b" = "a or b"', True),
            ('"can\\"t" = \'can"t\'', True),
            ('"C:\\\\" = "C:\\\\"', True),
            ('${input.missing} > 1', False),
            ('${input.n} > "text"', False),
            ('null = ${input.missing}', True),
            ('${input.n} = 5e0', True),
        ]
        runtime = WorkflowRuntime()
        for expression, expected in cases:
            with self.subTest(expression=expression):
                mapped = execute(ctx, [dict(target='passed', operator='if', condition=expression, constant=True)])
                self.assertEqual(bool(mapped.get('passed')), expected)
                self.assertEqual(runtime.condition(expression, ctx), expected)

    def test_unclosed_conditions_report_an_error(self):
        for expression in ('(${input.n} = 1', '"unfinished', 'true and', '${input.n'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                execute({'input': {'n': 1}}, [dict(target='passed', operator='if', condition=expression, constant=True)])

    def test_custom_functions_report_missing_arity_and_recursion_errors(self):
        definitions = [dict(id='identity', name='identity', parameters=['value'], expression='$value'),
                       dict(id='recursive', name='recursive', parameters=[], expression='custom:recursive()')]
        runtime = WorkflowRuntime()
        for expression, message in [('custom:missing()', 'not found'), ('custom:identity()', 'expects 1'),
                                    ('custom:recursive()', 'recursion exceeded')]:
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(ValueError, message):
                    execute({}, [dict(target='value', source=expression)], {'customFunctions': definitions})
                with self.assertRaisesRegex(RuntimeError, message):
                    runtime.evaluate_function_expression(expression, {'project': Project(id='custom', name='Custom', custom_functions=definitions)})

    def test_reference_normalization_preserves_literals(self):
        expression = 'contains(${input.text}, "${input.missing} and >")'
        self.assertEqual(rewrite_references(expression, lambda value: value[2:-1]),
                         'contains(input.text, "${input.missing} and >")')

    def test_mapper_preview_resolves_custom_function_activity_aliases(self):
        from app.main import mapper_test
        output = mapper_test({'input': {'name': '  ada  ', 'text': '${input.missing}'},
                              'options': {'customFunctions': [dict(name='normalize', parameters=['value'], expression='upperCase(trim($value))')]},
                              'mappings': [dict(target='name', source='custom:normalize(${Reader.name})'),
                                           dict(target='literal', operator='if', condition='${input.text} = "${input.missing}"', source='"kept"')]})
        self.assertEqual(output['output'], {'name': 'ADA', 'literal': 'kept'})
