import asyncio
import sys
import time
import types
import unittest
from unittest.mock import patch

from app.models import SharedResource
from app.runtime import WorkflowRuntime
from app.raw_python_support import connectors as direct_connectors


def context(resource):
    return {'resources': {resource.id: resource}, 'input': {}, 'last': {},
            'properties': {}, 'vars': {}, 'context': {}}


class PublisherReuseTests(unittest.TestCase):
    def test_kafka_reuses_producer_and_waits_for_each_delivery(self):
        producers = []

        class Message:
            def partition(self): return 2
            def offset(self): return 7
            def timestamp(self): return (1, 123)

        class Producer:
            def __init__(self, config):
                self.pending = []
                self.flush_calls = 0
                producers.append(self)

            def produce(self, topic, value, **kwargs):
                self.pending.append(kwargs['callback'])

            def poll(self, timeout):
                if self.pending:
                    self.pending.pop(0)(None, Message())

            def flush(self, timeout):
                self.flush_calls += 1
                return 0

        kafka = types.ModuleType('confluent_kafka')
        kafka.Producer = Producer
        kafka.Consumer = object
        kafka.TopicPartition = object
        resource = SharedResource(id='k', type='kafka', name='Kafka', config={'bootstrapServers': 'localhost:9092'})
        runtime = WorkflowRuntime()
        with patch.dict(sys.modules, {'confluent_kafka': kafka}):
            first = asyncio.run(runtime.messaging('kafka', {'resourceId': 'k', 'topic': 'events', 'data': 'one', 'waitForDelivery': True}, context(resource)))
            second = asyncio.run(runtime.messaging('kafka', {'resourceId': 'k', 'topic': 'events', 'data': 'two', 'waitForDelivery': True}, context(resource)))
        self.assertEqual(len(producers), 1)
        self.assertEqual(first['offset'], 7)
        self.assertIn('publishLatencyMs', first)
        self.assertTrue(second['published'])
        self.assertEqual(producers[0].flush_calls, 0)
        runtime.close_publishers()
        self.assertEqual(producers[0].flush_calls, 1)

    def test_kafka_buffered_publish_does_not_wait_for_broker_callback(self):
        class Producer:
            def __init__(self, config): self.pending = []
            def produce(self, topic, value, **kwargs): self.pending.append(kwargs['callback'])
            def poll(self, timeout):
                if timeout:
                    time.sleep(.1)
                    self.pending.pop(0)(None, types.SimpleNamespace(partition=lambda: 0, offset=lambda: 1, timestamp=lambda: (1, 1)))
            def flush(self, timeout): return 0

        kafka = types.ModuleType('confluent_kafka')
        kafka.Producer = Producer; kafka.Consumer = object; kafka.TopicPartition = object
        resource = SharedResource(id='k', type='kafka', name='Kafka', config={'bootstrapServers': 'localhost:9092'})
        runtime = WorkflowRuntime()
        started = time.perf_counter()
        with patch.dict(sys.modules, {'confluent_kafka': kafka}):
            result = asyncio.run(runtime.messaging('kafka', {'resourceId': 'k', 'topic': 'events', 'data': 'one'}, context(resource)))
        self.assertLess(time.perf_counter() - started, .05)
        self.assertTrue(result['queued'])
        self.assertFalse(result['deliveryConfirmed'])

    def test_transactional_kafka_reuses_initialized_producer(self):
        producers = []

        class Message:
            def partition(self): return 0
            def offset(self): return 1
            def timestamp(self): return (1, 123)

        class Producer:
            def __init__(self, config):
                self.pending = []; self.init_calls = self.begin_calls = self.commit_calls = 0
                producers.append(self)
            def init_transactions(self): self.init_calls += 1
            def begin_transaction(self): self.begin_calls += 1
            def commit_transaction(self): self.commit_calls += 1
            def abort_transaction(self): pass
            def produce(self, topic, value, **kwargs): self.pending.append(kwargs['callback'])
            def poll(self, timeout):
                if self.pending: self.pending.pop(0)(None, Message())
            def flush(self, timeout): return 0

        kafka = types.ModuleType('confluent_kafka')
        kafka.Producer = Producer; kafka.Consumer = object; kafka.TopicPartition = object
        resource = SharedResource(id='k', type='kafka', name='Kafka', config={'bootstrapServers': 'localhost:9092'})
        runtime = WorkflowRuntime()
        config = {'resourceId': 'k', 'topic': 'events', 'data': 'one', 'transactionalId': 'orders-writer'}
        with patch.dict(sys.modules, {'confluent_kafka': kafka}):
            asyncio.run(runtime.messaging('kafka', config, context(resource)))
            asyncio.run(runtime.messaging('kafka', {**config, 'data': 'two'}, context(resource)))
        self.assertEqual(len(producers), 1)
        self.assertEqual(producers[0].init_calls, 1)
        self.assertEqual(producers[0].begin_calls, 2)
        self.assertEqual(producers[0].commit_calls, 2)

    def test_direct_python_kafka_reuses_started_async_producer(self):
        producers = []

        class Metadata:
            partition = 1
            offset = 9

        class Producer:
            def __init__(self, **config): self.start_calls = self.stop_calls = 0; self.messages = []; producers.append(self)
            async def start(self): self.start_calls += 1
            async def stop(self): self.stop_calls += 1
            async def send_and_wait(self, topic, data, **kwargs): self.messages.append(data); return Metadata()

        aiokafka = types.ModuleType('aiokafka')
        aiokafka.AIOKafkaProducer = Producer
        aiokafka.AIOKafkaConsumer = object
        direct_connectors._KAFKA_PRODUCERS.clear(); direct_connectors._KAFKA_PRODUCER_LOCKS.clear()
        async def publish_twice():
            connection = {'bootstrapServers': 'localhost:9092'}
            first = await direct_connectors.kafka('publish', connection, {'topic': 'events', 'message': 'one', 'waitForDelivery': True}, None)
            second = await direct_connectors.kafka('publish', connection, {'topic': 'events', 'message': 'two', 'waitForDelivery': True}, None)
            await direct_connectors.close_kafka()
            return first, second
        try:
            with patch.dict(sys.modules, {'aiokafka': aiokafka}): results = asyncio.run(publish_twice())
            self.assertEqual(len(producers), 1)
            self.assertEqual(producers[0].start_calls, 1)
            self.assertEqual(producers[0].stop_calls, 1)
            self.assertEqual(producers[0].messages, [b'one', b'two'])
            self.assertTrue(all('publishLatencyMs' in result for result in results))
        finally:
            direct_connectors._KAFKA_PRODUCERS.clear(); direct_connectors._KAFKA_PRODUCER_LOCKS.clear()

    def test_direct_python_kafka_buffered_publish_uses_send_not_send_and_wait(self):
        producers = []
        class Producer:
            def __init__(self, **config): self.sent = self.confirmed = self.stop_calls = 0; producers.append(self)
            async def start(self): pass
            async def stop(self): self.stop_calls += 1
            async def send(self, topic, data, **kwargs): self.sent += 1; return object()
            async def send_and_wait(self, topic, data, **kwargs): self.confirmed += 1; raise AssertionError('must not wait')
        aiokafka = types.ModuleType('aiokafka')
        aiokafka.AIOKafkaProducer = Producer; aiokafka.AIOKafkaConsumer = object
        direct_connectors._KAFKA_PRODUCERS.clear(); direct_connectors._KAFKA_PRODUCER_LOCKS.clear()
        try:
            async def publish_and_close():
                result = await direct_connectors.kafka('publish', {'bootstrapServers': 'localhost:9092'}, {'topic': 'events', 'message': 'one'}, None)
                await direct_connectors.close_kafka()
                return result
            with patch.dict(sys.modules, {'aiokafka': aiokafka}):
                result = asyncio.run(publish_and_close())
            self.assertEqual(producers[0].sent, 1)
            self.assertEqual(producers[0].confirmed, 0)
            self.assertEqual(producers[0].stop_calls, 1)
            self.assertFalse(result['deliveryConfirmed'])
        finally:
            direct_connectors._KAFKA_PRODUCERS.clear(); direct_connectors._KAFKA_PRODUCER_LOCKS.clear()

    def test_pubsub_reuses_client_and_preserves_message_ids(self):
        clients = []

        class Future:
            def __init__(self, value): self.value = value
            def result(self, timeout): return self.value

        class Publisher:
            def __init__(self):
                self.published = []
                self.stop_calls = 0
                self.transport = types.SimpleNamespace(close=lambda: None)
                clients.append(self)

            def topic_path(self, project, topic): return f'projects/{project}/topics/{topic}'
            def publish(self, path, data, **kwargs):
                self.published.append((path, data))
                return Future(f'message-{len(self.published)}')
            def stop(self): self.stop_calls += 1

        google = types.ModuleType('google')
        cloud = types.ModuleType('google.cloud')
        pubsub = types.ModuleType('google.cloud.pubsub_v1')
        pubsub.PublisherClient = Publisher
        cloud.pubsub_v1 = pubsub
        google.cloud = cloud
        retry = types.ModuleType('google.api_core.retry')
        retry.Retry = lambda deadline: object()
        resource = SharedResource(id='p', type='pubsub', name='PubSub', config={'projectId': 'demo', 'serviceAccountJson': '{}'})
        runtime = WorkflowRuntime()
        modules = {'google': google, 'google.cloud': cloud, 'google.cloud.pubsub_v1': pubsub,
                   'google.api_core.retry': retry}
        with patch.dict(sys.modules, modules), patch('app.runtime.pubsub_client_configuration', return_value=({}, 'demo')), patch('app.runtime.create_pubsub_client', side_effect=lambda *_: Publisher()):
            first = asyncio.run(runtime.messaging('pubsub', {'resourceId': 'p', 'topic': 'events', 'data': 'one', 'waitForDelivery': True}, context(resource)))
            second = asyncio.run(runtime.messaging('pubsub', {'resourceId': 'p', 'topic': 'events', 'data': 'two', 'waitForDelivery': True}, context(resource)))
        self.assertEqual(len(clients), 1)
        self.assertEqual([first['MessageID'], second['MessageID']], ['message-1', 'message-2'])
        self.assertEqual(clients[0].stop_calls, 0)
        runtime.close_publishers()
        self.assertEqual(clients[0].stop_calls, 1)

    def test_pubsub_buffered_publish_reuses_client_across_execution_ids_without_waiting(self):
        clients = []
        class Future:
            def result(self, timeout=None): time.sleep(.2); return 'provider-id'
            def add_done_callback(self, callback): self.callback = callback
            def exception(self): return None
        class Publisher:
            def __init__(self):
                clients.append(self); self.transport = types.SimpleNamespace(close=lambda: None)
            def topic_path(self, project, topic): return f'projects/{project}/topics/{topic}'
            def publish(self, path, data, **kwargs): return Future()
            def stop(self): pass
        google = types.ModuleType('google'); cloud = types.ModuleType('google.cloud'); pubsub = types.ModuleType('google.cloud.pubsub_v1')
        pubsub.PublisherClient = Publisher; cloud.pubsub_v1 = pubsub; google.cloud = cloud
        retry = types.ModuleType('google.api_core.retry'); retry.Retry = lambda deadline: object()
        resource = SharedResource(id='p', type='pubsub', name='PubSub', config={'projectId':'demo', 'serviceAccountJson':'{}'})
        runtime = WorkflowRuntime(); modules = {'google':google, 'google.cloud':cloud, 'google.cloud.pubsub_v1':pubsub, 'google.api_core.retry':retry}
        def scoped(scope):
            value = context(resource); value['context']['executionId'] = scope; return value
        started = time.perf_counter()
        with patch.dict(sys.modules, modules), patch('app.runtime.pubsub_client_configuration', return_value=({}, 'demo')), patch('app.runtime.create_pubsub_client', side_effect=lambda *_: Publisher()):
            first = asyncio.run(runtime.messaging('pubsub', {'resourceId':'p', 'topic':'events', 'data':'one'}, scoped('run-1')))
            second = asyncio.run(runtime.messaging('pubsub', {'resourceId':'p', 'topic':'events', 'data':'two'}, scoped('run-2')))
        self.assertLess(time.perf_counter() - started, .1)
        self.assertEqual(len(clients), 1)
        self.assertTrue(first['queued']); self.assertFalse(first['deliveryConfirmed'])
        self.assertIsNone(first['providerMessageId'])
        self.assertIn('publishLatencyMs', second)

    def test_direct_python_pubsub_reuses_batched_client_and_does_not_wait_by_default(self):
        clients = []
        class Future:
            def result(self, timeout=None): raise AssertionError('buffered publish must not wait')
            def add_done_callback(self, callback): self.callback = callback
            def exception(self): return None
        class Publisher:
            def __init__(self, **kwargs): clients.append(self); self.transport = types.SimpleNamespace(close=lambda: None); self.stop_calls = 0
            def topic_path(self, project, topic): return f'projects/{project}/topics/{topic}'
            def publish(self, path, data, **kwargs): return Future()
            def stop(self): self.stop_calls += 1
        pubsub = types.ModuleType('google.cloud.pubsub_v1'); pubsub.PublisherClient = Publisher
        pubsub.types = types.SimpleNamespace(BatchSettings=lambda **kwargs: kwargs, PublisherOptions=lambda **kwargs: kwargs)
        cloud = types.ModuleType('google.cloud'); cloud.pubsub_v1 = pubsub
        service_account = types.ModuleType('google.oauth2.service_account')
        service_account.Credentials = types.SimpleNamespace(from_service_account_info=lambda info: object())
        oauth2 = types.ModuleType('google.oauth2'); oauth2.service_account = service_account
        google = types.ModuleType('google'); google.cloud = cloud; google.oauth2 = oauth2
        modules = {'google':google, 'google.cloud':cloud, 'google.cloud.pubsub_v1':pubsub, 'google.oauth2':oauth2, 'google.oauth2.service_account':service_account}
        direct_connectors._PUBSUB_PUBLISHERS.clear()
        async def publish_twice():
            connection = {'projectId':'demo'}
            first = await direct_connectors.pubsub('publish', connection, {'topic':'events', 'message':'one'}, None)
            second = await direct_connectors.pubsub('publish', connection, {'topic':'events', 'message':'two'}, None)
            await direct_connectors.close_pubsub()
            return first, second
        try:
            with patch.dict(sys.modules, modules): first, second = asyncio.run(publish_twice())
            self.assertEqual(len(clients), 1)
            self.assertFalse(first['deliveryConfirmed']); self.assertTrue(second['queued'])
            self.assertEqual(clients[0].stop_calls, 1)
        finally: direct_connectors._PUBSUB_PUBLISHERS.clear()


if __name__ == '__main__':
    unittest.main()
