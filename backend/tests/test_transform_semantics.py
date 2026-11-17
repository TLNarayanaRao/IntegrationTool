"""Documented transformation semantics, not a substitute vendor runtime."""
import unittest

from app.dataweave import DataWeaveError, execute


def transform(body, payload=None):
    return execute('%dw 2.0\noutput application/json\n---\n' + body, payload=payload)


class TransformSemanticsTests(unittest.TestCase):
    def test_equality_does_not_attempt_relational_comparison(self):
        self.assertTrue(transform('payload.value == null', {'value': None}))
        self.assertTrue(transform('payload == {a: 1}', {'a': 1}))
        self.assertFalse(transform('true == 1'))

    def test_only_selected_branch_and_needed_default_execute(self):
        self.assertEqual(transform('if (true) "ok" else (1 / 0)'), 'ok')
        self.assertEqual(transform('if (false) (1 / 0) else "ok"'), 'ok')
        self.assertEqual(transform('"ok" default (1 / 0)'), 'ok')
        self.assertEqual(transform('null default "fallback"'), 'fallback')
        self.assertFalse(transform('false and ((1 / 0) > 1)'))
        self.assertTrue(transform('true or ((1 / 0) > 1)'))

    def test_empty_and_null_collections_do_not_execute_lambda(self):
        self.assertEqual(transform('[] map (item) -> 1 / item'), [])
        self.assertEqual(transform('{} mapObject (value, key) -> 1 / value'), {})
        self.assertIsNone(transform('null map (item) -> 1 / item'))
        self.assertIsNone(transform('null filter (item) -> item > 0'))

    def test_object_filter_and_three_parameter_dynamic_keys(self):
        self.assertEqual(transform('payload filterObject (value, key, index) -> value != null and index < 2',
                                   {'a': 1, 'b': None, 'c': 3}), {'a': 1})
        self.assertEqual(transform('payload mapObject (value, key, index) -> {(index): {(value): key}}',
                                   {'a': 'b', 'c': 'd'}), {'0': {'b': 'a'}, '1': {'d': 'c'}})
        self.assertEqual(transform('payload pluck (value, key, index) -> {key: $$, index: $$$}',
                                   {'a': 1}), [{'key': 'a', 'index': 0}])

    def test_collection_extrema_and_sequence_functions(self):
        self.assertEqual(transform('payload maxBy (item) -> item.score', [{'score': 1}, {'score': 3}]), {'score': 3})
        self.assertEqual(transform('payload minBy (item) -> item.score', [{'score': 1}, {'score': 3}]), {'score': 1})
        self.assertIsNone(transform('[] maxBy (item) -> item.score'))
        self.assertEqual(transform('{z: zip([1,2], ["a"]), u: unzip([[1,"a"],[2,"b"]]), m: mod(5,2), p: pow(2,3)}'),
                         {'z': [[1, 'a']], 'u': [[1, 2], ['a', 'b']], 'm': 1, 'p': 8})

    def test_unicode_whitespace_and_numeric_lexing(self):
        self.assertEqual(transform("{city: 'München', greeting: 'こんにちは'}  \n"), {'city': 'München', 'greeting': 'こんにちは'})
        self.assertEqual(transform('1-2'), -1)
        self.assertEqual(transform('1e3 + -2'), 998)

    def test_xml_leaf_attributes_and_mime_parameters(self):
        result = execute('%dw 2.0\noutput application/json\n---\npayload',
                         payload='<root><entry id="A">value</entry></root>', input_mime_type='application/xml; charset=UTF-8')
        self.assertEqual(result, {'root': {'entry': {'@id': 'A', '#text': 'value'}}})

    def test_bad_arithmetic_is_a_transform_error(self):
        with self.assertRaises(DataWeaveError):
            transform('1 / 0')
        with self.assertRaises(DataWeaveError):
            transform('payload map (item) -> item', 4)

    def test_unsupported_language_features_fail_explicitly(self):
        for script in ('%dw 1.0\noutput application/json\n---\npayload',
                       '%dw 2.0\nimport * from unknown::Library\n---\npayload',
                       '%dw 2.0\noutput application/xml writeNilOnNull=true\n---\n{root: null}',
                       '%dw 2.0\noutput application/pdf\n---\npayload'):
            with self.subTest(script=script), self.assertRaises(DataWeaveError):
                execute(script, payload={})
        with self.assertRaisesRegex(DataWeaveError, 'Unknown transform identifier'):
            transform('paylod.name', {'name': 'Ada'})

    def test_unselected_branch_is_still_checked_for_valid_syntax(self):
        with self.assertRaises(DataWeaveError):
            transform('if (true) 1 else {broken: }')
        with self.assertRaises(DataWeaveError):
            transform('{a: [1, 2] map (item) -> item as Unknown}')

    def test_xml_rejects_entities_and_preserves_leaf_attributes_on_write(self):
        with self.assertRaises(DataWeaveError):
            execute('%dw 2.0\noutput application/json\n---\npayload',
                    payload='<!DOCTYPE x [<!ENTITY e "expanded">]><x>&e;</x>', input_mime_type='application/xml')
        result = execute('%dw 2.0\ninput payload application/xml\noutput application/xml\n---\npayload',
                         payload='<root><entry id="A">value</entry></root>')
        self.assertIn('id="A"', result)
        self.assertIn('>value<', result)


if __name__ == '__main__':
    unittest.main()
