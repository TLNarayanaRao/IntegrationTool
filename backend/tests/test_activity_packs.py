import asyncio
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import Activity, EnvironmentProperty, ProcessDefinition, Project, SchemaAsset, Transition
from app.runtime import WorkflowRuntime


class ActivityPackTests(unittest.TestCase):
    def setUp(self):
        self.runtime = WorkflowRuntime()

    def execute(self, activity, payload):
        context = {'input': payload, 'last': payload, 'vars': {}, 'resources': {}, 'properties': {}}
        return asyncio.run(self.runtime.execute(activity, context))

    def test_xml_parse_and_render(self):
        parsed = self.execute(Activity(id='x', type='xml', name='Parse XML', config={'operation': 'parse'}), '<order id="7"><name>Ada</name></order>')
        self.assertEqual(parsed['root'], 'order')
        self.assertEqual(parsed['value']['@id'], '7')
        rendered = self.execute(Activity(id='x', type='xml', name='Render XML', config={'operation': 'render'}), parsed)
        self.assertIn('<name>Ada</name>', rendered['content'])

    def test_json_parse_and_render(self):
        parsed = self.execute(Activity(id='j', type='json', name='Parse JSON', config={'operation': 'parse'}), '{"id":7}')
        self.assertEqual(parsed, {'id': 7})
        rendered = self.execute(Activity(id='j', type='json', name='Render JSON', config={'operation': 'render'}), parsed)
        self.assertEqual(__import__('json').loads(rendered['content']), {'id': 7})

    def test_designer_input_mapping_and_error_policy(self):
        context = {'input': {'payload': {'id': 9}}, 'last': {}, 'vars': {}, 'resources': {}, 'properties': {}}
        activity = Activity(id='j', type='json', name='Render mapped JSON', config={
            'operation': 'render', 'inputMappings': {'source': '${input.payload}'}, 'outputName': 'rendered'
        })
        rendered = asyncio.run(self.runtime.execute_with_policy(activity, context))
        self.assertEqual(__import__('json').loads(rendered['content']), {'id': 9})
        self.assertEqual(context['vars']['rendered'], rendered)
        fault_context = {'input': {}, 'last': {'id': 9}, 'vars': {}, 'resources': {}, 'properties': {}}
        faulting = Activity(id='file', type='file', name='Missing file', config={
            'operation': 'read', 'path': 'definitely-missing.file',
            'errorPolicy': {'action': 'continue', 'outputVariable': 'activityError', 'includeInput': True}
        })
        fault = asyncio.run(self.runtime.execute_with_policy(faulting, fault_context))
        self.assertEqual(fault['activityId'], 'file')
        self.assertEqual(fault_context['vars']['activityError'], fault)

    def test_delimited_and_fixed_width_data(self):
        csv_result = self.execute(Activity(id='f', type='flat', name='Parse Data', config={'operation': 'parse', 'delimiter': ',', 'header': True}), 'id,name\n7,Ada\n')
        self.assertEqual(csv_result['records'][0]['name'], 'Ada')
        fixed = self.execute(Activity(id='f', type='flat', name='Render Data', config={'operation': 'render', 'format': 'fixed', 'fields': 'id,name', 'widths': '3,5'}), {'records': [{'id': 7, 'name': 'Ada'}]})
        self.assertEqual(fixed['content'], '7  Ada  ')

    def test_listener_response_and_conditional_transition(self):
        process = ProcessDefinition(activities=[
            Activity(id='listen', type='http_listener', name='Listener', config={'operation': 'listen'}),
            Activity(id='reply', type='http_response', name='Reply', config={'operation': 'response', 'statusCode': 201, 'body': '${last}'})
        ], transitions=[Transition(id='t', source='listen', target='reply', type='success_condition', condition='${last.method} == "POST"')])
        result = asyncio.run(self.runtime.run(process, {'method': 'POST', 'body': {'id': 7}}, entry_activity_id='listen'))
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.output['statusCode'], 201)

    def test_condition_functions_and_single_event_invariant(self):
        context = {'last': {'status': 'READY', 'amount': 12}, 'input': {}, 'vars': {}, 'properties': {}}
        self.assertTrue(self.runtime.condition('contains(${last.status}, "EAD") and ${last.amount} > 0', context))
        self.assertTrue(self.runtime.condition('exists(${last.status}) and not(empty(${last.status}))', context))
        with self.assertRaises(ValueError):
            ProcessDefinition(activities=[
                Activity(id='timer', type='timer', name='Timer', config={'operation': 'schedule'}),
                Activity(id='poller', type='file', name='File Poller', config={'operation': 'poll'}),
            ])

    def test_rest_listener_endpoint_with_path_parameters(self):
        project = Project(id='listener-test', name='Listener Test', properties={'dev': [EnvironmentProperty(key='status', value=202, data_type='number')]}, process=ProcessDefinition(activities=[
            Activity(id='receive', type='rest', name='Receive', config={'operation': 'receiver', 'path': '/orders/{id}', 'methods': 'POST'}),
            Activity(id='reply', type='http_response', name='Reply', config={'operation': 'response', 'statusCode': '${properties.status}', 'body': '${last}'})
        ], transitions=[Transition(id='t', source='receive', target='reply')]))
        with patch('app.main.get_project', return_value=project):
            response = TestClient(app).post('/api/listeners/listener-test/orders/42?environment=dev', json={'name': 'Ada'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['pathParameters']['id'], '42')

    def test_project_persists_packaging_and_xsd_schemas(self):
        project = Project(
            id='schema-test', name='Schema Test',
            packaging={'artifact_name': 'schema-test', 'version': '2.1.0', 'format': 'zip'},
            schemas=[SchemaAsset(id='customer', name='Customer.xsd', content='<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>')],
            process=ProcessDefinition(),
        )
        restored = Project.model_validate_json(project.model_dump_json())
        self.assertEqual(restored.packaging['version'], '2.1.0')
        self.assertEqual(restored.schemas[0].name, 'Customer.xsd')
        typed = EnvironmentProperty(key='timeout', value='30', data_type='integer')
        self.assertEqual(typed.value, 30)


if __name__ == '__main__': unittest.main()
