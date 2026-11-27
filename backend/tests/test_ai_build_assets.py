import base64
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from lxml import etree
from openpyxl import Workbook

from app.ai_build_assets import prepare_assets, references
from app.main import app
from app.models import AIBuildAsset, SchemaAsset


def schema(root, field):
    return f'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:element name="{root}"><xs:complexType><xs:sequence>
        <xs:element name="{field}" type="xs:string"/>
      </xs:sequence></xs:complexType></xs:element>
    </xs:schema>'''.encode()


def workbook(source='Order.item', target='Delivery.product', transform=None):
    book = Workbook()
    book.active.append(['Source Field', 'Target Field', 'Transformation'])
    book.active.append([source, target, transform])
    data = BytesIO()
    book.save(data)
    book.close()
    return data.getvalue()


def asset(name, data):
    return AIBuildAsset(name=name, content=base64.b64encode(data).decode())


REQUIREMENT = ('Host POST /orders with a REST receiver. Source schema "order.xsd", target schema "delivery.xsd". '
               'Use workbook "mapping.xlsx" and return the mapped XML.')


class AIBuildAssetsTests(unittest.TestCase):
    def test_schema_paths_and_workbook_are_validated(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'order.xsd').write_bytes(schema('Order', 'item'))
            (root / 'delivery.xsd').write_bytes(schema('Delivery', 'product'))
            (root / 'mapping.xlsx').write_bytes(workbook())
            design = prepare_assets(REQUIREMENT, project_root=root)
            self.assertEqual(design['workbookRows'], 1)
            self.assertEqual(design['rules'][0]['source'], '${last.Order.item}')
            with self.assertRaisesRegex(ValueError, 'Attach order.xsd'):
                prepare_assets(REQUIREMENT.replace('order.xsd', '../order.xsd'), project_root=root)
            (root / 'mapping.xlsx').write_bytes(workbook(source='Order.doesNotExist'))
            with self.assertRaisesRegex(ValueError, 'row 2.*unknown'):
                prepare_assets(REQUIREMENT, project_root=root)

    def test_model_free_project_separates_a_multi_step_delivery(self):
        from app.ai_build_assets import attach_mapping
        from app.ai_builder import _review_proposal, local_proposal

        document = {'type': 'object', 'properties': {'id': {'type': 'string'}}, 'required': ['id']}
        assets = [asset('source.schema.json', json.dumps(document).encode()), asset('target.schema.json', json.dumps(document).encode()),
                  asset('mapping.xlsx', workbook('id', 'id', transform='Uppercase'))]
        spec = ('Map source schema "source.schema.json" to target schema "target.schema.json" with the attached workbook. '
                'Read a file. Source path: "in/orders.json". File write. Target path: "out/orders.json". '
                'Then publish to Kafka. Target topic: "orders".')
        bundle = prepare_assets(spec, assets)
        self.assertEqual((bundle['workbookRows'], bundle['rules'][0]['functions']), (1, ['upperCase']))
        proposal = _review_proposal(attach_mapping(local_proposal(spec, 'project'), bundle))['project']
        main, mapping_task, delivery = proposal['tasks']
        self.assertEqual([node['config']['taskId'] for node in main['activities'] if node['type'] == 'call_task'], [mapping_task['id'], delivery['id']])
        self.assertEqual([node['type'] for node in delivery['activities']], ['start', 'file', 'kafka', 'end'])
        self.assertEqual(delivery['activities'][1]['config']['path'], 'out/orders.json')
        self.assertEqual(delivery['activities'][2]['config']['topic'], 'orders')

    def test_includes_bundled_project_schema_dependencies(self):
        primary = b'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:include schemaLocation="types.xsd"/><xs:element name="Order" type="OrderType"/>
        </xs:schema>'''
        dependency = SchemaAsset(id='types', name='types.xsd', content='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:complexType name="OrderType"><xs:sequence><xs:element name="item" type="xs:string"/></xs:sequence></xs:complexType>
        </xs:schema>''')
        unused = SchemaAsset(id='unused', name='unused.xsd', content=schema('Unused', 'ignore').decode())
        bundle = prepare_assets(REQUIREMENT, [asset('order.xsd', primary), asset('delivery.xsd', schema('Delivery', 'product')),
                                               asset('mapping.xlsx', workbook())], [dependency, unused])
        self.assertEqual([item['name'] for item in bundle['schemas']], ['order.xsd', 'delivery.xsd', 'types.xsd'])

    def test_rejects_external_json_schema_references(self):
        source = b'{"type":"object","properties":{"id":{"$ref":"https://example.invalid/schema.json"}}}'
        target = b'{"type":"object","properties":{"id":{"type":"string"}}}'
        spec = 'Source schema "source.schema.json", target schema "target.schema.json". Map the fields.'
        with self.assertRaisesRegex(ValueError, 'must use local JSON Schema references'):
            prepare_assets(spec, [asset('source.schema.json', source), asset('target.schema.json', target)])
        paths = references('Source schema "schema.json" and source file "orders.json"; target schema "result.schema.json".')
        self.assertEqual([name for name, _ in paths], ['schema.json', 'result.schema.json'])

    def test_generates_an_executable_project_from_xsds_and_workbook(self):
        from app.raw_python import engine_python_files, raw_python_files
        from tests.test_python_mapper_parity import PythonMapperParityTests

        assets = [asset('order.xsd', schema('Order', 'item')), asset('delivery.xsd', schema('Delivery', 'product')),
                  asset('mapping.xlsx', workbook(transform='Trim'))]
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            reply = TestClient(app).post('/api/ai/generate', json={
                'requirement': REQUIREMENT, 'scope': 'project', 'design_assets': [item.model_dump() for item in assets]})
        self.assertEqual(reply.status_code, 200, reply.text)
        project = {'id': 'schema-driven-builder', **reply.json()['project']}
        main, child = project['tasks']
        main['id'] = 'main'
        self.assertEqual([main['kind'], child['kind']], ['starter', 'subtask'])
        self.assertEqual(main['activities'][1]['config']['taskId'], child['id'])
        self.assertEqual(len(project['schemas']), 2)
        payload = {'body': '<Order><item> bolts </item></Order>'}
        parity = PythonMapperParityTests()
        output = '<Delivery><product>bolts</product></Delivery>'
        expected = {'__httpResponse': True, 'headers': {'content-type': 'application/xml'}, 'statusCode': 200, 'body': output}
        parity.assert_studio(project, payload, expected)
        for compiler in (engine_python_files, raw_python_files):
            with self.subTest(archive=compiler.__name__):
                result = parity.exported_result(compiler, project, payload)
                self.assertEqual(result['statusCode'], 200)
                self.assertEqual(etree.fromstring(result['body'].encode()).findtext('product'), 'bolts')
