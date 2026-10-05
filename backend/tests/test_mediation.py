import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from backend.app.mediation import execute, execute_details, MediationError
from backend.tests.test_raw_python import compiler


class MediationTests(unittest.TestCase):
    def test_dynamic_upstream_target_mapping_studio_and_export(self):
        from backend.app.runtime import WorkflowRuntime
        from backend.app.models import Activity
        cfg={'operation':'mediate','targetSchemaText':'{"type":"object","properties":{"orderId":{"type":"string"}},"required":["orderId"]}', 'inputMappings':{'targetValues.orderId':'${ReadOrder.id}'}}
        cfg['inputMappings']['targetValues.literal']='__mina_constant__:"${untouched}"'
        ctx={'input':{},'last':{},'properties':{},'vars':{},'resources':{},'activities':{'ReadOrder':{'output':{'id':'A-100'}}}}
        self.assertEqual(asyncio.run(WorkflowRuntime().execute(Activity(id='m',name='Mediation',type='mediation',config=cfg),ctx)),{'orderId':'A-100','literal':'${untouched}'})
        project={'id':'p','name':'P','resources':[],'schemas':[],'tasks':[{'id':'main','name':'Main','kind':'starter','groups':[], 'activities':[{'id':'ReadOrder','name':'ReadOrder','type':'start','config':{}},{'id':'m','name':'Mediation','type':'mediation','config':cfg},{'id':'end','name':'End','type':'end','config':{}}], 'transitions':[{'source':'ReadOrder','target':'m'},{'source':'m','target':'end'}]}]}
        files=compiler.raw_python_files(project,{'local':[]})
        with tempfile.TemporaryDirectory() as folder:
            for name,body in files.items():
                path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
            sys.path.insert(0,folder)
            try:
                from application.main import run_task
                self.assertEqual(asyncio.run(run_task('main',{'id':'A-200'},'local')),{'orderId':'A-200','literal':'${untouched}'})
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name=='application' or name.startswith('application.'):sys.modules.pop(name)

    def test_target_contract_json_and_xsd(self):
        from backend.app.mediation import target_contract, schema_fields
        schema='{"type":"object","properties":{"buyer":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}},"required":["buyer"]}'
        cfg={'targetSchemaText':schema,'rules':[{'source':'name','target':'buyer.name'}]}
        self.assertEqual(execute({'name':'Ana'},cfg),{'buyer':{'name':'Ana'}})
        with self.assertRaisesRegex(MediationError,'expected string'): execute({'name':3},cfg)
        with self.assertRaisesRegex(MediationError,'required field'): execute({},cfg)
        xsd='<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="order"><xs:complexType><xs:sequence><xs:element name="quantity" type="xs:int"/></xs:sequence></xs:complexType></xs:element></xs:schema>'
        contract=target_contract(xsd)
        self.assertEqual(schema_fields(contract),[{'path':'quantity','type':'integer','required':True}])
        self.assertEqual(execute({'n':'2'},{'targetSchemaText':xsd,'rules':[{'source':'n','target':'quantity','operation':'integer'}]}),{'quantity':2})
        with self.assertRaisesRegex(MediationError,'Unsupported'): target_contract('{"type":"object","$ref":"https://example.com/schema"}')

    def recipe(self):
        return {'operation': 'mediate', 'collection': 'orders', 'asArray': True, 'rules': [
            {'source': 'name', 'target': 'buyer.name', 'operation': 'trim', 'required': True},
            {'source': 'amount', 'target': 'total', 'operation': 'number'},
            {'source': 'status', 'target': 'state', 'operation': 'lookup', 'values': {'N': 'New'}}]}

    def test_business_recipe(self):
        payload = {'orders': [{'name': ' Ana ', 'amount': '42.50', 'status': 'N'}]}
        result = execute_details(payload, self.recipe())
        self.assertEqual(result['output'], [{'buyer': {'name': 'Ana'}, 'total': 42.5, 'state': 'New'}])
        self.assertNotIn('Ana', str(result['trace']))
        self.assertEqual(payload['orders'][0]['name'], ' Ana ')

    def test_xml_csv_and_stable_single_record_array(self):
        cfg = {'inputFormat': 'xml', 'collection': 'orders.order', 'asArray': True, 'rules': [{'source': 'id', 'target': 'id'}]}
        self.assertEqual(execute('<orders><order><id>1</id></order></orders>', cfg), [{'id': '1'}])
        cfg.update(inputFormat='csv', collection='$', outputFormat='xml')
        self.assertIn('<record><id>1</id></record>', execute('id\n1', cfg))
        cfg.update(inputFormat='json', outputFormat='csv')
        self.assertEqual(execute([{'id': 'a,b'}], cfg), 'id\r\n"a,b"\r\n')

    def test_missing_defaults_constants_and_empty_array(self):
        cfg = {'rules': [{'source': 'missing', 'target': 'value', 'default': 0}, {'constant': True, 'target': 'enabled'}]}
        self.assertEqual(execute({}, cfg), {'value': 0, 'enabled': True})
        self.assertEqual(execute([], cfg), [])
        cfg['rules'][0] = {'source': 'missing', 'target': 'value', 'required': True}
        with self.assertRaisesRegex(MediationError, 'rule 1'): execute({}, cfg)

    def test_invalid_recipes_and_safe_errors(self):
        for cfg in ({'rules': []}, {'rules': [{'target': 'a'}, {'target': 'a.b'}]}, {'rules': [{'target': 'a', 'operation': 'eval'}]}):
            with self.assertRaises(MediationError): execute({}, cfg)
        with self.assertRaisesRegex(MediationError, 'conversion failed') as error:
            execute({'secret': 'sensitive-value'}, {'rules': [{'source': 'secret', 'target': 'a', 'operation': 'integer'}]})
        self.assertNotIn('sensitive-value', str(error.exception))
        with self.assertRaises(MediationError): execute('<!DOCTYPE a><a/>', {'inputFormat': 'xml', 'rules': [{'target': 'a'}]})
        with self.assertRaises(MediationError): execute('x'*2_000_001, {'rules': [{'target': 'a'}]})

    def test_studio_runtime_and_mapped_payload(self):
        from backend.app.runtime import WorkflowRuntime
        from backend.app.models import Activity
        data = {'orders': [{'name': ' Ana ', 'amount': '2', 'status': 'N'}]}
        config = {**self.recipe(), 'inputMappings': {'payload': '${input}'}}
        activity = Activity(id='m', name='Mediation', type='mediation', config=config)
        ctx = {'input': data, 'last': {}, 'properties': {}, 'resources': {}, 'vars': {}, 'activities': {}}
        self.assertEqual(asyncio.run(WorkflowRuntime().execute(activity, ctx)), execute(data, self.recipe()))

    def test_direct_python_export_executes_same_recipe(self):
        recipe = self.recipe()
        recipe['targetSchemaText'] = '{"type":"array","items":{"type":"object","properties":{"total":{"type":"number"}},"required":["total"]}}'
        project = {'id': 'mediation', 'name': 'Mediation', 'resources': [], 'schemas': [], 'tasks': [
            {'id': 'main', 'name': 'Main', 'kind': 'starter', 'groups': [], 'activities': [
                {'id': 's', 'name': 'Start', 'type': 'start', 'config': {}},
                {'id': 'm', 'name': 'Mediation', 'type': 'mediation', 'config': recipe},
                {'id': 'e', 'name': 'End', 'type': 'end', 'config': {}}],
             'transitions': [{'source': 's', 'target': 'm'}, {'source': 'm', 'target': 'e'}]}]}
        files = compiler.raw_python_files(project, {'local': []})
        self.assertIn('application/native/mediation.py', files)
        self.assertNotIn('application/native/sap.py', files)
        with tempfile.TemporaryDirectory() as folder:
            for name, content in files.items():
                path = Path(folder)/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
            sys.path.insert(0, folder)
            try:
                from application.main import run_task
                data = {'orders': [{'name': ' Ana ', 'amount': '1.5', 'status': 'N'}]}
                self.assertEqual(asyncio.run(run_task('main', data, 'local')), execute(data, recipe))
            finally:
                sys.path.remove(folder)
                for name in list(sys.modules):
                    if name == 'application' or name.startswith('application.'): sys.modules.pop(name)
