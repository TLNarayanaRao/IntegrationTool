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

    def test_transform_accepts_typed_constants_and_dynamic_tree_mappings(self):
        runtime = WorkflowRuntime()
        context = {'input': {'order': {'id': 42}}, 'last': {'status': 'NEW'}, 'vars': {}, 'resources': {}, 'properties': {}, 'activities': {'source': {'output': {'amount': 19.5}}}}
        activity = Activity(id='map', type='transform', name='Transform', config={'mappings':[
            {'target':'order.id', 'source':'${input.order.id}', 'enabled':True},
            {'target':'order.amount', 'source':'${activities.source.output.amount}', 'enabled':True},
            {'target':'order.active', 'constant':True, 'enabled':True},
            {'target':'order.tags', 'constant':['priority', 'new'], 'enabled':True},
        ]})
        result = asyncio.run(runtime.execute(activity, context))
        self.assertEqual(result, {'order': {'id':42, 'amount':19.5, 'active':True, 'tags':['priority', 'new']}})

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

if __name__ == '__main__': unittest.main()
