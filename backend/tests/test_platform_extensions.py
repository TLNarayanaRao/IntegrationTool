import io
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import event_contracts, observability, platform_connectors
from app.message_state import MessageStateException, operate


CONTRACT = {
    'asyncapi': '3.0.0', 'info': {'title': 'Orders', 'version': '1'},
    'channels': {'orders': {'address': 'orders.v1', 'messages': {
        'created': {'payload': {'$ref': '#/components/schemas/order'}}
    }}},
    'operations': {'create': {'action': 'send', 'channel': {'$ref': '#/channels/orders'},
                              'messages': [{'$ref': '#/channels/orders/messages/created'}]}},
    'components': {'schemas': {'order': {'type': 'object', 'required': ['id'],
                                       'properties': {'id': {'type': 'string'}}}}},
}


class PlatformExtensionsTests(unittest.TestCase):
    def test_event_contracts_run_debug_and_python_archives(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        parity = PythonMapperParityTests()
        review = event_contracts.review_contract(json.dumps(CONTRACT))
        self.assertEqual(review['operations'], [
            {'id': 'create', 'action': 'send', 'address': 'orders.v1', 'messages': ['created']}
        ])
        project = parity.project()
        task = project['tasks'][0]
        task['activities'][1:1] = [
            dict(id='Validate', name='Validate', type='basic', config={
                'operation': 'asyncapi_validate', 'operationId': 'create', 'asyncApiDocument': json.dumps(CONTRACT)
            }),
            dict(id='Encode', name='Encode', type='basic', config={
                'operation': 'cloudevent_encode',
                'eventAttributes': {'id': 'fixture-id', 'type': 'order.created', 'source': '/orders'}
            }),
            dict(id='Decode', name='Decode', type='basic', config={'operation': 'cloudevent_decode'}),
        ]
        task['transitions'] = [dict(id=f't{i}', source=left['id'], target=right['id'])
                               for i, (left, right) in enumerate(zip(task['activities'], task['activities'][1:]))]
        payload = {'id': 'ORDER-1'}
        expected = {'specversion': '1.0', 'id': 'fixture-id', 'type': 'order.created',
                    'source': '/orders', 'data': payload}
        parity.assert_studio(project, payload, expected)
        parity.assert_exports(project, payload, expected)
        with self.assertRaisesRegex(ValueError, 'failed'):
            event_contracts.execute('asyncapi_validate', task['activities'][1]['config'], {'id': 1})
        with self.assertRaisesRegex(ValueError, 'local'):
            event_contracts.parse_contract({**CONTRACT, 'operations': {'remote': {'$ref': 'https://example.com/outside'}}})

    def test_s3_and_sqs_calls_do_not_acknowledge_at_receive(self):
        sdk = MagicMock()
        sdk.__enter__.return_value = sdk
        sdk.get_object.return_value = {'Body': io.BytesIO(b'abc'), 'ContentType': 'text/plain'}
        sdk.receive_message.return_value = {'Messages': [{
            'MessageId': 'ID', 'Body': json.dumps({'Records': [
                {'eventName': 'ObjectCreated:Put', 'eventSource': 'aws:s3',
                 's3': {'bucket': {'name': 'orders'}, 'object': {'key': 'hello+world.json'}}}
            ]}), 'ReceiptHandle': 'receipt'
        }]}
        with patch.object(platform_connectors, '_aws', return_value=sdk):
            self.assertEqual(platform_connectors.execute('s3_get', {'bucket': 'orders', 'objectKey': 'one'}, None)['contentBase64'], 'YWJj')
            event = platform_connectors.execute('s3_event', {'queueUrl': 'queue'}, None)
            self.assertEqual(event['records'][0]['key'], 'hello world.json')
            sdk.delete_message.assert_not_called()
            platform_connectors.execute('sqs_ack', {'queueUrl': 'queue', 'receiptHandle': event['receiptHandle']}, None)
            sdk.delete_message.assert_called_once_with(QueueUrl='queue', ReceiptHandle='receipt')

    @unittest.skipUnless(importlib.util.find_spec('boto3'), 'AWS SDK is unavailable')
    def test_sqs_sdk_run_debug_and_python_archives(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        received = []

        class QueueEndpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                data = b'{"MessageId":"loopback-message","MD5OfMessageBody":"unused"}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-amz-json-1.0')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as settings, ThreadingHTTPServer(('127.0.0.1', 0), QueueEndpoint) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                config_file = Path(settings) / 'config'
                config_file.write_text('[default]\nregion = us-east-1\n', encoding='utf-8')
                endpoint = f'http://127.0.0.1:{server.server_port}'
                with patch.dict(os.environ, {
                    'AWS_ACCESS_KEY_ID': 'local-qa', 'AWS_SECRET_ACCESS_KEY': 'local-qa',
                    'AWS_SESSION_TOKEN': '', 'AWS_PROFILE': 'default',
                    'AWS_CONFIG_FILE': str(config_file),
                    'AWS_SHARED_CREDENTIALS_FILE': str(Path(settings) / 'no-credentials'),
                    'AWS_DEFAULT_REGION': 'us-east-1', 'AWS_ENDPOINT_URL_SQS': endpoint,
                    'AWS_EC2_METADATA_DISABLED': 'true',
                }):
                    parity = PythonMapperParityTests()
                    project = parity.project()
                    task = project['tasks'][0]
                    task['activities'].insert(1, dict(id='Send', name='Send', type='basic', config={
                        'operation': 'sqs_send', 'queueUrl': endpoint + '/queue/test'
                    }))
                    task['transitions'] = [dict(id='t0', source='Start', target='Send'),
                                           dict(id='t1', source='Send', target='End')]
                    payload = {'orderId': 'test'}
                    expected = {'messageId': 'loopback-message'}
                    parity.assert_studio(project, payload, expected)
                    parity.assert_exports(project, payload, expected)
                self.assertEqual(len(received), 5)
                self.assertTrue(all(json.loads(request['MessageBody']) == payload for request in received))
            finally:
                server.shutdown()
                worker.join(timeout=5)

    def test_requeue_one_returns_exact_message_without_changing_other_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {'stateFile': str(Path(folder) / 'messages.db'), 'namespace': 'test'}
            for key in ('first', 'second'):
                claim = operate('deduplicate', {**config, 'messageKey': key}, {'id': key})
                operate('message_receipt', {**config, 'messageKey': key, 'claimToken': claim['claimToken'], 'action': 'fail'}, None)
            requeue = operate('replay_messages', {**config, 'messageKey': 'second', 'action': 'requeue_one'}, None)
            self.assertEqual([(row['status'], row['payload']['id']) for row in requeue['messages']], [('ready', 'second')])
            listing = operate('replay_messages', {**config, 'metadataOnly': True}, None)
            self.assertEqual([(row['messageKey'], row['status']) for row in listing['messages']],
                             [('first', 'failed'), ('second', 'ready')])
            self.assertTrue(all('payload' not in row for row in listing['messages']))

    def test_trace_headers_keep_application_override_and_avoid_batch_parent(self):
        header = b'00-12345678901234567890123456789012-1234567890123456-01'
        self.assertEqual(observability.messaging_carrier({'messages': [{'headers': {b'traceparent': header}}]}),
                         {'traceparent': header.decode()})
        self.assertEqual(observability.messaging_carrier({'messages': [{}, {}], 'headers': {'traceparent': header}}), {})
        with patch.object(observability, '_propagator') as propagator, patch.dict(observability._status, {'configured': True}):
            self.assertEqual(observability.inject_messaging({'TraceParent': 'caller'}), {'TraceParent': 'caller'})
            propagator.inject.assert_not_called()
            observability.inject_messaging({})
            propagator.inject.assert_called_once()

    @unittest.skipUnless(importlib.util.find_spec('opentelemetry.sdk'), 'OpenTelemetry SDK is unavailable')
    def test_task_and_activity_spans_parentage_and_log_correlation(self):
        import asyncio
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from app.models import Project
        from app.runtime import WorkflowRuntime
        from tests.test_python_mapper_parity import PythonMapperParityTests

        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        project = Project.model_validate(PythonMapperParityTests().project())
        try:
            with patch.object(observability, '_tracer', provider.get_tracer('test')), patch.dict(observability._status, {'configured': True}):
                result = asyncio.run(WorkflowRuntime().run(project.tasks[0], {'secret': 'payload'}, project=project))
            spans = exporter.get_finished_spans()
            task = next(span for span in spans if span.name == 'mina.task')
            children = [span for span in spans if span.name == 'mina.activity']
            self.assertEqual(len(children), 2)
            self.assertTrue(all(span.parent.span_id == task.context.span_id for span in children))
            self.assertTrue(all('payload' not in str(span.attributes) for span in spans))
            self.assertEqual(result.logs[0]['traceId'], f'{task.context.trace_id:032x}')
        finally:
            provider.shutdown()

    @unittest.skipUnless(os.getenv('MINA_QA_POSTGRES_DSN'), 'disposable PostgreSQL is not configured')
    def test_shared_postgres_claim_and_leased_cdc(self):
        import psycopg
        from psycopg import sql
        dsn = os.environ['MINA_QA_POSTGRES_DSN']
        scope = 'test_' + uuid.uuid4().hex
        config = {'namespace': scope, 'stateBackend': 'postgresql', 'messageKey': 'repeat'}
        with patch.dict(os.environ, {'MINA_MESSAGE_STATE_POSTGRES_DSN': dsn, 'MINA_POSTGRES_CDC_DSN': dsn}):
            with ThreadPoolExecutor(max_workers=6) as pool:
                claims = list(pool.map(lambda _: operate('deduplicate', config, {'order': 1}), range(12)))
            self.assertEqual(sum(claim['accepted'] for claim in claims), 1)
            accepted = next(claim for claim in claims if claim['accepted'])
            operate('message_receipt', {**config, 'claimToken': accepted['claimToken'], 'action': 'fail'}, None)
            self.assertEqual(operate('replay_messages', {**config, 'action': 'requeue_one'}, None)['messages'][0]['payload'], {'order': 1})

            script = Path(__file__).resolve().parents[2] / 'scripts' / 'postgres-cdc.sql'
            with psycopg.connect(dsn) as db:
                db.execute(script.read_text(encoding='utf-8'))
                table = sql.Identifier(scope)
                db.execute(sql.SQL('CREATE TABLE {} (id integer)').format(table))
                db.execute(sql.SQL('CREATE TRIGGER capture AFTER INSERT OR UPDATE OR DELETE ON {} FOR EACH ROW EXECUTE FUNCTION mina_cdc.capture_row({})')
                           .format(table, sql.Literal(scope)))
                db.execute(sql.SQL('INSERT INTO {} VALUES (12)').format(table))
            try:
                received = platform_connectors.execute('cdc_receive', {'channel': scope}, None)
                self.assertEqual(received['after'], {'id': 12})
                self.assertFalse(platform_connectors.execute('cdc_receive', {'channel': scope}, None)['received'])
                with self.assertRaisesRegex(ValueError, 'expired'):
                    platform_connectors.execute('cdc_ack', {**received, 'channel': scope, 'leaseToken': 'wrong'}, None)
                self.assertTrue(platform_connectors.execute('cdc_ack', {**received, 'channel': scope}, None)['acknowledged'])
                self.assertFalse(platform_connectors.execute('cdc_receive', {'channel': scope}, None)['received'])
                with psycopg.connect(dsn) as db:
                    db.execute(sql.SQL('INSERT INTO {} SELECT * FROM generate_series(1,5)').format(table))
                from tests.test_python_mapper_parity import PythonMapperParityTests
                parity = PythonMapperParityTests()
                project = parity.project()
                task = project['tasks'][0]
                task['activities'][1:1] = [
                    dict(id='Receive', name='Receive', type='basic', config={'operation': 'cdc_receive', 'channel': scope}),
                    dict(id='Ack', name='Ack', type='basic', config={'operation': 'cdc_ack', 'channel': scope,
                         'inputMappings': {'changeId': '${last.changeId}', 'leaseToken': '${last.leaseToken}'}}),
                ]
                task['transitions'] = [dict(id=f't{i}', source=left['id'], target=right['id'])
                                       for i, (left, right) in enumerate(zip(task['activities'], task['activities'][1:]))]
                parity.assert_studio(project, {}, {'acknowledged': True})
                parity.assert_exports(project, {}, {'acknowledged': True})
                self.assertFalse(platform_connectors.execute('cdc_receive', {'channel': scope}, None)['received'])
            finally:
                with psycopg.connect(dsn) as db:
                    db.execute(sql.SQL('DROP TABLE {}').format(sql.Identifier(scope)))
                    db.execute('DELETE FROM mina_cdc.changes WHERE channel=%s', (scope,))
                    db.execute('DELETE FROM mina_message_state.messages WHERE namespace=%s', (scope,))
