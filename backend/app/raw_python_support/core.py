"""Small, dependency-light execution primitives for generated async tasks."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any


REFERENCE = re.compile(r'^\$\{([^}]+)\}$')
_GROUP_LOCKS: dict[str, asyncio.Lock] = {}


def group_lock(name: str) -> asyncio.Lock:
    return _GROUP_LOCKS.setdefault(name, asyncio.Lock())


@dataclass(frozen=True)
class Reference:
    path: str


@dataclass(frozen=True)
class Template:
    parts: tuple[str | Reference, ...]


@dataclass
class Context:
    input: Any
    properties: dict[str, Any]
    resources: dict[str, Any]
    last: Any = None
    variables: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    transactions: dict[str, Any] = field(default_factory=dict)
    transport: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    environment_name: str = 'local'
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.last = self.input

    def record(self, activity_id: str, result: Any) -> None:
        self.last = result
        self.outputs[activity_id] = {'output': result}

    def fork(self) -> 'Context':
        """Give a parallel branch its own flow values and shared output index."""
        child = Context(self.last, self.properties, self.resources)
        child.variables = dict(self.variables)
        child.outputs = self.outputs
        child.transactions = self.transactions
        child.transport = self.transport
        child.attributes = dict(self.attributes)
        child.environment_name = self.environment_name
        child.error = self.error
        return child


def lookup(path: str, ctx: Context) -> Any:
    head, _, rest = path.partition('.')
    if head == 'properties' and rest in ctx.properties:
        return ctx.properties[rest]
    value = {'input': ctx.input, 'last': ctx.last, 'properties': ctx.properties,
             'vars': ctx.variables, 'activities': ctx.outputs}.get(head)
    if head not in {'input', 'last', 'properties', 'vars', 'activities'}:
        if head in ctx.outputs: value = ctx.outputs[head].get('output')
        else: raise KeyError(f'Unknown expression root: {head}')
    for part in rest.split('.') if rest else []:
        if isinstance(value, dict): value = value[part]
        elif isinstance(value, (list, tuple)): value = value[int(part)]
        else: value = getattr(value, part)
    return value


def resolve(value: Any, ctx: Context) -> Any:
    if isinstance(value, Reference): return lookup(value.path, ctx)
    if isinstance(value, Template): return ''.join(str(resolve(part, ctx)) for part in value.parts)
    if isinstance(value, str):
        match = REFERENCE.fullmatch(value)
        if match: return lookup(match.group(1), ctx)
        return re.sub(r'\$\{([^}]+)\}', lambda item: str(lookup(item.group(1), ctx)), value)
    if isinstance(value, dict): return {key: resolve(child, ctx) for key, child in value.items()}
    if isinstance(value, list): return [resolve(child, ctx) for child in value]
    return value


def assign_path(target: dict, path: str, value: Any) -> None:
    parts = path.split('.')
    cursor = target
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _cron_matches(field: str, value: int, minimum: int, maximum: int) -> bool:
    for item in field.split(','):
        base, _, step_text = item.strip().partition('/')
        step = int(step_text or 1)
        if step < 1: raise ValueError('Cron step must be positive')
        if base == '*': start, end = minimum, maximum
        elif '-' in base: start, end = (int(piece) for piece in base.split('-', 1))
        else: start = end = int(base)
        if start < minimum or end > maximum or start > end: raise ValueError(f'Invalid cron field {item!r}')
        if start <= value <= end and (value - start) % step == 0: return True
    return False


def _next_cron(expression: str, now: datetime) -> datetime:
    fields = expression.split()
    if len(fields) != 5: raise ValueError('Cron schedule needs five fields')
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(527040):
        weekday = (candidate.weekday() + 1) % 7
        if all(_cron_matches(field, value, minimum, maximum) for field, value, minimum, maximum in zip(
            fields, (candidate.minute, candidate.hour, candidate.day, candidate.month, weekday),
            (0, 0, 1, 1, 0), (59, 23, 31, 12, 6))):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError('Cron schedule has no occurrence within one year')


def mapped(config: dict, ctx: Context) -> dict:
    result = {}
    for path, expression in (config.get('inputMappings') or {}).items():
        assign_path(result, path, resolve(expression, ctx))
    return result


def choose_transition(edges: list[dict], source: str, ctx: Context, error: Exception | None = None) -> str | None:
    outgoing = [edge for edge in edges if edge['source'] == source]
    if error is not None:
        return next((edge['target'] for edge in outgoing if edge.get('type') == 'error'), None)
    conditional = [edge for edge in outgoing if edge.get('type') == 'success_condition']
    for edge in conditional:
        condition = edge.get('condition') or False
        if isinstance(condition, str) and condition.lower() in {'true', 'false'}:
            condition = condition.lower() == 'true'
        if bool(resolve(condition, ctx)):
            return edge['target']
    if conditional:
        return next((edge['target'] for edge in outgoing if edge.get('type') == 'success_no_match'), None)
    return next((edge['target'] for edge in outgoing if edge.get('type', 'success') == 'success'), None)


async def execute_with_policy(kind: str, raw: dict, ctx: Context, activity_id: str, name: str) -> Any:
    advanced = resolve(raw.get('advanced') or {}, ctx)
    policy = resolve(raw.get('errorPolicy') or {}, ctx)
    outbound = False  # OUTBOUND_RETRY_EXPRESSION
    retry_enabled = advanced.get('retryEnabled', ctx.properties.get('advanced.retryEnabled', False))
    attempts = 1 + max(0, int(advanced.get('retryCount', ctx.properties.get('advanced.retryCount', 3)) or 0)) if outbound and retry_enabled else 1
    if policy.get('action') == 'retry':
        attempts = 1 + max(0, int(policy.get('retryCount') or 0))
    delay = float(advanced.get('retryIntervalSeconds', ctx.properties.get('advanced.retryIntervalSeconds', 60)) or 0) if outbound and retry_enabled else float(policy.get('retryDelay') or 0) / 1000
    for attempt in range(attempts):
        try:
            result = await execute(kind, raw, ctx, activity_id, name)
            if raw.get('outputName'): ctx.variables[str(raw['outputName'])] = result
            return result
        except Exception:
            if attempt + 1 < attempts:
                logging.warning('%s failed; retry %s of %s in %s seconds', name, attempt + 1, attempts - 1, delay)
                if delay: await asyncio.sleep(delay)
                continue
            if policy.get('action') == 'ignore': return ctx.last
            if policy.get('action') == 'continue': return {'type': 'ActivityError', 'activityId': activity_id}
            raise


async def execute(kind: str, raw: dict, ctx: Context, activity_id: str, name: str) -> Any:
    """Execute supported Python-native operations; never load Fabric JSON or DSL."""
    cfg = resolve({key: value for key, value in raw.items() if key != 'inputMappings'}, ctx)
    for key, value in mapped(raw, ctx).items():
        cfg[key] = value
    operation = str(cfg.get('operation') or '')
    if kind == 'start': return mapped(raw, ctx).get('payload', ctx.input)
    if kind == 'end': return mapped(raw, ctx).get('result', ctx.last)
    if kind == 'catch':
        if not ctx.error: return ctx.last
        return {'type': getattr(ctx.error, 'fault_type', type(ctx.error).__name__),
                'code': str(getattr(ctx.error, 'code', '') or ''), 'message': str(ctx.error),
                'details': getattr(ctx.error, 'details', {}) or {}, 'stackTrace': ''}
    # CAPABILITY timer START
    if kind == 'timer':
        now = datetime.now(timezone.utc)
        run_once = bool(cfg.get('runOnceOnLocalStart', True)) and ctx.environment_name == 'local'
        mode = str(cfg.get('scheduleMode') or 'dateTime')
        if run_once:
            scheduled, trigger_mode = now, 'local-run-once'
        elif mode == 'cron':
            scheduled, trigger_mode = _next_cron(str(cfg.get('cronExpression') or ''), now), 'cron'
        else:
            raw_time = str(cfg.get('scheduledDateTime') or '')
            if not raw_time: raise ValueError('Scheduler needs a date/time or a local Run once setting')
            scheduled = datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
            if scheduled.tzinfo is None: scheduled = scheduled.astimezone()
            scheduled, trigger_mode = scheduled.astimezone(timezone.utc), 'dateTime'
        delay = max(0.0, (scheduled - now).total_seconds())
        if delay: await asyncio.sleep(delay)
        return {'scheduledTime': scheduled.isoformat(), 'actualTime': datetime.now(timezone.utc).isoformat(),
                'sequence': 1, 'triggerMode': trigger_mode, 'payload': ctx.last}
    # CAPABILITY timer END
    # CAPABILITY confirm START
    if kind == 'confirm':
        from . import connectors
        delivery = ctx.transport
        delivery_id, listener_key = delivery.get('deliveryId'), delivery.get('listenerKey')
        if not delivery_id or not listener_key:
            if cfg.get('failIfMissing', True): raise RuntimeError('Confirm Message requires an active acknowledgement handle')
            return {'confirmed': False, 'count': 0}
        if str(cfg.get('ackId') or cfg.get('acknowledgementHandle') or delivery_id) != str(delivery_id):
            raise RuntimeError('Confirm Message acknowledgement handle does not match the active delivery')
        if delivery.get('completed'): raise RuntimeError('Delivery was already confirmed')
        if delivery.get('technology') == 'sap':
            await asyncio.to_thread(connectors.acknowledge_sap, listener_key, delivery_id, True)
        else:
            connectors.acknowledge_jms(listener_key, delivery_id, True)
        delivery['completed'] = True
        return {'confirmed': True, 'count': 1, 'ackIds': [str(delivery_id)]}
    # CAPABILITY confirm END
    # CAPABILITY faults START
    if kind in {'throw', 'rethrow'}:
        if kind == 'rethrow' and ctx.error: raise ctx.error
        raise RuntimeError(str(cfg.get('message') or 'Business fault'))
    # CAPABILITY faults END
    # CAPABILITY log START
    if kind == 'log':
        level = str(cfg.get('level') or 'INFO').upper()
        message = cfg.get('message') or f'{name} payload'
        payload = cfg.get('payload', ctx.last)
        logging.log(getattr(logging, level, logging.INFO), '%s%s', message,
                    f' | payload={json.dumps(payload, default=str)}' if cfg.get('includePayload') else '')
        return ctx.last
    # CAPABILITY log END
    # CAPABILITY basic START
    if kind == 'basic':
        if operation == 'empty': return ctx.last
        if operation == 'assign':
            key = str(cfg.get('variable') or '')
            if not key: raise ValueError('Assign Variable needs a name')
            ctx.variables[key] = cfg.get('value', ctx.last)
            return {'name': key, 'value': ctx.variables[key]}
        if operation == 'sleep':
            duration = float(cfg.get('duration') or 0)
            unit = str(cfg.get('unit') or 'milliseconds')
            seconds = duration * (60 if unit == 'minutes' else 1 if unit == 'seconds' else .001)
            await asyncio.sleep(max(0, seconds))
            return {'sleptMilliseconds': round(seconds * 1000), 'payload': ctx.last}
        if operation == 'checkpoint':
            from uuid import uuid4
            return {'checkpointId': str(uuid4()), 'name': str(cfg.get('checkpointName') or name),
                    'timestamp': datetime.now(timezone.utc).isoformat(), 'activityId': activity_id}
        if operation in {'get_shared_variable', 'set_shared_variable'}:
            from . import activities
            return activities.shared_variable(operation, cfg, ctx.last)
        if operation == 'external_command':
            from . import activities
            return await activities.external_command(cfg)
    # CAPABILITY basic END
    # CAPABILITY mapper START
    if kind == 'mapper':
        from .native.mapper import execute as execute_mapping
        mappings = raw.get('mappings') or []
        rules = [{'target': key, 'source': value} for key, value in mappings.items()] if isinstance(mappings, dict) else mappings
        normalized = []
        for rule in rules:
            if not isinstance(rule, dict): continue
            item = dict(rule)
            for field_name in ('source', 'select', 'condition'):
                value = item.get(field_name)
                if isinstance(value, Reference): item[field_name] = value.path
                elif isinstance(value, Template): item[field_name] = resolve(value, ctx)
            if 'constant' in item: item['constant'] = resolve(item['constant'], ctx)
            normalized.append(item)
        document = {'input': ctx.input, 'last': ctx.last, 'properties': ctx.properties,
                    'vars': ctx.variables, 'activities': ctx.outputs, **(ctx.input if isinstance(ctx.input, dict) else {})}
        return execute_mapping(document, normalized, cfg)
    # CAPABILITY mapper END
    # CAPABILITY call_task START
    if kind == 'call_task':
        from .registry import TASKS
        target = str(cfg.get('taskId') or '')
        values = mapped(raw, ctx)
        child = Context(values or ctx.last, ctx.properties, ctx.resources)
        return await TASKS[target](child)
    # CAPABILITY call_task END
    # CAPABILITY file START
    if kind == 'file':
        from . import activities
        return await asyncio.to_thread(activities.file_activity, operation, cfg, ctx.last)
    # CAPABILITY file END
    # CAPABILITY data_formats START
    if kind in {'xml', 'json', 'flat'}:
        from . import activities
        return activities.data_activity(kind, operation, cfg, ctx.last)
    # CAPABILITY data_formats END
    # CAPABILITY excel START
    if kind == 'excel':
        from . import activities
        return await asyncio.to_thread(activities.excel_read, cfg)
    # CAPABILITY excel END
    # CAPABILITY transfer START
    if kind in {'ftp', 'sftp'}:
        from . import activities
        resource_id = str(cfg.get('resourceId') or '')
        resource = ctx.resources.get(resource_id)
        if not resource or resource.type != kind: raise ValueError(f'{name} requires a shared {kind.upper()} connection')
        return await asyncio.to_thread(activities.transfer, kind, operation, resolve(resource.config, ctx), cfg)
    # CAPABILITY transfer END
    # CAPABILITY inbound_http START
    if kind == 'http_listener' or kind == 'rest' and operation == 'receiver' or kind == 'soap' and operation == 'service':
        return ctx.input
    # CAPABILITY inbound_http END
    # CAPABILITY http_client START
    if kind in {'http', 'rest', 'soap'}:
        from . import activities
        resource = ctx.resources.get(str(cfg.get('resourceId') or ''))
        connection = resolve(resource.config, ctx) if resource else {}
        request_cfg = dict(cfg)
        if kind == 'soap':
            request_cfg['method'] = 'POST'; request_cfg['body'] = cfg.get('envelope', ctx.last)
            request_cfg['headers'] = {'Content-Type': cfg.get('contentType') or 'text/xml; charset=utf-8', **(cfg.get('headers') or {})}
            if cfg.get('soapAction'): request_cfg['headers']['SOAPAction'] = cfg['soapAction']
        return await asyncio.to_thread(activities.http_request, request_cfg, connection)
    # CAPABILITY http_client END
    # CAPABILITY http_response START
    if kind == 'http_response':
        return {'statusCode': int(cfg.get('statusCode') or 200), 'headers': cfg.get('headers') or {},
                'body': cfg.get('body', ctx.last), 'sent': True}
    # CAPABILITY http_response END
    # CAPABILITY dataweave START
    if kind == 'dataweave':
        from .native.dataweave import execute as transform
        transformed = await asyncio.to_thread(transform, str(cfg.get('script') or '%dw 2.0\noutput application/json\n---\npayload'),
                                                payload=cfg.get('payload', ctx.last), attributes=cfg.get('attributes', ctx.attributes),
                                                variables={**ctx.variables, **(cfg.get('variables') or {})}, input_mime_type=str(cfg.get('inputMimeType') or ''))
        target = str(cfg.get('outputTarget') or 'payload').lower()
        if target == 'attributes': ctx.attributes = transformed
        elif target == 'variable':
            variable = str(cfg.get('outputVariable') or 'transformResult').strip()
            if not variable: raise ValueError('A variable output target requires a variable name')
            ctx.variables[variable] = transformed
        return transformed
    # CAPABILITY dataweave END
    # CAPABILITY python START
    if kind == 'python':
        from . import activities
        return await activities.python_invoke(cfg, ctx.last)
    # CAPABILITY python END
    # CAPABILITY java START
    if kind == 'java':
        from . import activities
        return await activities.java_invoke(cfg, ctx.last)
    # CAPABILITY java END
    # CAPABILITY kafka START
    if kind == 'kafka':
        from . import connectors
        resource_id = str(cfg.get('resourceId') or '')
        resource = ctx.resources.get(resource_id)
        if not resource: raise ValueError(f'{name} requires a shared {kind} connection')
        connection = resolve(resource.config, ctx)
        return await connectors.kafka(operation, connection, cfg, ctx.last)
    # CAPABILITY kafka END
    # CAPABILITY pubsub START
    if kind == 'pubsub':
        from . import connectors
        resource_id = str(cfg.get('resourceId') or '')
        resource = ctx.resources.get(resource_id)
        if not resource: raise ValueError(f'{name} requires a shared Pub/Sub connection')
        return await connectors.pubsub(operation, resolve(resource.config, ctx), cfg, ctx.last)
    # CAPABILITY pubsub END
    # CAPABILITY sap START
    if kind == 'sap':
        from . import connectors
        resource_id = str(cfg.get('resourceId') or '')
        resource = ctx.resources.get(resource_id)
        if not resource or resource.type != 'sap':
            raise ValueError(f'{name} requires a shared SAP connection')
        connection = resolve(resource.config, ctx)
        source = str(cfg.get('messagingSource') or 'NoMessaging').strip().lower().replace(' ', '')
        if operation == 'idoc_listener' and source not in {'', 'nomessaging', 'direct', 'sapjcorfc/idoc_inbound_asynchronous'}:
            technology = {'ems': 'ems', 'jms': 'jms', 'kafka': 'kafka'}.get(source)
            if not technology: raise ValueError(f'Unsupported SAP IDoc messaging source: {cfg.get("messagingSource")}')
            broker_resource = ctx.resources.get(str(cfg.get('messagingResourceId') or ''))
            if not broker_resource or broker_resource.type != technology:
                raise ValueError(f'{name} requires a shared {technology.upper()} messaging connection')
            broker_connection = resolve(broker_resource.config, ctx)
            destination = cfg.get('messagingDestination') or cfg.get('destination') or cfg.get('topic')
            broker_cfg = {**cfg, 'destination': destination, 'topic': destination, 'maxMessages': 1}
            if technology == 'kafka': received = await connectors.kafka('receive', broker_connection, broker_cfg, ctx.last)
            else: received = await connectors.jms(technology, 'queue_receiver' if technology == 'ems' else 'receive_message', broker_connection, broker_cfg, ctx.last, ctx)
            messages = received.get('messages') if isinstance(received, dict) else []
            first = messages[0] if isinstance(messages, list) and messages else {}
            broker_payload = received.get('body') if technology in {'ems', 'jms'} else (first.get('data') if isinstance(first, dict) else first)
            properties = received.get('properties') or {}
            return {**received, 'payload': broker_payload, 'SAPIDoc': properties.get('SAPIDoc', {}) if isinstance(properties, dict) else {}, 'messagingSource': technology.upper()}
        return await connectors.sap(operation, connection, cfg, cfg.get('payload', ctx.last), ctx)
    # CAPABILITY sap END
    # CAPABILITY jms START
    if kind in {'ems', 'jms'}:
        from . import connectors
        resource_id = str(cfg.get('resourceId') or '')
        resource = ctx.resources.get(resource_id)
        if not resource or resource.type != kind: raise ValueError(f'{name} requires a shared {kind.upper()} connection')
        connection = resolve(resource.config, ctx)
        cfg['_activityId'] = activity_id
        return await connectors.jms(kind, operation, connection, cfg, cfg.get('data', cfg.get('message', ctx.last)), ctx)
    # CAPABILITY jms END
    # CAPABILITY jdbc START
    if kind == 'jdbc':
        from . import connectors
        resource_id = str(cfg.get('resourceId') or '')
        resource = ctx.resources.get(resource_id)
        if not resource or resource.type != 'jdbc':
            raise ValueError(f'{name} requires a shared JDBC connection')
        return await connectors.jdbc(resolve(resource.config, ctx), cfg, ctx.transactions.get(resource_id))
    # CAPABILITY jdbc END
    # CAPABILITY snowflake START
    if kind == 'snowflake':
        from . import connectors
        resource_id = str(cfg.get('resourceId') or '')
        resource = ctx.resources.get(resource_id)
        if not resource or resource.type != 'snowflake': raise ValueError(f'{name} requires a shared Snowflake connection')
        return await connectors.snowflake(operation, resolve(resource.config, ctx), cfg, ctx.last)
    # CAPABILITY snowflake END
    # CAPABILITY amqp START
    if kind == 'amqp':
        from . import connectors
        resource_id = str(cfg.get('resourceId') or '')
        resource = ctx.resources.get(resource_id)
        if not resource or resource.type != 'amqp': raise ValueError(f'{name} requires a shared AMQP connection')
        return await connectors.amqp(operation, resolve(resource.config, ctx), cfg, ctx.last)
    # CAPABILITY amqp END
    raise NotImplementedError(f'Raw Python operation is not implemented: {kind}/{operation}')
