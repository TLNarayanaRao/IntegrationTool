import unittest

from app.mapper import apply_function, transform_value


class ExtendedFunctionsTests(unittest.TestCase):
    def test_comparisons(self):
        cases = [('equal', 3, 3, True), ('notEqual', 3, 4, True),
                 ('greaterThan', 4, 3, True), ('lessThan', 3, 4, True),
                 ('greaterOrEqual', 3, 3, True), ('lessOrEqual', 3, 3, True),
                 ('equal', 'a', 'b', False), ('lessThan', 'a', 'b', True)]
        for name, left, right, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(apply_function(name, left, [right]), expected)

    def test_math_and_pipeline(self):
        for name, expected in [('add', 10), ('subtract', 6), ('multiply', 16), ('divide', 4), ('mod', 0)]:
            with self.subTest(name=name):
                self.assertEqual(apply_function(name, 8, [2]), expected)
        self.assertEqual(apply_function('floor', -1.2), -2)
        self.assertEqual(transform_value(7, [{'name': 'add', 'args': [2]}, {'name': 'mod', 'args': [4]}]), 1)
        with self.assertRaises(ZeroDivisionError):
            apply_function('divide', 8, [0])

    def test_group_and_top(self):
        rows = [{'product': {'name': 'A'}, 'price': 3}, {'product': {'name': 'B'}}, {'product': {'name': 'A'}, 'price': 4}]
        self.assertEqual(apply_function('group', rows, ['product.name']), [[rows[0], rows[2]], [rows[1]]])
        self.assertEqual(apply_function('group', [1, 2, 1]), [[1, 1], [2]])
        self.assertEqual(apply_function('top', [1, 9, 3, 7], [2]), [9, 7])
        self.assertEqual(apply_function('top', [1, 9, 3]), [9])
        self.assertEqual(apply_function('top', [], [2]), [])
        self.assertEqual(apply_function('top', [1], [0]), [])
        with self.assertRaises(ValueError):
            apply_function('top', [1], [-1])
