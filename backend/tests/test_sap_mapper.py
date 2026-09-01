import asyncio, unittest
from fastapi.testclient import TestClient
from app.main import app
from app.models import Activity, ProcessDefinition, Project, SharedResource
from app.runtime import WorkflowRuntime

class SapMapperTests(unittest.TestCase):
    def setUp(self): self.client = TestClient(app)

    def test_mapper_recommends_nested_fields_and_executes_functions(self):
        suggested = self.client.post('/api/mapper/suggest', json={
            'sourceSchema': {'customer': {'id':'C1','firstName':'Ada','postalCode':'85001'}},
            'targetSchema': {'account': {'identifier':'','givenName':'','zip':''}}, 'threshold': 40
        })
        self.assertEqual(suggested.status_code, 200)
        recommendations = suggested.json()['recommendations']
        self.assertTrue(any(item['selected'] for item in recommendations))
        tested = self.client.post('/api/mapper/test', json={'input':{'customer':{'firstName':' Ada '}}, 'mappings':[{'source':'customer.firstName','target':'account.givenName','functions':['trim','upper']}]})
        self.assertEqual(tested.json()['output']['account']['givenName'], 'ADA')
        designer_test = self.client.post('/api/mapper/test', json={
            'input': {'customer': {'firstName': ' Ada '}},
            'mappings': [{'source': '${activities.read.output.customer.firstName}', 'target': 'account.givenName', 'functions': ['trim', 'upper']}],
        })
        self.assertEqual(designer_test.json()['output']['account']['givenName'], 'ADA')
        self.assertEqual(designer_test.json()['mappingCount'], 1)
        conditional = self.client.post('/api/mapper/test', json={
            'input': {'customer': {'firstName': 'Ada'}},
            'mappings': [{'source': '${input.customer.firstName}', 'target': 'account.givenName', 'operator': 'if', 'condition': 'exists(${input.customer.firstName})'}],
        })
        self.assertEqual(conditional.json()['output']['account']['givenName'], 'Ada')

    def test_transform_accepts_typed_constants_and_dynamic_tree_mappings(self):
        runtime = WorkflowRuntime()
        context = {'input': {'order': {'id': 42}}, 'last': {'status': 'NEW'}, 'vars': {}, 'resources': {}, 'properties': {}, 'activities': {'source': {'output': {'amount': 19.5}}}}
        self.assertEqual(runtime.resolve('"quoted string"', context), 'quoted string')
        self.assertEqual(runtime.resolve("'single quoted string'", context), 'single quoted string')
        activity = Activity(id='map', type='transform', name='Transform', config={'mappings':[
            {'target':'order.id', 'source':'${input.order.id}', 'enabled':True},
            {'target':'order.amount', 'source':'${activities.source.output.amount}', 'enabled':True},
            {'target':'order.active', 'constant':True, 'enabled':True},
            {'target':'order.tags', 'constant':['priority', 'new'], 'enabled':True},
        ]})
        result = asyncio.run(runtime.execute(activity, context))
        self.assertEqual(result, {'order': {'id':42, 'amount':19.5, 'active':True, 'tags':['priority', 'new']}})

    def test_mapper_repeats_target_and_maps_children_in_for_each_scope(self):
        response = self.client.post('/api/mapper/test', json={
            'input': {'catalog': {'book': [
                {'@id': 'bk101', 'author': 'Matthew', 'price': 44.95},
                {'@id': 'bk102', 'author': 'Kim', 'price': 12.50},
            ]}},
            'mappings': [
                {'target': 'catalog.book', 'source': 'catalog.book', 'select': 'catalog.book', 'operator': 'for-each'},
                {'target': 'catalog.book.@id', 'source': 'catalog.book.@id'},
                {'target': 'catalog.book.author', 'source': 'catalog.book.author'},
                {'target': 'catalog.book.price', 'source': 'catalog.book.price'},
            ],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['output']['catalog']['book'], [
            {'@id': 'bk101', 'author': 'Matthew', 'price': 44.95},
            {'@id': 'bk102', 'author': 'Kim', 'price': 12.50},
        ])

    def test_mapper_xpath_index_is_one_based_and_suppresses_iteration(self):
        response = self.client.post('/api/mapper/test', json={
            'input': {'catalog': {'book': [{'author': 'First'}, {'author': 'Second'}]}},
            'mappings': [{'target': 'selectedAuthor', 'source': 'catalog.book[1].author'}],
        })
        self.assertEqual(response.json()['output']['selectedAuthor'], 'First')

    def test_mapper_for_each_group_creates_one_target_per_group(self):
        response = self.client.post('/api/mapper/test', json={
            'input': {'orders': [
                {'customerId': 'A', 'orderId': '1'},
                {'customerId': 'A', 'orderId': '2'},
                {'customerId': 'B', 'orderId': '3'},
            ]},
            'mappings': [
                {'target': 'customers.customer', 'source': 'orders', 'operator': 'for-each-group', 'groupBy': 'customerId'},
                {'target': 'customers.customer.customerId', 'source': 'orders.customerId'},
            ],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['output']['customers']['customer'], [
            {'customerId': 'A'}, {'customerId': 'B'},
        ])

    def test_mapper_duplicate_repeating_occurrence_appends_complete_complex_nodes(self):
        source = {'catalog': {'book': [{'author': 'First'}, {'author': 'Second'}]}}
        family = [
            {'target': 'catalog.book', 'source': 'catalog.book', 'operator': 'for-each'},
            {'target': 'catalog.book.author', 'source': 'catalog.book.author'},
        ]
        duplicate = [{**rule, 'occurrenceId': 'copy-2', 'duplicateOf': 'primary'} for rule in family]
        response = self.client.post('/api/mapper/test', json={'input': source, 'mappings': [*family, *duplicate]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['output']['catalog']['book'], [
            {'author': 'First'}, {'author': 'Second'},
            {'author': 'First'}, {'author': 'Second'},
        ])

    def test_mapper_integration_policies_are_executable(self):
        schema = {'type': 'object', 'required': ['order'], 'properties': {'order': {'type': 'object', 'required': ['id'], 'properties': {'id': {'type': 'integer'}, 'note': {'type': 'string'}}}}}
        safe = self.client.post('/api/mapper/test', json={
            'input': {'source': {'id': '42', 'note': None}}, 'targetSchema': schema,
            'options': {'typeCoercion': 'safe', 'nullPolicy': 'omit', 'validateOutput': True},
            'mappings': [
                {'source': 'source.id', 'target': 'order.id', 'targetType': 'integer'},
                {'source': 'source.note', 'target': 'order.note', 'targetType': 'string'},
            ],
        })
        self.assertEqual(safe.status_code, 200)
        self.assertEqual(safe.json()['output'], {'order': {'id': 42}})
        strict = self.client.post('/api/mapper/test', json={
            'input': {'source': {'id': '42'}}, 'options': {'typeCoercion': 'strict'},
            'mappings': [{'source': 'source.id', 'target': 'order.id', 'targetType': 'integer'}],
        })
        self.assertEqual(strict.status_code, 400)
        invalid = self.client.post('/api/mapper/test', json={
            'input': {}, 'targetSchema': schema, 'options': {'validateOutput': True}, 'mappings': [],
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertFalse(invalid.json()['valid'])
        self.assertTrue(invalid.json()['validationErrors'])

    def test_mapper_preview_validates_xsd_and_normalizes_choose_branches(self):
        xsd = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="order"><xs:complexType><xs:sequence><xs:element name="id" type="xs:integer"/><xs:element name="status" type="xs:string"/></xs:sequence></xs:complexType></xs:element></xs:schema>'''
        response = self.client.post('/api/mapper/test', json={
            'input': {'active': True, 'identifier': 7}, 'targetSchemaText': xsd,
            'mappings': [
                {'source': 'identifier', 'target': 'order.id'},
                {'target': 'order.status', 'operator': 'choose', 'whens': [{'condition': 'active', 'source': '"ACTIVE"'}], 'otherwise': '"INACTIVE"'},
            ],
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['valid'], response.text)
        self.assertEqual(response.json()['output'], {'order': {'id': 7, 'status': 'ACTIVE'}})
        self.assertEqual(response.json()['diagnostics']['conditionalCount'], 1)

    def test_ai_mapper_recommends_for_each_for_compatible_arrays(self):
        response = self.client.post('/api/mapper/suggest', json={
            'threshold': 40,
            'sourceSchema': {'type': 'object', 'properties': {'books': {'type': 'array', 'items': {'type': 'object', 'properties': {'title': {'type': 'string'}}}}}},
            'targetSchema': {'type': 'object', 'properties': {'books': {'type': 'array', 'items': {'type': 'object', 'properties': {'title': {'type': 'string'}}}}}},
        })
        recommendation = next(item for item in response.json()['recommendations'] if item['target'] == 'books.title')
        self.assertEqual(recommendation['selected'], 'books.title')
        self.assertEqual(recommendation['operator'], 'for-each')
        self.assertEqual(recommendation['sourceRepeatPath'], 'books')
        self.assertEqual(recommendation['targetRepeatPath'], 'books')

    def test_all_documented_sap_operations_run_in_mock_mode(self):
        operations = ['dynamic_connection','idoc_acknowledgment','idoc_confirmation','idoc_converter','idoc_listener','idoc_parser','idoc_reader','post_idoc','idoc_renderer','rfc_bapi_listener','invoke_rfc_bapi','reply_rfc_bapi','read_table']
        resource = SharedResource(id='sap-ecc', type='sap', name='ECC', config={'mode':'mock'})
        runtime = WorkflowRuntime()
        for operation in operations:
            process = ProcessDefinition(id=operation, name=operation, activities=[
                Activity(id='start',type='start',name='Start'),
                Activity(id='sap',type='sap',name=operation,config={'operation':operation,'resourceId':'sap-ecc','functionName':'BAPI_TEST','tableName':'T000'}),
                Activity(id='end',type='end',name='End')], transitions=[
                {'id':'a','source':'start','target':'sap'}, {'id':'b','source':'sap','target':'end'}])
            result = asyncio.run(runtime.run(process, {'rawIDoc':'EDI_DC40\nE1TEST'}, {'sap-ecc':resource}))
            self.assertEqual(result.status, 'completed', operation)

    def test_sap_connection_design_time_test(self):
        result = self.client.post('/api/connections/test',json={'id':'sap','type':'sap','name':'ECC','config':{'mode':'mock'}})
        self.assertTrue(result.json()['ok'])

    def test_sap_connection_can_browse_and_download_idoc_metadata(self):
        resource = {'id':'sap','type':'sap','name':'ECC','config':{'mode':'mock','release':'720'}}
        listed = self.client.post('/api/sap/idocs', json={'resource':resource, 'search':'ORDER'})
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(item['idocType'] == 'ORDERS05' for item in listed.json()['idocs']))
        self.assertTrue(all(item['release'] == '720' for item in listed.json()['idocs']))
        fetched = self.client.post('/api/sap/idocs', json={'resource':resource, 'idocType':'ORDERS05'})
        self.assertEqual(fetched.status_code, 200)
        metadata = fetched.json()['idoc']
        self.assertEqual(metadata['idocType'], 'ORDERS05')
        self.assertEqual(metadata['release'], '720')
        self.assertIn('schema', metadata)
        self.assertIn('EDI_DC40', metadata['schema'])
        self.assertIn('release 720', metadata['schema'])

        resource['config']['release'] = '730'
        fetched_730 = self.client.post('/api/sap/idocs', json={'resource':resource, 'idocType':'ORDERS05'})
        self.assertEqual(fetched_730.json()['idoc']['release'], '730')

    def test_project_seeds_global_advanced_and_connector_properties(self):
        project = Project(id='defaults', name='Defaults')
        for environment in ('local','dev','qa','pre','production'):
            values = {item.key:item.value for item in project.properties[environment]}
            self.assertEqual(values['advanced.retryCount'], 3)
            self.assertEqual(values['advanced.retryIntervalSeconds'], 60)
            self.assertIn('connections.sap.applicationServerHost', values)
            for required in (
                'connections.jdbc.driver', 'connections.jdbc.url', 'connections.jdbc.host',
                'connections.jdbc.username', 'connections.jdbc.password', 'connections.ftp.username',
                'connections.sftp.privateKeyFile', 'connections.http.proxyHost', 'connections.ems.clientId',
                'connections.kafka.securityProtocol', 'connections.pubsub.credentialsFile',
                'connections.pubsub.authenticationType', 'connections.pubsub.serviceAccountJson',
                'connections.sap.client', 'connections.sap.username', 'connections.sap.password',
            ):
                self.assertIn(required, values)

    def test_advanced_logging_and_property_driven_outbound_retry(self):
        class FlakyRuntime(WorkflowRuntime):
            def __init__(self): super().__init__(); self.calls = 0
            async def execute(self, activity, ctx):
                if activity.id == 'outbound':
                    self.calls += 1
                    if self.calls < 3: raise RuntimeError('temporary target failure')
                    return {'sent':True,'payload':ctx['last']}
                return await super().execute(activity, ctx)
        runtime = FlakyRuntime()
        process = ProcessDefinition(id='advanced',name='Advanced',activities=[
            Activity(id='start',type='start',name='Start'),
            Activity(id='outbound',type='http',name='Target Call',config={'operation':'request','advanced':{
                'logPayload':'${properties.advanced.logPayload}','retryEnabled':'${properties.advanced.retryEnabled}',
                'retryCount':'${properties.advanced.retryCount}','retryIntervalSeconds':0}}),
            Activity(id='end',type='end',name='End')],transitions=[
                {'id':'a','source':'start','target':'outbound'},{'id':'b','source':'outbound','target':'end'}])
        result = asyncio.run(runtime.run(process, {'id':42}, properties={
            'advanced.logPayload':True,'advanced.retryEnabled':True,'advanced.retryCount':2}))
        self.assertEqual(result.status, 'completed')
        self.assertEqual(runtime.calls, 3)
        self.assertTrue(any('input payload' in item['message'] for item in result.logs))
        self.assertEqual(sum('retry' in item['message'] for item in result.logs), 2)

    def test_mapper_ai_understands_xsd_attributes_and_repeating_cardinality(self):
        xsd = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="catalog"><xs:complexType><xs:sequence><xs:element name="book" maxOccurs="unbounded"><xs:complexType><xs:sequence><xs:element name="title" type="xs:string"/></xs:sequence><xs:attribute name="id" type="xs:string"/></xs:complexType></xs:element></xs:sequence></xs:complexType></xs:element></xs:schema>'''
        response = self.client.post('/api/mapper/suggest', json={'sourceSchema':xsd, 'targetSchema':xsd, 'threshold':50})
        self.assertEqual(response.status_code, 200, response.text)
        recommendations = response.json()['recommendations']
        self.assertTrue(any(item['target'].endswith('book.title') and item['sourceRepeating'] for item in recommendations))
        self.assertTrue(any(item['target'].endswith('book.@id') for item in recommendations))
        generated = self.client.post('/api/dataweave/generate', json={'sourceSchema':xsd, 'targetSchema':xsd, 'threshold':50})
        self.assertEqual(generated.status_code, 200, generated.text)
        tested = self.client.post('/api/dataweave/test', json={'script':generated.json()['script'], 'input':{'catalog':{'book':[{'title':'A','@id':'1'},{'title':'B','@id':'2'}]}}})
        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertEqual(len(tested.json()['output']['catalog']['book']), 2)

    def test_mapper_choose_executes_multiple_when_branches_and_otherwise(self):
        rules = [{'target':'route', 'operator':'choose', 'whens':[
            {'condition':'amount >= 1000', 'source':'"priority"'},
            {'condition':'amount >= 100', 'source':'"standard"'},
        ], 'otherwise':'"economy"'}]
        high = self.client.post('/api/mapper/test', json={'input':{'amount':1500}, 'mappings':rules})
        medium = self.client.post('/api/mapper/test', json={'input':{'amount':250}, 'mappings':rules})
        low = self.client.post('/api/mapper/test', json={'input':{'amount':25}, 'mappings':rules})
        self.assertEqual(high.json()['output']['route'], 'priority')
        self.assertEqual(medium.json()['output']['route'], 'standard')
        self.assertEqual(low.json()['output']['route'], 'economy')

if __name__ == '__main__': unittest.main()
