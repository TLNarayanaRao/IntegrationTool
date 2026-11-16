"""Offline correctness guards for throughput optimizations, not rate claims."""
import asyncio
import io
import json
import queue
import threading
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app import java_bridge
from app.models import SharedResource
from app.runtime import WorkflowRuntime
from app.raw_python_support import connectors


def context(kind, config=None):
    resource = SharedResource(id='c', name='QA', type=kind, config=config or {})
    return {'resources': {'c': resource}, 'last': {}, 'input': {}, 'properties': {},
            'vars': {}, 'context': {}, 'activities': {}, 'tasks': {}}


class MessagingThroughput(unittest.TestCase):
    def test_generated_kafka_routes_both_publish_modes_to_requested_partition(self):
        producer = MagicMock()
        producer.start = AsyncMock(); producer.stop = AsyncMock(); producer.send = AsyncMock()
        producer.send_and_wait = AsyncMock(return_value=types.SimpleNamespace(partition=3, offset=0))
        async def exercise():
            await connectors.close_kafka()
            try:
                for confirmed in (True, False):
                    await connectors.kafka('publish', {'bootstrapServers': 'qa'},
                        {'topic': 'test', 'assignCustomPartition': True, 'partitionId': 3,
                         'waitForDelivery': confirmed}, 'data')
            finally: await connectors.close_kafka()
        with patch.dict('sys.modules', {'aiokafka': types.SimpleNamespace(AIOKafkaProducer=lambda **_: producer, AIOKafkaConsumer=MagicMock())}):
            asyncio.run(exercise())
        self.assertEqual(producer.send.call_args.kwargs['partition'], 3)
        self.assertEqual(producer.send_and_wait.call_args.kwargs['partition'], 3)

    def test_jms_batch_keeps_every_body_and_legacy_first_body(self):
        native = {'received': True, 'body': '1', 'messages': [
            {'body': str(i), 'headers': {'JMSMessageID': str(i)}, 'properties': {'n': i}}
            for i in range(3)], 'count': 3}
        async def exercise():
            runtime = WorkflowRuntime()
            result = await runtime.messaging('jms', {'resourceId': 'c', 'operation': 'get_queue_message',
                'destination': 'qa', 'maxMessages': 3, 'acknowledgeMode': 'Client'},
                context('jms', {'serverUrl': 'test', 'username': 'qa', 'password': 'qa'}))
            self.assertEqual(result['body'], 0)
            self.assertEqual([x['data'] for x in result['messages']], [0, 1, 2])
            self.assertEqual(result['count'], 3)
            self.assertEqual(len(set(result['ackIds'])), 3)
        with patch('app.runtime.execute_jms', return_value=native) as invoke:
            asyncio.run(exercise())
        self.assertEqual(invoke.call_args.args[1], 'receive')
        self.assertEqual(invoke.call_args.args[-1]['maxMessages'], 3)

    def test_jms_request_reply_and_empty_get_remain_distinct(self):
        async def exercise():
            runtime = WorkflowRuntime(); ctx = context('jms', {'serverUrl': 'test', 'username': 'qa', 'password': 'qa'})
            with patch('app.runtime.execute_jms', return_value={'received': True, 'body': '{"reply":1}'}) as invoke:
                value = await runtime.messaging('jms', {'resourceId': 'c', 'operation': 'request_reply'}, ctx)
                self.assertEqual(value['body'], {'reply': 1}); self.assertEqual(invoke.call_args.args[1], 'request')
            with patch('app.runtime.execute_jms', return_value={'received': False}):
                value = await runtime.messaging('jms', {'resourceId': 'c', 'operation': 'get_queue_message'}, ctx)
                self.assertEqual(value['count'], 0); self.assertEqual(value['messages'], [])
        asyncio.run(exercise())

    def test_get_batch_limit_is_bounded_and_defaults_to_one(self):
        with patch.object(java_bridge, 'invoke', return_value={}) as invoke:
            java_bridge.execute_jms({}, 'receive', 'qa')
            self.assertEqual(invoke.call_args.args[2]['maxMessages'], 1)
            with patch.object(java_bridge, '_send_jms_reused', return_value={}) as reuse:
                java_bridge.execute_jms({}, 'receive', 'qa', options={'maxMessages': 50000})
                self.assertEqual(reuse.call_args.args[1]['maxMessages'], 10000)
                self.assertEqual(reuse.call_args.kwargs['operation'], 'receive')
            invoke.assert_called_once()
            java_bridge.execute_jms({'clientId':'explicit-owner'}, 'receive', 'qa', options={'maxMessages':2})
            self.assertEqual(invoke.call_count,2)

    def test_kafka_empty_batch_waits_once_and_does_not_block_event_loop(self):
        polling = threading.Event(); release = threading.Event(); instance = MagicMock()
        def poll(timeout):
            polling.set()
            if not release.wait(2): raise AssertionError('Event loop was blocked by consumer polling')
            return None
        instance.poll.side_effect = poll
        sdk = types.SimpleNamespace(Consumer=MagicMock(return_value=instance), Producer=MagicMock(), TopicPartition=MagicMock())
        async def exercise():
            runtime = WorkflowRuntime()
            task = asyncio.create_task(runtime.messaging('kafka', {'resourceId': 'c', 'operation': 'get',
                'maxMessages': 1000}, context('kafka', {'bootstrapServers': 'qa'})))
            for _ in range(100):
                if polling.is_set(): break
                await asyncio.sleep(.005)
            release.set()
            self.assertEqual((await task)['count'], 0)
        with patch.dict('sys.modules', {'confluent_kafka': sdk}): asyncio.run(exercise())
        instance.poll.assert_called_once(); instance.close.assert_called_once()

    def test_kafka_consumer_closes_if_subscription_fails(self):
        consumer = MagicMock(); consumer.subscribe.side_effect = ValueError('bad destination')
        sdk = types.SimpleNamespace(Consumer=lambda _: consumer, Producer=MagicMock(), TopicPartition=MagicMock())
        with patch.dict('sys.modules', {'confluent_kafka': sdk}):
            with self.assertRaisesRegex(ValueError, 'bad destination'):
                asyncio.run(WorkflowRuntime().messaging('kafka', {'resourceId': 'c', 'operation': 'get'},
                    context('kafka', {'bootstrapServers': 'qa'})))
        consumer.close.assert_called_once()

    def test_pubsub_cached_publisher_does_not_reload_private_key(self):
        client = MagicMock(); client.publish.return_value.result.return_value = 'confirmed'
        client.topic_path.return_value = 'projects/qa/topics/test'
        async def exercise():
            runtime = WorkflowRuntime()
            try:
                for _ in range(10):
                    value = await runtime.messaging('pubsub', {'resourceId': 'c', 'operation': 'publish',
                        'topic': 'test', 'waitForDelivery': True}, context('pubsub', {'projectId': 'qa'}))
                    self.assertTrue(value['deliveryConfirmed'])
            finally: runtime.close_publishers()
        with patch('app.runtime.create_pubsub_client', return_value=client) as create, \
                patch('app.runtime.pubsub_client_configuration', side_effect=AssertionError('Repeated credentials parsing')):
            asyncio.run(exercise())
        create.assert_called_once(); self.assertEqual(client.publish.call_count, 10)

    def test_direct_pubsub_loads_credentials_on_cache_miss_only(self):
        client = MagicMock(); client.publish.return_value.result.return_value = 'confirmed'
        async def exercise():
            await connectors.close_pubsub()
            try:
                for _ in range(10):
                    await connectors.pubsub('publish', {'serviceAccountJson': json.dumps({'project_id': 'qa'})},
                        {'topic': 'test', 'waitForDelivery': True}, {})
            finally: await connectors.close_pubsub()
        with patch('google.cloud.pubsub_v1.PublisherClient', return_value=client), \
                patch('google.oauth2.service_account.Credentials.from_service_account_info', return_value=object()) as load:
            asyncio.run(exercise())
        load.assert_called_once()

    def test_pubsub_failed_pull_closes_transport(self):
        subscriber = MagicMock(); subscriber.pull.side_effect = ValueError('pull failed')
        with patch('app.runtime.create_pubsub_client', return_value=subscriber):
            with self.assertRaisesRegex(ValueError, 'pull failed'):
                asyncio.run(WorkflowRuntime().messaging('pubsub', {'resourceId': 'c', 'operation': 'pull'},
                    context('pubsub', {'projectId': 'qa'})))
        subscriber.close.assert_called_once()

    def test_pubsub_manual_confirmation_keeps_transport_until_last_ack(self):
        subscriber = MagicMock()
        subscriber.pull.return_value.received_messages = [types.SimpleNamespace(ack_id=str(i), message=
            types.SimpleNamespace(message_id=str(i), data=b'test', attributes={}, publish_time=None)) for i in range(2)]
        async def exercise():
            runtime = WorkflowRuntime()
            value = await runtime.messaging('pubsub', {'resourceId': 'c', 'operation': 'pull', 'acknowledgeMode': 'Client'},
                context('pubsub', {'projectId': 'qa'}))
            subscriber.close.assert_not_called()
            callbacks = [runtime.acknowledgements[x['ackId']]['callback'] for x in value['messages']]
            callbacks[0](); subscriber.close.assert_not_called()
            callbacks[1](); subscriber.close.assert_called_once()
        with patch('app.runtime.create_pubsub_client', return_value=subscriber): asyncio.run(exercise())

    def test_listener_notifications_cancel_without_orphan_waiters(self):
        # No reader thread/process is needed to exercise the cross-thread handoff.
        listener = object.__new__(java_bridge.SapJcoListener)
        listener._events = queue.Queue(2); listener._closed = threading.Event()
        listener._event_waiters_lock = threading.Lock(); listener._event_waiters = set()
        listener.process = MagicMock(); listener.process.poll.return_value = None
        async def exercise():
            for i in range(50):
                task = asyncio.create_task(listener.next_event(timeout=2))
                await asyncio.sleep(0)
                thread = threading.Thread(target=listener._put_event, args=({'value': i},))
                thread.start()
                self.assertEqual((await task)['value'], i); thread.join()
            pending = asyncio.create_task(listener.next_event())
            await asyncio.sleep(0); pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            self.assertEqual(listener._event_waiters, set())
            with self.assertRaises(java_bridge.JavaBridgeError): await listener.next_event(timeout=.01)
            self.assertEqual(listener._event_waiters, set())
        asyncio.run(exercise())


if __name__ == '__main__': unittest.main()
