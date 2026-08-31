from __future__ import annotations

import json
import ssl
import uuid
from typing import Any


class AmqpAdapterError(RuntimeError):
    def __init__(self, message: str, fault_type: str = "AMQPPluginException"):
        super().__init__(message)
        self.fault_type = fault_type


def _host_port(config: dict) -> tuple[str, int]:
    value = str(config.get("hostPort") or config.get("host") or "localhost:5672").split(",")[0].strip()
    if ":" in value:
        host, port = value.rsplit(":", 1)
        return host, int(port)
    return value, int(config.get("port") or (5671 if config.get("sslEnabled") else 5672))


def _rabbit_connection(config: dict):
    try:
        import pika
    except ImportError as exc:
        raise AmqpAdapterError("RabbitMQ AMQP 0.9.1 requires the pika package", "AMQPConnectionException") from exc
    host, port = _host_port(config)
    credentials = pika.PlainCredentials(str(config.get("username") or "guest"), str(config.get("password") or "guest"))
    ssl_options = None
    if config.get("sslEnabled"):
        context = ssl.create_default_context(cafile=config.get("caFile") or None)
        if config.get("clientCertificateFile") and config.get("clientKeyFile"):
            context.load_cert_chain(config.get("clientCertificateFile"), config.get("clientKeyFile"), config.get("clientKeyPassword") or None)
        ssl_options = pika.SSLOptions(context, host)
    parameters = pika.ConnectionParameters(host=host, port=port, virtual_host=config.get("virtualHost") or "/", credentials=credentials, socket_timeout=float(config.get("connectionTimeoutMsec") or 30000) / 1000, heartbeat=int(config.get("heartbeatSeconds") or 60), connection_attempts=max(1, int(config.get("retryAttempts") or 1)), retry_delay=float(config.get("retryIntervalMsec") or 3000) / 1000, ssl_options=ssl_options)
    return pika.BlockingConnection(parameters)


def _address(config: dict, activity: dict) -> str:
    return str(activity.get("queueName") or activity.get("topicName") or activity.get("entityName") or config.get("entityName") or "default")


def _azure_client(config: dict):
    try:
        from azure.servicebus import ServiceBusClient
        from azure.identity import ClientSecretCredential, ManagedIdentityCredential
    except ImportError as exc:
        raise AmqpAdapterError("Azure Service Bus requires azure-servicebus and azure-identity", "AMQPConnectionException") from exc
    connection_string = str(config.get("connectionString") or "").strip()
    authentication = str(config.get("authenticationType") or "SAS")
    if authentication == "SAS":
        if not connection_string:
            endpoint = str(config.get("hostPort") or "").strip()
            key_name = str(config.get("sharedAccessKeyName") or "").strip()
            key = str(config.get("sharedAccessKey") or "").strip()
            if endpoint and key_name and key:
                endpoint = endpoint if endpoint.startswith("sb://") else f"sb://{endpoint}"
                connection_string = f"Endpoint={endpoint.rstrip('/')}/;SharedAccessKeyName={key_name};SharedAccessKey={key}"
        if not connection_string:
            raise AmqpAdapterError("Azure SAS requires a connection string or endpoint and shared-access credentials", "AMQPConnectionException")
        return ServiceBusClient.from_connection_string(connection_string)
    namespace = connection_string.removeprefix("sb://").split("/", 1)[0].rstrip(";")
    if not namespace:
        raise AmqpAdapterError("Azure OAuth and managed identity require a fully qualified Service Bus namespace", "AMQPConnectionException")
    client_id = str(config.get("azureClientId") or "").strip() or None
    if authentication == "OAuth":
        tenant_id = str(config.get("tenantId") or "").strip()
        secret = str(config.get("clientSecret") or "").strip()
        if not tenant_id or not client_id or not secret:
            raise AmqpAdapterError("Azure OAuth requires tenant ID, client ID, and client secret", "AMQPConnectionException")
        credential = ClientSecretCredential(tenant_id, client_id, secret)
    else:
        credential = ManagedIdentityCredential(client_id=client_id)
    return ServiceBusClient(namespace, credential)


def _azure_receiver(client, config: dict, activity: dict, receive_mode):
    entity_type = str(activity.get("entityType") or config.get("entityType") or "Queue")
    entity_name = _address(config, activity)
    options = {"receive_mode": receive_mode, "prefetch_count": int(activity.get("prefetchCount") or 20)}
    if entity_type == "Topic":
        subscription = str(activity.get("subscriptionName") or config.get("entitySubscriberName") or "").strip()
        if not subscription:
            raise AmqpAdapterError("Azure topic receiving requires a subscription name")
        return client.get_subscription_receiver(topic_name=entity_name, subscription_name=subscription, **options)
    return client.get_queue_receiver(queue_name=entity_name, **options)


def test_connection(config: dict) -> dict:
    if config.get("mode") == "memory":
        return {"ok": True, "message": "Local in-memory AMQP broker is ready"}
    broker = str(config.get("brokerType") or "Qpid-1-0")
    if broker == "AzureSB-1-0":
        try:
            from azure.servicebus import ServiceBusReceiveMode
            client = _azure_client(config)
            client.__enter__()
            receiver = _azure_receiver(client, config, config, ServiceBusReceiveMode.PEEK_LOCK)
            receiver.__enter__()
            receiver.peek_messages(max_message_count=1)
            receiver.__exit__(None, None, None)
            client.__exit__(None, None, None)
            return {"ok": True, "message": "Azure Service Bus AMQP 1.0 connection succeeded"}
        except AmqpAdapterError:
            raise
        except Exception as exc:
            raise AmqpAdapterError(str(exc), "AMQPConnectionException") from exc
    if broker == "RabbitMQ" and str(config.get("amqpVersion") or "AMQP-0-9-1") == "AMQP-0-9-1":
        connection = _rabbit_connection(config)
        connection.close()
        return {"ok": True, "message": "RabbitMQ AMQP 0.9.1 connection succeeded"}
    try:
        from proton.utils import BlockingConnection
        from proton import SSLDomain
    except ImportError as exc:
        raise AmqpAdapterError("AMQP 1.0 brokers require python-qpid-proton", "AMQPConnectionException") from exc
    host, port = _host_port(config)
    scheme = "amqps" if config.get("sslEnabled") else "amqp"
    connection = BlockingConnection(f"{scheme}://{host}:{port}", user=config.get("username") or None, password=config.get("password") or None, timeout=float(config.get("connectionTimeoutMsec") or 30000) / 1000)
    connection.close()
    return {"ok": True, "message": f"{broker} AMQP 1.0 connection succeeded"}


def send(config: dict, activity: dict) -> dict:
    broker = str(config.get("brokerType") or "Qpid-1-0")
    body = activity.get("body", activity.get("message", ""))
    message_id = str(activity.get("messageID") or uuid.uuid4())
    properties = activity.get("userProperties") or {}
    if isinstance(properties, list): properties = {str(item.get("name")): item.get("value") for item in properties}
    if broker == "AzureSB-1-0":
        try:
            from azure.servicebus import ServiceBusMessage
            client = _azure_client(config)
            message = ServiceBusMessage(body, application_properties=properties, message_id=message_id, correlation_id=activity.get("correlationID"), content_type=activity.get("contentType"), subject=activity.get("type"), session_id=activity.get("sessionId") or None)
            with client:
                entity = _address(config, activity)
                entity_type = str(activity.get("entityType") or config.get("entityType") or "Queue")
                sender = client.get_topic_sender(entity) if entity_type == "Topic" else client.get_queue_sender(entity)
                with sender: sender.send_messages(message)
            return {"sendResult": True, "MessageId": message_id}
        except AmqpAdapterError:
            raise
        except Exception as exc:
            raise AmqpAdapterError(str(exc), "AMQPPluginException") from exc
    if broker == "RabbitMQ" and str(config.get("amqpVersion") or "AMQP-0-9-1") == "AMQP-0-9-1":
        import pika
        connection = _rabbit_connection(config)
        try:
            channel = connection.channel()
            destination_type = activity.get("destinationType") or "Queue"
            exchange = str(activity.get("exchangeName") or "") if destination_type == "Exchange" else ""
            routing_key = str(activity.get("routingKey") or activity.get("queueName") or config.get("entityName") or "")
            if destination_type == "Queue" and routing_key: channel.queue_declare(queue=routing_key, durable=activity.get("deliveryMode", "Persistent") == "Persistent")
            channel.basic_publish(exchange=exchange, routing_key=routing_key, body=body if isinstance(body, bytes) else str(body).encode(), properties=pika.BasicProperties(message_id=message_id, content_type=activity.get("contentType"), correlation_id=activity.get("correlationID"), type=activity.get("type"), priority=int(activity.get("priority") or 4), expiration=str(activity.get("expiration") or 0) or None, delivery_mode=2 if activity.get("deliveryMode", "Persistent") == "Persistent" else 1, headers=properties))
        finally: connection.close()
        return {"sendResult": True, "MessageId": message_id}
    try:
        from proton import Message
        from proton.utils import BlockingConnection
    except ImportError as exc:
        raise AmqpAdapterError("AMQP 1.0 sending requires python-qpid-proton") from exc
    host, port = _host_port(config); scheme = "amqps" if config.get("sslEnabled") else "amqp"
    connection = BlockingConnection(f"{scheme}://{host}:{port}", user=config.get("username") or None, password=config.get("password") or None, timeout=float(config.get("connectionTimeoutMsec") or 30000) / 1000)
    try:
        sender = connection.create_sender(_address(config, activity))
        sender.send(Message(body=body, id=message_id, correlation_id=activity.get("correlationID"), content_type=activity.get("contentType"), properties=properties, durable=activity.get("deliveryMode", "Persistent") == "Persistent", priority=int(activity.get("priority") or 4), ttl=int(activity.get("expiration") or 0) or None))
    finally: connection.close()
    return {"sendResult": True, "MessageId": message_id}


def get(config: dict, activity: dict) -> tuple[dict | None, Any]:
    broker = str(config.get("brokerType") or "Qpid-1-0")
    client_ack = str(activity.get("acknowledgeMode") or "Auto") != "Auto"
    if broker == "AzureSB-1-0":
        try:
            from azure.servicebus import ServiceBusReceiveMode
            mode = ServiceBusReceiveMode.PEEK_LOCK if client_ack else ServiceBusReceiveMode.RECEIVE_AND_DELETE
            client = _azure_client(config); client.__enter__()
            receiver = _azure_receiver(client, config, activity, mode); receiver.__enter__()
            messages = receiver.receive_messages(max_message_count=1, max_wait_time=float(activity.get("receiveTimeoutSeconds") or 1))
            if not messages:
                receiver.__exit__(None, None, None); client.__exit__(None, None, None)
                return None, None
            message = messages[0]
            def settle(dead: bool = False):
                try:
                    if dead:
                        receiver.dead_letter_message(message, reason=str(activity.get("deadLetterReason") or "Rejected by process"), error_description=str(activity.get("deadLetterDescription") or ""))
                    else: receiver.complete_message(message)
                finally:
                    receiver.__exit__(None, None, None); client.__exit__(None, None, None)
            output = {"UserProperties": dict(message.application_properties or {}), "MessageProperties": {"deliveryMode": True, "messageID": str(message.message_id or ""), "expiration": message.expires_at_utc.isoformat() if message.expires_at_utc else None, "contentType": message.content_type, "correlationID": str(message.correlation_id or ""), "type": message.subject, "sessionId": message.session_id}, "body": str(message), "messageId": str(message.message_id or uuid.uuid4()), "deliveryCount": message.delivery_count, "lockToken": str(message.lock_token or "")}
            return output, settle if client_ack else None
        except AmqpAdapterError:
            raise
        except Exception as exc:
            raise AmqpAdapterError(str(exc), "AMQPPluginException") from exc
    if broker == "RabbitMQ" and str(config.get("amqpVersion") or "AMQP-0-9-1") == "AMQP-0-9-1":
        connection = _rabbit_connection(config); channel = connection.channel(); queue = _address(config, activity)
        channel.basic_qos(prefetch_count=int(activity.get("prefetchCount") or 20)); method, props, body = channel.basic_get(queue=queue, auto_ack=not client_ack)
        if not method: connection.close(); return None, None
        callback = (lambda dead=False: (channel.basic_nack(method.delivery_tag, requeue=False) if dead else channel.basic_ack(method.delivery_tag), connection.close())) if client_ack else None
        output = {"UserProperties": props.headers or {}, "MessageProperties": {"deliveryMode": props.delivery_mode == 2, "messageID": props.message_id, "timestamp": props.timestamp, "expiration": props.expiration, "priority": props.priority, "type": props.type, "contentType": props.content_type, "correlationID": props.correlation_id}, "body": body.decode(errors="replace") if activity.get("messageType", "TextMessage") != "BytesMessage" else body, "messageId": props.message_id or str(uuid.uuid4())}
        return output, callback
    try:
        from proton.utils import BlockingConnection
    except ImportError as exc: raise AmqpAdapterError("AMQP 1.0 receiving requires python-qpid-proton") from exc
    host, port = _host_port(config); scheme = "amqps" if config.get("sslEnabled") else "amqp"
    connection = BlockingConnection(f"{scheme}://{host}:{port}", user=config.get("username") or None, password=config.get("password") or None, timeout=float(config.get("connectionTimeoutMsec") or 30000) / 1000)
    receiver = connection.create_receiver(_address(config, activity), credit=int(activity.get("prefetchCount") or 20), auto_accept=not client_ack)
    try: message = receiver.receive(timeout=float(activity.get("receiveTimeoutSeconds") or 1))
    except Exception: connection.close(); return None, None
    callback = (lambda dead=False: (receiver.reject(message) if dead else receiver.accept(message), connection.close())) if client_ack else None
    if not client_ack: connection.close()
    return {"UserProperties": message.properties or {}, "MessageProperties": {"deliveryMode": bool(message.durable), "messageID": str(message.id or ""), "expiration": message.ttl, "priority": message.priority, "contentType": message.content_type, "correlationID": str(message.correlation_id or "")}, "body": message.body, "messageId": str(message.id or uuid.uuid4())}, callback


amqp_adapter = type("AmqpAdapter", (), {"test": staticmethod(test_connection), "send": staticmethod(send), "get": staticmethod(get)})()
