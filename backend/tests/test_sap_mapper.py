import asyncio, unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import Activity, ProcessDefinition, Project, SharedResource
from app.runtime import WorkflowRuntime
from app.sap import SapAdapter

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

    def test_mapper_function_catalog_executes_string_date_number_collection_and_encoding(self):
        tested = self.client.post('/api/mapper/test', json={
            'input': {
                'name':'  customer  ', 'created':'2026-01-30', 'amount':'42.567',
                'tags':['a','b','a'], 'empty':'', 'plain':'hello',
            },
            'mappings': [
                {'source':'name', 'target':'result.name', 'functions':['trim','upperCase', {'name':'replace','args':['CUSTOMER','ACCOUNT']}]},
                {'source':'created', 'target':'result.deliveryDate', 'functions':[{'name':'addDays','args':[2]}, {'name':'formatDate','args':['yyyy-MM-dd']}]},
                {'source':'amount', 'target':'result.amount', 'functions':['number', {'name':'round','args':[2]}]},
                {'source':'tags', 'target':'result.tags', 'functions':['distinctValues','reverse']},
                {'source':'empty', 'target':'result.fallback', 'functions':[{'name':'default','args':['UNKNOWN']}]},
                {'source':'plain', 'target':'result.encoded', 'functions':['base64Encode']},
                {'source':'upperCase(trim(name))', 'target':'result.expression'},
            ],
        })
        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertEqual(tested.json()['output'], {'result': {
            'name':'ACCOUNT', 'deliveryDate':'2026-02-01', 'amount':42.57,
            'tags':['b','a'], 'fallback':'UNKNOWN', 'encoded':'aGVsbG8=', 'expression':'CUSTOMER',
        }})
        runtime = WorkflowRuntime()
        context = {'input':{}, 'last':{}, 'vars':{}, 'resources':{}, 'properties':{}}
        self.assertEqual(runtime.resolve('formatDate(addDays("2026-01-30", 2), "yyyy-MM-dd")', context), '2026-02-01')
        self.assertEqual(runtime.resolve('padLeft("42", 5, "0")', context), '00042')

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

    def test_idoc_response_extracts_control_and_data_rfc_tables(self):
        control = {'DOCNUM':'0000000000000042', 'IDOCTYP':'ORDERS05'}
        data = [{'DOCNUM':'0000000000000042', 'SEGNAM':'E1EDK01', 'SDATA':'value'}]
        extracted_control, extracted_data = SapAdapter._idoc_response_parts({'tables': {
            'IDOC_CONTROL_REC_40':[control], 'IDOC_DATA_REC_40':data,
        }})
        self.assertEqual(extracted_control, control)
        self.assertEqual(extracted_data, data)

    def test_idoc_parser_rejects_malformed_xml_and_wrong_basic_type(self):
        adapter = SapAdapter()
        with self.assertRaisesRegex(RuntimeError, 'Malformed SAP IDoc XML'):
            adapter.execute('idoc_parser', {'mode':'mock', 'idocType':'ORDERS05'}, '<ORDERS05><IDOC>')
        wrong = '<MATMAS05><IDOC><EDI_DC40><IDOCTYP>MATMAS05</IDOCTYP></EDI_DC40></IDOC></MATMAS05>'
        with self.assertRaisesRegex(RuntimeError, 'parser expects ORDERS05'):
            adapter.execute('idoc_parser', {'mode':'mock', 'idocType':'ORDERS05'}, wrong)

    def test_sap_idoc_transaction_contract_selects_tids_and_bounded_listener_settings(self):
        adapter = SapAdapter()
        values = adapter._listener_values({'mode':'mock', 'programId':'FABRIC_IDOC', 'gatewayHost':'sapqa2', 'gatewayService':'sapgw00', 'maximumConnections':12, 'ackTimeoutSeconds':420})
        self.assertEqual(values['jco.server.connection_count'], 12)
        self.assertEqual(values['jco.server.ack_timeout_seconds'], 420)
        self.assertEqual(values['jco.server.tid_management'], 'active')

        with patch('app.sap.invoke_java', return_value={'ok':True}) as invoke:
            adapter._jco_call({'mode':'mock', 'transactional':True, 'transactionProtocol':'qRFC', 'queueName':'ARTMAS_QUEUE'}, 'IDOC_INBOUND_ASYNCHRONOUS')
        sent = invoke.call_args.args[2]
        self.assertEqual(sent['transactional'], 'true')
        self.assertEqual(sent['transactionProtocol'], 'qrfc')
        self.assertEqual(sent['queueName'], 'ARTMAS_QUEUE')

        with patch('app.sap.invoke_java', return_value={'exports':{}, 'committed':True}) as invoke:
            result = adapter._jco_call({'mode':'mock', 'transactional':True, 'transactionProtocol':'Request/Reply', 'autoCommit':True}, 'BAPI_SALESORDER_CREATEFROMDAT2')
        sent = invoke.call_args.args[2]
        self.assertEqual(sent['transactionProtocol'].lower(), 'request/reply')
        self.assertEqual(sent['transactional'], 'true')
        self.assertEqual(sent['autoCommit'], 'true')
        self.assertTrue(result['committed'])

    def test_rfc_bapi_listener_and_reply_are_executable_runtime_contracts(self):
        adapter = SapAdapter()
        received = asyncio.run(adapter.receive_idoc({
            'mode':'mock', 'operation':'rfc_bapi_listener', 'functionName':'Z_GET_ORDER',
            'invocationProtocol':'Request/Reply', 'mockInput':{'imports':{'ORDER_ID':'42'}, 'tables':{}},
        }))
        self.assertEqual(received['functionName'], 'Z_GET_ORDER')
        self.assertEqual(received['RfcRequest']['imports']['ORDER_ID'], '42')

        runtime = WorkflowRuntime()
        resource = SharedResource(id='sap-ecc', type='sap', name='ECC', config={'mode':'external'})
        context = {
            'input':{}, 'last':{'exports':{'STATUS':'OK'}, 'tables':{'MESSAGES':[{'TYPE':'S'}]}},
            'vars':{}, 'resources':{'sap-ecc':resource}, 'properties':{}, 'activities':{}, 'tasks':{},
            'context':{'taskId':'main'}, 'logs':[],
            'transport':{'listenerKey':'server|z_get_order', 'deliveryId':'delivery-1', 'functionName':'Z_GET_ORDER'},
        }
        with patch('app.runtime.sap_adapter.acknowledge_idoc') as reply:
            result = asyncio.run(runtime.execute(Activity(id='reply', type='sap', name='Reply', config={
                'operation':'reply_rfc_bapi', 'resourceId':'sap-ecc',
            }), context))
        self.assertTrue(result['replied'])
        reply.assert_called_once_with('server|z_get_order', 'delivery-1', True, context['last'])
        self.assertTrue(context['transport']['completed'])

    def test_sap_rfc_complex_parameters_are_flattened_without_python_repr(self):
        adapter = SapAdapter()
        config = {'mode':'mock', 'transactionProtocol':'sRFC'}
        with patch('app.sap.invoke_java', return_value={'ok':True}) as invoke:
            adapter._jco_call(config, 'Z_COMPLEX', {
                'HEADER': {'ORDER_ID':'42', 'CUSTOMER':{'ID':'C1'}},
            }, {'ITEMS':[{'POS':'10', 'MATERIAL':'A'}]}, {'STATE':{'CODE':'NEW'}})
        values = invoke.call_args.args[2]
        self.assertEqual(values['argument.HEADER.ORDER_ID'], '42')
        self.assertEqual(values['argument.HEADER.CUSTOMER.ID'], 'C1')
        self.assertEqual(values['changing.STATE.CODE'], 'NEW')
        self.assertEqual(values['tableArg.ITEMS.0.MATERIAL'], 'A')
        self.assertNotIn("{'ORDER_ID'", str(values))

    def test_post_idoc_uses_standard_control_and_data_tables(self):
        adapter = SapAdapter()
        payload = {
            'control': {'TABNAM':'EDI_DC40', 'IDOCTYP':'ORDERS05', 'MESTYP':'ORDERS'},
            'data': [{'SEGNAM':'E1EDK01', 'SEGNUM':'1', 'PSGNUM':'0', 'SDATA':'0001'}],
        }
        with patch.object(adapter, '_jco_call', return_value={'TID':'T1'}) as call:
            result = adapter.execute('post_idoc', {
                'mode':'external', 'idocType':'ORDERS05', 'idocInputMode':'tRFC',
            }, payload)
        self.assertEqual(result['TID'], 'T1')
        config, function, arguments, tables, changing = call.call_args.args
        self.assertEqual(function, 'IDOC_INBOUND_ASYNCHRONOUS')
        self.assertEqual(config['transactionProtocol'], 'trfc')
        self.assertEqual(arguments, {})
        self.assertEqual(tables['IDOC_CONTROL_REC_40'][0]['IDOCTYP'], 'ORDERS05')
        self.assertEqual(tables['IDOC_DATA_REC_40'][0]['SEGNAM'], 'E1EDK01')
        self.assertEqual(changing, {})

    def test_dynamic_sap_sessions_expire_and_are_bounded(self):
        adapter = SapAdapter()
        created = adapter.execute('dynamic_connection', {'mode':'mock', 'maximumDynamicSessions':1, 'timeout':60000}, {})
        with self.assertRaisesRegex(RuntimeError, 'limit'):
            adapter.execute('dynamic_connection', {'mode':'mock', 'maximumDynamicSessions':1, 'timeout':60000}, {})
        terminated = adapter.execute('dynamic_connection', {'mode':'mock', 'sessionID':created['sessionID'], 'terminateConnection':True}, {})
        self.assertTrue(terminated['terminated'])
        self.assertFalse(adapter.sessions)

    def test_read_table_publishes_named_rows(self):
        adapter = SapAdapter()
        response = {'tables': {
            'FIELDS':[{'FIELDNAME':'MANDT'}, {'FIELDNAME':'MTEXT'}],
            'DATA':[{'WA':'100|Production'}, {'WA':'200|Quality'}],
        }}
        with patch.object(adapter, '_jco_call', return_value=response):
            result = adapter.execute('read_table', {'mode':'external', 'tableName':'T000', 'fields':'MANDT,MTEXT'}, {})
        self.assertEqual(result['rows'][0], {'MANDT':'100', 'MTEXT':'Production'})
        self.assertEqual(result['rowCount'], 2)

    def test_idoc_parser_decodes_physical_segments_to_named_bounded_fields(self):
        adapter = SapAdapter()
        selected = {
            'idocType': 'ARTMAS05',
            'segments': [{'SEGMENTTYP': 'E1BPE1MATHEAD', 'SEGMENTDEF': 'E2BPE1MATHEAD002', 'SEGLEN': '24'}],
            'fields': [
                {'SEGMENTTYP': 'E1BPE1MATHEAD', 'FIELDNAME': 'FUNCTION', 'BYTE_FIRST': '000064', 'BYTE_LAST': '000066', 'INTLEN': '000003'},
                {'SEGMENTTYP': 'E1BPE1MATHEAD', 'FIELDNAME': 'MATERIAL', 'BYTE_FIRST': '000067', 'BYTE_LAST': '000084', 'INTLEN': '000018'},
            ],
        }
        # The physical E2 name is what SAP supplies in the row; the output
        # must use the logical E1 name and must not retain SDATA.
        raw = {'E2BPE1MATHEAD002': {'SDATA': '005' + '5370119HAWA'.ljust(18) + 'ignored-overflow-data', '_attributes': {'SEGMENT': '1'}}}
        result = adapter.execute('idoc_parser', {'idocType': 'ARTMAS05', 'selectedIdoc': selected, 'idocOutputMode': 'JSON'}, raw)
        self.assertEqual(result['SAPIDoc']['E1BPE1MATHEAD']['FUNCTION'], '005')
        self.assertEqual(result['SAPIDoc']['E1BPE1MATHEAD']['MATERIAL'], '5370119HAWA')
        self.assertNotIn('SDATA', str(result['SAPIDoc']))

        rendered = adapter.execute('idoc_renderer', {'idocType': 'ARTMAS05', 'selectedIdoc': selected}, result['SAPIDoc'])
        row = rendered['rawIDoc']['data'][0]
        self.assertEqual(row['SEGNAM'], 'E2BPE1MATHEAD002')
        self.assertEqual(len(row['SDATA']), 24)
        self.assertEqual(row['SDATA'][:3], '005')
        self.assertEqual(row['SDATA'][3:21], '5370119HAWA'.ljust(18))

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
