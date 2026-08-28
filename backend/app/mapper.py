from __future__ import annotations
import re
from difflib import SequenceMatcher
from typing import Any

SYNONYMS = {
    'id': {'identifier', 'number', 'no', 'key'}, 'name': {'label', 'title'},
    'customer': {'client', 'account', 'buyer'}, 'amount': {'total', 'value', 'price'},
    'address': {'location'}, 'phone': {'telephone', 'mobile'}, 'postal': {'zip'},
    'created': {'creation', 'createdat'}, 'updated': {'modified', 'updatedat'},
}

def _tokens(value: str) -> set[str]:
    words = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', value).lower().replace('_', ' ').replace('-', ' ').split()
    expanded = set(words)
    for word in words:
        for key, values in SYNONYMS.items():
            if word == key or word in values: expanded |= {key, *values}
    return expanded

def flatten_schema(schema: Any, path: str = '') -> list[dict[str, Any]]:
    """Accept JSON Schema, a sample JSON value, or a compact field-list schema."""
    fields: list[dict[str, Any]] = []
    if isinstance(schema, dict) and ('properties' in schema or schema.get('type') == 'object'):
        required = set(schema.get('required', []))
        for name, child in schema.get('properties', {}).items():
            child_path = f'{path}.{name}'.strip('.')
            if isinstance(child, dict) and (child.get('type') == 'object' or 'properties' in child): fields.extend(flatten_schema(child, child_path))
            else: fields.append({'path': child_path, 'name': name, 'type': child.get('type', 'any') if isinstance(child, dict) else type(child).__name__, 'required': name in required})
        return fields
    if isinstance(schema, dict):
        for name, child in schema.items():
            child_path = f'{path}.{name}'.strip('.')
            if isinstance(child, dict): fields.extend(flatten_schema(child, child_path))
            else: fields.append({'path': child_path, 'name': name, 'type': type(child).__name__, 'required': False})
    elif isinstance(schema, list) and schema and isinstance(schema[0], dict): fields.extend(flatten_schema(schema[0], path))
    return fields

def recommend(source_schema: Any, target_schema: Any, threshold: float = 0.7, weights: dict | None = None) -> list[dict]:
    weights = weights or {'linguistic': .5, 'type': .2, 'ancestor': .2, 'cardinality': .1}
    sources, targets = flatten_schema(source_schema), flatten_schema(target_schema)
    result = []
    for target in targets:
        candidates = []
        for source in sources:
            st, tt = _tokens(source['name']), _tokens(target['name'])
            linguistic = max(SequenceMatcher(None, source['name'].lower(), target['name'].lower()).ratio(), len(st & tt) / max(1, len(st | tt)))
            type_score = 1 if source['type'] == target['type'] else (.55 if {source['type'], target['type']} <= {'integer','number','float'} else .2)
            sp, tp = source['path'].split('.')[:-1], target['path'].split('.')[:-1]
            ancestor = SequenceMatcher(None, '.'.join(sp).lower(), '.'.join(tp).lower()).ratio() if sp and tp else .5
            cardinality = 1 if source.get('required') == target.get('required') else .5
            score = linguistic*weights.get('linguistic',.5)+type_score*weights.get('type',.2)+ancestor*weights.get('ancestor',.2)+cardinality*weights.get('cardinality',.1)
            candidates.append({'source': source['path'], 'score': round(score*100, 1), 'sourceType': source['type']})
        candidates.sort(key=lambda x: x['score'], reverse=True)
        top = candidates[:3]
        result.append({'target': target['path'], 'targetType': target['type'], 'selected': top[0]['source'] if top and top[0]['score'] >= threshold*100 else None, 'confidence': top[0]['score'] if top else 0, 'alternatives': top})
    return result

def get_path(value: Any, path: str):
    current = value
    for part in path.replace('[', '.').replace(']', '').strip('.').split('.'):
        if not part: continue
        if isinstance(current, list): current = current[int(part)]
        elif isinstance(current, dict): current = current.get(part)
        else: return None
    return current

def set_path(target: dict, path: str, value: Any):
    parts = path.strip('.').split('.'); current = target
    for part in parts[:-1]: current = current.setdefault(part, {})
    if parts: current[parts[-1]] = value

def transform_value(value: Any, functions: list[Any]):
    for spec in functions or []:
        name, args = (spec, []) if isinstance(spec, str) else (spec.get('name'), spec.get('args', []))
        if name == 'trim': value = str(value).strip()
        elif name == 'upper': value = str(value).upper()
        elif name == 'lower': value = str(value).lower()
        elif name == 'string': value = '' if value is None else str(value)
        elif name == 'number': value = float(value) if '.' in str(value) else int(value)
        elif name == 'boolean': value = str(value).lower() in ('true','1','yes','on')
        elif name == 'replace': value = str(value).replace(str(args[0]), str(args[1]))
        elif name == 'prefix': value = str(args[0]) + str(value)
        elif name == 'suffix': value = str(value) + str(args[0])
        elif name == 'default' and (value is None or value == ''): value = args[0] if args else None
        elif name == 'split': value = str(value).split(str(args[0] if args else ','))
        elif name == 'join': value = str(args[0] if args else ',').join(map(str, value or []))
        elif name == 'substring': value = str(value)[int(args[0]):int(args[1]) if len(args)>1 else None]
    return value

def execute(document: Any, mappings: Any) -> dict:
    result: dict[str, Any] = {}
    rules = [{'target': k, 'source': v} for k,v in mappings.items()] if isinstance(mappings, dict) else mappings or []
    for rule in rules:
        if not rule.get('enabled', True): continue
        value = rule.get('constant') if 'constant' in rule else get_path(document, rule.get('source',''))
        set_path(result, rule.get('target','result'), transform_value(value, rule.get('functions', [])))
    return result
