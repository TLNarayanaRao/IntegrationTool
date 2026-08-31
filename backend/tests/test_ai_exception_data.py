import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ai_builder import generate
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


if __name__ == '__main__': unittest.main()
