import copy
import unittest
from unittest.mock import patch
from app.api_blueprint import validate_blueprint, blueprint_plan
from app.http_server import route_pattern


def contract():
    return {'openapi':'3.1.0','info':{'title':'Robust API','version':'1.0.0'},'paths':{
        '/orders/{order-id}':{'get':{'operationId':'getOrder','parameters':[
            {'in':'path','name':'order-id','required':True,'schema':{'type':'string'}}],
            'responses':{'200':{'description':'OK','content':{'application/json':{
                'schema':{'type':'object'},'example':{'ok':True}}}}}}}}}


class BlueprintRobustnessTests(unittest.TestCase):
    def test_large_contract_is_not_reloaded_for_each_operation(self):
        document=contract();document['paths']={f'/item-{index}':{'get':{'operationId':f'item{index}',
            'responses':{'200':{'description':'OK'}}}} for index in range(64)}
        with patch('app.rest_contract.bundle_document',side_effect=AssertionError('Contract was already bundled')):
            self.assertEqual(len(validate_blueprint(document)['operations']),64)

    def test_multifile_import_is_offline_and_bundles_reusable_schemas(self):
        document=contract()
        definition=document['paths']['/orders/{order-id}']['get']['responses']['200']['content']['application/json']
        definition['schema']={'$ref':'models/order.yaml'}
        references={'models/order.yaml':'type: object\nrequired: [ok]\nproperties:\n  ok: {type: boolean}\n'}
        with patch('app.http_transport.client_for',side_effect=AssertionError('Must not fetch documents')):
            result=validate_blueprint(document,reference_documents=references,document_path='openapi.yaml')
            plan=blueprint_plan(document,['getOrder'],{'type':'http','config':{}},reference_documents=references,document_path='openapi.yaml')
        self.assertIn('x-mina-refs',result['document'])
        self.assertIn('x-mina-refs',plan['resource']['config']['openApiDocument'])
        self.assertNotIn('x-mina-refs',document)
        with self.assertRaises(ValueError):validate_blueprint(document)

    def test_reference_limits_and_remote_urls_fail_without_fetching(self):
        for references in ({str(index):{} for index in range(16)}, [], {'large.yaml':'x'*(8*1024**2+1)}):
            with self.subTest(type=type(references)),self.assertRaises(ValueError):
                validate_blueprint(contract(),reference_documents=references)
        document=contract();document['paths']['/remote']={'$ref':'https://provider.invalid/path.yaml'}
        with patch('app.http_transport.client_for',side_effect=AssertionError('No network')),self.assertRaises(ValueError):
            validate_blueprint(document)

    def test_every_media_schema_and_example_is_validated(self):
        document=contract();operation=document['paths']['/orders/{order-id}']['get']
        operation['responses']['200']['content']['text/plain']={'schema':{'type':'string'},'example':'ready'}
        self.assertTrue(validate_blueprint(document)['operations'][0]['hasExample'])
        operation['responses']['200']['content']['text/plain']['example']=123
        with self.assertRaisesRegex(ValueError,'text/plain'):validate_blueprint(document)
        operation['responses']['200']['content']['text/plain']={'schema':{'type':'invalid-type'}}
        with self.assertRaisesRegex(ValueError,'invalid schema'):validate_blueprint(document)
        operation['responses']['200']['content'].pop('text/plain')
        operation['requestBody']={'content':{'application/json':{'schema':{'type':'object'}},'text/plain':{'schema':{'type':'invalid-type'}}}}
        with self.assertRaisesRegex(ValueError,'invalid schema'):validate_blueprint(document)

    def test_mock_supports_named_null_references_schema_examples_and_headers(self):
        document=contract();definition=document['paths']['/orders/{order-id}']['get']['responses']['200']
        definition['content']={'application/json':{'schema':{'type':['object','null']},'examples':{'empty':{'$ref':'#/components/examples/Empty'}}}}
        definition['headers']={'X-Version':{'schema':{'type':'string','default':'v1'}}}
        document['components']={'examples':{'Empty':{'value':None}}}
        result=validate_blueprint(document)
        self.assertIsNone(result['operations'][0]['example']['body'])
        plan=blueprint_plan(document,['getOrder'],{'type':'http','config':{}},response_mode='example')
        mapping=plan['tasks'][0]['activities'][1]['config']['inputMappings']
        self.assertEqual(mapping['body'],'null');self.assertIn('X-Version',mapping['headers'])
        definition['content']={'application/json':{'schema':{'type':'string','example':'ready'}}}
        self.assertEqual(validate_blueprint(document)['operations'][0]['example']['body'],'ready')

    def test_bodyless_mock_and_hyphenated_path_parameters(self):
        document=contract();document['paths']['/orders/{order-id}']['get']['responses']={'204':{'description':'Empty'}}
        plan=blueprint_plan(document,['getOrder'],{'type':'http','config':{}},response_mode='example')
        self.assertEqual(plan['tasks'][0]['activities'][1]['config']['statusCode'],204)
        pattern,names=route_pattern('/orders/{order-id}')
        self.assertEqual(names,['order-id']);self.assertEqual(pattern.match('/orders/100').groups(),('100',))

    def test_malformed_metadata_is_rejected_before_scaffolding(self):
        mutations=[lambda op:op.update(parameters={}),lambda op:op.update(responses={'oops':{}}),
                   lambda op:op.update(responses={'200':{'content':[]}}),
                   lambda op:op.update(responses={'200':{'headers':['bad']}}),
                   lambda op:op.update(responses={'200':{'headers':{'X-Version':{'example':'bad\nheader'}}}}),
                   lambda op:op['parameters'].append(copy.deepcopy(op['parameters'][0])),
                   lambda op:op['parameters'][0].update(required='true'),
                   lambda op:op['parameters'][0].update(name='absent')]
        for mutate in mutations:
            document=contract();mutate(document['paths']['/orders/{order-id}']['get'])
            with self.subTest(mutation=mutate),self.assertRaises(ValueError):validate_blueprint(document)
        document=contract();document['x-invalid']=float('nan')
        with self.assertRaises(ValueError):validate_blueprint(document)

    def test_generated_names_are_unique_even_when_routes_only_differ_in_case(self):
        document=contract();operation=document['paths']['/orders/{order-id}']['get']
        operation['callbacks']={'onDone':{
            '{$request.query.first}':{'post':{'responses':{'200':{'description':'OK'}}}},
            '{$request.query.second}':{'post':{'responses':{'200':{'description':'OK'}}}}}}
        document['paths']['/Orders/{order-id}']=copy.deepcopy(document['paths']['/orders/{order-id}'])
        document['paths']['/Orders/{order-id}']['get']['operationId']='getOtherOrder'
        selected=[item['operationId'] for item in validate_blueprint(document)['operations']]
        plan=blueprint_plan(document,selected,{'type':'http','config':{}})
        names=[item['name'].casefold() for item in [plan['resource'],*plan['tasks']]]
        self.assertEqual(len(names),len(set(names)))
        self.assertTrue(all(' ' not in name for name in names))

    def test_swagger_resolves_named_examples_and_preserves_response_headers(self):
        from app.api_docs import generate_openapi, postman_collection
        from app.http_server import listener_config
        document=contract();operation=document['paths']['/orders/{order-id}']['get']
        operation['responses']['200']['headers']={'X-Version':{'schema':{'type':'string','default':'v1'}}}
        operation['responses']['200']['content']['application/json'].pop('example')
        operation['responses']['200']['content']['application/json']['examples']={'success':{'$ref':'examples/order.yaml'}}
        operation['requestBody']={'content':{'application/json':{'schema':{'type':['object','null']},'examples':{'empty':{'value':None}}}}}
        plan=blueprint_plan(document,['getOrder'],{'type':'http','config':{}},reference_documents={'examples/order.yaml':{'value':{'ok':True}}},document_path='openapi.yaml')
        cfg=listener_config(plan['resource']['config'],plan['tasks'][0]['activities'][0]['config'])
        spec=generate_openapi([(None,cfg)])
        generated=spec['paths']['/orders/{order-id}']['get']
        self.assertEqual(generated['responses']['200']['content']['application/json']['examples']['success']['value'],{'ok':True})
        self.assertIn('X-Version',generated['responses']['200']['headers'])
        collection=postman_collection(spec,'http://localhost')
        self.assertEqual(collection['item'][0]['request']['body']['raw'],'null')
        swagger={'swagger':'2.0','info':{'title':'Legacy API','version':'1'},'paths':{'/':{'get':{'operationId':'legacy','responses':{'200':{
            'description':'OK','schema':{'type':'string','example':'ready'},'headers':{'X-Version':{'type':'string','default':'v1'}}}}}}}}
        plan=blueprint_plan(swagger,['legacy'],{'type':'http','config':{}},response_mode='example')
        self.assertEqual(plan['tasks'][0]['activities'][1]['config']['inputMappings']['body'],'"ready"')
        cfg=listener_config(plan['resource']['config'],plan['tasks'][0]['activities'][0]['config'])
        generated=generate_openapi([(None,cfg)])['paths']['/']['get']
        self.assertIn('schema',generated['responses']['200']['headers']['X-Version'])


if __name__=='__main__':unittest.main()
