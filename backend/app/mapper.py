from __future__ import annotations
import json, re
from difflib import SequenceMatcher
from typing import Any
from xml.etree import ElementTree

_OMIT = object()

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

def flatten_schema(schema: Any, path: str = '', repeating: bool = False, repeat_path: str = '') -> list[dict[str, Any]]:
    """Accept JSON Schema, a sample JSON value, or a compact field-list schema."""
    fields: list[dict[str, Any]] = []
    if isinstance(schema, str) and schema.strip():
        try: return flatten_schema(json.loads(schema), path, repeating, repeat_path)
        except (ValueError, TypeError):
            try:
                root = ElementTree.fromstring(schema)
                def local(element): return element.tag.rsplit('}', 1)[-1]
                def walk(element, current_path='', inherited_repeat=False, inherited_repeat_path=''):
                    rows = []
                    if local(element) not in ('element', 'attribute'): return rows
                    name = element.attrib.get('name') or element.attrib.get('ref', '').split(':')[-1]
                    if not name: return rows
                    current = f'{current_path}.{("@" if local(element) == "attribute" else "")}{name}'.strip('.')
                    repeated = inherited_repeat or element.attrib.get('maxOccurs', '1') not in ('0', '1')
                    current_repeat = current if repeated and not inherited_repeat else inherited_repeat_path
                    direct = []
                    def declarations(container):
                        for child in container:
                            if local(child) in ('element', 'attribute'): direct.append(child)
                            else: declarations(child)
                    complex_type = next((child for child in element if local(child) == 'complexType'), None)
                    if complex_type is not None: declarations(complex_type)
                    if direct:
                        for child in direct: rows.extend(walk(child, current, repeated, current_repeat))
                    else:
                        xsd_type = element.attrib.get('type', 'string').split(':')[-1]
                        normalized = {'decimal':'number','double':'number','float':'number','int':'integer','long':'integer','dateTime':'string'}.get(xsd_type, xsd_type)
                        rows.append({'path': current, 'name': ('@' if local(element) == 'attribute' else '') + name, 'type': normalized, 'required': element.attrib.get('minOccurs', '1') != '0' and element.attrib.get('use') != 'optional', 'repeating': repeated, 'repeatPath': current_repeat})
                    return rows
                top = next((child for child in root if local(child) == 'element'), None)
                return walk(top, path, repeating, repeat_path) if top is not None else []
            except ElementTree.ParseError: return []
    if isinstance(schema, dict) and ('properties' in schema or schema.get('type') == 'object'):
        required = set(schema.get('required', []))
        for name, child in schema.get('properties', {}).items():
            child_path = f'{path}.{name}'.strip('.')
            child_repeating = isinstance(child, dict) and child.get('type') == 'array'
            definition = child.get('items', {}) if child_repeating else child
            next_repeat_path = child_path if child_repeating else repeat_path
            if isinstance(definition, dict) and (definition.get('type') == 'object' or 'properties' in definition): fields.extend(flatten_schema(definition, child_path, repeating or child_repeating, next_repeat_path))
            else: fields.append({'path': child_path, 'name': name, 'type': definition.get('type', 'any') if isinstance(definition, dict) else type(definition).__name__, 'required': name in required, 'repeating': repeating or child_repeating, 'repeatPath': next_repeat_path})
        return fields
    if isinstance(schema, dict):
        for name, child in schema.items():
            child_path = f'{path}.{name}'.strip('.')
            if isinstance(child, dict): fields.extend(flatten_schema(child, child_path, repeating, repeat_path))
            elif isinstance(child, list) and child and isinstance(child[0], dict): fields.extend(flatten_schema(child[0], child_path, True, child_path))
            else: fields.append({'path': child_path, 'name': name, 'type': type(child).__name__, 'required': False, 'repeating': repeating, 'repeatPath': repeat_path})
    elif isinstance(schema, list) and schema and isinstance(schema[0], dict): fields.extend(flatten_schema(schema[0], path, True, path))
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
            cardinality = 1 if source.get('repeating') == target.get('repeating') else (.65 if source.get('required') == target.get('required') else .35)
            score = linguistic*weights.get('linguistic',.5)+type_score*weights.get('type',.2)+ancestor*weights.get('ancestor',.2)+cardinality*weights.get('cardinality',.1)
            candidates.append({'source': source['path'], 'score': round(score*100, 1), 'sourceType': source['type'], 'sourceRepeating': bool(source.get('repeating')), 'sourceRepeatPath': source.get('repeatPath', '')})
        candidates.sort(key=lambda x: x['score'], reverse=True)
        top = candidates[:3]
        selected = top[0] if top and top[0]['score'] >= threshold*100 else None
        result.append({'target': target['path'], 'targetType': target['type'], 'targetRepeating': bool(target.get('repeating')), 'targetRepeatPath': target.get('repeatPath', ''), 'selected': selected['source'] if selected else None, 'sourceRepeating': bool(selected and selected.get('sourceRepeating')), 'sourceRepeatPath': selected.get('sourceRepeatPath', '') if selected else '', 'operator': 'for-each' if selected and selected.get('sourceRepeating') and target.get('repeating') else None, 'confidence': top[0]['score'] if top else 0, 'alternatives': top})
    return result

def _path_tokens(path: str) -> list[tuple[str, bool]]:
    """Return (token, was_bracket_index) pairs for mapper/XPath-like paths."""
    text = str(path or '').strip().removeprefix('${').removesuffix('}')
    tokens: list[tuple[str, bool]] = []
    for name, index in re.findall(r'([^\.\[\]]+)|\[(\d+)\]', text):
        tokens.append((name or index, bool(index)))
    return tokens


def get_path(value: Any, path: str):
    current = value
    for part, bracket_index in _path_tokens(path):
        if isinstance(current, list):
            if not part.isdigit():
                # XPath-style traversal through a sequence preserves the sequence.
                return [item.get(part) if isinstance(item, dict) else None for item in current]
            # BW/XPath positions are one-based: book[1] is the first book.
            position = int(part) - 1 if bracket_index else int(part)
            if position < 0 or position >= len(current): return None
            current = current[position]
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


def _coerce(value: Any, target_type: str, policy: str):
    if value is None or policy == 'off': return value
    target = str(target_type or '').lower().removesuffix('[]')
    if target in ('string', 'normalizedstring', 'token', 'date', 'datetime', 'time', 'anyuri'):
        if isinstance(value, str): return value
        if policy == 'strict': raise ValueError(f'Expected {target_type}, received {type(value).__name__}')
        return str(value)
    if target in ('integer', 'int', 'long', 'short', 'byte'):
        if isinstance(value, bool): raise ValueError(f'Expected {target_type}, received boolean')
        if isinstance(value, int): return value
        if policy == 'strict': raise ValueError(f'Expected {target_type}, received {type(value).__name__}')
        return int(value)
    if target in ('number', 'decimal', 'double', 'float'):
        if isinstance(value, bool): raise ValueError(f'Expected {target_type}, received boolean')
        if isinstance(value, (int, float)): return value
        if policy == 'strict': raise ValueError(f'Expected {target_type}, received {type(value).__name__}')
        return float(value)
    if target in ('boolean', 'bool'):
        if isinstance(value, bool): return value
        if policy == 'strict': raise ValueError(f'Expected {target_type}, received {type(value).__name__}')
        text = str(value).strip().lower()
        if text not in ('true', 'false', '1', '0', 'yes', 'no', 'on', 'off'): raise ValueError(f'Cannot coerce {value!r} to boolean')
        return text in ('true', '1', 'yes', 'on')
    return value


def _clean_empty(value: Any):
    if isinstance(value, dict):
        cleaned = {key: _clean_empty(item) for key, item in value.items()}
        return {key: item for key, item in cleaned.items() if item not in (None, '', [], {})}
    if isinstance(value, list): return [item for item in (_clean_empty(entry) for entry in value) if item not in (None, '', [], {})]
    return value


def validate_output(document: Any, schema: Any) -> list[str]:
    """Validate the JSON-schema subset used by project schemas and mapper tests."""
    errors: list[str] = []
    if not isinstance(schema, dict) or not schema: return errors
    def walk(value: Any, definition: dict, path: str):
        expected = definition.get('type')
        if expected == 'object' or 'properties' in definition:
            if not isinstance(value, dict): errors.append(f'{path or "result"}: expected object'); return
            for required in definition.get('required', []):
                if required not in value: errors.append(f'{path + "." if path else ""}{required}: required field is not mapped')
            for key, child in definition.get('properties', {}).items():
                if key in value and isinstance(child, dict): walk(value[key], child, f'{path}.{key}'.strip('.'))
        elif expected == 'array':
            if not isinstance(value, list): errors.append(f'{path}: expected array'); return
            child = definition.get('items', {})
            if isinstance(child, dict):
                for index, item in enumerate(value): walk(item, child, f'{path}[{index + 1}]')
        elif expected == 'string' and not isinstance(value, str): errors.append(f'{path}: expected string')
        elif expected in ('integer', 'int') and (isinstance(value, bool) or not isinstance(value, int)): errors.append(f'{path}: expected integer')
        elif expected in ('number', 'decimal') and (isinstance(value, bool) or not isinstance(value, (int, float))): errors.append(f'{path}: expected number')
        elif expected in ('boolean', 'bool') and not isinstance(value, bool): errors.append(f'{path}: expected boolean')
    walk(document, schema, '')
    return errors

def _clean_path(value: Any) -> str:
    text = str(value or '').strip()
    return text[2:-1] if text.startswith('${') and text.endswith('}') else text


def _relative_path(path: str, parent: str) -> str | None:
    path, parent = _clean_path(path), _clean_path(parent)
    if path == parent: return ''
    if parent and path.startswith(parent + '.'): return path[len(parent) + 1:]
    return None


def execute(document: Any, mappings: Any, options: dict | None = None) -> dict:
    """Execute BW-style mapping statements, including nested repeating targets."""
    options = options or {}
    result: dict[str, Any] = {}
    raw_rules = [{'target': key, 'source': value} for key, value in mappings.items()] if isinstance(mappings, dict) else mappings or []
    rules = [dict(rule) for rule in raw_rules if rule.get('enabled', True) and rule.get('target')]
    loops = [rule for rule in rules if str(rule.get('operator', '')).lower() in ('for-each', 'for-each-group')]

    def under(path: str, parent: str) -> bool:
        return path.startswith(parent + '.')

    def resolve_value(rule: dict, scope: Any = None, scope_source: str = ''):
        if 'constant' in rule: return rule['constant']
        source_path = _clean_path(rule.get('select') or rule.get('source', ''))
        relative = _relative_path(source_path, scope_source) if scope is not None else None
        return get_path(scope, relative) if relative is not None else get_path(document, source_path)

    def condition_passes(rule: dict, scope: Any = None, scope_source: str = '') -> bool:
        condition = str(rule.get('condition', '')).strip()
        if re.search(r'\s+or\s+', condition, re.I):
            return any(condition_passes({'condition': part}, scope, scope_source) for part in re.split(r'\s+or\s+', condition, flags=re.I))
        if re.search(r'\s+and\s+', condition, re.I):
            return all(condition_passes({'condition': part}, scope, scope_source) for part in re.split(r'\s+and\s+', condition, flags=re.I))
        match = re.fullmatch(r'(exists|empty)\(([^)]+)\)', condition, re.I)
        if match:
            probe = {'source': match.group(2).strip()}
            tested = resolve_value(probe, scope, scope_source)
            passed = tested not in (None, '', [], {})
            return not passed if match.group(1).lower() == 'empty' else passed
        comparison = re.fullmatch(r'(.+?)\s*(==|=|!=|>=|<=|>|<)\s*(.+)', condition)
        if comparison:
            def operand(text: str):
                text = text.strip()
                if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')): return text[1:-1]
                if text.lower() in ('true', 'true()'): return True
                if text.lower() in ('false', 'false()'): return False
                if text.lower() in ('null', '()'): return None
                try: return float(text) if '.' in text else int(text)
                except ValueError: return resolve_value({'source': text}, scope, scope_source)
            left, right, operator = operand(comparison.group(1)), operand(comparison.group(3)), comparison.group(2)
            if operator in ('=', '=='): return left == right
            if operator == '!=': return left != right
            if operator == '>': return left > right
            if operator == '<': return left < right
            if operator == '>=': return left >= right
            return left <= right
        return condition.lower() in ('true', 'true()', '1')

    def conditional_value(rule: dict, scope: Any = None, scope_source: str = ''):
        operator = str(rule.get('operator', '')).lower()
        if operator == 'choose':
            def branch_value(value: Any):
                if not isinstance(value, str): return value
                text = value.strip()
                if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')): return text[1:-1]
                if text.lower() in ('true', 'true()'): return True
                if text.lower() in ('false', 'false()'): return False
                if text.lower() in ('null', '()'): return None
                try: return float(text) if '.' in text else int(text)
                except ValueError: return resolve_value({'source': text}, scope, scope_source)
            branches = rule.get('whens', []) or []
            if not branches and isinstance(rule.get('source'), str):
                try: branches = json.loads(rule['source'])
                except (TypeError, ValueError, json.JSONDecodeError): branches = []
            for branch in branches:
                if condition_passes({'condition': branch.get('condition', '')}, scope, scope_source):
                    return branch_value(branch.get('source', '')), True
            otherwise = rule.get('otherwise', _OMIT)
            return branch_value(otherwise), otherwise is not _OMIT
        value = resolve_value(rule, scope, scope_source)
        if operator in ('if', 'when-otherwise') and not condition_passes(rule, scope, scope_source):
            if operator == 'if': return _OMIT, False
            value = rule.get('otherwise')
        return value, True

    def mapped_value(rule: dict, value: Any):
        try:
            value = transform_value(value, rule.get('functions', []))
            if value is None:
                if options.get('copyNil') is False: return _OMIT
                policy = str(rule.get('nullPolicy') or options.get('nullPolicy') or 'omit').lower()
                if policy == 'omit': return _OMIT
                if policy == 'empty-string': value = ''
                elif policy == 'default': value = rule.get('defaultValue', options.get('defaultValue'))
            if options.get('trimStrings') and isinstance(value, str): value = value.strip()
            return _coerce(value, rule.get('targetType', ''), str(options.get('typeCoercion') or 'safe').lower())
        except Exception:
            behavior = str(options.get('onMappingError') or 'fail').lower()
            if behavior == 'skip-field': return _OMIT
            if behavior == 'use-null': return None
            raise

    def render_loop(loop: dict, scope: Any = None, scope_source: str = '') -> list[Any]:
        loop_source = _clean_path(loop.get('select') or loop.get('source', ''))
        value = resolve_value(loop, scope, scope_source)
        values = value if isinstance(value, list) else ([] if value in (None, '') else [value])
        operator = str(loop.get('operator', '')).lower()
        iterations: list[tuple[Any, list[Any] | None]] = [(item, None) for item in values]
        if operator == 'for-each-group':
            grouped: dict[str, list[Any]] = {}
            group_by = _clean_path(loop.get('groupBy', '')).strip('.')
            for item in values:
                grouped.setdefault(str(get_path(item, group_by) if group_by else item), []).append(item)
            iterations = [(items[0] if items else {}, items) for items in grouped.values()]

        target = str(loop['target']).strip('.')
        occurrence_id = loop.get('occurrenceId')
        descendants = [rule for rule in rules if under(str(rule['target']).strip('.'), target) and rule.get('occurrenceId') == occurrence_id]
        nested_loops = [candidate for candidate in loops if candidate in descendants and not any(
            other is not candidate and other in descendants and under(str(candidate['target']), str(other['target']))
            for other in loops
        )]
        nested_targets = [str(candidate['target']).strip('.') for candidate in nested_loops]
        direct = [rule for rule in descendants if rule not in nested_loops and not any(under(str(rule['target']).strip('.'), nested) for nested in nested_targets)]
        output: list[Any] = []
        for current, current_group in iterations:
            item_result: dict[str, Any] = {}
            for child in direct:
                relative_target = _relative_path(str(child['target']), target)
                if relative_target is None or not relative_target: continue
                child_value, present = conditional_value(child, current, loop_source)
                if not present: continue
                child_value = mapped_value(child, child_value)
                if child_value is not _OMIT: set_path(item_result, relative_target, child_value)
            for nested in nested_loops:
                relative_target = _relative_path(str(nested['target']), target)
                if relative_target:
                    nested_scope = current_group if _clean_path(nested.get('source')) == 'current-group()' else current
                    set_path(item_result, relative_target, render_loop(nested, nested_scope, loop_source))
            output.append(transform_value(item_result, loop.get('functions', [])))
        return output

    top_loops = [loop for loop in loops if not any(other is not loop and under(str(loop['target']), str(other['target'])) for other in loops)]
    loop_targets = [str(loop['target']).strip('.') for loop in top_loops]
    for rule in rules:
        target = str(rule['target']).strip('.')
        if rule in loops or any(under(target, loop_target) for loop_target in loop_targets): continue
        value, present = conditional_value(rule)
        if not present: continue
        value = mapped_value(rule, value)
        if value is not _OMIT: set_path(result, target, value)
    for loop in top_loops:
        target = str(loop['target'])
        generated = render_loop(loop)
        existing = get_path(result, target)
        set_path(result, target, ([*existing, *generated] if isinstance(existing, list) else generated))
    if options.get('removeEmptyStructures'): result = _clean_empty(result)
    schema = options.get('targetSchema')
    validation_errors = validate_output(result, schema) if options.get('validateOutput', True) else []
    if validation_errors: raise ValueError('Target schema validation failed: ' + '; '.join(validation_errors))
    maximum_kb = int(options.get('maxOutputSizeKb') or 0)
    if maximum_kb and len(str(result).encode('utf-8')) > maximum_kb * 1024: raise ValueError(f'Mapped output exceeds {maximum_kb} KB limit')
    return result
