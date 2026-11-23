"""Generate deterministic, schema-checked debugger inputs without running activities."""
from copy import deepcopy
from dataclasses import dataclass
from itertools import islice
import json
import math
from urllib.parse import quote
from typing import Callable

from .api_docs import methods_for, sample
from .http_contracts import listener_media_types, media_name, media_schema
from .http_server import route_pattern
from .rest_contract import listener_parameters, operation_config
from .models import effective_event_activities
from .schema_validation import schema_errors
from .subtask_testing import configured_start_schema, start_xsd_definition, subtask_input


@dataclass
class FixtureContract:
    title: str
    schema: dict | bool | None
    validate: Callable
    wrap: Callable
    mode: str
    unwrap: Callable = lambda payload: payload


def resolved_schema(definition, root, seen=()):
    if not isinstance(definition, dict):
        return {}
    reference = definition.get('$ref')
    if not isinstance(reference, str) or not reference.startswith('#/') or reference in seen or len(seen) >= 10:
        return definition
    try:
        target = root
        for part in reference[2:].split('/'):
            target = target[part.replace('~1', '/').replace('~0', '~')]
        return {**resolved_schema(target, root, (*seen, reference)), **definition}
    except (KeyError, TypeError):
        return definition


def numeric_boundary(schema, upper=False):
    kind = schema.get('type')
    key, exclusive = ('maximum', 'exclusiveMaximum') if upper else ('minimum', 'exclusiveMinimum')
    bound = schema.get(exclusive)
    if isinstance(bound, (int, float)) and not isinstance(bound, bool):
        if kind == 'integer':
            return math.ceil(bound) - 1 if upper else math.floor(bound) + 1
        return math.nextafter(bound, -math.inf if upper else math.inf)
    bound = schema.get(key)
    if isinstance(bound, (int, float)) and not isinstance(bound, bool):
        if schema.get(exclusive) is True:
            if kind == 'integer':
                return math.ceil(bound) - 1 if upper else math.floor(bound) + 1
            return math.nextafter(bound, -math.inf if upper else math.inf)
        if kind == 'integer':
            return math.floor(bound) if upper else math.ceil(bound)
        return bound
    return None


def seed(definition, root, style, depth=0, *, budget):
    budget[0] -= 1
    if depth > 8 or budget[0] < 0:
        return None
    schema = resolved_schema(definition, root)
    if 'const' in schema:
        return deepcopy(schema['const'])
    if style == 'example' and 'example' in schema:
        return deepcopy(schema['example'])
    if schema.get('enum'):
        return deepcopy(schema['enum'][-1 if style == 'maximum' else 0])
    branches = schema.get('oneOf') or schema.get('anyOf')
    if branches:
        return seed(branches[-1 if style == 'maximum' else 0], root, style, depth + 1, budget=budget)
    kind = schema.get('type')
    if isinstance(kind, list):
        kind = next((item for item in kind if item != 'null'), 'null')
    child = lambda definition: seed(definition, root, style, depth + 1, budget=budget)
    if kind == 'object' or 'properties' in schema or 'allOf' in schema:
        fields = schema.get('properties', {})
        required = set(schema.get('required', []))
        value = {}
        for part in schema.get('allOf', []):
            if isinstance(result := child(part), dict):
                value.update(result)
        for name, item in islice(fields.items(), 128):
            if name in required or style != 'minimal':
                value[name] = child(item)
        return value
    if kind == 'array':
        count = min(24, schema.get('minItems', 0) if style == 'minimal' else max(1, schema.get('minItems', 0)))
        return [child(schema.get('items', {})) for _ in range(min(count, schema.get('maxItems', count)))]
    if kind in ('integer', 'number'):
        low, high = numeric_boundary(schema), numeric_boundary(schema, upper=True)
        value = high if style == 'maximum' and high is not None else low if low is not None else min(1, high) if high is not None else 1
        multiple = schema.get('multipleOf')
        if multiple:
            value = (math.floor(value / multiple) if style == 'maximum' or low is None else math.ceil(value / multiple)) * multiple
        return int(value) if kind == 'integer' else value
    if kind == 'string':
        result = sample({key: value for key, value in schema.items() if key not in ('example', 'default')}, root)
        if schema.get('format') or schema.get('pattern'):
            return result
        minimum = min(1024, schema.get('minLength', 0))
        length = minimum if style == 'minimal' else schema.get('maxLength', max(minimum, len(result or ''))) if style == 'maximum' else max(minimum, len(result or ''))
        length = min(1024, length, schema.get('maxLength', length))
        return ((result or 'x') * (length // len(result or 'x') + 1))[:length]
    if kind == 'boolean':
        return style != 'minimum'
    return None if kind == 'null' else {}


def negative_candidates(value, definition, root, path=(), depth=0):
    if depth > 6:
        return
    schema = resolved_schema(definition, root)
    label = '.'.join(map(str, path)) or 'input'
    kind = schema.get('type')
    invalid_value = {} if not isinstance(value, dict) else []
    if kind:
        yield f'Wrong type for {label}', path, invalid_value, False
    if schema.get('enum'):
        yield f'Unknown value for {label}', path, '__unknown_test_value__', False
    low = numeric_boundary(schema)
    high = numeric_boundary(schema, upper=True)
    if low is not None:
        yield f'Below minimum for {label}', path, low - 1, False
    if high is not None:
        yield f'Above maximum for {label}', path, high + 1, False
    if schema.get('minLength') or schema.get('minItems'):
        yield f'Empty value for {label}', path, '' if isinstance(value, str) else [], False
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key in value:
                child_path = (*path, key)
                yield f'Missing required {".".join(map(str, child_path))}', child_path, None, True
        for key, child in schema.get('properties', {}).items():
            if key in value:
                yield from negative_candidates(value[key], child, root, (*path, key), depth + 1)
    elif isinstance(value, list) and value:
        yield from negative_candidates(value[0], schema.get('items', {}), root, (*path, 0), depth + 1)


def input_cases(contract):
    cases, seen = [], set()

    def add(name, value, expected):
        fingerprint = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if fingerprint in seen:
            return
        errors = contract.validate(value) if contract.schema is not None else []
        valid = not errors
        if valid != expected:
            return
        seen.add(fingerprint)
        cases.append({'id': f'case-{len(cases) + 1}', 'name': name[:300], 'expected': 'accept' if expected else 'reject',
                      'actual': 'unchecked' if contract.schema is None else 'accept' if valid else 'reject',
                      'input': contract.wrap(value), 'errors': errors})

    schema = contract.schema
    if schema is None:
        add('Generic input', {}, True)
        return cases, 'No input contract is configured. The generic case is a starting point for manual testing.'
    baseline = None
    for style, title in (('minimal', 'Required fields only'), ('minimum', 'Lower boundary'), ('maximum', 'Upper boundary'), ('example', 'Schema example')):
        value = seed(schema, schema, style, budget=[512])
        count = len(cases)
        add(title, value, True)
        if len(cases) > count:
            baseline = value
    if not cases:
        return [], 'Studio could not generate a valid example for this contract. Supply a representative fixture in the Test Bench.'

    for name, path, replacement, omit in islice(negative_candidates(baseline, schema, schema), 24):
        value = deepcopy(baseline)
        if path:
            target = value
            for key in path[:-1]:
                target = target[key]
            if omit:
                del target[path[-1]]
            else:
                target[path[-1]] = replacement
        else:
            value = replacement
        add(name, value, False)
        if len(cases) >= 12:
            break
    return cases, ''


def http_fixture_contract(project, entry):
    resource = next((item for item in project.resources if item.id == entry.config.get('resourceId')), None)
    config = {**(resource.config if resource else {}), **entry.config}
    try:
        cfg = operation_config({**config, 'operation': 'receiver', 'openApiAllowedRefOrigins': ''})
    except KeyError as error:
        raise ValueError(f'The selected OpenAPI operation has an unresolved local reference: {error}') from None
    path = '/' + '/'.join(part for part in (str(cfg.get('basePath') or '').strip('/'), str(cfg.get('path') or '').strip('/')) if part)
    _, names = route_pattern(path)
    params = {location: {} for location in ('path', 'query', 'header')}
    for item in listener_parameters(cfg, names):
        location, key = item['in'], item['name']
        if location not in params or (location == 'header' and key.lower() in ('authorization', 'cookie', 'proxy-authorization')):
            continue
        if location == 'path' or item.get('required'):
            definition = item.get('schema') or {}
            params[location][key.lower() if location == 'header' else key] = seed(definition, definition, 'minimal', budget=[64])
    for name in names:
        params['path'].setdefault(name, 'example')
        path = path.replace('{' + name + '}', quote(str(params['path'][name]), safe=''))
    formats = listener_media_types(config, 'requestContentTypes') or list(cfg.get('_restRequestSchemas') or {})
    media = [media_name(item) for item in formats] or [media_name(cfg.get('contentType') or 'application/json')]
    content_type = next((item for item in media if item == 'application/json' or item.endswith('+json')), media[0])
    schema = config.get('requestSchema')
    if schema in (None, ''):
        schema = media_schema(cfg.get('_restRequestSchemas') or {}, content_type)[1]
    if isinstance(schema, str):
        schema = None if schema.lstrip().startswith('<') else json.loads(schema)
    if not (content_type == 'application/json' or content_type.endswith('+json')):
        schema = None
    method = next(iter(methods_for(cfg)), 'POST')
    envelope = {'method': method, 'path': path, 'pathParameters': params['path'], 'query': params['query'],
                'headers': {'content-type': content_type, **params['header']}, 'headerPairs': [], 'auth': {}}
    def wrap(value):
        return {**deepcopy(envelope), 'body': value}
    def unwrap(payload):
        if not isinstance(payload, dict) or 'body' not in payload:
            raise ValueError('The saved HTTP fixture is missing its request body envelope.')
        return payload['body']
    return FixtureContract(f'{method} {path} request body', schema, lambda value: schema_errors(value, schema), wrap, 'starter-output', unwrap)


def check_saved_cases(contract, saved):
    results = []
    for index, case in enumerate(saved):
        payload = case['input']
        errors = contract.validate(contract.unwrap(payload)) if contract.schema is not None else []
        results.append({'id': f'case-{index + 1}', 'name': case['name'], 'input': payload, 'expected': case['expected'],
                        'actual': 'unchecked' if contract.schema is None else 'reject' if errors else 'accept', 'errors': errors})
    return results


def task_input_suite(project, task, saved=None):
    if task.library_origin:
        raise ValueError('Choose an editable task in this project.')
    entries = effective_event_activities(task.activities, task.transitions)
    if len(entries) != 1:
        raise ValueError('Test case generation needs a task with one effective entry activity.')
    entry = entries[0]
    identity = lambda payload: payload
    contract = FixtureContract(entry.name, None, lambda payload: [], identity, 'bench-only')
    if entry.type == 'start':
        configured, name, schema_id = configured_start_schema(project, task, entry)
        if isinstance(configured, str) and configured.lstrip().startswith('<'):
            schema, *_ = start_xsd_definition(project, configured, schema_id)
            contract = FixtureContract(name, schema, lambda payload: subtask_input(project, task, entry, payload)['errors'], identity, 'task-input')
        elif configured:
            schema = json.loads(configured) if isinstance(configured, str) else configured
            contract = FixtureContract(name, schema, lambda payload: schema_errors(payload, schema), identity, 'task-input')
        else:
            contract.mode = 'task-input'
    elif entry.type == 'http_listener' or entry.type == 'rest' and entry.config.get('operation') == 'receiver':
        contract = http_fixture_contract(project, entry)
    elif entry.type == 'timer':
        value = {'scheduledTime': '2026-01-01T00:00:00Z', 'actualTime': '2026-01-01T00:00:00Z', 'sequence': 1}
        contract = FixtureContract(entry.name, None, lambda payload: [], lambda payload: deepcopy(value), 'starter-output')
    if saved is None:
        cases, note = input_cases(contract)
    else:
        cases = check_saved_cases(contract, saved)
        note = 'No input contract is available to check these saved cases.' if contract.schema is None else ''
    return {'taskId': task.id, 'activityId': entry.id, 'contract': contract.title, 'mode': contract.mode, 'note': note, 'cases': cases}
