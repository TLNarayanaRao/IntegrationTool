"""Integration document functions: standards examples, bounds and real exports."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import random
import tempfile
import unittest

from app.mapper import apply_function, execute, validate_mapping_rules
from app.mapping_documents import json_pointer, json_patch, json_merge_patch, json_diff, join_records, deduplicate_records, redact_keys, mask_text
from app.models import Project


class MappingDocumentTests(unittest.TestCase):
    def test_pointer_escapes_fragments_indices_defaults_and_null(self):
        value = {'a/b': {'~key': [None, 2]}, '': 3, '~1': 4, 'café': 5}
        self.assertEqual(json_pointer(value, '/a~1b/~0key/1'), 2)
        self.assertIsNone(json_pointer(value, '/a~1b/~0key/0', 'fallback'))
        self.assertEqual(json_pointer(value, '/'), 3)
        self.assertEqual(json_pointer(value, '/~01'), 4)
        self.assertEqual(json_pointer(value, '#/caf%C3%A9'), 5)
        self.assertEqual(json_pointer(value, '/missing', 'fallback'), 'fallback')
        self.assertEqual(json_pointer([1], '/-', 'missing'), 'missing')
        for pointer in ('missing', '/~2key', '#/%xx', '#/%ff'):
            with self.subTest(pointer=pointer), self.assertRaises(ValueError): json_pointer(value, pointer)
        with self.assertRaises(ValueError): json_pointer([1], '/01', 'fallback')

    def test_all_patch_operations_are_atomic_and_copy_values(self):
        value = {'rows': [{'id': 1}, {'id': 2}], 'old': 'remove'}
        before = copy.deepcopy(value)
        result = json_patch(value, [
            {'op': 'test', 'path': '/rows/0/id', 'value': 1.0},
            {'op': 'add', 'path': '/rows/-', 'value': {'id': 3}},
            {'op': 'copy', 'from': '/rows/0', 'path': '/copied'},
            {'op': 'replace', 'path': '/copied/id', 'value': 10},
            {'op': 'move', 'from': '/rows/1', 'path': '/rows/0'},
            {'op': 'remove', 'path': '/old'},
            {'op': 'add', 'path': '/new', 'value': None}])
        self.assertEqual(result, {'rows': [{'id': 2}, {'id': 1}, {'id': 3}], 'copied': {'id': 10}, 'new': None})
        self.assertEqual(value, before)
        for failing in ([{'op': 'replace', 'path': '/old', 'value': 'changed'}, {'op': 'test', 'path': '/rows/0/id', 'value': True}],
                        [{'op': 'move', 'from': '/rows', 'path': '/rows/0/nested'}],
                        [{'op': 'remove', 'path': '/missing'}], [{'op': 'replace', 'path': '/old'}],
                        [{'op': 'add', 'path': '/rows/10', 'value': 2}]):
            with self.subTest(operations=failing), self.assertRaises(ValueError): json_patch(value, failing)
            self.assertEqual(value, before)

    def test_patch_root_arrays_aliases_and_move_identity(self):
        removed = [{'op': 'remove', 'path': ''}]
        for document in ({'id': 1}, [1], None, 'text', 3):
            self.assertIsNone(json_patch(document, removed))
        self.assertEqual(json_patch({}, removed + [{'op': 'add', 'path': '', 'value': {'new': 1}}]), {'new': 1})
        for operation in ({'op': 'remove', 'path': ''}, {'op': 'test', 'path': '', 'value': None},
                          {'op': 'replace', 'path': '', 'value': 1}, {'op': 'add', 'path': '/child', 'value': 1}):
            with self.assertRaises(ValueError): json_patch({}, removed + [operation])
        self.assertEqual(json_patch([1, 2], [{'op': 'add', 'path': '/1', 'value': 3}]), [1, 3, 2])
        self.assertEqual(json_patch({}, [{'op': 'replace', 'path': '', 'value': [1]}]), [1])
        self.assertEqual(json_patch({'id': 1}, [{'op': 'move', 'from': '/id', 'path': '/id'}]), {'id': 1})
        shared = {'id': 1}
        self.assertEqual(json_patch({'a': shared, 'b': shared}, [{'op': 'replace', 'path': '/a/id', 'value': 2}]), {'a': {'id': 2}, 'b': {'id': 1}})
        self.assertEqual(shared, {'id': 1})

    def test_merge_patch_removal_nested_objects_and_root_replacement(self):
        before = {'name': 'Ada', 'contact': {'old': 1, 'keep': 2}, 'rows': [1, 2]}
        self.assertEqual(json_merge_patch(before, {'contact': {'old': None, 'new': 3}, 'rows': [9]}),
                         {'name': 'Ada', 'contact': {'keep': 2, 'new': 3}, 'rows': [9]})
        self.assertIsNone(json_merge_patch(before, None))
        self.assertEqual(json_merge_patch([1], {'a': 2}), {'a': 2})
        self.assertEqual(before['contact']['old'], 1)

    def test_generated_patch_round_trips_varied_json_and_escaped_keys(self):
        generator = random.Random(17)
        for _ in range(100):
            before = {'a/b': generator.randrange(4), '~': [generator.randrange(4), None], 'flag': True}
            after = {'a/b': generator.randrange(4), '~': [generator.randrange(4)], 'flag': 1, 'new': {'': 'x'}}
            operations = json_diff(before, after)
            self.assertEqual(json_patch(before, operations), after)
            self.assertEqual(operations, json_diff(before, after))
        self.assertEqual(json_diff(1, 1.0), [])
        self.assertEqual(json_diff(True, 1), [{'op': 'replace', 'path': '', 'value': 1}])

    def test_indexed_join_modes_composite_keys_and_null_semantics(self):
        left = [{'id': 1, 'org': 'A'}, {'id': 1, 'org': 'B'}, {'id': None, 'org': 'A'}]
        right = [{'key': 1.0, 'org': 'A'}, {'key': 3, 'org': 'C'}]
        keys = ['/id', '/org']; other = ['/key', '/org']
        self.assertEqual(join_records(left, right, keys, other), [{'left': left[0], 'right': right[0]}])
        self.assertEqual(len(join_records(left, right, keys, other, 'left')), 3)
        self.assertEqual(len(join_records(left, right, keys, other, 'right')), 2)
        self.assertEqual(len(join_records(left, right, keys, other, 'full')), 4)
        self.assertEqual(join_records(left, right, keys, other, 'semi'), [left[0]])
        self.assertEqual(join_records(left, right, keys, other, 'anti'), left[1:])
        self.assertEqual(join_records([{'id': True}], [{'id': 1}], '/id', '/id'), [])
        self.assertEqual(len(join_records([{'id': 1}] * 2, [{'id': 1}] * 2, '/id', '/id')), 4)

    def test_deduplication_first_last_and_unkeyed_rows(self):
        rows = [{'id': 1, 'name': 'first'}, {'id': 2}, {'id': 1.0, 'name': 'last'}, {'id': None}, {}]
        self.assertEqual(deduplicate_records(rows, ['/id']), [rows[0], rows[1], rows[3], rows[4]])
        self.assertEqual(deduplicate_records(rows, ['/id'], 'last'), rows[1:])
        with self.assertRaises(ValueError): deduplicate_records(rows, [], 'first')

    def test_explicit_recursive_redaction_and_text_masks(self):
        value = {'Password': 'secret', 'rows': [{'token': 'sensitive', 'safe': 1}], 'safe': 'untouched'}
        self.assertEqual(redact_keys(value, ['password', 'TOKEN']), {'Password': '[REDACTED]', 'rows': [{'token': '[REDACTED]', 'safe': 1}], 'safe': 'untouched'})
        self.assertEqual(value['Password'], 'secret')
        self.assertEqual(mask_text('123456789', 4), '*****6789')
        self.assertEqual(mask_text('secret', 0), '******')
        self.assertEqual(mask_text('short', 20), 'short')
        self.assertIsNone(mask_text(None))

    def test_non_json_and_expanding_outputs_fail_with_bounds(self):
        cyclic = []; cyclic.append(cyclic)
        for value in ({1: 'bad key'}, float('nan'), cyclic):
            with self.assertRaises(ValueError): json_diff(value, {})
        large = 'x' * (2 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, '8 MiB'): redact_keys({f'secret{i}': 1 for i in range(8)}, [f'secret{i}' for i in range(8)], large)
        with self.assertRaisesRegex(ValueError, '8 MiB'):
            join_records([{'id': 1}] * 8, [{'id': 1, 'data': large}], '/id', '/id')

    def test_mapper_expressions_pipelines_validation_and_script_modules(self):
        rules = [{'target': 'id', 'source': 'jsonPointer(${input.document}, "/id")'},
                 {'target': 'safe', 'source': '${input.document}', 'functions': [{'name': 'redactKeys', 'args': [['password']]}]}]
        self.assertEqual(validate_mapping_rules(rules), [])
        normalized = [{**rule, 'source': rule['source'][2:-1] if rule['source'].startswith('${') and rule['source'].endswith('}') else rule['source']} for rule in rules]
        result = execute({'input': {'document': {'id': 3, 'password': 'secret'}}}, normalized)
        self.assertEqual(result, {'id': 3, 'safe': {'id': 3, 'password': '[REDACTED]'}})
        from app.script_transform import execute as transform
        self.assertEqual(transform('%mina 2.0\nimport jsonPointer from mina::Documents\noutput application/json\n---\njsonPointer(payload, "/id")', payload={'id': 3}), 3)

    def test_new_functions_in_preview_run_debug_and_both_archives(self):
        from app.main import mapper_test
        mappings = [{'target': 'patched', 'source': 'jsonPatch(${input.document}, ${input.patch})'},
                    {'target': 'delta', 'source': 'jsonDiff(${input.document}, ${input.after})'},
                    {'target': 'merged', 'source': 'jsonMergePatch(${input.document}, ${input.merge})'},
                    {'target': 'safe', 'source': 'redactKeys(${input.document}, ["password"])'},
                    {'target': 'masked', 'source': 'maskText(${input.text}, 4)'},
                    {'target': 'joined', 'source': 'joinRecords(${input.left}, ${input.right}, ["/id"], ["/key"], "left")'},
                    {'target': 'deduped', 'source': 'deduplicateRecords(${input.left}, ["/id"], "last")'},
                    {'target': 'selected', 'source': 'jsonPointer(${input.document}, "/id")'}]
        payload = {'document': {'id': 3, 'password': 'secret'}, 'patch': [{'op': 'replace', 'path': '/id', 'value': 4}],
                   'after': {'id': 4, 'password': 'secret'}, 'merge': {'password': None}, 'text': '12345678',
                   'left': [{'id': 1}, {'id': 2}], 'right': [{'key': 1}]}
        expected = {'patched': {'id': 4, 'password': 'secret'}, 'delta': [{'op': 'replace', 'path': '/id', 'value': 4}],
                    'merged': {'id': 3}, 'safe': {'id': 3, 'password': '[REDACTED]'}, 'masked': '****5678',
                    'joined': [{'left': {'id': 1}, 'right': {'key': 1}}, {'left': {'id': 2}, 'right': None}],
                    'deduped': [{'id': 1}, {'id': 2}], 'selected': 3}
        self.assertEqual(mapper_test({'input': payload, 'mappings': mappings})['output'], expected)
        nodes = [{'id': 's', 'type': 'start', 'name': 'Start'}, {'id': 'm', 'type': 'mapper', 'name': 'Mapper', 'config': {'mappings': mappings}}, {'id': 'e', 'type': 'end', 'name': 'End'}]
        project = Project.model_validate({'id': 'standards', 'name': 'Standards', 'tasks': [{'id': 'main', 'name': 'Main', 'kind': 'subtask', 'activities': nodes,
            'transitions': [{'id': str(index), 'source': a['id'], 'target': b['id']} for index, (a, b) in enumerate(zip(nodes, nodes[1:]))]}]})
        value = project.model_dump()
        value['tasks'].append({'id': 'generic', 'name': 'Generic-input', 'kind': 'subtask', 'activities': [
            {'id': 'gs', 'type': 'start', 'name': 'Start'},
            {'id': 'ge', 'type': 'end', 'name': 'End', 'config': {'inputMappings': {rule['target']: rule['source'] for rule in mappings}}}],
            'transitions': [{'id': 'gt', 'source': 'gs', 'target': 'ge'}]})
        value['tasks'].append({'id': 'failed', 'name': 'Failed-end-input', 'kind': 'subtask', 'activities': [
            {'id': 'fs', 'type': 'start', 'name': 'Start'},
            {'id': 'fe', 'type': 'end', 'name': 'End', 'config': {'inputMappings': {'result': 'jsonPatch(${input.document}, [{"op":"test","path":"/id","value":99}])'}}}],
            'transitions': [{'id': 'ft', 'source': 'fs', 'target': 'fe'}]})
        value['tasks'].append({'id': 'failed-response', 'name': 'Failed-response', 'kind': 'subtask', 'activities': [
            {'id': 'hs', 'type': 'start', 'name': 'Start'},
            {'id': 'he', 'type': 'http_response', 'name': 'Response', 'config': {'statusCode': 'invalid-status'}}],
            'transitions': [{'id': 'ht', 'source': 'hs', 'target': 'he'}]})
        project = Project.model_validate(value)
        spec = importlib.util.spec_from_file_location('document_flows', Path(__file__).parents[2] / 'scripts/flow-throughput.py')
        flow = importlib.util.module_from_spec(spec); spec.loader.exec_module(flow)
        async def run(folder):
            for mode in ('run', 'debug', 'python-direct', 'python-engine'):
                executor = flow.Executor(mode, project, str(Path(folder) / (mode + '.log')))
                try:
                    await executor.start()
                    self.assertEqual(await executor.execute('main', payload), expected, mode)
                    self.assertEqual(await executor.execute('generic', payload), expected, ('generic-input', mode))
                    with self.assertRaises(RuntimeError): await executor.execute('failed', payload)
                    with self.assertRaises(RuntimeError): await executor.execute('failed-response', payload)
                finally: await executor.close()
        with tempfile.TemporaryDirectory() as folder: asyncio.run(run(folder))


if __name__ == '__main__': unittest.main()
