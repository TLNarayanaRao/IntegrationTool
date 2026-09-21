"""Python-native connector implementations for generated applications.

Optional client packages are imported only when their connector is used.
No Integration Fabric runtime, bridge, DSL, or project descriptor is required.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any


_MEMORY_KAFKA: dict[str, asyncio.Queue] = {}
_MEMORY_JMS: dict[tuple[str, str], asyncio.Queue] = {}
_JMS_LISTENERS: dict[str, Any] = {}
_MEMORY_ACKS: dict[str, tuple[asyncio.Queue, Any]] = {}
_AMQP_SETTLEMENTS: dict[str, Any] = {}


async def jms(kind: str, operation: str, connection: dict, cfg: dict, payload: Any, ctx=None) -> dict:
    """Direct Python task to JMS bridge; licensed provider JARs remain external."""
    receive = operation in {'queue_receiver', 'topic_subscriber', 'receive_message', 'get_queue_message', 'wait_request'}
    send = operation in {'send', 'publish', 'send_message', 'reply', 'reply_message'}
    request_reply = operation == 'request_reply'
    if not (receive or send or request_reply): raise NotImplementedError(f'{kind.upper()} {operation} is unsupported')
    transport = ctx.transport if ctx is not None else {}
    destination = str(cfg.get('destination') or cfg.get('queue') or cfg.get('topic') or (transport.get('replyTo') if send else '') or '')
    if not destination: raise ValueError(f'{kind.upper()} destination is required')
    client_ack = str(cfg.get('acknowledgeMode') or 'Auto').strip().lower() not in {'auto', 'automatic'}
    if connection.get('mode') == 'memory':
        queue = _MEMORY_JMS.setdefault((kind, destination), asyncio.Queue())
        if send:
            await queue.put({'body': payload, 'correlationId': cfg.get('correlationId') or transport.get('correlationId'), 'replyTo': cfg.get('replyTo')})
            return {'destination': destination, 'published': True}
        if request_reply:
            from uuid import uuid4
            correlation_id, reply_to = str(cfg.get('correlationId') or uuid4()), str(cfg.get('replyTo') or f'_fabric.reply.{uuid4()}')
            await queue.put({'body': payload, 'correlationId': correlation_id, 'replyTo': reply_to})
            reply_queue = _MEMORY_JMS.setdefault((kind, reply_to), asyncio.Queue())
            timeout = max(.001, float(cfg.get('receiveTimeout') or cfg.get('timeoutMs') or 30000) / 1000)
            try:
                while True:
                    reply = await asyncio.wait_for(reply_queue.get(), timeout=timeout)
                    envelope = reply if isinstance(reply, dict) else {'body': reply}
                    if not envelope.get('correlationId') or envelope.get('correlationId') == correlation_id: break
            except asyncio.TimeoutError: return {'destination': destination, 'received': False, 'body': None, 'count': 0}
            return {'destination': destination, 'received': True, 'body': envelope.get('body'), 'count': 1,
                    'headers': {'JMSCorrelationID': envelope.get('correlationId')}}
        try:
            value = await asyncio.wait_for(queue.get(), timeout=max(0.001, float(cfg.get('receiveTimeout') or 30000) / 1000))
        except asyncio.TimeoutError:
            return {'destination': destination, 'body': None, 'count': 0, 'messages': []}
        envelope = value if isinstance(value, dict) and 'body' in value else {'body': value}
        output = {'destination': destination, 'body': envelope.get('body'), 'count': 1,
                  'headers': {'JMSCorrelationID': envelope.get('correlationId'), 'JMSReplyTo': envelope.get('replyTo')},
                  'properties': envelope.get('properties') or {}, 'messages': [{'data': envelope.get('body')}],
                  'correlationId': envelope.get('correlationId'), 'replyTo': envelope.get('replyTo')}
        if client_ack:
            from uuid import uuid4
            delivery_id = str(uuid4())
            _MEMORY_ACKS[delivery_id] = (queue, value)
            output.update({'ackId': delivery_id, '_jmsDeliveryId': delivery_id, '_jmsListenerKey': 'memory'})
        return output
    from .native.java_bridge import execute_jms, start_jms_listener
    options = dict(cfg)
    options['topic'] = operation in {'publish', 'topic_subscriber'} or str(cfg.get('messagingStyle') or '').lower() == 'topic'
    if receive and (client_ack or operation == 'wait_request'):
        key = f'{kind}:{cfg.get("_activityId") or destination}:{destination}'
        listener = _JMS_LISTENERS.get(key)
        if listener is None or listener.process.poll() is not None:
            if listener is not None: listener.close()
            listener = await asyncio.to_thread(start_jms_listener, connection, destination, options)
            _JMS_LISTENERS[key] = listener
        output = await listener.next_event()
        if output.get('event') == 'listening':
            return {'destination': destination, 'body': None, 'count': 0, 'messages': [], 'listening': True}
        body = output.get('body')
        try: body = json.loads(body) if isinstance(body, str) else body
        except ValueError: pass
        delivery_id = str(output.get('deliveryId') or '')
        if not delivery_id: raise RuntimeError('JMS bridge did not return a delivery identifier')
        return {**output, 'body': body, 'count': 1, 'messages': [{'data': body}],
                'replyTo': (output.get('headers') or {}).get('JMSReplyTo'),
                'correlationId': (output.get('headers') or {}).get('JMSCorrelationID'),
                'ackId': delivery_id, '_jmsDeliveryId': delivery_id, '_jmsListenerKey': key}
    if send and operation in {'reply', 'reply_message'} and transport.get('listenerKey') and transport.get('deliveryId'):
        listener = _JMS_LISTENERS.get(str(transport['listenerKey']))
        if listener is None: raise RuntimeError('Persistent JMS request session is no longer available')
        listener.reply_jms(str(transport['deliveryId']), payload); transport['completed'] = True
        return {'destination': transport.get('replyTo'), 'correlationId': transport.get('correlationId'), 'replied': True, 'published': True}
    native_operation = 'request' if request_reply else 'receive' if receive else 'send'
    if send:
        options['correlationId'] = cfg.get('correlationId') or transport.get('correlationId')
        options['replyTo'] = cfg.get('replyTo') or transport.get('replyTo')
    output = await asyncio.to_thread(execute_jms, connection, native_operation, destination,
                                     None if receive else payload, options)
    if receive:
        if not output.get('received'):
            return {'destination': destination, 'body': None, 'count': 0, 'messages': []}
        body = output.get('body')
        try: body = json.loads(body) if isinstance(body, str) else body
        except ValueError: pass
        return {**output, 'body': body, 'count': 1, 'messages': [{'data': body}]}
    if request_reply:
        body = output.get('body')
        try: body = json.loads(body) if isinstance(body, str) else body
        except ValueError: pass
        return {**output, 'body': body, 'count': 1 if output.get('received') else 0}
    return {**output, 'destination': destination, 'published': True}


def acknowledge_jms(listener_key: str, delivery_id: str, success: bool) -> None:
    if listener_key == 'memory':
        queue, value = _MEMORY_ACKS.pop(delivery_id)
        if not success: queue.put_nowait(value)
        return
    listener = _JMS_LISTENERS.get(listener_key)
    if listener is None: raise RuntimeError('Persistent JMS listener is no longer available')
    listener.acknowledge(delivery_id, success)


def close_jms() -> None:
    for listener in _JMS_LISTENERS.values(): listener.close()
    _JMS_LISTENERS.clear()


_SAP_ADAPTER = None


async def jdbc(connection: dict, cfg: dict, transaction=None) -> dict:
    from .native.jdbc import jdbc_adapter
    return await asyncio.to_thread(jdbc_adapter.execute, connection, cfg, transaction, transaction is None)


async def snowflake(operation: str, connection: dict, cfg: dict, payload: Any) -> dict:
    from .native.snowflake import snowflake_adapter
    return await asyncio.to_thread(snowflake_adapter.execute, connection, {**cfg, 'operation': operation}, payload)


async def amqp(operation: str, connection: dict, cfg: dict, payload: Any) -> dict:
    from .native.amqp import amqp_adapter
    destination = str(cfg.get('queueName') or cfg.get('topicName') or cfg.get('entityName') or connection.get('entityName') or 'default')
    if connection.get('mode') == 'memory':
        queue = _MEMORY_JMS.setdefault(('amqp', destination), asyncio.Queue())
        if operation == 'send':
            await queue.put(cfg.get('body', cfg.get('message', payload)))
            return {'sendResult': True, 'destination': destination}
        if operation in {'get', 'receive'}:
            try: body = await asyncio.wait_for(queue.get(), timeout=max(.001, float(cfg.get('receiveTimeout') or 30000) / 1000))
            except asyncio.TimeoutError: return {'received': False, 'body': None, 'UserProperties': {}, 'MessageProperties': {}}
            return {'received': True, 'body': body, 'destination': destination, 'UserProperties': {}, 'MessageProperties': {}}
    if operation == 'send':
        activity = {**cfg, 'body': cfg.get('body', cfg.get('message', payload))}
        return await asyncio.to_thread(amqp_adapter.send, connection, activity)
    if operation in {'get', 'receive'}:
        message, callback = await asyncio.to_thread(amqp_adapter.get, connection, cfg)
        if not message: return {'received': False, 'body': None, 'UserProperties': {}, 'MessageProperties': {}}
        if callback:
            from uuid import uuid4
            token = str(uuid4()); _AMQP_SETTLEMENTS[token] = callback
            message['settlementToken'] = token; message['ackId'] = token
        return {'received': True, **message}
    if operation == 'dead_letter':
        token = str(cfg.get('settlementToken') or cfg.get('ackId') or '')
        callback = _AMQP_SETTLEMENTS.pop(token, None)
        if not callback: raise RuntimeError('AMQP settlement token was not found or expired')
        result = callback(True)
        if asyncio.iscoroutine(result): await result
        return {'status': 'Success', 'settlementToken': token}
    raise ValueError(f'Unsupported AMQP operation: {operation}')


async def sap(operation: str, connection: dict, cfg: dict, payload: Any, ctx=None) -> dict:
    """Reuse the standalone SAP Python adapter with an externally installed JCo runtime."""
    global _SAP_ADAPTER
    if _SAP_ADAPTER is None:
        from .native.sap import SapAdapter
        _SAP_ADAPTER = SapAdapter()
    merged = {**connection, **cfg}
    if operation in {'idoc_listener', 'rfc_bapi_listener'}:
        return await _SAP_ADAPTER.receive_idoc(merged)
    if operation == 'reply_rfc_bapi':
        delivery = ctx.transport if ctx is not None else {}
        delivery_id, listener_key = delivery.get('deliveryId'), delivery.get('listenerKey')
        if not delivery_id or not listener_key:
            raise RuntimeError('Reply from RFC/BAPI requires an active inbound RFC delivery')
        response = payload if isinstance(payload, dict) else {'RESULT': payload}
        await asyncio.to_thread(_SAP_ADAPTER.acknowledge_idoc, listener_key, delivery_id, True, response)
        delivery['completed'] = True
        return {'replied': True, 'response': response}
    return await asyncio.to_thread(_SAP_ADAPTER.execute, operation, merged, payload)


def acknowledge_sap(listener_key: str, delivery_id: str, success: bool) -> None:
    if _SAP_ADAPTER is not None:
        _SAP_ADAPTER.acknowledge_idoc(listener_key, delivery_id, success)


def close_sap() -> None:
    if _SAP_ADAPTER is not None:
        _SAP_ADAPTER.close_all()


async def kafka(operation: str, connection: dict, cfg: dict, payload: Any) -> dict:
    operation = {'send': 'publish', 'get': 'receive'}.get(operation, operation)
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
    operation = 'pull' if operation == 'subscribe' else operation
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
