"""Python-native connector implementations for generated applications.

Optional client packages are imported only when their connector is used.
No Integration Fabric runtime, bridge, DSL, or project descriptor is required.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any


_MEMORY_KAFKA: dict[str, asyncio.Queue] = {}


async def kafka(operation: str, connection: dict, cfg: dict, payload: Any) -> dict:
    topic = str(cfg.get('topic') or connection.get('topic') or '')
    if not topic: raise ValueError('Kafka topic is required')
    if connection.get('mode') == 'memory':
        queue = _MEMORY_KAFKA.setdefault(topic, asyncio.Queue())
        if operation == 'publish':
            message = cfg.get('message', payload)
            await queue.put(message)
            return {'topic': topic, 'published': True, 'message': message}
        if operation == 'receive':
            count = max(1, int(cfg.get('maxMessages') or 1))
            values = [await queue.get()]
            for _ in range(count - 1):
                if queue.empty(): break
                values.append(queue.get_nowait())
            return {'topic': topic, 'count': len(values), 'messages': values}
    try:
        from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
    except ImportError as error:
        raise RuntimeError('Kafka requires the optional aiokafka package') from error
    servers = connection.get('bootstrapServers') or connection.get('bootstrap_servers') or 'localhost:9092'
    if operation == 'publish':
        producer = AIOKafkaProducer(bootstrap_servers=servers)
        await producer.start()
        try:
            message = cfg.get('message', payload)
            data = message if isinstance(message, bytes) else json.dumps(message, default=str).encode()
            metadata = await producer.send_and_wait(topic, data)
            return {'topic': topic, 'partition': metadata.partition, 'offset': metadata.offset, 'published': True}
        finally:
            await producer.stop()
    if operation == 'receive':
        consumer = AIOKafkaConsumer(topic, bootstrap_servers=servers,
                                   group_id=cfg.get('groupId') or connection.get('groupId'),
                                   enable_auto_commit=bool(cfg.get('autoCommit', True)))
        await consumer.start()
        try:
            batch = await consumer.getmany(timeout_ms=int(cfg.get('timeoutMs') or 30000),
                                           max_records=max(1, int(cfg.get('maxMessages') or 1)))
            values = [record.value.decode(errors='replace') for records in batch.values() for record in records]
            return {'topic': topic, 'count': len(values), 'messages': values}
        finally:
            await consumer.stop()
    raise ValueError(f'Unsupported Kafka operation: {operation}')


async def pubsub(operation: str, connection: dict, cfg: dict, payload: Any) -> dict:
    try:
        from google.cloud import pubsub_v1
        from google.oauth2 import service_account
    except ImportError as error:
        raise RuntimeError('Pub/Sub requires google-cloud-pubsub and google-auth') from error
    credentials = None
    service_account_json = connection.get('serviceAccountJson') or connection.get('serviceAccount')
    if service_account_json:
        info = json.loads(service_account_json) if isinstance(service_account_json, str) else service_account_json
        credentials = service_account.Credentials.from_service_account_info(info)
    project_id = str(cfg.get('projectId') or connection.get('projectId') or '')
    if not project_id: raise ValueError('Pub/Sub projectId is required')
    if operation == 'publish':
        topic = str(cfg.get('topic') or '')
        client = pubsub_v1.PublisherClient(credentials=credentials)
        path = topic if topic.startswith('projects/') else client.topic_path(project_id, topic)
        value = cfg.get('message', payload)
        data = value if isinstance(value, bytes) else json.dumps(value, default=str).encode()
        message_id = await asyncio.to_thread(lambda: client.publish(path, data).result())
        return {'topic': path, 'messageId': message_id, 'published': True}
    if operation == 'pull':
        subscription = str(cfg.get('subscription') or '')
        client = pubsub_v1.SubscriberClient(credentials=credentials)
        path = subscription if subscription.startswith('projects/') else client.subscription_path(project_id, subscription)
        response = await asyncio.to_thread(client.pull, request={'subscription': path, 'max_messages': max(1, int(cfg.get('maxMessages') or 1))}, timeout=float(cfg.get('timeoutSeconds') or 30))
        values = [{'data': item.message.data.decode(errors='replace'), 'ackId': item.ack_id} for item in response.received_messages]
        return {'subscription': path, 'count': len(values), 'messages': values}
    raise ValueError(f'Unsupported Pub/Sub operation: {operation}')
