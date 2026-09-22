import asyncio
import sys
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
            first = asyncio.run(runtime.messaging('kafka', {'resourceId': 'k', 'topic': 'events', 'data': 'one'}, context(resource)))
            second = asyncio.run(runtime.messaging('kafka', {'resourceId': 'k', 'topic': 'events', 'data': 'two'}, context(resource)))
        self.assertEqual(len(producers), 1)
        self.assertEqual(first['offset'], 7)
        self.assertIn('publishLatencyMs', first)
        self.assertTrue(second['published'])
        self.assertEqual(producers[0].flush_calls, 0)
        runtime.close_publishers()
        self.assertEqual(producers[0].flush_calls, 1)

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
            def __init__(self, **config): self.start_calls = 0; self.messages = []; producers.append(self)
            async def start(self): self.start_calls += 1
            async def send_and_wait(self, topic, data, **kwargs): self.messages.append(data); return Metadata()

        aiokafka = types.ModuleType('aiokafka')
        aiokafka.AIOKafkaProducer = Producer
        aiokafka.AIOKafkaConsumer = object
        direct_connectors._KAFKA_PRODUCERS.clear(); direct_connectors._KAFKA_PRODUCER_LOCKS.clear()
        async def publish_twice():
            connection = {'bootstrapServers': 'localhost:9092'}
            first = await direct_connectors.kafka('publish', connection, {'topic': 'events', 'message': 'one'}, None)
            second = await direct_connectors.kafka('publish', connection, {'topic': 'events', 'message': 'two'}, None)
            return first, second
        try:
            with patch.dict(sys.modules, {'aiokafka': aiokafka}): results = asyncio.run(publish_twice())
            self.assertEqual(len(producers), 1)
            self.assertEqual(producers[0].start_calls, 1)
            self.assertEqual(producers[0].messages, [b'one', b'two'])
            self.assertTrue(all('publishLatencyMs' in result for result in results))
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
            first = asyncio.run(runtime.messaging('pubsub', {'resourceId': 'p', 'topic': 'events', 'data': 'one'}, context(resource)))
            second = asyncio.run(runtime.messaging('pubsub', {'resourceId': 'p', 'topic': 'events', 'data': 'two'}, context(resource)))
        self.assertEqual(len(clients), 1)
        self.assertEqual([first['MessageID'], second['MessageID']], ['message-1', 'message-2'])
        self.assertEqual(clients[0].stop_calls, 0)
        runtime.close_publishers()
        self.assertEqual(clients[0].stop_calls, 1)


if __name__ == '__main__':
    unittest.main()
