import json
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.mapper_xml import xpath_function_palette

ROOT=Path(__file__).resolve().parents[2]


class XPathDesignerPaletteTests(unittest.TestCase):
    def test_checked_in_designer_inventory_matches_executable_runtime(self):
        source=(ROOT/'frontend/src/xpath-catalog.ts').read_text(encoding='utf-8')
        catalog=json.loads(source.split('export const xpathCatalog: Record<string,XPathFunction[]> = ',1)[1].rstrip().removesuffix(';'))
        for version in ('1.0','2.0'):
            self.assertEqual(catalog[version],xpath_function_palette(version))
            self.assertEqual(len({(item['name'],len(item['args'])) for item in catalog[version]}),len(catalog[version]))
            self.assertTrue(all(item['description'] for item in catalog[version]))
        self.assertGreaterEqual(len(catalog['1.0']),49)
        self.assertGreaterEqual(len(catalog['2.0']),200)
        with self.assertRaises(ValueError):xpath_function_palette('3.1')

    def test_palette_api_has_categories_descriptions_and_correct_overloads(self):
        client=TestClient(app)
        response=client.get('/api/mapper/xpath/functions?version=2.0')
        self.assertEqual(response.status_code,200)
        entries=response.json()['functions']
        self.assertEqual({entry['category'] for entry in entries if entry['name'] in ('floor','avg','sum')},{'Numbers'})
        self.assertEqual([len(entry['args']) for entry in entries if entry['name']=='substring'],[2,3])
        self.assertTrue(all(entry['description'] for entry in entries))
        self.assertFalse({'doc','doc-available','collection','trace'}&{entry['name'] for entry in entries})
        self.assertEqual(client.get('/api/mapper/xpath/functions?version=3.1').status_code,400)

    def test_designer_functions_in_map_test_run_debug_and_both_python_formats(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        helper=PythonMapperParityTests()
        examples=[
            ('count',"count(/orders/order)",2,'number'),
            ('floor','floor(9.8)',9,'number'),
            ('round','round-half-to-even(2.5)',2,'number'),
            ('sum','sum(/orders/order/@amount)',10,'number'),
            ('average','avg((2,4,6))',4,'number'),
            ('minimum','min((7,2,5))',2,'number'),
            ('distinct',"distinct-values(('a','a','b'))",['a','b'],None),
            ('part',"subsequence(('a','b','c'),2,2)",['b','c'],None),
            ('replace',"replace('a.b','[.]','-')",'a-b',None),
            ('matches',"matches('AB12','^[A-Z]+[0-9]+$')",True,None),
            ('tokens',"tokenize('a,b,c',',')",['a','b','c'],None),
            ('year',"year-from-date(xs:date('2026-11-13'))",2026,'number'),
            ('local','local-name(/orders)','orders',None),
            ('encoded',"encode-for-uri('a b')",'a%20b',None),
            ('boolean',"xs:boolean('true')",True,None),
        ]
        rules=[{'target':name,'source':'xpath2('+json.dumps(expression)+')',**({'targetType':type} if type else {})}
               for name,expression,_,type in examples]
        project=helper.project(rules);project['tasks'][0]['activities'][1]['config']['xpathVersion']='1.0'
        payload={'xmlString':'<orders><order amount="2.4"/><order amount="7.6"/></orders>'}
        expected={name:value for name,_,value,_ in examples}
        response=TestClient(app).post('/api/mapper/test',json={'input':payload,'mappings':rules,'options':{'xpathVersion':'1.0'}})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['output'],expected)
        helper.assert_studio(project,payload,expected)
        helper.assert_exports(project,payload,expected)
