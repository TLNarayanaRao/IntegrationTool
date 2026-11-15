"""Regressions discovered using live brokers; these unit cases need no network."""
import asyncio
import importlib.util
import types
import unittest
import subprocess
from unittest.mock import MagicMock, patch

from app import amqp, google_pubsub, java_bridge
from app.raw_python import raw_python_files


def exported_adapter(kind, operation):
    project={'id':'alias-regression','name':'Alias-regression','resources':[], 'tasks': [{
        'id':'main','name':'Main','kind':'subtask','groups':[],'transitions':[],
        'activities':[{'id':'test','name':'Test','type':kind,'config':{'operation':operation}}]}]}
    files=raw_python_files(project,{'local':[]})
    module=types.ModuleType('generated_live_adapter')
    exec(compile(files['application/connectors.py'],'generated-connectors.py','exec'),module.__dict__)
    return module


class MessagingExportRegressions(unittest.TestCase):
    def test_java_timeout_reports_configured_budget_after_host_interruption(self):
        process=MagicMock()
        process.communicate.side_effect=[subprocess.TimeoutExpired('java',-3587),('','')]
        with patch.object(java_bridge,'_classpath',return_value=('classpath',[])), \
                patch.object(java_bridge,'_java_command',return_value=['java']), patch('subprocess.Popen',return_value=process):
            with self.assertRaisesRegex(java_bridge.JavaBridgeError,'after 15 seconds'):
                java_bridge.invoke('jms.receive',{},family='jms',timeout=15)
        process.kill.assert_called_once()

    def test_forced_java_stop_reaps_only_the_selected_execution(self):
        process,other=MagicMock(),MagicMock()
        process.poll.return_value=None
        process.wait.side_effect=[subprocess.TimeoutExpired('java',1),0]
        processes={'stop':{process},'keep':{other}}
        with patch.object(java_bridge,'_active_processes',processes),patch.object(java_bridge,'close_jms_senders'):
            java_bridge.terminate_execution_processes('stop')
        self.assertEqual(process.wait.call_count,2)
        process.kill.assert_called_once();other.kill.assert_not_called()
        self.assertIn('keep',processes)

    def test_explicit_google_tls_transport_closes_when_client_construction_fails(self):
        class BrokenPublisher:
            def __init__(self,**kwargs):raise RuntimeError('client construction failed')
        transport=MagicMock()
        with patch.object(google_pubsub,'client_configuration',return_value=({'_ssl_channel_credentials':object()},'qa')), \
                patch('google.pubsub_v1.services.publisher.transports.PublisherGrpcTransport',return_value=transport):
            with self.assertRaisesRegex(RuntimeError,'construction failed'):
                google_pubsub.create_client(BrokenPublisher,{})
        transport.close.assert_called_once()

    def test_real_google_credentials_keep_sdk_copy_contract_with_custom_ca(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        source=google_pubsub._credentials_from_info({'type':'service_account','project_id':'local-copy-test',
            'client_email':'test@example.invalid','private_key':pem,'token_uri':'https://example.invalid/token'})
        wrapped=google_pubsub._credentials_with_ca(source,'test-root.pem')
        copied=wrapped.with_scopes(['test-scope']).with_always_use_jwt_access(True).with_quota_project('qa')
        self.assertIs(type(wrapped),type(copied))
        self.assertEqual(copied.scopes,['test-scope'])
        self.assertEqual(copied.quota_project_id,'qa')
        copied.token='local-test-token'
        self.assertIsNone(source.token)
        self.assertIs(type(wrapped),type(google_pubsub._credentials_with_ca(source,'test-root.pem')))
        for index in range(50):google_pubsub._credentials_with_ca(source,f'root-{index}.pem')
        self.assertLessEqual(google_pubsub._ca_credentials_type.cache_info().currsize,32)

    def test_get_alias_retains_consumer_and_applies_partition_offset(self):
        module=exported_adapter('kafka','get')
        class Consumer:
            instance=None
            def __init__(self,*topics,**options):
                Consumer.instance=self;self.options=options;self.stopped=False
            async def start(self):pass
            def assign(self,partitions):self.partitions=partitions
            def seek(self,partition,offset):self.offset=offset
            async def getmany(self,**kwargs):return {'partition':[types.SimpleNamespace(value=b'token')]}
            async def stop(self):self.stopped=True
        sdk=types.ModuleType('aiokafka')
        sdk.AIOKafkaProducer=object;sdk.AIOKafkaConsumer=Consumer;sdk.TopicPartition=lambda topic,index:(topic,index)
        import sys
        with patch.dict(sys.modules,{'aiokafka':sdk}):
            result=asyncio.run(module.kafka('get',{}, {'topic':'events','assignCustomPartition':True,
                'partitionIds':'0','seekPosition':'custom','customOffset':7},None))
        self.assertEqual(result['messages'],['token'])
        self.assertEqual(Consumer.instance.offset,7)
        self.assertEqual(Consumer.instance.options['auto_offset_reset'],'earliest')
        self.assertTrue(Consumer.instance.stopped)

    def test_subscribe_alias_retains_pull_and_releases_transport(self):
        module=exported_adapter('pubsub','subscribe')
        client=MagicMock();client.pull.return_value=types.SimpleNamespace(received_messages=[])
        with patch('google.cloud.pubsub_v1.SubscriberClient',return_value=client):
            result=asyncio.run(module.pubsub('subscribe',{'projectId':'demo'},{'subscription':'test'},None))
        self.assertEqual(result['count'],0)
        client.pull.assert_called_once();client.transport.close.assert_called_once()


@unittest.skipUnless(importlib.util.find_spec('proton'),'Optional Proton SDK required')
class ProtonSdkRegressions(unittest.TestCase):
    config={'brokerType':'Qpid-1-0','hostPort':'localhost:5672'}

    def test_no_expiration_and_optional_content_type_are_omitted(self):
        from proton import Message
        with patch('proton.utils.BlockingConnection') as factory, patch('proton.Message',wraps=Message) as constructor:
            amqp.send(self.config,{'body':'hello'})
        message=factory.return_value.create_sender.return_value.send.call_args.args[0]
        self.assertEqual(message.ttl,0)
        self.assertNotIn('content_type',constructor.call_args.kwargs)
        self.assertNotIn('ttl',constructor.call_args.kwargs)
        factory.return_value.close.assert_called_once()

    def test_expiration_milliseconds_are_converted_to_proton_seconds(self):
        with patch('proton.utils.BlockingConnection') as factory:
            amqp.send(self.config,{'body':'hello','expiration':2500,'contentType':'application/json'})
        message=factory.return_value.create_sender.return_value.send.call_args.args[0]
        self.assertEqual(message.ttl,2.5)
        self.assertEqual(message.content_type,'application/json')

    def test_auto_and_manual_receives_use_real_blocking_sdk_signatures(self):
        from proton import Message
        from proton.utils import BlockingConnection,BlockingReceiver
        for manual in (False,True):
            connection=MagicMock(spec=BlockingConnection)
            receiver=MagicMock(spec=BlockingReceiver)
            receiver.receive.return_value=Message(body='hello',ttl=2)
            connection.create_receiver.return_value=receiver
            # Explicit signature checks catch unsupported kwargs and settlement args.
            original=BlockingConnection.create_receiver
            def create(*args,**kwargs):
                import inspect
                inspect.signature(original).bind(connection,*args,**kwargs)
                return receiver
            connection.create_receiver.side_effect=create
            with patch('proton.utils.BlockingConnection',return_value=connection):
                message,settle=amqp.get(self.config,{'acknowledgeMode':'Client' if manual else 'Auto'})
                self.assertEqual(message['MessageProperties']['expiration'],2000)
                if manual:
                    connection.close.assert_not_called();settle(True)
                    receiver.reject.assert_called_once_with()
                else:receiver.accept.assert_called_once_with()
            connection.close.assert_called_once()

    def test_only_timeout_is_reported_as_no_message(self):
        from proton import Timeout
        for error in (Timeout('empty'),RuntimeError('broken link')):
            with patch('proton.utils.BlockingConnection') as factory:
                factory.return_value.create_receiver.return_value.receive.side_effect=error
                if isinstance(error,Timeout):self.assertEqual(amqp.get(self.config,{}),(None,None))
                else:
                    with self.assertRaises(amqp.AmqpAdapterError):amqp.get(self.config,{})
                factory.return_value.close.assert_called_once()
