"""Failure-path ownership checks; broker doubles do not qualify live services."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

from app import amqp, google_pubsub
from app.runtime import WorkflowRuntime
from app.raw_python import engine_python_files, raw_python_files
from app.raw_python_support.activities import excel_read
from app.raw_python_support import connectors
from app.debugger import DebugManager
from app.models import Project


class RemainingActivityResources(unittest.TestCase):
    def test_direct_dynamic_publisher_configurations_are_bounded_and_closed(self):
        producers = []
        class Producer:
            def __init__(self, **options):
                self.options, self.stops = options, 0
                producers.append(self)
            async def start(self):
                if self.options['client_id'] == 'fail': raise RuntimeError('start failed')
            async def stop(self): self.stops += 1
            async def send(self, *args, **kwargs): return object()
        sdk = types.ModuleType('aiokafka')
        sdk.AIOKafkaProducer, sdk.AIOKafkaConsumer = Producer, object
        publishers = []
        def publisher(**kwargs):
            client = MagicMock()
            client.publish.return_value.result.return_value = 'message-id'
            client.topic_path.return_value = 'projects/demo/topics/events'
            publishers.append(client)
            return client
        async def exercise():
            try:
                with self.assertRaises(RuntimeError):
                    await connectors.kafka('publish', {'clientId': 'fail'}, {'topic': 'events'}, {})
                self.assertEqual(producers[-1].stops, 1)
                for index in range(100):
                    await connectors.kafka('publish', {'clientId': str(index)}, {'topic': 'events'}, {})
                    await connectors.pubsub('publish', {'projectId': f'project-{index}'}, {'topic': 'events'}, {})
                self.assertEqual(len(connectors._KAFKA_PRODUCERS), 32)
                self.assertEqual(len(connectors._PUBSUB_PUBLISHERS), 32)
                self.assertLessEqual(len(connectors._KAFKA_PRODUCER_LOCKS), 64)
                self.assertTrue(all(client.stops == 1 for client in producers[33:]))
                self.assertTrue(all(client.transport.close.call_count == 1 for client in publishers[32:]))
            finally:
                await connectors.close_kafka()
                await connectors.close_pubsub()
        with patch.dict(sys.modules, {'aiokafka': sdk}), patch('google.cloud.pubsub_v1.PublisherClient', side_effect=publisher):
            asyncio.run(exercise())
        self.assertTrue(all(client.stops == 1 for client in producers))
        self.assertTrue(all(client.transport.close.call_count == 1 for client in publishers))

    def test_refresh_closes_http_session_on_success_and_error(self):
        class Credentials:
            error = False
            def refresh(self, request):
                if self.error: raise ValueError('token rejected')
                return 'token'
        credentials = google_pubsub._credentials_with_ca(Credentials(), 'roots.pem')
        for fail in (False, True):
            credentials.error = fail
            with patch('requests.Session') as session, patch.object(google_pubsub, '_merged_ca_bundle', return_value='bundle.pem'):
                if fail:
                    with self.assertRaises(ValueError): credentials.refresh(None)
                else: self.assertEqual(credentials.refresh(None), 'token')
                session.return_value.__exit__.assert_called_once()

    def test_transaction_lock_registry_is_bounded_and_stable(self):
        runtime = WorkflowRuntime()
        first_key, first_lock = runtime._publisher_operation_lock('kafka', {'id': 0})
        for number in range(10000): runtime._publisher_operation_lock('kafka', {'id': number})
        self.assertLessEqual(len(runtime._publisher_operation_locks), 64)
        self.assertEqual(runtime._publisher_operation_lock('kafka', {'id': 0}), (first_key, first_lock))
        runtime.close_publishers()

    def test_failed_jms_shutdown_and_pubsub_stop_do_not_skip_other_cleanup(self):
        runtime = WorkflowRuntime()
        runtime._jms_executor = MagicMock()
        executor = runtime._jms_executor
        pubsub, kafka = MagicMock(), MagicMock()
        pubsub.stop.side_effect = RuntimeError('stop failed')
        runtime._publishers = {'pubsub:a': pubsub, 'kafka:b': kafka}
        with patch('app.runtime.close_jms_senders', side_effect=RuntimeError('bridge stopped')):
            runtime.close_publishers()
        pubsub.transport.close.assert_called_once()
        kafka.flush.assert_called_once_with(3)
        executor.shutdown.assert_called_once()
        self.assertFalse(runtime._publishers)

    def test_excel_direct_closes_workbook_even_when_selection_fails(self):
        workbook = MagicMock()
        workbook.__getitem__.side_effect = KeyError('missing sheet')
        with patch('openpyxl.load_workbook', return_value=workbook):
            with self.assertRaises(KeyError): excel_read({'filePath': 'test.xlsx', 'sheetName': 'missing'})
        workbook.close.assert_called_once()

    def test_excel_default_rows_in_run_debug_and_both_executable_archives(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'records.xlsx'
            book = Workbook()
            book.active.append(['id', 'customer.name'])
            book.active.append([1, 'MINA'])
            book.save(path)
            book.close()
            project = Project.model_validate({'id': 'excel-resources', 'name': 'Excel', 'tasks': [{
                'id': 'main', 'name': 'Main', 'kind': 'subtask', 'activities': [
                    {'id': 'start', 'name': 'Start', 'type': 'start'},
                    {'id': 'excel', 'name': 'Excel', 'type': 'excel', 'config': {'operation': 'read', 'filePath': str(path)}},
                    {'id': 'end', 'name': 'End', 'type': 'end'}],
                'transitions': [{'id': 'a', 'source': 'start', 'target': 'excel'}, {'id': 'b', 'source': 'excel', 'target': 'end'}]}]})
            def check(output):
                self.assertEqual(output['workbook']['sheets'][0]['rows'], [{'id': 1, 'customer': {'name': 'MINA'}}])
            runtime = WorkflowRuntime()
            result = asyncio.run(runtime.run(project.tasks[0], {}, project=project))
            self.assertEqual(result.status, 'completed', result.logs)
            check(result.output)
            async def debug():
                manager = DebugManager(runtime)
                session = manager.start(project, 'main', {}, {}, {}, [])['sessionId']
                try:
                    state = await manager.action(session, 'resume')
                    self.assertEqual(state['status'], 'completed', state.get('logs'))
                    check(state['output'])
                finally: await manager.stop(session)
            asyncio.run(debug())
            for index, build in enumerate((raw_python_files, engine_python_files)):
                archive = Path(directory) / f'excel-{index}.pyifpkg'
                with zipfile.ZipFile(archive, 'w') as package:
                    for name, body in build(project.model_dump(), {'local': []}).items(): package.writestr(name, body)
                command = ('import sys,asyncio,json;sys.path.insert(0,sys.argv[1]);'
                    'from application.main import run_task;'
                    'print(json.dumps(asyncio.run(run_task("main",{}))))')
                result = subprocess.run([sys.executable, '-c', command, str(archive)],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                import json
                check(json.loads(result.stdout))
            runtime.close_publishers()

    def test_direct_pubsub_pull_closes_transport_on_success_and_error(self):
        for fail in (False, True):
            client = MagicMock()
            client.subscription_path.return_value = 'projects/demo/subscriptions/sub'
            client.pull.return_value = types.SimpleNamespace(received_messages=[])
            if fail: client.pull.side_effect = RuntimeError('pull failed')
            with patch('google.cloud.pubsub_v1.SubscriberClient', return_value=client):
                if fail:
                    with self.assertRaises(RuntimeError): asyncio.run(connectors.pubsub('pull', {'projectId': 'demo'}, {'subscription': 'sub'}, None))
                else: self.assertEqual(asyncio.run(connectors.pubsub('pull', {'projectId': 'demo'}, {'subscription': 'sub'}, None))['count'], 0)
            client.transport.close.assert_called_once()

    def rabbit(self):
        connection = MagicMock()
        channel = connection.channel.return_value
        channel.basic_get.return_value = (types.SimpleNamespace(delivery_tag=1),
            types.SimpleNamespace(headers={}, delivery_mode=2, message_id='m', timestamp=None,
                expiration=None, priority=1, type=None, content_type=None, correlation_id=None), b'hello')
        return connection, channel

    def test_rabbit_auto_receive_closes_and_manual_receive_defers_close(self):
        for manual in (False, True):
            connection, channel = self.rabbit()
            with patch.object(amqp, '_rabbit_connection', return_value=connection):
                output, settle = amqp.get({'brokerType': 'RabbitMQ'}, {'acknowledgeMode': 'Client' if manual else 'Auto'})
            self.assertEqual(output['body'], 'hello')
            if manual:
                connection.close.assert_not_called()
                channel.basic_ack.side_effect = RuntimeError('ack failed')
                with self.assertRaises(RuntimeError): settle()
            connection.close.assert_called_once()

    def test_rabbit_receive_setup_and_body_errors_close_connection(self):
        for step in ('channel', 'basic_get', 'body'):
            connection, channel = self.rabbit()
            if step == 'channel': connection.channel.side_effect = ValueError('channel')
            elif step == 'basic_get': channel.basic_get.side_effect = ValueError('receive')
            else:
                method, props, _ = channel.basic_get.return_value
                channel.basic_get.return_value = (method, props, None)
            with patch.object(amqp, '_rabbit_connection', return_value=connection):
                with self.assertRaises((ValueError, AttributeError)): amqp.get({'brokerType': 'RabbitMQ'}, {'acknowledgeMode': 'Client'})
            connection.close.assert_called_once()

    def test_azure_auto_manual_empty_and_error_paths_close_resources(self):
        sdk = types.ModuleType('azure.servicebus')
        sdk.ServiceBusReceiveMode = types.SimpleNamespace(PEEK_LOCK='peek', RECEIVE_AND_DELETE='auto')
        for mode in ('auto', 'manual', 'empty', 'error', 'peek-error'):
            closed = []
            receiver = MagicMock()
            receiver.__enter__.return_value = receiver
            receiver.__exit__.side_effect = lambda *a: closed.append('receiver')
            receiver.receive_messages.return_value = [] if mode == 'empty' else [types.SimpleNamespace(
                application_properties={}, message_id='m', expires_at_utc=None, content_type=None,
                correlation_id=None, subject=None, session_id=None, delivery_count=1, lock_token='lock')]
            if mode == 'error': receiver.receive_messages.side_effect = RuntimeError('receive failed')
            receiver.peek_messages.side_effect = RuntimeError('peek failed')
            @contextmanager
            def client(config):
                try: yield object()
                finally: closed.append('client')
            with patch.dict(sys.modules, {'azure.servicebus': sdk}), patch.object(amqp, '_azure_client', client), patch.object(amqp, '_azure_receiver', return_value=receiver):
                if mode in ('error', 'peek-error'):
                    with self.assertRaises(amqp.AmqpAdapterError):
                        if mode == 'peek-error': amqp.test_connection({'brokerType': 'AzureSB-1-0', 'connectionString': 'namespace'})
                        else: amqp.get({'brokerType': 'AzureSB-1-0'}, {})
                else:
                    _, settle = amqp.get({'brokerType': 'AzureSB-1-0'}, {'acknowledgeMode': 'Client' if mode == 'manual' else 'Auto'})
                    if mode == 'manual':
                        self.assertEqual(closed, [])
                        receiver.complete_message.side_effect = RuntimeError('complete failed')
                        with self.assertRaises(RuntimeError): settle()
                self.assertEqual(closed, ['receiver', 'client'])

    def test_azure_owns_identity_credential_even_when_client_creation_fails(self):
        sdk, identity = types.ModuleType('azure.servicebus'), types.ModuleType('azure.identity')
        sdk.ServiceBusClient = MagicMock(side_effect=RuntimeError('constructor failed'))
        credential = MagicMock()
        identity.ClientSecretCredential = MagicMock(return_value=credential)
        identity.ManagedIdentityCredential = MagicMock(return_value=credential)
        with patch.dict(sys.modules, {'azure.servicebus': sdk, 'azure.identity': identity}):
            with self.assertRaises(RuntimeError):
                with amqp._azure_client({'authenticationType': 'Managed Identity', 'connectionString': 'sb://test.example'}): pass
        credential.close.assert_called_once()

    def test_java_timeout_waits_for_child_exit_before_temp_cleanup(self):
        compiler = MagicMock(returncode=0, communicate=AsyncMock(return_value=(b'', b'')))
        child = MagicMock(returncode=None, communicate=AsyncMock(side_effect=asyncio.TimeoutError), wait=AsyncMock())
        with patch('asyncio.create_subprocess_exec', AsyncMock(side_effect=[compiler, child])):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                asyncio.run(WorkflowRuntime().java_worker({'sourceCode': 'class Example {}', 'className': 'Example', 'method': 'run'}, {}))
        child.kill.assert_called_once()
        child.wait.assert_awaited_once()

    def test_resource_fixes_are_packaged_in_both_archive_formats(self):
        project = {'id': 'resources', 'name': 'Resources', 'resources': [], 'schemas': [], 'tasks': [{
            'id': 'main', 'name': 'Main', 'kind': 'subtask', 'groups': [], 'transitions': [],
            'activities': [dict(id=kind, name=kind, type=kind, config={'operation': operation}) for kind, operation in
                [('amqp', 'get'), ('pubsub', 'publish'), ('excel', 'read'), ('java', 'invoke')]]}]}
        project['tasks'][0]['transitions'] = [dict(id=str(i), source=a, target=b)
            for i, (a, b) in enumerate(zip(('amqp', 'pubsub', 'excel'), ('pubsub', 'excel', 'java')))]
        for build, prefix in ((raw_python_files, 'application/native/'), (engine_python_files, 'application/engine/')):
            files = build(project, {'local': []})
            for name in (('amqp.py',) if build is raw_python_files else ('amqp.py', 'google_pubsub.py')):
                self.assertEqual(files[prefix + name].decode().replace('\r\n', '\n'),
                    (Path(__file__).parents[1] / 'app' / name).read_text())
            with tempfile.TemporaryDirectory() as directory:
                for name, body in files.items():
                    path = Path(directory) / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                result = subprocess.run([sys.executable, '-c', 'import application.main'], cwd=directory,
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
