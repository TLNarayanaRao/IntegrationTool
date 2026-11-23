import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import Project


class SubtaskTestingTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.project = Project.model_validate({
            'id': 'direct-subtask-test', 'name': 'Example', 'active_task_id': 'worker',
            'tasks': [{'id': 'worker', 'name': 'Worker', 'kind': 'subtask', 'activities': [
                {'id': 'begin', 'name': 'Start', 'type': 'start', 'config': {}},
                {'id': 'done', 'name': 'End', 'type': 'end', 'config': {}},
            ], 'transitions': [{'id': 'next', 'source': 'begin', 'target': 'done'}]}],
        })
        self.config = self.project.tasks[0].activities[0].config
        for context in (
            patch('app.main.get_project', return_value=self.project),
            patch('app.main._write_runtime_logs'),
            patch('app.main._startup_diagnostics', return_value=[]),
            patch('app.main.runtime_states', {}),
        ):
            self.enterContext(context)
        self.setup_url = '/api/projects/direct-subtask-test/tasks/worker/test-input'
        self.run_url = '/api/projects/direct-subtask-test/run'

    def run_test(self, input=None, **options):
        return self.client.post(self.run_url, json={
            'task_id': 'worker', 'test_subtask': True, **({'input': input} if input is not None else {}), **options,
        })

    def test_direct_run_without_input_executes_the_subtask(self):
        self.assertEqual(self.client.post(self.setup_url, json={}).json()['format'], 'none')
        self.assertEqual(self.run_test(test_subtask=False).status_code, 400)
        with patch('app.main._start_http_listener') as listener:
            result = self.run_test()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['output'], {})
        self.assertEqual(result.json()['status'], 'completed')
        self.assertEqual(set(result.json()['activity_outputs']), {'begin', 'done'})
        listener.assert_not_called()

    def test_schema_validation_runs_before_workflow_and_valid_input_reaches_start(self):
        self.config['interfaceSchemaText'] = json.dumps({
            'type': 'object', 'required': ['order'],
            'properties': {'order': {'type': 'integer', 'minimum': 1}},
        })
        report = self.client.post(self.setup_url, json={}).json()
        self.assertEqual(report['example'], {'order': 1})
        self.assertEqual(report['fields'][0]['path'], 'order')
        self.assertTrue(self.client.post(self.setup_url, json={'input': {'order': 'wrong'}}).json()['errors'])
        with patch('app.main.runtime.run') as runtime:
            self.assertEqual(self.run_test().status_code, 422)
            self.assertEqual(self.run_test({'order': 0}).status_code, 422)
            runtime.assert_not_called()
        result = self.run_test({'order': 42}, environment='qa')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['activity_outputs']['begin']['output'], {'order': 42})
        self.assertEqual(result.json()['output'], {'order': 42})

    def test_selected_xsd_with_include_uses_the_selected_root_and_validates_facets(self):
        schema = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:include schemaLocation="parts/types.xsd"/>
          <xs:element name="unselected" type="xs:string"/>
          <xs:element name="order" type="Order"/>
        </xs:schema>'''
        types = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:simpleType name="OrderId"><xs:restriction base="xs:string">
            <xs:pattern value="[A-Z][0-9]{2}"/>
          </xs:restriction></xs:simpleType>
          <xs:complexType name="Order"><xs:sequence><xs:element name="id" type="OrderId"/></xs:sequence></xs:complexType>
        </xs:schema>'''
        from app.models import SchemaAsset
        self.project.schemas.extend([
            SchemaAsset(id='order', name='order.xsd', source_path='schemas/order.xsd', content=schema),
            SchemaAsset(id='types', name='types.xsd', source_path='schemas/parts/types.xsd', content=types),
        ])
        self.config.update(interfaceSchemaId='order', interfaceSchemaText=schema.replace(
            '<xs:schema ', '<xs:schema xmlns:selection="urn:mina:schema-selection" selection:structure="element|{}order" ', 1))
        report = self.client.post(self.setup_url, json={})
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(list(report.json()['example']), ['order'])
        for invalid in ({'unselected': 'anything'}, {'order': {'id': 'wrong'}}):
            self.assertEqual(self.run_test(invalid).status_code, 422)
        result = self.run_test({'order': {'id': 'A42'}})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['output'], {'order': {'id': 'A42'}})
        raw = self.run_test('<order><id>A42</id></order>', input_format='xml')
        self.assertEqual(raw.status_code, 200, raw.text)
        self.assertEqual(raw.json()['output'], {'order': {'id': 'A42'}})

    def test_raw_xml_checks_selected_root_namespace_and_validates_before_execution(self):
        self.config['interfaceSchemaText'] = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
          xmlns:pick="urn:mina:schema-selection" pick:element="{urn:orders}order"
          targetNamespace="urn:orders" elementFormDefault="qualified">
          <xs:element name="other" type="xs:string"/>
          <xs:element name="order"><xs:complexType><xs:sequence>
            <xs:element name="quantity" type="xs:int" maxOccurs="unbounded"/>
            <xs:element name="paid" type="xs:boolean"/>
          </xs:sequence><xs:attribute name="id" type="xs:integer" use="required"/></xs:complexType></xs:element>
        </xs:schema>'''
        correct = '<m:order xmlns:m="urn:orders" id="21"><m:quantity>3</m:quantity><m:paid>0</m:paid></m:order>'
        invalid = [
            ('<other xmlns="urn:orders">valid sibling</other>', 'Expected selected XSD root'),
            (correct.replace('urn:orders', 'urn:wrong'), 'Expected selected XSD root'),
            (correct.replace('>3<', '>wrong<'), 'not a valid value'),
            ('<!DOCTYPE order>' + correct, 'DTDs'),
            ('<order>', 'Premature end'),
        ]
        self.assertEqual(self.client.post(self.setup_url, json={}).json()['root'], '{urn:orders}order')
        with patch('app.main.runtime.run') as execute:
            for xml, message in invalid:
                with self.subTest(message=message):
                    validation = self.client.post(self.setup_url, json={'input': xml, 'input_format': 'xml'})
                    self.assertIn(message, validation.json()['errors'][0])
                    launched = self.run_test(xml, input_format='xml')
                    self.assertEqual(launched.status_code, 422, launched.text)
                    self.assertIn(message, launched.json()['detail'])
            execute.assert_not_called()
        self.assertEqual(self.client.post(self.setup_url, json={'input': correct, 'input_format': 'xml'}).json()['errors'], [])
        result = self.run_test(correct, input_format='xml')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['output'], {'order': {'@id': 21, 'quantity': [3], 'paid': False}})
        self.config.clear()
        self.assertEqual(self.run_test(correct, input_format='xml').status_code, 422)

    def test_json_root_array_and_explicit_null_follow_start_schema(self):
        self.config['interfaceSchemaText'] = '{"type":"array","items":{"type":"integer"},"minItems":1}'
        response = self.run_test([1, 2])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['activity_outputs']['begin']['output'], [1, 2])
        self.assertEqual(response.json()['output'], {'result': [1, 2]})
        self.assertEqual(self.run_test(['invalid']).status_code, 422)
        self.config['interfaceSchemaText'] = '{"type":"null"}'
        self.assertEqual(self.client.post(self.setup_url, json={'input': None}).json()['errors'], [])
        response = self.client.post(self.run_url, json={'task_id': 'worker', 'test_subtask': True, 'input': None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['output'], {'result': None})
