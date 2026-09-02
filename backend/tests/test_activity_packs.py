import asyncio
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, runtime
from app.models import Activity, EnvironmentProperty, ProcessDefinition, Project, SchemaAsset, SharedResource, Transition
from app.runtime import WorkflowRuntime


class ActivityPackTests(unittest.TestCase):
    def setUp(self):
        self.runtime = WorkflowRuntime()

    def execute(self, activity, payload):
        context = {'input': payload, 'last': payload, 'vars': {}, 'resources': {}, 'properties': {}}
        return asyncio.run(self.runtime.execute(activity, context))

    def test_ems_queue_receiver_deploys_continuously_and_starts_each_event_automatically(self):
        project_id = f'ems-listener-{uuid.uuid4()}'
        project = Project(
            id=project_id, name='EMS Continuous Listener',
            resources=[SharedResource(id='ems', type='ems', name='Local EMS', config={'mode':'memory'})],
            process=ProcessDefinition(activities=[
                Activity(id='receive', type='ems', name='EMS Queue Receiver', config={'operation':'queue_receiver', 'resourceId':'ems', 'queue':'orders'}),
                Activity(id='end', type='end', name='End'),
            ], transitions=[Transition(id='success', source='receive', target='end')]),
        )
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/projects', json=project.model_dump(mode='json')).status_code, 200)
            deployed = client.post(f'/api/projects/{project_id}/run', json={'environment':'local'}).json()
            self.assertEqual(deployed['status'], 'listening')
            self.assertEqual(deployed['endpoints'][0]['kind'], 'subscription')
            for order_id in (101, 102):
                context = {'input': {}, 'last': {'orderId':order_id}, 'vars': {}, 'resources': {'ems':project.resources[0]}, 'properties': {}}
                asyncio.run(runtime.execute(Activity(id='send', type='ems', name='Send', config={'operation':'send', 'resourceId':'ems', 'queue':'orders', 'message':'${last}'}), context))
                deadline = time.time() + 3
                while time.time() < deadline:
                    state = client.get(f'/api/projects/{project_id}/runtime-state').json()
                    if len(state.get('executions', [])) >= order_id - 100: break
                    time.sleep(.05)
                self.assertGreaterEqual(len(state.get('executions', [])), order_id - 100)
                self.assertEqual(state['activityOutputs']['receive']['output']['body']['orderId'], order_id)
                self.assertEqual(state['status'], 'listening')
            stopped = client.post(f'/api/projects/{project_id}/stop').json()
            self.assertEqual(stopped['status'], 'stopped')
            debug = client.post(f'/api/projects/{project_id}/debug', json={'environment':'local', 'breakpoints':[]}).json()
            self.assertEqual(debug['status'], 'listening')
            session_id = debug['sessionId']
            context = {'input': {}, 'last': {'orderId':103}, 'vars': {}, 'resources': {'ems':project.resources[0]}, 'properties': {}}
            asyncio.run(runtime.execute(Activity(id='send-debug', type='ems', name='Send', config={'operation':'send', 'resourceId':'ems', 'queue':'orders', 'message':'${last}'}), context))
            deadline = time.time() + 3
            while time.time() < deadline:
                debug_state = client.get(f'/api/debug/{session_id}').json()
                received = debug_state.get('activityOutputs', {}).get('receive', {}).get('output', {})
                if received.get('body', {}).get('orderId') == 103: break
                time.sleep(.05)
            self.assertEqual(received['body']['orderId'], 103)
            self.assertEqual(debug_state['status'], 'listening')
            client.post(f'/api/debug/{session_id}/action', json={'action':'stop'})
            client.delete(f'/api/projects/{project_id}')

    def test_ems_connection_requires_only_direct_fields_and_completes(self):
        client = TestClient(app)
        missing = client.post('/api/connections/test', json={'id':'ems','type':'ems','name':'EMS','config':{'serverUrl':'tcp://ems:7222'}}).json()
        self.assertFalse(missing['ok'])
        self.assertIn('Username', missing['message'])
        with patch('app.main.test_jms', return_value={'ok':True, 'message':'Native JMS connection succeeded', 'loadedJars':['tibjms.jar']} ) as bridge:
            response = client.post('/api/connections/test', json={'id':'ems','type':'ems','name':'EMS','config':{'serverUrl':'tcp://ems.example:7222','username':'admin','password':'secret','connectionTimeoutSeconds':3}})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        bridge.assert_called_once()
        self.assertEqual(bridge.call_args.args[0]['serverUrl'], 'tcp://ems.example:7222')
        self.assertEqual(response.json()['loadedJars'], ['tibjms.jar'])

    def test_ems_jndi_fields_are_conditional_requirements(self):
        response = TestClient(app).post('/api/connections/test', json={'id':'ems','type':'ems','name':'EMS','config':{
            'serverUrl':'tcp://ems:7222','username':'admin','password':'secret','connectionFactoryType':'JNDI',
        }}).json()
        self.assertFalse(response['ok'])
        self.assertIn('JNDI context factory', response['message'])
        self.assertIn('JNDI provider URL', response['message'])

    def test_xml_parse_and_render(self):
        parsed = self.execute(Activity(id='x', type='xml', name='Parse XML', config={'operation': 'parse'}), '<order id="7"><name>Ada</name></order>')
        self.assertEqual(parsed['root'], 'order')
        self.assertEqual(parsed['value']['@id'], '7')
        self.assertEqual(parsed['mediaType'], 'application/xml')
        self.assertEqual(parsed['xml'], '<order id="7"><name>Ada</name></order>')
        debug_context = {'activities': {}, 'context': {}}
        self.runtime.record_activity_output(Activity(id='x', type='xml', name='Parse XML', config={'operation': 'parse'}), parsed, debug_context)
        self.assertEqual(debug_context['activities']['x']['displayOutput'], parsed['xml'])
        rendered = self.execute(Activity(id='x', type='xml', name='Render XML', config={'operation': 'render'}), parsed)
        self.assertIn('<name>Ada</name>', rendered['content'])

    def test_json_parse_and_render(self):
        parsed = self.execute(Activity(id='j', type='json', name='Parse JSON', config={'operation': 'parse'}), '{"id":7}')
        self.assertEqual(parsed, {'id': 7})
        rendered = self.execute(Activity(id='j', type='json', name='Render JSON', config={'operation': 'render'}), parsed)
        self.assertEqual(__import__('json').loads(rendered['content']), {'id': 7})

    def test_schema_editor_contracts_drive_parse_render_and_flat_data(self):
        xsd = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="catalog"><xs:complexType><xs:sequence><xs:element name="book"><xs:complexType><xs:sequence><xs:element name="price" type="xs:decimal"/></xs:sequence><xs:attribute name="id" type="xs:string"/></xs:complexType></xs:element></xs:sequence></xs:complexType></xs:element></xs:schema>'''
        parsed = self.execute(Activity(id='px', type='xml', name='Parse XML', config={
            'operation': 'parse', 'schemaText': xsd, 'validateOutput': True, 'xmlString': '<catalog><book id="bk101"><price>44.95</price></book></catalog>'
        }), {})
        self.assertEqual(parsed['catalog']['book']['@id'], 'bk101')
        rendered = self.execute(Activity(id='rx', type='xml', name='Render XML', config={
            'operation': 'render', 'schemaText': xsd, 'catalog': {'book': {'@id': 'bk102', 'price': 10.5}}
        }), {})
        self.assertIn('<catalog>', rendered['xmlString'])
        self.assertIn('id="bk102"', rendered['xmlString'])
        json_rendered = self.execute(Activity(id='rj', type='json', name='Render JSON', config={
            'operation': 'render', 'schemaText': xsd, 'catalog': {'book': {'id': 'bk103', 'price': 12.5}}, 'rootStyle': 'With root'
        }), {})
        self.assertEqual(__import__('json').loads(json_rendered['jsonString'])['catalog']['book']['id'], 'bk103')
        flat_xsd = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="record"><xs:complexType><xs:sequence><xs:element name="id" type="xs:integer"/><xs:element name="price" type="xs:decimal"/><xs:element name="active" type="xs:boolean"/></xs:sequence></xs:complexType></xs:element></xs:schema>'''
        flat = self.execute(Activity(id='pd', type='flat', name='Parse Data', config={
            'operation': 'parse', 'schemaText': flat_xsd, 'text': '1,44.95,true', 'header': False, 'delimiter': ','
        }), {})
        self.assertEqual(flat['records'][0], {'id': 1, 'price': 44.95, 'active': True})

    def test_designer_input_mapping_and_error_policy(self):
        context = {'input': {'payload': {'id': 9}}, 'last': {}, 'vars': {}, 'resources': {}, 'properties': {}}
        activity = Activity(id='j', type='json', name='Render mapped JSON', config={
            'operation': 'render', 'inputMappings': {'source': '${input.payload}'}, 'outputName': 'rendered'
        })
        rendered = asyncio.run(self.runtime.execute_with_policy(activity, context))
        self.assertEqual(__import__('json').loads(rendered['content']), {'id': 9})
        self.assertEqual(context['vars']['rendered'], rendered)
        fault_context = {'input': {}, 'last': {'id': 9}, 'vars': {}, 'resources': {}, 'properties': {}}
        faulting = Activity(id='file', type='file', name='Missing file', config={
            'operation': 'read', 'path': 'definitely-missing.file',
            'errorPolicy': {'action': 'continue', 'outputVariable': 'activityError', 'includeInput': True}
        })
        fault = asyncio.run(self.runtime.execute_with_policy(faulting, fault_context))
        self.assertEqual(fault['activityId'], 'file')
        self.assertEqual(fault_context['vars']['activityError'], fault)

    def test_delimited_and_fixed_width_data(self):
        csv_result = self.execute(Activity(id='f', type='flat', name='Parse Data', config={'operation': 'parse', 'delimiter': ',', 'header': True}), 'id,name\n7,Ada\n')
        self.assertEqual(csv_result['records'][0]['name'], 'Ada')
        self.assertEqual(csv_result['mediaType'], 'application/xml')
        self.assertEqual(csv_result['xml'], '<records><record><id>7</id><name>Ada</name></record></records>')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'orders.csv'
            path.write_text('id,name\n8,Grace\n', encoding='utf-8')
            file_result = self.execute(Activity(id='fp', type='flat', name='Parse Data File', config={
                'operation': 'parse', 'inputSource': 'File path', 'filePath': str(path),
                'fileEncoding': 'utf-8', 'delimiter': ',', 'header': True,
                'rootElement': 'orders', 'recordElement': 'order',
            }), {})
            self.assertEqual(file_result['records'][0]['name'], 'Grace')
            self.assertEqual(file_result['xml'], '<orders><order><id>8</id><name>Grace</name></order></orders>')
        fixed = self.execute(Activity(id='f', type='flat', name='Render Data', config={'operation': 'render', 'format': 'fixed', 'fields': 'id,name', 'widths': '3,5'}), {'records': [{'id': 7, 'name': 'Ada'}]})
        self.assertEqual(fixed['content'], '7  Ada  ')

    def test_listener_response_and_conditional_transition(self):
        process = ProcessDefinition(activities=[
            Activity(id='listen', type='http_listener', name='Listener', config={'operation': 'listen'}),
            Activity(id='reply', type='http_response', name='Reply', config={'operation': 'response', 'statusCode': 201, 'body': '${last}'})
        ], transitions=[Transition(id='t', source='listen', target='reply', type='success_condition', condition='${last.method} == "POST"')])
        result = asyncio.run(self.runtime.run(process, {'method': 'POST', 'body': {'id': 7}}, entry_activity_id='listen'))
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.output['statusCode'], 201)

    def test_condition_functions_and_single_event_invariant(self):
        context = {'last': {'status': 'READY', 'amount': 12}, 'input': {}, 'vars': {}, 'properties': {}}
        self.assertTrue(self.runtime.condition('contains(${last.status}, "EAD") and ${last.amount} > 0', context))
        self.assertTrue(self.runtime.condition('exists(${last.status}) and not(empty(${last.status}))', context))
        with self.assertRaises(ValueError):
            ProcessDefinition(activities=[
                Activity(id='timer', type='timer', name='Timer', config={'operation': 'schedule'}),
                Activity(id='poller', type='file', name='File Poller', config={'operation': 'poll'}),
            ])

    def test_rest_listener_endpoint_with_path_parameters(self):
        project = Project(id='listener-test', name='Listener Test', properties={'dev': [EnvironmentProperty(key='status', value=202, data_type='number')]}, process=ProcessDefinition(activities=[
            Activity(id='receive', type='rest', name='Receive', config={'operation': 'receiver', 'path': '/orders/{id}', 'methods': 'POST'}),
            Activity(id='reply', type='http_response', name='Reply', config={'operation': 'response', 'statusCode': '${properties.status}', 'body': '${last}'})
        ], transitions=[Transition(id='t', source='receive', target='reply')]))
        with patch('app.main.get_project', return_value=project):
            response = TestClient(app).post('/api/listeners/listener-test/orders/42?environment=dev', json={'name': 'Ada'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['pathParameters']['id'], '42')

    def test_rest_receiver_supports_all_standard_http_methods(self):
        methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE', 'CONNECT']
        project = Project(id='all-methods', name='All Methods', process=ProcessDefinition(activities=[
            Activity(id='receive', type='rest', name='Receive', config={
                'operation': 'receiver', 'path': '/universal', 'methods': ','.join(methods),
            }),
            Activity(id='end', type='end', name='End'),
        ], transitions=[Transition(id='t', source='receive', target='end')]))
        with patch('app.main.get_project', return_value=project):
            client = TestClient(app)
            responses = {
                method: client.request(method, '/api/listeners/all-methods/universal', json={'method': method})
                for method in methods
            }
        self.assertEqual({method: response.status_code for method, response in responses.items()}, {method: 200 for method in methods})

    def test_run_deploys_inbound_listener_and_returns_live_endpoint(self):
        project = Project(
            id='listener-deploy', name='Listener Deployment',
            resources=[SharedResource(id='http-server', type='http', name='HTTPS Server', config={
                'host': 'api.internal.example', 'port': 8443, 'tlsEnabled': True,
                'authentication': 'Certificate', 'basePath': '/services',
            })],
            process=ProcessDefinition(activities=[
                Activity(id='receive', type='http_listener', name='Orders Listener', config={
                    'operation': 'listen', 'path': '/orders', 'method': 'POST', 'resourceId': 'http-server',
                }),
                Activity(id='end', type='end', name='End'),
            ], transitions=[Transition(id='t', source='receive', target='end')]),
        )
        with patch('app.main.get_project', return_value=project):
            client = TestClient(app)
            response = client.post('/api/projects/listener-deploy/run', json={'environment': 'local'})
            invocation = client.post('/api/listeners/listener-deploy/orders', json={'orderId': '10001'})
            runtime_state = client.get('/api/projects/listener-deploy/runtime-state').json()
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['status'], 'listening')
        self.assertEqual(result['endpoints'][0]['url'], 'http://testserver/api/listeners/listener-deploy/orders')
        self.assertEqual(result['endpoints'][0]['configuredUrl'], 'https://api.internal.example:8443/services/orders')
        self.assertIn('Application Listener Deployment started', [entry['message'] for entry in result['logs']])
        self.assertEqual(invocation.status_code, 200)
        self.assertEqual(runtime_state['status'], 'listening')
        self.assertEqual(runtime_state['lastExecution']['status'], 'completed')
        uuid.UUID(runtime_state['lastExecution']['correlationId'])
        self.assertIn('receive', runtime_state['activityOutputs'])
        self.assertGreaterEqual(runtime_state['lastExecution']['durationMs'], 0)
        self.assertTrue(any('Job started' in entry['message'] for entry in runtime_state['logs']))
        self.assertTrue(any('Job completed' in entry['message'] for entry in runtime_state['logs']))

    def test_project_persists_packaging_and_xsd_schemas(self):
        project = Project(
            id='schema-test', name='Schema Test',
            packaging={'artifact_name': 'schema-test', 'version': '2.1.0', 'format': 'zip'},
            schemas=[SchemaAsset(id='customer', name='Customer.xsd', content='<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>')],
            process=ProcessDefinition(),
        )
        restored = Project.model_validate_json(project.model_dump_json())
        self.assertEqual(restored.packaging['version'], '2.1.0')
        self.assertEqual(restored.schemas[0].name, 'Customer.xsd')
        typed = EnvironmentProperty(key='timeout', value='30', data_type='integer')
        self.assertEqual(typed.value, 30)

    def test_universal_confirm_acknowledges_client_managed_messages(self):
        cases = (
            ('ems', {'operation': 'queue_receiver', 'queue': 'orders', 'acknowledgeMode': 'Client'}),
            ('kafka', {'operation': 'receive', 'topic': 'orders', 'acknowledgeMode': 'Manual'}),
            ('pubsub', {'operation': 'subscribe', 'subscription': 'orders', 'acknowledgeMode': 'Client'}),
        )
        for technology, receive_config in cases:
            with self.subTest(technology=technology):
                resource = SharedResource(id=f'{technology}-connection', type=technology, name=technology, config={'mode': 'memory'})
                context = {'input': {'id': 42}, 'last': {'id': 42}, 'vars': {}, 'resources': {resource.id: resource}, 'properties': {}}
                destination_key = 'queue' if technology == 'ems' else ('topic' if technology == 'kafka' else 'topic')
                destination = 'orders' if technology != 'pubsub' else 'orders-topic'
                send = Activity(id='send', type=technology, name='Send', config={
                    'operation': 'publish', 'resourceId': resource.id, destination_key: destination,
                })
                asyncio.run(self.runtime.execute(send, context))
                if technology == 'pubsub':
                    receive_config = {**receive_config, 'subscription': destination}
                receive = Activity(id='receive', type=technology, name='Receive', config={**receive_config, 'resourceId': resource.id})
                received = asyncio.run(self.runtime.execute(receive, context))
                ack_id = received.get('ackId') or received.get('AckID')
                self.assertIn(ack_id, self.runtime.acknowledgements)
                context['last'] = received
                confirmed = asyncio.run(self.runtime.execute(Activity(
                    id='confirm', type='confirm', name='Confirm Message',
                    config={'ackId': '${last.ackId}', 'failIfMissing': True},
                ), context))
                self.assertTrue(confirmed['confirmed'])
                self.assertEqual(confirmed['technologies'], [technology])
                self.assertNotIn(ack_id, self.runtime.acknowledgements)

    def test_native_ems_receiver_resolves_property_configuration_and_exposes_confirm_handle(self):
        resource = SharedResource(id='ems-native', type='ems', name='EMS', config={
            'serverUrl':'tcp://ems.example:7222', 'username':'admin', 'password':'secret',
        })
        context = {
            'input': {}, 'last': {}, 'vars': {}, 'resources': {resource.id: resource},
            'properties': {
                'connections.ems.destination':'orders.dev', 'connections.ems.sessionCount':3,
                'connections.ems.flowLimit':25, 'connections.ems.receiveTimeoutMs':4500,
            },
        }
        bridge_output = {
            'received': True, 'body': '{"orderId":42}',
            'headers': {'JMSMessageID':'ID:orders-42'}, 'properties': {'source':'test'},
        }
        receiver = Activity(id='receive', type='ems', name='EMS Queue Receiver', config={
            'operation':'queue_receiver', 'resourceId':resource.id,
            'queue':'${properties.connections.ems.destination}',
            'maxSessions':'${properties.connections.ems.sessionCount}',
            'flowLimit':'${properties.connections.ems.flowLimit}',
            'receiveTimeout':'${properties.connections.ems.receiveTimeoutMs}',
            'acknowledgeMode':'Client',
        })
        with patch('app.runtime.execute_jms', return_value=bridge_output) as bridge:
            received = asyncio.run(self.runtime.execute(receiver, context))
        bridge.assert_called_once()
        _, operation, destination, _, options = bridge.call_args.args
        self.assertEqual((operation, destination), ('receive', 'orders.dev'))
        self.assertEqual((options['maxSessions'], options['flowLimit'], options['receiveTimeout']), (3, 25, 4500))
        self.assertEqual(received['body'], {'orderId':42})
        self.assertIn(received['ackId'], self.runtime.acknowledgements)
        context['last'] = received
        confirmed = asyncio.run(self.runtime.execute(Activity(
            id='confirm', type='confirm', name='Confirm Message',
            config={'ackId':'${last.ackId}', 'failIfMissing':True},
        ), context))
        self.assertTrue(confirmed['confirmed'])
        self.assertEqual(confirmed['technologies'], ['ems'])

    def test_confirm_reports_a_missing_acknowledgement_handle(self):
        context = {'input': {}, 'last': {}, 'vars': {}, 'resources': {}, 'properties': {}}
        with self.assertRaisesRegex(RuntimeError, 'requires an acknowledgement handle'):
            asyncio.run(self.runtime.execute(Activity(
                id='confirm', type='confirm', name='Confirm Message',
                config={'ackId': '${last.ackId}', 'failIfMissing': True},
            ), context))

    def test_execution_path_outputs_are_retained_and_mappable_by_activity(self):
        resource = SharedResource(id='ems-connection', type='ems', name='EMS', config={'mode': 'memory'})
        seed_context = {'input': {'orderId': 42}, 'last': {'orderId': 42}, 'vars': {}, 'resources': {resource.id: resource}, 'properties': {}}
        asyncio.run(self.runtime.execute(Activity(
            id='sender', type='ems', name='Seed Queue',
            config={'operation': 'publish', 'resourceId': resource.id, 'queue': 'orders'},
        ), seed_context))
        process = ProcessDefinition(id='path-task', name='Path Task', activities=[
            Activity(id='receiver', type='ems', name='EMS Queue Receiver', config={
                'operation': 'queue_receiver', 'resourceId': resource.id, 'queue': 'orders', 'acknowledgeMode': 'Client',
            }),
            Activity(id='confirm', type='confirm', name='Confirm Message', config={
                'operation': 'acknowledge', 'inputMappings': {'ackId': '${activities.receiver.output.ackId}'},
            }),
            Activity(id='end', type='end', name='End'),
            Activity(id='unrelated', type='log', name='Unrelated Branch'),
        ], transitions=[
            Transition(id='receive-unrelated', source='receiver', target='unrelated', type='success_condition', condition='false == true'),
            Transition(id='receive-confirm', source='receiver', target='confirm'),
            Transition(id='confirm-end', source='confirm', target='end'),
        ])
        result = asyncio.run(self.runtime.run(process, {}, {resource.id: resource}))
        self.assertEqual(result.status, 'completed')
        self.assertTrue(result.activity_outputs['receiver']['output']['ackId'])
        self.assertTrue(result.activity_outputs['confirm']['output']['confirmed'])
        self.assertNotIn('unrelated', result.activity_outputs)
        self.assertEqual(result.task_outputs['path-task']['output'], result.output)

    def test_log_activity_emits_configured_message_and_preserves_payload(self):
        payload = {'orderId': '10001'}
        process = ProcessDefinition(id='logging-task', name='Logging Task', activities=[
            Activity(id='start', type='start', name='Start'),
            Activity(id='log', type='log', name='Log', config={
                'level': 'INFO', 'message': 'Order payload', 'includePayload': True,
                'inputMappings': {'payload': '${last}'},
            }),
            Activity(id='end', type='end', name='End'),
        ], transitions=[
            Transition(id='start-log', source='start', target='log'),
            Transition(id='log-end', source='log', target='end'),
        ])

        result = asyncio.run(self.runtime.run(process, payload))

        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.output, payload)
        event = next(item for item in result.logs if item.get('activityId') == 'log' and item['level'] == 'INFO')
        self.assertEqual(event['message'], 'Order payload')
        self.assertEqual(event['payload'], payload)
        self.assertEqual(result.activity_outputs['log']['output'], payload)
        self.assertEqual(result.activity_outputs['log']['logEvent']['payload'], payload)
        self.assertTrue(all(item['level'] == 'DEBUG' for item in result.logs if item['message'].startswith('Executing ')))

    def test_file_activity_runtime_inputs_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'orders' / 'order.txt'; copied = root / 'archive' / 'order.txt'
            context = {'input': {}, 'last': {'orderId': 42}, 'vars': {}, 'resources': {}, 'properties': {}}
            written = asyncio.run(self.runtime.execute(Activity(id='write', type='file', name='Write File', config={
                'operation':'write', 'path':str(source), 'createDirectories':True, 'writeAs':'Text', 'encoding':'utf-8',
                'inputMappings':{'textContent':'${last}'},
            }), context))
            self.assertTrue(written['success'])
            self.assertEqual(__import__('json').loads(source.read_text()), {'orderId':42})
            read = asyncio.run(self.runtime.execute(Activity(id='read', type='file', name='Read File', config={
                'operation':'read', 'path':str(source), 'readAs':'Text', 'encoding':'utf-8',
            }), context))
            self.assertEqual(read['fileInfo']['fileName'], 'order.txt')
            self.assertEqual(__import__('json').loads(read['textContent']), {'orderId':42})
            copied_result = asyncio.run(self.runtime.execute(Activity(id='copy', type='file', name='Copy File', config={
                'operation':'copy', 'path':str(source), 'destination':str(copied), 'createDirectories':True,
            }), context))
            self.assertTrue(copied_result['success'])
            listed = asyncio.run(self.runtime.execute(Activity(id='list', type='file', name='List Files', config={
                'operation':'list', 'path':str(root), 'pattern':'*.txt', 'recursive':True, 'listType':'Only Files',
            }), context))
            self.assertEqual(listed['count'], 2)
            self.assertTrue(all('lastModified' in item for item in listed['files']))


if __name__ == '__main__': unittest.main()
