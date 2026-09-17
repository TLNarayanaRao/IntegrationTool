"""Small, dependency-light execution primitives for generated async tasks."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any


REFERENCE = re.compile(r'^\$\{([^}]+)\}$')


@dataclass
class Context:
    input: Any
    properties: dict[str, Any]
    resources: dict[str, Any]
    last: Any = None
    variables: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.last = self.input

    def record(self, activity_id: str, result: Any) -> None:
        self.last = result
        self.outputs[activity_id] = {'output': result}


def lookup(path: str, ctx: Context) -> Any:
    head, _, rest = path.partition('.')
    if head == 'properties' and rest in ctx.properties:
        return ctx.properties[rest]
    value = {'input': ctx.input, 'last': ctx.last, 'properties': ctx.properties,
             'vars': ctx.variables, 'activities': ctx.outputs}.get(head)
    if head not in {'input', 'last', 'properties', 'vars', 'activities'}:
        raise KeyError(f'Unknown expression root: {head}')
    for part in rest.split('.') if rest else []:
        if isinstance(value, dict): value = value[part]
        elif isinstance(value, (list, tuple)): value = value[int(part)]
        else: value = getattr(value, part)
    return value


def resolve(value: Any, ctx: Context) -> Any:
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
    outbound = (kind == 'kafka' and raw.get('operation') == 'publish') or (kind == 'pubsub' and raw.get('operation') == 'publish')
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
    from . import connectors
    cfg = resolve({key: value for key, value in raw.items() if key != 'inputMappings'}, ctx)
    for key, value in mapped(raw, ctx).items():
        cfg[key] = value
    operation = str(cfg.get('operation') or '')
    if kind == 'start': return mapped(raw, ctx).get('payload', ctx.input)
    if kind == 'end': return mapped(raw, ctx).get('result', ctx.last)
    if kind == 'catch': return {'type': type(ctx.error).__name__, 'message': str(ctx.error)} if ctx.error else ctx.last
    if kind in {'throw', 'rethrow'}:
        if kind == 'rethrow' and ctx.error: raise ctx.error
        raise RuntimeError(str(cfg.get('message') or 'Business fault'))
    if kind == 'log':
        level = str(cfg.get('level') or 'INFO').upper()
        message = cfg.get('message') or f'{name} payload'
        payload = cfg.get('payload', ctx.last)
        logging.log(getattr(logging, level, logging.INFO), '%s%s', message,
                    f' | payload={json.dumps(payload, default=str)}' if cfg.get('includePayload') else '')
        return ctx.last
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
    if kind == 'mapper':
        result = {}
        mappings = raw.get('mappings') or []
        rules = [{'target': key, 'source': value} for key, value in mappings.items()] if isinstance(mappings, dict) else mappings
        for rule in rules:
            target = rule.get('target')
            if not target: continue
            if 'constant' in rule:
                value = resolve(rule['constant'], ctx)
            else:
                source = rule.get('source')
                value = resolve(source, ctx) if isinstance(source, str) and REFERENCE.fullmatch(source) else lookup(str(source), ctx)
            assign_path(result, target, value)
        return result
    if kind == 'call_task':
        from .registry import TASKS
        target = str(cfg.get('taskId') or '')
        values = mapped(raw, ctx)
        child = Context(values or ctx.last, ctx.properties, ctx.resources)
        return await TASKS[target](child)
    if kind in {'kafka', 'pubsub'}:
        resource_id = str(cfg.get('resourceId') or '')
        resource = ctx.resources.get(resource_id)
        if not resource: raise ValueError(f'{name} requires a shared {kind} connection')
        connection = resolve(resource.config, ctx)
        if kind == 'kafka': return await connectors.kafka(operation, connection, cfg, ctx.last)
        return await connectors.pubsub(operation, connection, cfg, ctx.last)
    raise NotImplementedError(f'Raw Python operation is not implemented: {kind}/{operation}')
