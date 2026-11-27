"""AsyncAPI operation contracts and structured CloudEvents JSON."""
import base64
import json
import re
import uuid
from datetime import datetime
from urllib.parse import unquote, urlsplit

from .http_contracts import load_document
from .schema_validation import schema_errors


def _reference(document, value):
    seen = set()
    while isinstance(value, dict) and '$ref' in value:
        ref = value['$ref']
        if not isinstance(ref, str) or not ref.startswith('#/') or ref in seen or len(seen) >= 64:
            raise ValueError('AsyncAPI references must be local and acyclic')
        seen.add(ref)
        value = document
        try:
            for key in unquote(ref[2:]).split('/'):
                value = value[key.replace('~1', '/').replace('~0', '~')]
        except (KeyError, TypeError):
            raise ValueError(f'Unresolved AsyncAPI reference {ref}') from None
    return value


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object')
    return value


def parse_contract(value):
    if isinstance(value, str) and len(value.encode()) > 1048576:
        raise ValueError('AsyncAPI document exceeds 1 MiB')
    document = _object(load_document(value), 'AsyncAPI document')
    if not re.fullmatch(r'3\.[01]\.\d+', str(document.get('asyncapi', ''))):
        raise ValueError('Choose an AsyncAPI 3.0 or 3.1 document')
    info = _object(document.get('info'), 'info')
    if not all(isinstance(info.get(key), str) and info[key].strip() for key in ('title', 'version')):
        raise ValueError('AsyncAPI info.title and info.version are required')
    operations = {}
    for name, source in _object(document.get('operations', {}), 'operations').items():
        operation = _object(_reference(document, source), 'Operation')
        if operation.get('action') not in ('send', 'receive'):
            raise ValueError(f'Operation {name} requires a send or receive action')
        channel = _object(_reference(document, operation.get('channel')), 'Operation channel')
        declared = _object(channel.get('messages', {}), 'Channel messages')
        messages = list(declared)
        if 'messages' in operation:
            if not isinstance(operation['messages'], list):
                raise ValueError(f'Operation {name} messages must be an array')
            messages = []
            for definition in operation['messages']:
                ref = _object(definition, 'Operation message reference').get('$ref', '')
                selected = _reference(document, definition)
                key = unquote(ref.rsplit('/', 1)[-1]).replace('~1', '/').replace('~0', '~')
                if key not in declared or selected is not _reference(document, declared[key]):
                    raise ValueError(f'Operation {name} must reference a message on its channel')
                messages.append(key)
        for key in messages:
            _object(_reference(document, declared[key]), 'Channel message')
        operations[name] = {'action': operation['action'], 'address': channel.get('address'),
                            'messages': messages, 'definitions': declared}
    return document, operations


def review_contract(value):
    document, operations = parse_contract(value)
    return {'document': document, 'operations': [{'id': key, 'action': entry['action'],
             'address': entry['address'], 'messages': entry['messages']} for key, entry in operations.items()]}


def _validate_message(config, payload):
    document, operations = parse_contract(config.get('asyncApiDocument'))
    operation = operations.get(config.get('operationId'))
    if operation is None:
        raise ValueError('Select an AsyncAPI operation ID')
    messages = operation['messages']
    name = config.get('messageName') or (messages[0] if len(messages) == 1 else '')
    if name not in messages:
        raise ValueError('Select a message name for this AsyncAPI operation')
    message = _reference(document, operation['definitions'][name])
    schema = message.get('payload')
    if isinstance(schema, dict) and 'schemaFormat' in schema:
        if 'json' not in str(schema['schemaFormat']).lower():
            raise ValueError('Event validation supports JSON Schema payloads')
        schema = schema.get('schema')
    if not isinstance(schema, (dict, bool)):
        raise ValueError('The selected AsyncAPI message has no JSON payload schema')
    if isinstance(schema, dict):
        schema = {**schema, 'components': document.get('components', {})}
    if schema_errors(payload, schema):
        raise ValueError('Event payload failed the selected AsyncAPI message schema')
    return payload


def _uri(value, absolute=False):
    if not isinstance(value, str) or not value or re.search(r'\s|%(?![0-9a-fA-F]{2})', value):
        return False
    return bool(urlsplit(value).scheme) if absolute else True


def _validate_event(value):
    value = _object(value, 'Structured CloudEvent')
    for name in value:
        if not re.fullmatch(r'[a-z0-9]+(?:_[a-z0-9]+)?', name) or '_' in name and name != 'data_base64':
            raise ValueError(f'Invalid CloudEvents attribute {name}')
        if name not in {'data', 'data_base64'} and type(value[name]) not in (str, int, bool):
            raise ValueError(f'Invalid CloudEvents attribute value for {name}')
    if value.get('specversion') != '1.0':
        raise ValueError('CloudEvents specversion must be 1.0')
    if any(not isinstance(value.get(name), str) or not value[name].strip() for name in ('id', 'type')):
        raise ValueError('CloudEvents id and type are required')
    if any(name in value and not isinstance(value[name], str) for name in ('subject', 'datacontenttype')):
        raise ValueError('CloudEvents subject and datacontenttype must be strings')
    if not _uri(value.get('source')) or ('dataschema' in value and not _uri(value['dataschema'], True)):
        raise ValueError('CloudEvents source or dataschema is invalid')
    if 'time' in value:
        stamp = value['time']
        if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)', stamp):
            raise ValueError('CloudEvents time requires an RFC 3339 timestamp')
        datetime.fromisoformat(stamp.upper().replace('Z', '+00:00'))
    if 'data_base64' in value:
        if 'data' in value or not isinstance(value['data_base64'], str):
            raise ValueError('Use either data or data_base64')
        base64.b64decode(value['data_base64'], validate=True)
    return value


def execute(operation, config, payload):
    if operation == 'asyncapi_validate':
        return _validate_message(config, payload)
    if operation == 'cloudevent_encode':
        attributes = _object(config.get('eventAttributes') or {}, 'CloudEvents attributes')
        if {'data', 'data_base64'} & attributes.keys():
            raise ValueError('Map CloudEvents payload separately from attributes')
        event = {'specversion': '1.0', 'id': str(uuid.uuid4()), **attributes}
        if config.get('contentBase64') is not None:
            event['data_base64'] = config['contentBase64']
        else:
            event['data'] = payload
        return _validate_event(event)
    if isinstance(payload, str):
        if len(payload.encode()) > 16 * 1024 * 1024:
            raise ValueError('CloudEvent exceeds 16 MiB')
        payload = json.loads(payload)
    return _validate_event(payload)
