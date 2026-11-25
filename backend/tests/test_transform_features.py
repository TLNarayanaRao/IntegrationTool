"""Shared module, output, streaming and contract behavior across execution modes."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from app.script_transform import ScriptTransformError, execute
from app.models import Project, Activity
from app.runtime import WorkflowRuntime
from app.transform_engine import execute_plan, execute_activity, validate_contract, TransformContractError
from app.transform_stream import execute_file
from app.transform_visual import script_to_visual, visual_to_script


def script(body, header=''):
    return '%mina 2.0\noutput application/json\n' + header + '\n---\n' + body


def flow_module():
    spec = importlib.util.spec_from_file_location('feature_flows', Path(__file__).parents[2] / 'scripts/flow-throughput.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


LIBRARIES = {'company::Names': 'fun normalize(value) = upper(trim(value))',
             'company::Greeting': 'import normalize from company::Names\nvar prefix = "Hello "\nfun greet(value) = prefix ++ normalize(value)'}


class TransformFeatureTests(unittest.TestCase):
    def test_saved_transformer_ids_and_script_imports_still_work(self):
        from app.main import app
        from fastapi.testclient import TestClient

        kind = 'data' + 'weave'
        source = '%dw 2.0\nimport capitalize from dw::core::Strings\noutput application/json\n---\ncapitalize(payload)'
        activity = Activity(id='t', type=kind, name='Transform', config={'script': source})
        self.assertEqual(activity.type, 'script_transform')
        self.assertEqual(activity.config['script'], source)
        caught = Activity(id='c', type='catch', name='Catch', config={'errorType': kind.upper() + '_SYNTAX'})
        self.assertEqual(caught.config['errorType'], 'SCRIPT_TRANSFORM_SYNTAX')
        with TestClient(app) as client:
            for path in ('/api/transform-script/test', '/api/' + kind + '/test'):
                response = client.post(path, json={'script': source, 'input': 'mina'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['output'], 'Mina')
            paths = client.get('/openapi.json').json()['paths']
            self.assertIn('/api/transform-script/test', paths)
            self.assertNotIn('/api/' + kind + '/test', paths)

    def test_modules_named_wildcard_qualified_alias_and_lexical_scope(self):
        self.assertEqual(execute(script('Names::normalize(payload)', 'import company::Names'), payload=' ada ', libraries=LIBRARIES), 'ADA')
        self.assertEqual(execute(script('greet(payload)', 'import * from company::Greeting'), payload=' ada ', libraries=LIBRARIES), 'Hello ADA')
        self.assertEqual(execute(script('S::padLeft(payload, 4, "0")', 'import mina::core::Strings as S'), payload='7'), '0007')
        self.assertEqual(execute(script('camelize(payload)', 'import camelize from mina::core::Strings'), payload='customer_name'), 'customerName')
        self.assertEqual(execute(script('normalize(payload)', 'import normalize from company::Names'), payload=' grace ', libraries=LIBRARIES), 'GRACE')
        self.assertEqual(execute(script('C::upper(payload)', 'import mina::Core as C'), payload='ada'), 'ADA')
        self.assertEqual(execute(script('fromHex("ff")', 'import fromHex from mina::core::Numbers')), 255)
        self.assertIsNone(execute(script('logn(-2)', 'import logn from mina::util::Math')))
        with self.assertRaisesRegex(ScriptTransformError, 'Cyclic'):
            execute(script('x()', 'import * from A'), libraries={'A': 'import * from B\nfun x() = 1', 'B': 'import * from A'})
        with self.assertRaisesRegex(ScriptTransformError, 'Unknown script library'):
            execute(script('payload', 'import java::lang::Runtime'))
        self.assertEqual(execute(script('normalized(payload)', 'import normalized from Example'), payload=' ada ',
                         libraries={'Example': 'module Example\nfun normalized(value) = {\n name: upper(\ntrim(value)\n)\n}'}), {'name': 'ADA'})

    def test_selected_contract_reload_project_refs_and_xsd_includes(self):
        assets = [{'id': 'root', 'name': 'schemas/root.json', 'content': json.dumps({'$ref': 'types.json'})},
                  {'id': 'types', 'name': 'schemas/types.json', 'content': json.dumps({'type': 'object', 'required': ['id']})}]
        cfg = {'script': script('payload'), 'sourceSchemaId': 'root', 'sourceSchemaText': '{"type":"string"}'}
        self.assertEqual(execute_plan(cfg, {'id': 2}, schemas=assets)['output'], {'id': 2})
        with self.assertRaises(TransformContractError): execute_plan(cfg, {}, schemas=assets)
        xsd = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include schemaLocation="types.xsd"/><xs:element name="root" type="Record"/></xs:schema>'
        types = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:complexType name="Record"><xs:sequence><xs:element name="id" type="xs:int"/></xs:sequence></xs:complexType></xs:schema>'
        cfg = {'script': '%mina 2.0\noutput application/xml\n---\npayload', 'inputMimeType': 'application/xml', 'sourceSchemaId': 'xsd', 'targetSchemaId': 'xsd'}
        assets = [{'id': 'xsd', 'name': 'schemas/root.xsd', 'content': xsd}, {'id': 'types', 'name': 'schemas/types.xsd', 'content': types}]
        self.assertIn('<id>2</id>', execute_plan(cfg, '<root><id>2</id></root>', schemas=assets)['output'])
        with self.assertRaises(TransformContractError): execute_plan(cfg, '<root><id>wrong</id></root>', schemas=assets)

    def test_output_plan_uses_original_snapshot_and_validates_before_commit(self):
        config = {'outputs': [
            {'target': 'payload', 'script': script('{id: payload.id + 1}')},
            {'target': 'attributes', 'script': script('{original: payload.id}')},
            {'target': 'variable', 'name': 'original', 'script': script('payload.id')}]}
        plan = execute_plan(config, {'id': 7}, {}, {})
        self.assertEqual(plan['output'], {'id': 8})
        self.assertEqual(plan['attributes'], {'original': 7})
        self.assertEqual(plan['variables'], {'original': 7})
        config['outputs'][-1]['targetSchema'] = {'type': 'string'}
        ctx = {'last': {'id': 7}, 'input': {}, 'vars': {'keep': 'unchanged'}, 'attributes': {'keep': 'unchanged'},
               'properties': {}, 'resources': {}}
        prior = copy.deepcopy(ctx)
        with self.assertRaises(Exception):
            asyncio.run(WorkflowRuntime().execute(Activity(id='t', name='T', type='script_transform', config=config), ctx))
        self.assertEqual(ctx['vars'], prior['vars'])
        self.assertEqual(ctx['attributes'], prior['attributes'])

    def test_json_and_xsd_contracts_fail_closed(self):
        cfg = {'script': script('payload'), 'sourceSchema': {'type': 'object', 'required': ['id']},
               'targetSchema': {'type': 'object', 'properties': {'id': {'type': 'integer'}}}}
        self.assertEqual(execute_plan(cfg, {'id': 2})['output'], {'id': 2})
        for value in ({}, {'id': 'wrong'}):
            with self.assertRaises(TransformContractError): execute_plan(cfg, value)
        xsd = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="root"><xs:complexType><xs:sequence><xs:element name="id" type="xs:int"/></xs:sequence></xs:complexType></xs:element></xs:schema>'
        validate_contract('<root><id>2</id></root>', {'sourceSchema': xsd}, 'source')
        with self.assertRaises(TransformContractError): validate_contract('<root><id>no</id></root>', {'sourceSchema': xsd}, 'source')
        with self.assertRaises(TransformContractError): validate_contract({}, {'targetSchema': {'$ref': 'https://example.invalid/remote.json'}}, 'target')
        with self.assertRaises(TransformContractError): validate_contract({}, {'targetSchema': False}, 'target')

    def test_preview_and_visual_api_enforce_the_same_configuration(self):
        from fastapi import HTTPException
        from app.main import script_transform_test, script_transform_visual
        config = {'libraries': LIBRARIES, 'script': script('{name: normalize(payload.name)}', 'import normalize from company::Names'),
                  'sourceSchema': {'type': 'object', 'required': ['name']}, 'targetSchema': {'type': 'object', 'required': ['name']}}
        self.assertEqual(script_transform_test({'config': config, 'input': {'name': ' ada '}})['output'], {'name': 'ADA'})
        with self.assertRaises(HTTPException): script_transform_test({'config': config, 'input': {}})
        view = script_transform_visual({'script': script('{name: payload.name, empty: {}}')})
        rebuilt = script_transform_visual(view)['script']
        self.assertEqual(execute(rebuilt, payload={'name': 'Ada'}), {'name': 'Ada', 'empty': {}})
        with self.assertRaises(HTTPException): script_transform_visual({'mappings': [{'target': 'a', 'expression': '1 /'}]})

    def test_visual_round_trip_preserves_headers_empty_objects_and_complex_expressions(self):
        for body in ('{name: upper(payload.name), empty: {}, nested: {id: payload.id}}',
                     'payload.items map (item) -> {id: item.id}', '{"literal.key": payload.name}'):
            original = script(body)
            visual = script_to_visual(original)
            rebuilt = visual_to_script(visual['header'], visual['mappings'])
            data = {'name': 'Ada', 'id': 2, 'items': [{'id': 4}]}
            self.assertEqual(execute(original, payload=data), execute(rebuilt, payload=data))
        with self.assertRaisesRegex(ScriptTransformError, 'Duplicate'):
            visual_to_script('', [{'target': 'a', 'expression': '1'}, {'target': 'a', 'expression': '2'}])

    def test_stream_is_atomic_bounded_and_does_not_read_ahead(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.jsonl'; target = Path(directory) / 'output.json'
            source.write_text('{"id":1}\n{"id":2}\n'); target.write_text('previous')
            cfg = {'streamInputFile': str(source), 'streamOutputFile': str(target), 'streamOutputFormat': 'json'}
            def fail(record):
                if record['id'] == 2: raise ValueError('second record fails')
                return record
            with self.assertRaises(ValueError): execute_file(cfg, fail)
            self.assertEqual(target.read_text(), 'previous')
            self.assertFalse(list(Path(directory).glob('.mina-transform-*')))
            report = execute_file(cfg, lambda item: {'id': item['id'] + 1})
            self.assertEqual(report['recordsWritten'], 2)
            self.assertEqual(json.loads(target.read_text()), [{'id': 2}, {'id': 3}])
            with self.assertRaisesRegex(ValueError, 'cancelled'): execute_file(cfg, lambda item: item, lambda: True)
            self.assertEqual(json.loads(target.read_text()), [{'id': 2}, {'id': 3}])
            source.write_text('"' + 'x' * 300 + '"\n')
            with self.assertRaisesRegex(ValueError, 'record limit'): execute_file({**cfg, 'streamMaxRecordBytes': 256}, lambda item: item)

    def test_streamed_json_array_edges_and_multi_output_envelopes(self):
        from app.transform_stream import json_array_records
        import io
        class SmallReads(io.StringIO):
            def read(self, size=-1):
                self.assert_bounded = size > 0
                if size < 0: raise AssertionError('Unbounded read')
                return super().read(min(size, 2))
        self.assertEqual(list(json_array_records(SmallReads('[1e3, {"a": "hello"}, null]'), 256)), [1000, {'a': 'hello'}, None])
        for text in ('[1,]', '[1', '[NaN]', '[1] garbage'):
            with self.subTest(text=text), self.assertRaises(ValueError): list(json_array_records(io.StringIO(text), 256))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'in.json'; target = Path(directory) / 'out.jsonl'
            source.write_text('[{"id":1},{"id":2}]')
            cfg = {'streamEnabled': True, 'streamInputFile': str(source), 'streamInputFormat': 'json', 'streamOutputFile': str(target),
                   'outputs': [{'target': 'payload', 'script': script('{id: payload.id + 1}')}, {'target': 'variable', 'name': 'before', 'script': script('payload.id')}]}
            self.assertEqual(execute_activity(cfg, {})['output']['recordsWritten'], 2)
            self.assertEqual([json.loads(line) for line in target.read_text().splitlines()], [
                {'payload': {'id': 2}, 'attributes': {}, 'variables': {'before': 1}},
                {'payload': {'id': 3}, 'attributes': {}, 'variables': {'before': 2}}])

    def test_streamed_mapper_keeps_properties_and_conditions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.jsonl'; target = Path(directory) / 'out.jsonl'
            source.write_text('{"id":2,"include":true}\n')
            cfg = {'streamEnabled': True, 'streamInputFile': str(source), 'streamOutputFile': str(target), 'mappings': [
                {'target': 'label', 'source': '${properties.label}'},
                {'target': 'id', 'operator': 'if', 'condition': '${input.include} = true', 'source': '${input.id}'}]}
            execute_activity(cfg, {}, kind='mapper', mapping_context={'properties': {'label': 'kept'}})
            self.assertEqual(json.loads(target.read_text()), {'label': 'kept', 'id': 2})

    def test_async_stream_stop_drains_worker_and_preserves_destination(self):
        import threading
        import time
        from unittest.mock import patch
        from app.transform_engine import execute_activity_async
        async def run(directory):
            source = Path(directory) / 'input.jsonl'; target = Path(directory) / 'out.jsonl'
            source.write_text('{"id":1}\n' * 100); target.write_text('previous')
            started = threading.Event()
            actual = execute_plan
            def slow(*args, **kwargs):
                started.set(); time.sleep(.02)
                return actual(*args, **kwargs)
            cfg = {'streamEnabled': True, 'streamInputFile': str(source), 'streamOutputFile': str(target), 'script': script('payload')}
            with patch('app.transform_engine.execute_plan', side_effect=slow):
                task = asyncio.create_task(execute_activity_async(cfg, {}))
                self.assertTrue(await asyncio.to_thread(started.wait, 3))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            self.assertEqual(target.read_text(), 'previous')
            self.assertFalse(list(Path(directory).glob('.mina-transform-*')))
        with tempfile.TemporaryDirectory() as directory: asyncio.run(run(directory))

    def test_features_run_debug_and_both_archives(self):
        flow = flow_module()
        config = {'libraries': LIBRARIES, 'sourceSchemaId': 'input-contract', 'outputs': [
            {'target': 'payload', 'targetSchemaId': 'output-contract', 'script': script('{name: normalize(payload.name)}', 'import normalize from company::Names')},
            {'target': 'attributes', 'script': script('{original: payload.name}')},
            {'target': 'variable', 'name': 'saved', 'script': script('payload.name')}]}
        nodes = [{'id': 's', 'name': 'Start', 'type': 'start'}, {'id': 't', 'name': 'Transform', 'type': 'data' + 'weave', 'config': config},
                 {'id': 'e', 'name': 'End', 'type': 'end', 'config': {'inputMappings': {'payload': '${last}', 'saved': '${vars.saved}', 'attributes': '${attributes}'}}}]
        project = Project.model_validate({'id': 'features', 'name': 'Features', 'schemas': [
            {'id': 'input-contract', 'name': 'input.json', 'content': json.dumps({'type': 'object', 'required': ['name']})},
            {'id': 'output-contract', 'name': 'output.json', 'content': json.dumps({'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']})}],
            'tasks': [{'id': 'main', 'name': 'Main', 'kind': 'subtask', 'activities': nodes,
                       'transitions': [{'id': str(i), 'source': a['id'], 'target': b['id']} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}]})
        value = project.model_dump()
        value['schemas'].extend([
            {'id': 'xsd', 'name': 'schema/root.xsd', 'content': '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include schemaLocation="types.xsd"/><xs:element name="root" type="Record"/></xs:schema>'},
            {'id': 'types', 'name': 'schema/types.xsd', 'content': '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:complexType name="Record"><xs:sequence><xs:element name="id" type="xs:int"/></xs:sequence></xs:complexType></xs:schema>'}])
        xml_nodes = [{'id': 'xs', 'name': 'Start', 'type': 'start'},
                     {'id': 'xt', 'name': 'Transform', 'type': 'script_transform', 'config': {'script': '%mina 2.0\noutput application/xml\n---\npayload', 'inputMimeType': 'application/xml', 'sourceSchemaId': 'xsd', 'targetSchemaId': 'xsd'}},
                     {'id': 'xe', 'name': 'End', 'type': 'end'}]
        value['tasks'].append({'id': 'xml', 'name': 'XML', 'kind': 'subtask', 'activities': xml_nodes, 'transitions': [
            {'id': str(i), 'source': a['id'], 'target': b['id']} for i, (a, b) in enumerate(zip(xml_nodes, xml_nodes[1:]))]})
        project = Project.model_validate(value)
        async def run(directory):
            for mode in ('run', 'debug', 'python-direct', 'python-engine'):
                executor = flow.Executor(mode, project, str(Path(directory) / (mode + '.log')))
                try:
                    await executor.start()
                    output = await executor.execute('main', {'name': ' ada '})
                    self.assertEqual(output, {'payload': {'name': 'ADA'}, 'saved': ' ada ', 'attributes': {'original': ' ada '}}, mode)
                    xml_output = await executor.execute('xml', '<root><id>2</id></root>')
                    self.assertIn('<id>2</id>', xml_output.get('result') if isinstance(xml_output, dict) else xml_output, mode)
                    with self.assertRaises(RuntimeError): await executor.execute('xml', '<root><id>wrong</id></root>')
                finally: await executor.close()
        with tempfile.TemporaryDirectory() as directory: asyncio.run(run(directory))

    def test_streaming_mapper_and_transformer_in_all_modes(self):
        flow = flow_module()
        async def run(directory):
            source = Path(directory) / 'input.csv'; source.write_text('id,name\n1,Ada\n2,Grace\n')
            for kind in ('mapper', 'script_transform'):
                for mode in ('run', 'debug', 'python-direct', 'python-engine'):
                    target = Path(directory) / (kind + '-' + mode + '.jsonl')
                    config = {'streamEnabled': True, 'streamInputFile': str(source), 'streamOutputFile': str(target), 'streamInputFormat': 'csv',
                              'script': script('{name: upper(payload.name)}'), 'mappings': [{'target': 'name', 'source': '${input.name}', 'functions': ['upperCase']}]}
                    nodes = [{'id': 's', 'name': 'Start', 'type': 'start'}, {'id': 't', 'name': 'Transform', 'type': kind, 'config': config}, {'id': 'e', 'name': 'End', 'type': 'end'}]
                    project = Project.model_validate({'id': 'stream', 'name': 'Stream', 'tasks': [{'id': 'main', 'name': 'Main', 'kind': 'subtask', 'activities': nodes,
                        'transitions': [{'id': str(i), 'source': a['id'], 'target': b['id']} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}]})
                    executor = flow.Executor(mode, project, str(Path(directory) / (kind + '-' + mode + '.log')))
                    try:
                        await executor.start()
                        result = await executor.execute('main', {})
                        self.assertEqual(result['recordsWritten'], 2, (kind, mode))
                        self.assertEqual([json.loads(line) for line in target.read_text().splitlines()], [{'name': 'ADA'}, {'name': 'GRACE'}], (kind, mode))
                    finally: await executor.close()
        with tempfile.TemporaryDirectory() as directory: asyncio.run(run(directory))


if __name__ == '__main__': unittest.main()
