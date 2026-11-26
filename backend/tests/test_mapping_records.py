"""Record rollups and snapshot reconciliation across execution boundaries."""
import asyncio
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from app.mapping_documents import aggregate_records, pivot_records, reconcile_records, unpivot_records
from app.mapper import execute, validate_mapping_rules
from app.models import Project


def fixture():
    payload = {'before': [{'id': 1, 'value': 'old'}, {'id': 2, 'value': 'same'}, {'id': 4}],
               'after': [{'id': 3}, {'id': 2, 'value': 'same'}, {'id': 1, 'value': 'new'}],
               'records': [{'region': 'US', 'amount': 0.1}, {'region': 'US', 'amount': 0.2},
                           {'region': 'EU', 'amount': 10}, {'region': 'US', 'amount': None}, {'region': 'EU'}]}
    metrics = [{'name': 'total', 'op': 'sum', 'path': '/amount'}, {'name': 'mean', 'op': 'average', 'path': '/amount'},
               {'name': 'min', 'op': 'min', 'path': '/amount'}, {'name': 'max', 'op': 'max', 'path': '/amount'},
               {'name': 'present', 'op': 'count', 'path': '/amount'}, {'name': 'rows', 'op': 'count'}]
    expected = {'changes': {'inserted': [{'id': 3}],
                            'updated': [{'key': [1], 'before': {'id': 1, 'value': 'old'}, 'after': {'id': 1, 'value': 'new'}}],
                            'deleted': [{'id': 4}], 'unchanged': [{'id': 2, 'value': 'same'}]},
                'totals': [{'key': ['US'], 'count': 3, 'values': {'total': 0.3, 'mean': 0.15, 'min': 0.1, 'max': 0.2, 'present': 2, 'rows': 3}},
                           {'key': ['EU'], 'count': 2, 'values': {'total': 10, 'mean': 10, 'min': 10, 'max': 10, 'present': 1, 'rows': 2}}]}
    mappings = [{'target': 'changes', 'source': 'reconcileRecords(${input.before}, ${input.after}, ["/id"])'},
                {'target': 'totals', 'source': '${input.records}', 'functions': [{'name': 'aggregateRecords', 'args': [['/region'], metrics]}]}]
    return payload, metrics, mappings, expected


def reshape_fixture():
    narrow = [{'id': 1, 'region': 'EU', 'metric': 'tax', 'amount': None},
              {'id': True, 'region': 'EU', 'metric': 'tax', 'amount': 2},
              {'id': 1.0, 'region': 'EU', 'metric': 'net', 'amount': {'currency': 'EUR', 'value': 5}}]
    wide = [{'key': [1, 'EU'], 'values': {'tax': None, 'net': {'currency': 'EUR', 'value': 5}}},
            {'key': [True, 'EU'], 'values': {'tax': 2}}]
    rows = [{'key': [1, 'EU'], 'column': 'net', 'value': {'currency': 'EUR', 'value': 5}},
            {'key': [1, 'EU'], 'column': 'tax', 'value': None},
            {'key': [True, 'EU'], 'column': 'tax', 'value': 2}]
    mappings = [{'target': 'wide', 'source': 'pivotRecords(${input.narrow}, ["/id","/region"], "/metric", "/amount")'},
                {'target': 'narrow', 'source': '${input.wide}', 'functions': [
                    {'name': 'unpivotRecords', 'args': [['/key/0', '/key/1'], '/values', ['net', 'tax', 'missing']]},
                ]}]
    return {'narrow': narrow, 'wide': wide}, mappings, {'wide': wide, 'narrow': rows}


class MappingRecordsTests(unittest.TestCase):
    def test_pivot_and_unpivot_order_null_types_and_no_mutation(self):
        payload, mappings, expected = reshape_fixture()
        self.assertEqual(validate_mapping_rules(mappings), [])
        output = execute({'input': payload}, mappings)
        self.assertEqual(output, expected)
        output['wide'][0]['values']['net']['value'] = 99
        self.assertEqual(payload['narrow'][-1]['amount']['value'], 5)
        self.assertEqual(pivot_records(expected['narrow'], ['/key/0', '/key/1'], '/column', '/value'), expected['wide'])

    def test_invalid_reshape_declarations_and_expansion_raise(self):
        row = {'id': 1, 'metric': 'net', 'amount': 3}
        for records in ([row, row], [{**row, 'metric': False}], [{**row, 'id': None}], [{'id': 1, 'metric': 'net'}]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                pivot_records(records, '/id', '/metric', '/amount')
        for names in ([], ['net', 'net'], [''], [None], ['x' * 129]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                unpivot_records([], '/id', '/values', names)
        with self.assertRaisesRegex(ValueError, 'must select an object'):
            unpivot_records([{'id': 1, 'values': []}], '/id', '/values', ['net'])
        wide = [{'id': 'x' * 80000, 'values': {str(i): i for i in range(128)}}]
        with self.assertRaisesRegex(ValueError, '8 MiB'):
            unpivot_records(wide, '/id', '/values', [str(i) for i in range(128)])

    def test_rollups_and_changes_are_stable_without_mutation(self):
        payload, metrics, mappings, expected = fixture(); before = copy.deepcopy(payload)
        self.assertEqual(aggregate_records(payload['records'], ['/region'], metrics), expected['totals'])
        self.assertEqual(reconcile_records(payload['before'], payload['after'], ['/id']), expected['changes'])
        self.assertEqual(validate_mapping_rules(mappings), [])
        self.assertEqual(execute({'input': payload}, mappings), expected)
        self.assertEqual(payload, before)

    def test_typed_composite_keys_and_json_equality(self):
        before = [{'id': 1, 'org': 'A', 'value': True}, {'id': True, 'org': 'A'}, {'id': '1', 'org': 'A'}]
        after = [{'id': '1', 'org': 'A'}, {'id': True, 'org': 'A'}, {'id': 1.0, 'org': 'A', 'value': 1}]
        result = reconcile_records(before, after, ['/id', '/org'])
        self.assertEqual(result['inserted'], []); self.assertEqual(result['deleted'], [])
        self.assertEqual(len(result['updated']), 1); self.assertEqual(result['updated'][0]['key'], [1.0, 'A'])
        self.assertEqual(result['unchanged'], after[:2])
        self.assertEqual(len(aggregate_records(after, ['/id', '/org'], [{'name': 'rows', 'op': 'count'}])), 3)

    def test_large_json_numbers_compare_and_aggregate_consistently(self):
        before = [{'id': 1, 'value': 1e30}]; after = [{'id': 1, 'value': 10**30}]
        self.assertEqual(reconcile_records(before, after, '/id'), {'inserted': [], 'updated': [], 'deleted': [], 'unchanged': after})
        from app.mapping_documents import json_diff
        self.assertEqual(json_diff(before, after), [])
        for op in ('min', 'max', 'sum', 'average'):
            result = aggregate_records([{'id': 'A', 'v': 1e30}], '/id', [{'name': 'v', 'op': op, 'path': '/v'}])
            self.assertEqual(result[0]['values']['v'], 10**30)

    def test_empty_null_metrics_escaped_keys_and_output_isolation(self):
        self.assertEqual(reconcile_records([], [], '/id'), {'inserted': [], 'updated': [], 'deleted': [], 'unchanged': []})
        self.assertEqual(aggregate_records([], '/id', [{'name': 'n', 'op': 'count'}]), [])
        row = {'a/b': 'A', 'amount': None}
        metrics = [{'name': op, 'op': op, 'path': '/amount'} for op in ('sum', 'average', 'min', 'max', 'count')]
        result = aggregate_records([row], '/a~1b', metrics)
        self.assertEqual(result, [{'key': ['A'], 'count': 1, 'values': {'sum': 0, 'average': None, 'min': None, 'max': None, 'count': 0}}])
        source = [{'id': 1, 'nested': [1]}]; changed = reconcile_records([], source, '/id')
        changed['inserted'][0]['nested'].append(2); self.assertEqual(source[0]['nested'], [1])

    def test_invalid_keys_and_ambiguous_snapshots_fail_atomically(self):
        for rows in ([{}], [{'id': None}], [{'id': []}], [None], 'bad'):
            with self.subTest(rows=rows), self.assertRaises(ValueError): reconcile_records([], rows, '/id')
            with self.subTest(aggregate=rows), self.assertRaises(ValueError): aggregate_records(rows, '/id', [{'name': 'n', 'op': 'count'}])
        for left, right in [([{'id': 1}, {'id': 1.0}], []), ([], [{'id': 1}, {'id': 1}])]:
            original = copy.deepcopy((left, right))
            with self.assertRaisesRegex(ValueError, 'Duplicate'): reconcile_records(left, right, '/id')
            self.assertEqual((left, right), original)

    def test_metric_configuration_and_numeric_types_are_strict(self):
        invalid = [[], [{'name': 'n', 'op': 'unknown'}], [{'name': 'n', 'op': 'sum'}],
                   [{'name': 'n', 'op': 'sum', 'path': 'bad'}], [{'name': '', 'op': 'count'}],
                   [{'name': 'n', 'op': 'count', 'typo': True}], [{'name': 'n', 'op': 'count'}] * 2]
        for metrics in invalid:
            # Invalid specifications also fail for an empty input collection.
            with self.subTest(metrics=metrics), self.assertRaises(ValueError): aggregate_records([], '/id', metrics)
        for value in ('1', True, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                aggregate_records([{'id': 1, 'amount': value}], '/id', [{'name': 'n', 'op': 'sum', 'path': '/amount'}])
        for value in (float('nan'), float('inf')):
            with self.assertRaises(ValueError): aggregate_records([{'id': 1, 'amount': value}], '/id', [{'name': 'n', 'op': 'sum', 'path': '/amount'}])
        with self.assertRaises(ValueError): reconcile_records([{'id': 1}] * 100001, [], '/id')

    def test_expanding_reconciliation_is_rejected_before_returning(self):
        large = 'x' * (2 * 1024 * 1024)
        before = [{'a': large, 'b': large, 'v': 1}]
        after = [{'a': large, 'b': large, 'v': 2}]
        with self.assertRaisesRegex(ValueError, '8 MiB'): reconcile_records(before, after, ['/a', '/b'])
        self.assertEqual(before[0]['v'], 1); self.assertEqual(after[0]['v'], 2)

    def test_preview_run_debug_and_both_archives(self):
        from app.main import mapper_test
        from app.script_transform import execute as transform
        payload, metrics, mappings, expected = fixture()
        reshape_input, reshape_mappings, reshape_expected = reshape_fixture()
        self.assertEqual(mapper_test({'input': payload, 'mappings': mappings})['output'], expected)
        self.assertEqual(mapper_test({'input': reshape_input, 'mappings': reshape_mappings})['output'], reshape_expected)
        self.assertEqual(transform('%mina 2.0\nimport pivotRecords from mina::Records\noutput application/json\n---\npivotRecords(payload.narrow, ["/id","/region"], "/metric", "/amount")',
                                   payload=reshape_input), reshape_expected['wide'])
        self.assertEqual(transform('%mina 2.0\nimport reconcileRecords from mina::Records\noutput application/json\n---\nreconcileRecords(payload.before, payload.after, ["/id"])', payload=payload), expected['changes'])
        script = ('%mina 2.0\nimport aggregateRecords, reconcileRecords from mina::Records\noutput application/json\n---\n'
                  '{changes: reconcileRecords(payload.before, payload.after, ["/id"]), '
                  'totals: aggregateRecords(payload.records, ["/region"], payload.metrics)}')
        self.assertEqual(transform(script, payload={**payload, 'metrics': metrics}), expected)
        tasks = []
        for name, activity in [('mapper', {'id': 'm', 'name': 'Mapper', 'type': 'mapper', 'config': {'mappings': mappings}}),
                               ('reshape', {'id': 'm', 'name': 'Reshape', 'type': 'mapper', 'config': {'mappings': reshape_mappings}}),
                               ('script', {'id': 'm', 'name': 'Transform', 'type': 'script_transform', 'config': {'payload': '${input}', 'script': script}}),
                               ('generic', {'id': 'm', 'name': 'End', 'type': 'end', 'config': {'inputMappings': {
                                   'changes': mappings[0]['source'],
                                   'totals': 'aggregateRecords(${input.records}, ["/region"], ${input.metrics})'}}})]:
            nodes = [{'id': 's', 'name': 'Start', 'type': 'start'}, activity]
            if name != 'generic': nodes.append({'id': 'e', 'name': 'End', 'type': 'end'})
            tasks.append({'id': name, 'name': name, 'kind': 'subtask', 'activities': nodes,
                          'transitions': [{'id': str(i), 'source': a['id'], 'target': b['id']} for i, (a,b) in enumerate(zip(nodes,nodes[1:]))]})
        project = Project.model_validate({'id': 'record-qa', 'name': 'Record-QA', 'tasks': tasks})
        spec = importlib.util.spec_from_file_location('record_flows', Path(__file__).parents[2] / 'scripts/flow-throughput.py')
        flow = importlib.util.module_from_spec(spec); spec.loader.exec_module(flow)
        async def run(folder):
            for mode in ('run', 'debug', 'python-direct', 'python-engine'):
                executor = flow.Executor(mode, project, str(Path(folder) / (mode + '.log')))
                try:
                    await executor.start()
                    for task in ('mapper', 'generic', 'script'):
                        self.assertEqual(await executor.execute(task, {**payload, 'metrics': metrics}), expected, (mode, task))
                    self.assertEqual(await executor.execute('reshape', reshape_input), reshape_expected, mode)
                    print('Record functions:', mode, 'Mapper, generic End input and imported script passed', flush=True)
                finally: await executor.close()
        with tempfile.TemporaryDirectory() as folder: asyncio.run(run(folder))


if __name__ == '__main__': unittest.main()
