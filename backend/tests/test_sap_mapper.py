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
