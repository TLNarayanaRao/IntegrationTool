import asyncio
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.debug_fixtures import task_input_suite
from app.main import app, debugger
from app.models import Project


def project_for(kind='start', config=None, schemas=None):
    return Project.model_validate({
        'id': 'debug-input-cases', 'name': 'Fixture Tests', 'active_task_id': 'worker',
        'schemas': schemas or [],
        'tasks': [{'id': 'worker', 'name': 'Worker', 'kind': 'subtask' if kind == 'start' else 'starter',
                   'activities': [{'id': 'entry', 'name': 'Entry', 'type': kind, 'config': config or {}},
                                  {'id': 'end', 'name': 'End', 'type': 'end', 'config': {}}],
                   'transitions': [{'id': 'next', 'source': 'entry', 'target': 'end'}]}],
    })


class DebugInputCaseTests(unittest.TestCase):
    def test_json_input_cases_and_saved_cases_report_contract_changes(self):
        schema = {'type': 'object', 'properties': {'amount': {'type': 'integer', 'minimum': 1, 'maximum': 5},
                                                   'kind': {'type': 'string', 'enum': ['retail', 'online']}},
                  'required': ['amount', 'kind'], 'additionalProperties': False}
        item = project_for(config={'interfaceSchemaText': schema})
        task = item.tasks[0]
        report = task_input_suite(item, task)
        self.assertEqual(report, task_input_suite(item, task))
        accepted = [case['input'] for case in report['cases'] if case['actual'] == 'accept']
        self.assertIn({'amount': 1, 'kind': 'retail'}, accepted)
        self.assertIn({'amount': 5, 'kind': 'online'}, accepted)
        self.assertTrue(any(case['name'] == 'Missing required amount' for case in report['cases']))
        self.assertTrue(all(case['actual'] == case['expected'] for case in report['cases']))

        changed = {**schema, 'properties': {**schema['properties'], 'amount': {'type':'integer', 'minimum':3, 'maximum':5}}}
        task.activities[0].config['interfaceSchemaText'] = changed
        replay = task_input_suite(item, task, report['cases'])
        self.assertEqual(replay['cases'][0]['expected'], 'accept')
        self.assertEqual(replay['cases'][0]['actual'], 'reject')

    def test_selected_xsd_only_generates_the_selected_root_and_repeats(self):
        xsd = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:p="urn:mina:schema-selection" p:element="{}order">
          <xs:element name="different" type="xs:string"/>
          <xs:element name="order"><xs:complexType><xs:sequence>
          <xs:element name="quantity" type="xs:integer" minOccurs="1" maxOccurs="unbounded"/>
          </xs:sequence></xs:complexType></xs:element>
        </xs:schema>'''
        project = project_for(config={'interfaceSchemaText': xsd})
        cases = task_input_suite(project, project.tasks[0])['cases']
        accepted = [case['input'] for case in cases if case['actual'] == 'accept']
        self.assertIn({'order': {'quantity': [1]}}, accepted)
        self.assertTrue(all(list(item) == ['order'] for item in accepted))
        self.assertTrue(any(case['actual'] == 'reject' for case in cases))

    def test_http_openapi_cases_build_debug_receiver_envelopes(self):
        spec = {'openapi':'3.0.0', 'paths':{'/orders/{id}': {'post': {
            'operationId':'newOrder', 'parameters': [{'in':'path','name':'id','required':True,'schema':{'type':'integer'}}],
            'requestBody': {'content': {'application/json': {'schema': {
                'type':'object','required':['count'],'properties':{'count':{'type':'integer','minimum':1}},
            }}}}, 'responses': {'200': {'description':'OK'}},
        }}}}
        project = project_for('rest', {'operation':'receiver', 'openApiDocument':spec, 'operationId':'newOrder'})
        with patch('app.http_transport.client_for', side_effect=AssertionError('Unexpected network call')):
            report = task_input_suite(project, project.tasks[0])
        self.assertEqual(report['mode'], 'starter-output')
        fixture = next(case['input'] for case in report['cases'] if case['actual'] == 'accept')
        self.assertEqual((fixture['method'], fixture['path'], fixture['pathParameters'], fixture['body']),
                         ('POST', '/orders/1', {'id': 1}, {'count': 1}))
        self.assertTrue(any(case['expected'] == 'reject' for case in report['cases']))

    def test_debug_endpoint_checks_cases_and_loads_input_without_running(self):
        project = project_for(config={'interfaceSchemaText': {'type':'object','required':['id'],
                                                                 'properties':{'id':{'type':'integer'}}}})
        state = debugger.start(project, 'worker', {}, {}, {}, [])
        session_id = state['sessionId']
        client = TestClient(app)
        try:
            url = f'/api/debug/{session_id}'
            with patch.object(debugger.runtime, 'execute_with_policy') as execute, patch('app.main._persist_debug_logs'):
                report = client.post(f'{url}/input-cases', json={'task_id':'worker'})
                self.assertEqual(report.status_code, 200, report.text)
                saved = report.json()['cases']
                checked = client.post(f'{url}/input-cases', json={'task_id':'worker', 'cases':saved})
                self.assertEqual(checked.status_code, 200, checked.text)
                self.assertEqual(checked.json()['cases'], saved)
                loaded = client.post(f'{url}/action', json={'action':'load_task_input', 'task_id':'worker',
                                                                'activity_id':'entry', 'value':saved[0]['input']})
                self.assertEqual(loaded.status_code, 200, loaded.text)
                self.assertEqual(loaded.json()['variables']['input'], {'id':1})
                self.assertEqual(loaded.json()['variables']['last'], {'id':1})
                execute.assert_not_called()
            completed = asyncio.run(debugger.action(session_id, 'continue'))
            self.assertEqual(completed['output'], {'id':1})
        finally:
            debugger.sessions.pop(session_id, None)
