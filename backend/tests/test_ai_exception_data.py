import asyncio
import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

from app.ai_builder import generate, _review_proposal
from app.main import app
from app.models import Activity, ProcessDefinition, Project, SchemaAsset, Transition
from app.runtime import WorkflowRuntime


class AIExceptionDataTests(unittest.TestCase):
    def test_throw_is_caught_and_exposes_structured_fault(self):
        process = ProcessDefinition(activities=[
            Activity(id='start', type='start', name='Start'),
            Activity(id='throw', type='throw', name='Reject Order', config={'message':'Invalid order','errorType':'BusinessFault','code':'ORDER_001','details':'{"field":"id"}'}),
            Activity(id='catch', type='catch', name='Catch Business Fault', config={'catchAll':False,'errorType':'BusinessFault'}),
            Activity(id='end', type='end', name='End'),
        ], transitions=[Transition(id='one',source='start',target='throw'),Transition(id='handled',source='catch',target='end')])
        result = asyncio.run(WorkflowRuntime().run(process, {'id':''}))
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.output['type'], 'BusinessFault')
        self.assertEqual(result.output['code'], 'ORDER_001')
        self.assertEqual(result.output['details']['field'], 'id')
        self.assertTrue(any(entry.get('kind') == 'exception' for entry in result.logs))

    def test_rethrow_propagates_to_next_handler(self):
        process = ProcessDefinition(activities=[
            Activity(id='start', type='start', name='Start'), Activity(id='throw', type='throw', name='Throw', config={'message':'boom','errorType':'SpecificFault'}),
            Activity(id='specific', type='catch', name='Specific Catch', config={'catchAll':False,'errorType':'SpecificFault'}), Activity(id='rethrow', type='rethrow', name='Rethrow'),
            Activity(id='all', type='catch', name='Outer Catch', config={'catchAll':True}), Activity(id='end', type='end', name='End'),
        ], transitions=[Transition(id='one',source='start',target='throw'),Transition(id='two',source='specific',target='rethrow'),Transition(id='three',source='all',target='end')])
        result = asyncio.run(WorkflowRuntime().run(process, {}))
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.output['type'], 'SpecificFault')
        self.assertEqual(result.output['cause']['type'], 'SpecificFault')

    def test_xml_json_and_data_follow_configured_modes(self):
        runtime = WorkflowRuntime()
        xml = '<catalog><book id="bk101"><price>44.95</price></book></catalog>'
        parsed = runtime.parse_xml(xml)
        self.assertEqual(parsed['value']['book']['@id'], 'bk101')
        self.assertEqual(parsed['value']['book']['price'], '44.95')
        rendered = runtime.render_xml(parsed, pretty=True)
        self.assertIn('id="bk101"', rendered)
        json_process = ProcessDefinition(activities=[Activity(id='start',type='start',name='Start'),Activity(id='parse',type='json',name='Parse JSON',config={'operation':'parse','jsonString':'{"id":1,"id":2}','duplicateKeyPolicy':'Error'}),Activity(id='end',type='end',name='End')],transitions=[Transition(id='a',source='start',target='parse'),Transition(id='b',source='parse',target='end')])
        self.assertEqual(asyncio.run(runtime.run(json_process, {})).status, 'failed')
        flat = runtime.flat_data({'operation':'parse','text':'id,price,active\n1,44.95,true','format':'delimited','header':True,'fieldTypes':'integer,decimal,boolean'}, {'last':{}})
        self.assertEqual(flat['records'][0], {'id':1,'price':44.95,'active':True})

    def test_ai_builder_has_safe_local_preview_and_api(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('OPENAI_API_KEY', None)
            proposal = asyncio.run(generate('Receive a REST order, parse JSON, run a JDBC query, log and send response', 'project'))
        self.assertEqual(proposal['provider'], 'local-blueprint')
        task = proposal['project']['tasks'][0]
        self.assertEqual(len([item for item in task['activities'] if item['type'] == 'rest' and item['config']['operation'] == 'receiver']), 1)
        self.assertTrue(any(item['type'] == 'http_response' for item in task['activities']))
        Project(id='ai-preview', name=proposal['project']['name'], tasks=[task], resources=proposal['project']['resources'])
        response = TestClient(app).post('/api/ai/generate', json={'requirement':'Receive a REST order and parse JSON before logging it','scope':'task'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['provider'], 'local-blueprint')

    def test_ai_builder_generated_rest_flow_executes_in_studio_and_archives(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        from app.raw_python import engine_python_files, raw_python_files

        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            proposal = asyncio.run(generate('Host POST /orders using a REST receiver, parse JSON, log, catch errors and send response with status 201.', 'project'))
        project = {'id': 'ai-regression', **proposal['project']}
        task = project['tasks'][0]
        task['id'] = 'main'
        receiver, parser, logger, handler, reply, rethrow = task['activities']
        self.assertEqual((receiver['config']['path'], receiver['config']['methods']), ('/orders', 'POST'))
        self.assertEqual(parser['config']['inputMappings'], {'jsonString': '${last.body}'})
        self.assertFalse(logger['config']['includePayload'])
        self.assertEqual((handler['type'], reply['type'], rethrow['type']), ('catch', 'http_response', 'rethrow'))
        self.assertTrue(any(edge['source'] == handler['id'] and edge['target'] == rethrow['id'] for edge in task['transitions']))
        expected = {'__httpResponse': True, 'headers': {'content-type': 'application/json'}, 'statusCode': 201, 'body': {'id': 42}}
        parity = PythonMapperParityTests()
        payload = {'body': '{"id":42}'}
        parity.assert_studio(project, payload, expected)
        for compiler in (engine_python_files, raw_python_files):
            with self.subTest(archive=compiler.__name__):
                output = parity.exported_result(compiler, project, payload)
                self.assertEqual({key: output[key] for key in ('headers', 'statusCode', 'body')},
                                 {key: expected[key] for key in ('headers', 'statusCode', 'body')})

    def test_ai_builder_reuses_starter_and_rejects_incomplete_designs(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            starter = asyncio.run(generate('Create a REST receiver for POST /orders and log the request', 'project'))['project']['tasks'][0]
            self.assertEqual(starter['activities'][-1]['config']['inputMappings'], {'body': '${last.body}'})
            updated = asyncio.run(generate('Parse JSON, then log the parsed document', 'task', starter))['project']
            self.assertEqual(updated['tasks'][0]['activities'][0]['config'], starter['activities'][0]['config'])
            self.assertEqual(updated['resources'], [])
            with self.assertRaisesRegex(ValueError, 'could not identify any supported activities'):
                asyncio.run(generate('Build a solution to make my work easier', 'project'))
            invoke = asyncio.run(generate('Host POST /orders with a REST receiver, then REST invoke GET /accounts', 'project'))['project']
            self.assertEqual(invoke['tasks'][0]['activities'][0]['config']['methods'], 'POST')
            self.assertEqual({resource['config']['connectorMode'] for resource in invoke['resources']}, {'server', 'client'})
            query = asyncio.run(generate('Run a JDBC query\n```sql\nSELECT id FROM log\n```', 'project'))['project']
            self.assertEqual([activity['type'] for activity in query['tasks'][0]['activities']], ['start', 'jdbc', 'end'])
            self.assertEqual(query['tasks'][0]['activities'][1]['config']['sql'], 'SELECT id FROM log')
        with self.assertRaisesRegex(ValueError, 'must contain a task'):
            _review_proposal({'scope': 'project', 'project': {'name': 'Empty', 'tasks': []}})
        updated['tasks'][0]['transitions'].pop()
        with self.assertRaisesRegex(ValueError, 'disconnected activities'):
            _review_proposal({'scope': 'task', 'project': updated}, model_generated=True)

    def test_ai_builder_checks_model_output_and_keeps_task_credentials_local(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            proposed = asyncio.run(generate('Parse JSON, then log the parsed document', 'project'))
        request_body = []
        response = {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps(proposed)}]}]}
        base_client = httpx.AsyncClient

        def mock_provider(request):
            request_body.append(json.loads(request.content))
            return httpx.Response(200, json=response)

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key'}), patch(
                'app.ai_builder.httpx.AsyncClient', side_effect=lambda **kwargs: base_client(
                    transport=httpx.MockTransport(mock_provider), **kwargs)):
            draft = asyncio.run(generate('Parse JSON, then log the parsed document', 'task', {
                'name': 'Orders', 'activities': [{'config': {'password': 'private-fixture-value'}}]}))
            self.assertEqual(draft['provider'], 'openai')
            self.assertNotIn('private-fixture-value', json.dumps(request_body))
            response.update(status='incomplete', output=[])
            with self.assertRaisesRegex(ValueError, 'did not return a complete design'):
                asyncio.run(generate('Parse JSON, then log the parsed document'))


if __name__ == '__main__': unittest.main()
