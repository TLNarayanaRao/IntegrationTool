import copy
import unittest
from backend.app.runtime import WorkflowRuntime


class InputLoopTreeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = WorkflowRuntime()
        self.ctx = {'input': {'orders': [
            {'product': 'A', 'price': 10}, {'product': 'A', 'price': 20}, {'product': 'B', 'price': 30}
        ]}, 'last': {}, 'vars': {}, 'properties': {}, 'activities': {}}

    def test_for_each_maps_children_per_record_without_changing_process_data(self):
        original = copy.deepcopy(self.ctx)
        mappings = {
            'Orders.Order': {'$rule': 'for-each', 'source': '${input.orders}'},
            'Orders.Order.Name': '${input.orders.product}',
            'Orders.Order.Price': '${input.orders.price}',
        }
        self.assertEqual(self.runtime.map_input_values(mappings, self.ctx), {'Orders': {'Order': [
            {'Name': 'A', 'Price': 10}, {'Name': 'A', 'Price': 20}, {'Name': 'B', 'Price': 30}
        ]}})
        self.assertEqual(self.ctx, original)

    def test_grouping_emits_one_target_per_group_and_exposes_current_group(self):
        mappings = {
            'Orders.Order': {'$rule': 'for-each-group', 'source': '${input.orders}', 'groupBy': 'product'},
            'Orders.Order.Name': '${input.orders.product}',
            'Orders.Order.Members': '${vars.currentGroup}',
        }
        result = self.runtime.map_input_values(mappings, self.ctx)['Orders']['Order']
        self.assertEqual([row['Name'] for row in result], ['A', 'B'])
        self.assertEqual([len(row['Members']) for row in result], [2, 1])

    def test_nested_loops_and_direct_activity_paths(self):
        self.ctx['activities']['Read'] = {'output': {'orders': [{'items': [{'id': 1}, {'id': 2}]}]}}
        mappings = {
            'Orders.Order': {'$rule': 'for-each', 'source': '${Read.orders}'},
            'Orders.Order.Items': {'$rule': 'for-each', 'source': '${Read.orders.items}'},
            'Orders.Order.Items.Id': '${Read.orders.items.id}',
        }
        self.assertEqual(self.runtime.map_input_values(mappings, self.ctx), {'Orders': {'Order': [{'Items': [{'Id': 1}, {'Id': 2}]}]}})

    def test_empty_source_keeps_target_empty_and_omits_children(self):
        self.ctx['input']['orders'] = []
        self.assertEqual(self.runtime.map_input_values({
            'records': {'$rule': 'for-each', 'source': '${input.orders}'},
            'records.id': '${input.orders.product}',
        }, self.ctx), {'records': []})


if __name__ == '__main__':
    unittest.main()
