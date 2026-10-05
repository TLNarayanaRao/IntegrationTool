from __future__ import annotations
import ast
import base64, calendar, hashlib, json, math, re, urllib.parse, uuid
from datetime import date, datetime, time, timedelta, timezone
import ipaddress
import time as clock
import asyncio
import threading
from decimal import Decimal, ROUND_HALF_EVEN
from difflib import SequenceMatcher
from typing import Any
from xml.etree import ElementTree

_OMIT = object()

def pattern_matches(pattern, value, full=False):
    """Bound untrusted pattern matching; never fall back to unbounded re."""
    try: import regex
    except ImportError as error: raise ValueError('Pattern validation requires the regex package') from error
    if len(pattern) > 8192: raise ValueError('Schema pattern exceeds 8192 characters')
    try: return bool((regex.fullmatch if full else regex.search)(pattern, value, timeout=.1))
    except TimeoutError as error: raise ValueError('Schema pattern matching timed out') from error
    except regex.error as error: raise ValueError(f'Invalid schema pattern: {error}') from error

def format_valid(value, kind):
    """Assert commonly used wire formats. Unknown annotations remain annotations."""
    try:
        if kind == 'date': return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)) and bool(date.fromisoformat(value))
        if kind in ('time', 'date-time'):
            if kind == 'date-time':
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})', value): return False
                return datetime.fromisoformat(value.upper().replace('Z', '+00:00')).tzinfo is not None
            if not re.fullmatch(r'\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})', value): return False
            return time.fromisoformat(value.upper().replace('Z', '+00:00')).tzinfo is not None
        if kind in ('ipv4', 'ipv6'): return ipaddress.ip_address(value).version == (4 if kind == 'ipv4' else 6)
        if kind == 'uuid': return bool(re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value)) and bool(uuid.UUID(value))
        if kind == 'email': return len(value) <= 254 and bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value))
        if kind == 'hostname': return len(value.rstrip('.')) <= 253 and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in value.rstrip('.').split('.'))
        if kind == 'uri': return bool(urllib.parse.urlsplit(value).scheme) and not any(char.isspace() for char in value)
    except (ValueError, OverflowError): return False
    return True


async def execute_async(document, mappings, options=None):
    """Keep workflow control responsive and stop evaluation after cancellation."""
    cancelled = threading.Event()
    options = dict(options or {})
    previous = options.get('_cancelled')
    options['_cancelled'] = lambda: cancelled.is_set() or callable(previous) and previous()
    try: return await asyncio.to_thread(execute, document, mappings, options)
    except asyncio.CancelledError:
        cancelled.set()
        raise

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

def flatten_schema(schema: Any, path: str = '', repeating: bool = False, repeat_path: str = '', _root=None, _active=()) -> list[dict[str, Any]]:
    """Accept JSON Schema, a sample JSON value, or a compact field-list schema."""
    fields: list[dict[str, Any]] = []
    if isinstance(schema, str) and schema.strip():
        try: return flatten_schema(json.loads(schema), path, repeating, repeat_path)
        except (ValueError, TypeError):
            try:
                root = ElementTree.fromstring(schema)
                def local(element): return element.tag.rsplit('}', 1)[-1]
                types = {child.attrib.get('name'): child for child in root if local(child) in ('complexType', 'simpleType')}
                elements = {child.attrib.get('name'): child for child in root if local(child) == 'element'}
                def walk(element, current_path='', inherited_repeat=False, inherited_repeat_path='', active=()):
                    rows = []
                    if local(element) not in ('element', 'attribute'): return rows
                    name = element.attrib.get('name') or element.attrib.get('ref', '').split(':')[-1]
                    if not name: return rows
                    declaration = elements.get(element.attrib.get('ref', '').split(':')[-1], element)
                    type_name = declaration.attrib.get('type', '').split(':')[-1]
                    current = f'{current_path}.{("@" if local(element) == "attribute" else "")}{name}'.strip('.')
                    repeated = inherited_repeat or element.attrib.get('maxOccurs', '1') not in ('0', '1')
                    current_repeat = current if repeated and not inherited_repeat else inherited_repeat_path
                    direct = []
                    def declarations(container, visited=()):
                        if id(container) in visited: return
                        visited = (*visited, id(container))
                        for child in container:
                            if local(child) in ('element', 'attribute'): direct.append(child)
                            else:
                                if local(child) == 'extension':
                                    base = types.get(child.attrib.get('base', '').split(':')[-1])
                                    if base is not None: declarations(base, visited)
                                declarations(child, visited)
                    complex_type = next((child for child in declaration if local(child) == 'complexType'), None)
                    if complex_type is None and type_name not in active: complex_type = types.get(type_name)
                    if complex_type is not None: declarations(complex_type)
                    if direct:
                        for child in direct: rows.extend(walk(child, current, repeated, current_repeat, (*active, type_name)))
                    else:
                        xsd_type = declaration.attrib.get('type', 'string').split(':')[-1]
                        simple_type = types.get(xsd_type)
                        if simple_type is not None:
                            restriction = next((node for node in simple_type.iter() if local(node) == 'restriction'), None)
                            if restriction is not None: xsd_type = restriction.attrib.get('base', 'string').split(':')[-1]
                        normalized = {'decimal':'number','double':'number','float':'number','int':'integer','long':'integer','dateTime':'string'}.get(xsd_type, xsd_type)
                        rows.append({'path': current, 'name': ('@' if local(element) == 'attribute' else '') + name, 'type': normalized, 'required': element.attrib.get('use') == 'required' if local(element) == 'attribute' else element.attrib.get('minOccurs', '1') != '0', 'repeating': repeated, 'repeatPath': current_repeat})
                    return rows
                top = next((child for child in root if local(child) == 'element'), None)
                return walk(top, path, repeating, repeat_path) if top is not None else []
            except ElementTree.ParseError: return []
    if _root is None: _root = schema
    def resolve(node, active):
        while isinstance(node, dict) and '$ref' in node:
            reference = node['$ref']
            if not isinstance(reference, str) or (reference != '#' and not reference.startswith('#/')) or reference in active: return {}, active
            resolved = _root
            try:
                for part in reference[2:].split('/') if reference.startswith('#/') else []:
                    resolved = resolved[part.replace('~1', '/').replace('~0', '~')]
            except (KeyError, TypeError): return {}, active
            if not isinstance(resolved, dict): return {}, active
            node = {**resolved, **{key: value for key, value in node.items() if key != '$ref'}}
            active = (*active, reference)
        return node, active
    schema, _active = resolve(schema, _active)
    if len(_active) > 32: return []
    if isinstance(schema, dict) and ('properties' in schema or schema.get('type') == 'object'):
        required = set(schema.get('required', []))
        for name, child in schema.get('properties', {}).items():
            child_path = f'{path}.{name}'.strip('.')
            child, child_active = resolve(child, _active)
            child_repeating = isinstance(child, dict) and child.get('type') == 'array'
            definition, child_active = resolve(child.get('items', {}) if child_repeating else child, child_active)
            next_repeat_path = child_path if child_repeating else repeat_path
            if isinstance(definition, dict) and (definition.get('type') == 'object' or 'properties' in definition): fields.extend(flatten_schema(definition, child_path, repeating or child_repeating, next_repeat_path, _root, child_active))
            else: fields.append({'path': child_path, 'name': name, 'type': ('|'.join(definition['type']) if isinstance(definition.get('type'), list) else definition.get('type', 'any')) if isinstance(definition, dict) else type(definition).__name__, 'required': name in required, 'repeating': repeating or child_repeating, 'repeatPath': next_repeat_path})
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
    linguistic_cache, ancestor_cache, token_cache = {}, {}, {}
    def tokens(name):
        if name not in token_cache: token_cache[name] = _tokens(name)
        return token_cache[name]
    for target in targets:
        candidates = []
        for source in sources:
            source_name, target_name = source['name'].lower(), target['name'].lower()
            pair = (source_name, target_name)
            if pair not in linguistic_cache:
                st, tt = tokens(source_name), tokens(target_name)
                linguistic_cache[pair] = max(SequenceMatcher(None, source_name, target_name).ratio(), len(st & tt) / max(1, len(st | tt)))
            linguistic = linguistic_cache[pair]
            type_score = 1 if source['type'] == target['type'] else (.55 if {source['type'], target['type']} <= {'integer','number','float'} else .2)
            sp, tp = source['path'].split('.')[:-1], target['path'].split('.')[:-1]
            ancestors = ('.'.join(sp).lower(), '.'.join(tp).lower())
            if ancestors not in ancestor_cache: ancestor_cache[ancestors] = SequenceMatcher(None, *ancestors).ratio() if sp and tp else .5
            ancestor = ancestor_cache[ancestors]
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
    tokens = _path_tokens(path)
    def walk(current, index):
        if index == len(tokens): return current
        part, bracket_index = tokens[index]
        if isinstance(current, list):
            if not part.isdigit():
                # XPath-style traversal through a sequence preserves the sequence.
                return [walk(item, index) for item in current]
            # BW/XPath positions are one-based: book[1] is the first book.
            position = int(part) - 1 if bracket_index else int(part)
            if position < 0 or position >= len(current): return None
            current = current[position]
        elif isinstance(current, dict):
            remaining = '.'.join(token for token, bracket in tokens[index:] if not bracket)
            if all(not bracket for _, bracket in tokens[index:]) and remaining in current: return current[remaining]
            current = current.get(part)
        else: return None
        return walk(current, index + 1)
    return walk(value, 0)

def set_path(target: dict, path: str, value: Any):
    parts = path.strip('.').split('.'); current = target
    for part in parts[:-1]: current = current.setdefault(part, {})
    if parts: current[parts[-1]] = value

def _values(value: Any, args: list[Any]) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple, set)) and not args else [value, *args]


def _date_value(value: Any) -> datetime:
    if isinstance(value, datetime): return value
    if isinstance(value, date): return datetime.combine(value, time(), timezone.utc)
    text = str(value or '').strip().replace('Z', '+00:00')
    try: parsed = datetime.fromisoformat(text)
    except ValueError: parsed = datetime.strptime(text, '%Y-%m-%d')
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _date_pattern(value: str) -> str:
    pattern = str(value or '%Y-%m-%d')
    for source, target in [('yyyy','%Y'),('MM','%m'),('dd','%d'),('HH','%H'),('mm','%M'),('ss','%S'),('XXX','%z')]: pattern = pattern.replace(source, target)
    return pattern


def _render_xml(value: Any, root_name: str = 'root', pretty: bool = False) -> str:
    """Render the mapper's XML object representation as serialized XML.

    Parsed XML values use ``{root, value}``; ordinary dictionaries use keys
    as element names, ``@name`` for attributes, and ``#text`` for text. Lists
    become repeated sibling elements. This mirrors the Render XML activity so
    mapping expressions and activities produce the same wire format.
    """
    if isinstance(value, dict):
        # Parsed XML activities retain both the object representation and the
        # original wire value.  If a caller passes that envelope back through
        # render-xml, return the XML string rather than serializing the
        # envelope itself.
        for key in ('xmlString', 'xml', 'IDocXML'):
            candidate = value.get(key)
            if isinstance(candidate, (str, bytes)) and str(candidate).lstrip().startswith('<'):
                return candidate.decode() if isinstance(candidate, bytes) else candidate
        if 'root' in value and 'value' in value:
            root_name, value = value['root'], value['value']
    root_name = re.sub(r'[^A-Za-z0-9_.-]', '_', str(root_name or 'root')) or 'root'

    def build(name: str, item: Any):
        element = ElementTree.Element(re.sub(r'[^A-Za-z0-9_.-]', '_', str(name)) or 'item')
        if isinstance(item, dict):
            for key, child in item.items():
                key = str(key)
                if key.startswith('@'):
                    element.set(key[1:], '' if child is None else str(child))
                elif key == '#text':
                    element.text = '' if child is None else str(child)
                elif isinstance(child, list):
                    for entry in child:
                        element.append(build(key, entry))
                else:
                    element.append(build(key, child))
        elif item is not None:
            element.text = str(item)
        return element

    if isinstance(value, list):
        value = {'item': value}
    root = build(root_name, value)
    if pretty:
        ElementTree.indent(root, space='  ')
    return ElementTree.tostring(root, encoding='unicode')


def apply_function(name: str, value: Any = None, args: list[Any] | None = None):
    """Execute the built-in integration-mapper function catalog."""
    args = list(args or []); key = str(name or '').lower().replace('-', '').replace('_', '')
    text = '' if value is None else str(value)
    if key in ('lookup', 'lookuptable'):
        if not args or not isinstance(args[0], dict): raise ValueError('lookup requires a lookup table object')
        return args[0].get(str(value), args[1] if len(args) > 1 else None)
    if key == 'enrich':
        if not isinstance(value, dict) or not args or not isinstance(args[0], dict): raise ValueError('enrich requires two objects')
        return {**value, **args[0]}
    if key == 'chunks':
        size = int(args[0] if args else 100)
        if not isinstance(value, list) or size < 1 or size > 10000: raise ValueError('chunks requires an array and a size between 1 and 10000')
        return [value[index:index + size] for index in range(0, len(value), size)]
    if key == 'joinby':
        if not isinstance(value, list) or len(args) < 3 or not isinstance(args[0], list): raise ValueError('joinBy requires two arrays and their key paths')
        index = {}
        for row in args[0]: index.setdefault(json.dumps(get_path(row, str(args[2])), sort_keys=True), []).append(row)
        result = []
        for row in value:
            left_key = get_path(row, str(args[1]))
            if left_key is None: continue
            for match in index.get(json.dumps(left_key, sort_keys=True), []):
                if len(result) >= 100000: raise ValueError('joinBy exceeds 100000 result records')
                result.append({**row, **match})
        return result
    if key in ('equal', 'notequal', 'greaterthan', 'lessthan', 'greaterorequal', 'lessorequal'):
        other = args[0] if args else None
        if key == 'equal': return value == other
        if key == 'notequal': return value != other
        if key == 'greaterthan': return value > other
        if key == 'lessthan': return value < other
        if key == 'greaterorequal': return value >= other
        return value <= other
    if key in ('add', 'subtract', 'multiply', 'divide'):
        left, right = float(value), float(args[0])
        if key == 'add': return left + right
        if key == 'subtract': return left - right
        if key == 'multiply': return left * right
        return left / right
    if key in ('group', 'groupby'):
        groups = {}
        for item in value or []:
            group_key = get_path(item, str(args[0])) if args and args[0] else item
            token = json.dumps(group_key, sort_keys=True, default=str)
            groups.setdefault(token, []).append(item)
        return list(groups.values())
    if key == 'top':
        count = int(args[0]) if args else 1
        if count < 0: raise ValueError('top count must be nonnegative')
        return sorted(value or [], reverse=True)[:count]
    if key == 'concat': return ''.join('' if item is None else str(item) for item in [value, *args])
    if key in ('uppercase','upper'): return text.upper()
    if key in ('lowercase','lower'): return text.lower()
    if key == 'trim': return text.strip()
    if key == 'normalizespace': return ' '.join(text.split())
    if key == 'stringlength': return len(text)
    if key == 'substring':
        start = max(0, int(args[0]) - 1) if args else 0; end = start + int(args[1]) if len(args) > 1 else None
        return text[start:end]
    if key == 'substringbefore': return text.split(str(args[0]), 1)[0] if args and str(args[0]) in text else ''
    if key == 'substringafter': return text.split(str(args[0]), 1)[1] if args and str(args[0]) in text else ''
    if key == 'replace': return re.sub(str(args[0]), str(args[1]), text) if len(args) > 1 else text
    if key in ('tokenize','split'): return re.split(str(args[0] if args else ','), text)
    if key == 'join': return str(args[0] if args else ',').join(map(str, value or []))
    if key == 'matches': return bool(re.search(str(args[0] if args else ''), text))
    if key == 'startswith': return text.startswith(str(args[0] if args else ''))
    if key == 'endswith': return text.endswith(str(args[0] if args else ''))
    if key == 'contains': return str(args[0] if args else '') in text
    if key == 'compare': return (text > str(args[0])) - (text < str(args[0])) if args else 0
    if key == 'translate': return text.translate(str.maketrans(str(args[0]), str(args[1]))) if len(args) > 1 else text
    if key == 'padleft': return text.rjust(int(args[0]), str(args[1] if len(args) > 1 else ' ')[:1])
    if key == 'padright': return text.ljust(int(args[0]), str(args[1] if len(args) > 1 else ' ')[:1])
    if key == 'capitalize': return text.capitalize()
    if key == 'prefix': return str(args[0] if args else '') + text
    if key == 'suffix': return text + str(args[0] if args else '')
    if key in ('string','tostring'): return '' if value is None else str(value)
    if key in ('number','decimal'): return float(value)
    if key in ('integer','tointeger'): return int(float(value))
    if key == 'boolean': return value if isinstance(value, bool) else str(value).strip().lower() in ('true','1','yes','on')
    if key == 'round': return round(float(value), int(args[0]) if args else 0)
    if key == 'roundhalftoeven': return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-(int(args[0]) if args else 0)), rounding=ROUND_HALF_EVEN))
    if key == 'floor': return math.floor(float(value))
    if key in ('ceiling','ceil'): return math.ceil(float(value))
    if key == 'abs': return abs(float(value))
    if key == 'sqrt': return math.sqrt(float(value))
    if key == 'power': return math.pow(float(value), float(args[0]))
    if key in ('modulo','mod'): return float(value) % float(args[0])
    if key == 'clamp': return max(float(args[0]), min(float(args[1]), float(value)))
    if key in ('min','max','sum','average','avg','count'):
        values = _values(value, args)
        if key == 'count': return len(value) if isinstance(value, (list, tuple, dict, set, str)) and not args else len(values)
        numeric = [float(item) for item in values]
        if key == 'min': return min(numeric) if numeric else None
        if key == 'max': return max(numeric) if numeric else None
        if key == 'sum': return sum(numeric)
        return sum(numeric) / len(numeric) if numeric else 0
    now = datetime.now(timezone.utc)
    if key == 'currentdate': return now.date().isoformat()
    if key == 'currenttime': return now.time().isoformat(timespec='seconds')
    if key in ('currentdatetime','now'): return now.isoformat()
    if key in ('parsedate','parsedatetime'): return _date_value(value).isoformat()
    if key in ('formatdate','formatdatetime'): return _date_value(value).strftime(_date_pattern(str(args[0] if args else 'yyyy-MM-dd')))
    if key in ('adddays','addhours','addminutes','addseconds'):
        amount = float(args[0] if args else 0); unit = {'adddays':'days','addhours':'hours','addminutes':'minutes','addseconds':'seconds'}[key]
        return (_date_value(value) + timedelta(**{unit: amount})).isoformat()
    if key == 'addmonths':
        parsed = _date_value(value); total = parsed.year * 12 + parsed.month - 1 + int(args[0] if args else 0); year, month = divmod(total, 12)
        return parsed.replace(year=year, month=month + 1, day=min(parsed.day, calendar.monthrange(year, month + 1)[1])).isoformat()
    if key == 'datedifference': return (_date_value(args[0]) - _date_value(value)).total_seconds() / 86400 if args else 0
    if key in ('year','month','day','hour','minute','second'): return getattr(_date_value(value), key)
    if key == 'timezonefromdatetime': return _date_value(value).strftime('%z')
    if key == 'not': return not bool(value)
    if key in ('exists','isnotempty'): return value not in (None, '', [], {})
    if key in ('empty','isempty'): return value in (None, '', [], {})
    if key in ('default','coalesce'):
        return next((item for item in [value, *args] if item not in (None, '')), None)
    if key == 'ifthenelse': return args[0] if bool(value) and args else (args[1] if len(args) > 1 else None)
    if key == 'distinctvalues': return list(dict.fromkeys(value or []))
    if key == 'deepequal': return value == (args[0] if args else None)
    if key == 'sort': return sorted(value or [], reverse=bool(args and str(args[0]).lower() in ('desc','true','1')))
    if key == 'reverse': return list(reversed(value)) if isinstance(value, (list, tuple)) else text[::-1]
    if key == 'first': return value[0] if value else None
    if key == 'last': return value[-1] if value else None
    if key == 'indexof':
        try: return value.index(args[0])
        except (ValueError, AttributeError, IndexError): return -1
    if key == 'subsequence': return list(value or [])[int(args[0] if args else 0):int(args[1]) if len(args) > 1 else None]
    if key == 'flatten': return [item for group in (value or []) for item in (group if isinstance(group, list) else [group])]
    if key == 'jsonparse': return json.loads(text)
    if key == 'jsonrender': return json.dumps(value, separators=(',', ':') if args and args[0] is False else None, default=str)
    if key in ('renderxml', 'xmlrender'): return _render_xml(value, str(args[0]) if args and args[0] not in (None, '') else 'root', bool(args[1]) if len(args) > 1 else False)
    if key == 'base64encode': return base64.b64encode(text.encode()).decode()
    if key == 'base64decode': return base64.b64decode(text).decode()
    if key == 'hexencode': return text.encode().hex()
    if key == 'hexdecode': return bytes.fromhex(text).decode()
    if key == 'urlencode': return urllib.parse.quote(text, safe='')
    if key == 'urldecode': return urllib.parse.unquote(text)
    if key == 'uuid': return str(uuid.uuid4())
    if key == 'hash': return hashlib.new(str(args[0] if args else 'sha256').replace('-', '').lower(), text.encode()).hexdigest()
    raise ValueError(f'Unsupported mapper function {name!r}')


def transform_value(value: Any, functions: list[Any], lookup_tables=None):
    for spec in functions or []:
        name, args = (spec, []) if isinstance(spec, str) else (spec.get('name'), spec.get('args', []))
        if str(name).lower().replace('-', '') == 'lookuptable' and args and isinstance(args[0], str):
            if args[0] not in (lookup_tables or {}): raise ValueError(f'Lookup table {args[0]!r} was not found')
            args = [(lookup_tables or {})[args[0]], *args[1:]]
        value = apply_function(name, value, args)
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
        if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
            raise ValueError(f'Cannot safely coerce {value!r} to {target_type} without losing precision')
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


def validate_xsd_output(document: Any, schema: str, _budget=None) -> list[str]:
    """Validate named/inline XSD structures without requiring optional parents."""
    errors = []
    try: root = ElementTree.fromstring(schema)
    except ElementTree.ParseError: return ['Invalid target XSD']
    local = lambda node: node.tag.rsplit('}', 1)[-1]
    types = {node.attrib.get('name'): node for node in root if local(node) in ('complexType', 'simpleType')}
    elements = {node.attrib.get('name'): node for node in root if local(node) == 'element'}

    def scalar(value, name):
        name = name.split(':')[-1].lower()
        if name in ('string', 'normalizedstring', 'token', 'date', 'datetime', 'time', 'anyuri', 'hexbinary', 'base64binary'): return isinstance(value, str)
        if name in ('integer', 'int', 'long', 'short', 'byte', 'nonnegativeinteger', 'positiveinteger'): return isinstance(value, int) and not isinstance(value, bool)
        if name in ('number', 'decimal', 'double', 'float'): return isinstance(value, (int, float)) and not isinstance(value, bool)
        if name in ('boolean', 'bool'): return isinstance(value, bool)
        return True

    def contents(container, value, path, active):
        for child in container:
            tag = local(child)
            if tag in ('element', 'attribute'): field(child, value, path, active)
            elif tag == 'choice':
                choices = [node for node in child if local(node) == 'element']
                present = [node for node in choices if (node.attrib.get('name') or node.attrib.get('ref', '').split(':')[-1]) in value]
                if not present and child.attrib.get('minOccurs', '1') != '0': errors.append(f'{path}: a choice element is required')
                for node in present: field(node, value, path, active)
            elif tag == 'extension':
                base = child.attrib.get('base', '').split(':')[-1]
                if base in types and base not in active: contents(types[base], value, path, (*active, base))
                contents(child, value, path, active)
            elif tag in ('sequence', 'all', 'complexContent', 'simpleContent'): contents(child, value, path, active)

    def field(node, parent, prefix, active=()):
        if _budget: _budget()
        name = node.attrib.get('name') or node.attrib.get('ref', '').split(':')[-1]
        if not name: return
        if local(node) == 'attribute': name = '@' + name
        path = f'{prefix}.{name}'.strip('.')
        minimum = 1 if node.attrib.get('use') == 'required' else 0 if local(node) == 'attribute' else int(node.attrib.get('minOccurs', '1'))
        maximum = node.attrib.get('maxOccurs', '1')
        value = parent.get(name) if isinstance(parent, dict) else None
        if value is None:
            if minimum: errors.append(f'{path}: required field is not mapped')
            return
        values = value if isinstance(value, list) else [value]
        if maximum not in ('0', '1') and not isinstance(value, list): errors.append(f'{path}: expected repeating value')
        if len(values) < minimum or maximum != 'unbounded' and len(values) > int(maximum): errors.append(f'{path}: occurrence count is outside {minimum}..{maximum}')
        declaration = elements.get(node.attrib.get('ref', '').split(':')[-1], node)
        type_name = declaration.attrib.get('type', 'string').split(':')[-1]
        definition = next((child for child in declaration if local(child) in ('complexType', 'simpleType')), None)
        if definition is None: definition = types.get(type_name)
        for index, item in enumerate(values):
            item_path = f'{path}[{index + 1}]' if isinstance(value, list) else path
            if definition is not None and local(definition) == 'complexType':
                if not isinstance(item, dict): errors.append(f'{item_path}: expected object'); continue
                contents(definition, item, item_path, (*active, type_name))
            else:
                restriction = next((child for child in definition.iter() if local(child) == 'restriction'), None) if definition is not None else None
                expected = restriction.attrib.get('base', type_name) if restriction is not None else type_name
                if not scalar(item, expected): errors.append(f'{item_path}: expected {expected.split(":")[-1]}')
                if restriction is not None:
                    lexical = str(item).lower() if isinstance(item, bool) else str(item)
                    facets = {}
                    for facet in restriction: facets.setdefault(local(facet), []).append(facet.attrib.get('value', ''))
                    if 'enumeration' in facets and lexical not in facets['enumeration']: errors.append(f'{item_path}: value is not in enumeration')
                    for facet in ('length', 'minLength', 'maxLength'):
                        if facet in facets:
                            bound = int(facets[facet][0]); length = len(lexical)
                            if (facet == 'length' and length != bound or facet == 'minLength' and length < bound or facet == 'maxLength' and length > bound): errors.append(f'{item_path}: violates {facet}')
                    for pattern in facets.get('pattern', []):
                        if not pattern_matches(pattern, lexical, full=True): errors.append(f'{item_path}: does not match XSD pattern')
                    if not isinstance(item, bool) and isinstance(item, (int, float)):
                        numeric = Decimal(str(item))
                        for facet in ('minInclusive', 'maxInclusive', 'minExclusive', 'maxExclusive'):
                            if facet in facets:
                                bound = Decimal(facets[facet][0])
                                if {'minInclusive': numeric < bound, 'maxInclusive': numeric > bound, 'minExclusive': numeric <= bound, 'maxExclusive': numeric >= bound}[facet]: errors.append(f'{item_path}: violates {facet}')
                        digits = numeric.normalize().as_tuple()
                        if 'fractionDigits' in facets and max(0, -digits.exponent) > int(facets['fractionDigits'][0]): errors.append(f'{item_path}: violates fractionDigits')
                        if 'totalDigits' in facets and len(digits.digits) + max(0, digits.exponent) > int(facets['totalDigits'][0]): errors.append(f'{item_path}: violates totalDigits')

    top = next((node for node in root if local(node) == 'element'), None)
    if top is not None: field(top, document, '')
    return errors


def validate_output(document: Any, schema: Any, _budget=None) -> list[str]:
    """Validate project JSON contracts, including local refs and value constraints.

    This dependency-free subset does not fetch remote references or infer formats.
    """
    started = clock.monotonic()
    def budget():
        if _budget: _budget()
        if clock.monotonic() - started > 30: raise ValueError('Contract validation deadline exceeded')
    if isinstance(schema, str) and schema.strip():
        try: schema = json.loads(schema)
        except (ValueError, TypeError): return validate_xsd_output(document, schema, budget)
    if schema is None or schema == '': return []
    if isinstance(schema, dict) and schema and not any(key in schema for key in
            ('type', 'properties', '$ref', '$defs', 'definitions', 'enum', 'const', 'allOf', 'anyOf', 'oneOf', 'not', 'items', 'required', 'pattern', 'format', 'patternProperties', 'if', 'dependentRequired', 'contains')):
        return [f'{field["path"]}: required field is not mapped' for field in flatten_schema(schema)
                if field.get('required') and get_path(document, field['path']) is None]
    def fingerprint(value):
        if isinstance(value, bool): return ('boolean', value)
        if isinstance(value, (int, float)): return ('number', value)
        if isinstance(value, dict): return ('object', tuple(sorted((key, fingerprint(item)) for key, item in value.items())))
        if isinstance(value, list): return ('array', tuple(fingerprint(item) for item in value))
        return (type(value).__name__, value)
    def matches(value, expected):
        if expected == 'null': return value is None
        if expected == 'object': return isinstance(value, dict)
        if expected == 'array': return isinstance(value, list)
        if expected == 'string': return isinstance(value, str)
        if expected in ('integer', 'int'): return not isinstance(value, bool) and isinstance(value, (int, float)) and (not isinstance(value, float) or math.isfinite(value)) and int(value) == value
        if expected in ('number', 'decimal', 'double', 'float'): return not isinstance(value, bool) and isinstance(value, (int, float)) and (not isinstance(value, float) or math.isfinite(value))
        if expected in ('boolean', 'bool'): return isinstance(value, bool)
        return True
    def walk(value, definition, path='', depth=0):
        budget()
        label = path or 'result'
        errors = []
        if depth > 128: return [f'{label}: schema recursion limit exceeded']
        if definition is True: return []
        if definition is False: return [f'{label}: value is prohibited by schema']
        if not isinstance(definition, dict): return [f'{label}: invalid schema definition']
        if '$ref' in definition:
            reference = definition['$ref']
            if not isinstance(reference, str) or not (reference == '#' or reference.startswith('#/')):
                return [f'{label}: only local JSON schema references are supported']
            resolved = schema
            try:
                for part in reference[2:].split('/') if reference != '#' else []:
                    part = part.replace('~1', '/').replace('~0', '~')
                    resolved = resolved[int(part)] if isinstance(resolved, list) else resolved[part]
            except (KeyError, IndexError, TypeError, ValueError): return [f'{label}: unresolved schema reference {reference}']
            errors.extend(walk(value, resolved, path, depth + 1))
        expected = definition.get('type')
        types = expected if isinstance(expected, list) else [expected] if expected else []
        if types and not any(matches(value, kind) for kind in types): return [*errors, f'{label}: expected {" or ".join(types)}']
        if 'const' in definition and fingerprint(value) != fingerprint(definition['const']): errors.append(f'{label}: value does not match const')
        if 'enum' in definition and not any(fingerprint(value) == fingerprint(item) for item in definition['enum']): errors.append(f'{label}: value is not in enum')
        for keyword in ('allOf', 'anyOf', 'oneOf'):
            if keyword in definition:
                branches = [walk(value, child, path, depth + 1) for child in definition[keyword]]
                passed = sum(not branch for branch in branches)
                if keyword == 'allOf': errors.extend(error for branch in branches for error in branch)
                elif keyword == 'anyOf' and not passed: errors.append(f'{label}: does not match any allowed schema')
                elif keyword == 'oneOf' and passed != 1: errors.append(f'{label}: must match exactly one allowed schema')
        if 'if' in definition:
            branch = 'then' if not walk(value, definition['if'], path, depth + 1) else 'else'
            if branch in definition: errors.extend(walk(value, definition[branch], path, depth + 1))
        if 'not' in definition and not walk(value, definition['not'], path, depth + 1): errors.append(f'{label}: matches a prohibited schema')
        if isinstance(value, dict):
            for required in definition.get('required', []):
                if required not in value: errors.append(f'{path + "." if path else ""}{required}: required field is not mapped')
            properties = definition.get('properties', {})
            patterns = definition.get('patternProperties', {})
            for trigger, dependencies in definition.get('dependentRequired', {}).items():
                if trigger in value:
                    for dependency in dependencies:
                        if dependency not in value: errors.append(f'{label}: {trigger} requires {dependency}')
            for key, item in value.items():
                matched = []
                for pattern, child in patterns.items():
                    budget()
                    if pattern_matches(pattern, key): matched.append(child)
                children = ([properties[key]] if key in properties else []) + matched
                if not children: children = [definition.get('additionalProperties', True)]
                for child in children: errors.extend(walk(item, child, f'{path}.{key}'.strip('.'), depth + 1))
                if 'propertyNames' in definition: errors.extend(walk(key, definition['propertyNames'], f'{label} property {key}', depth + 1))
            for keyword, comparison in (('minProperties', len(value) < definition.get('minProperties', 0)), ('maxProperties', len(value) > definition.get('maxProperties', len(value)))):
                if comparison: errors.append(f'{label}: violates {keyword}')
        elif isinstance(value, list):
            if len(value) < definition.get('minItems', 0): errors.append(f'{label}: fewer than minItems')
            if len(value) > definition.get('maxItems', len(value)): errors.append(f'{label}: more than maxItems')
            if definition.get('uniqueItems') and len({fingerprint(item) for item in value}) != len(value): errors.append(f'{label}: duplicate items are not allowed')
            if 'contains' in definition:
                count = sum(not walk(item, definition['contains'], f'{label}[{index + 1}]', depth + 1) for index, item in enumerate(value))
                if count < definition.get('minContains', 1) or count > definition.get('maxContains', len(value)): errors.append(f'{label}: violates contains count')
            prefix = definition.get('prefixItems', [])
            items = definition.get('items', True)
            if isinstance(items, list): prefix, items = items, definition.get('additionalItems', True)
            for index, item in enumerate(value):
                child = prefix[index] if index < len(prefix) else items
                errors.extend(walk(item, child, f'{label}[{index + 1}]', depth + 1))
        elif isinstance(value, str):
            if 'pattern' in definition and not pattern_matches(definition['pattern'], value): errors.append(f'{label}: does not match pattern')
            if 'format' in definition and not format_valid(value, definition['format']): errors.append(f'{label}: invalid {definition["format"]} format')
            if len(value) < definition.get('minLength', 0): errors.append(f'{label}: shorter than minLength')
            if len(value) > definition.get('maxLength', len(value)): errors.append(f'{label}: longer than maxLength')
        elif not isinstance(value, bool) and isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value): errors.append(f'{label}: number must be finite')
            else:
                for keyword, failed in (('minimum', value < definition.get('minimum', value)), ('maximum', value > definition.get('maximum', value)),
                                        ('exclusiveMinimum', value <= definition.get('exclusiveMinimum', value - 1)), ('exclusiveMaximum', value >= definition.get('exclusiveMaximum', value + 1))):
                    if keyword in definition and failed: errors.append(f'{label}: violates {keyword}')
                if 'multipleOf' in definition:
                    divisor = Decimal(str(definition['multipleOf']))
                    if divisor <= 0: errors.append(f'{label}: multipleOf must be positive')
                    elif Decimal(str(value)) % divisor != 0: errors.append(f'{label}: violates multipleOf')
        return errors
    return walk(document, schema)


def _clean_path(value: Any) -> str:
    text = str(value or '').strip()
    return text[2:-1] if text.startswith('${') and text.endswith('}') else text


def _relative_path(path: str, parent: str) -> str | None:
    path, parent = _clean_path(path), _clean_path(parent)
    if path == parent: return ''
    if parent and path.startswith(parent + '.'): return path[len(parent) + 1:]
    return None


def _function_arguments(raw: str) -> list[str]:
    arguments: list[str] = []; start = 0; depth = 0; quote = ''; escaped = False
    for index, character in enumerate(raw):
        if quote:
            if escaped: escaped = False
            elif character == '\\': escaped = True
            elif character == quote: quote = ''
        elif character in ('"', "'"): quote = character
        elif character in '([{': depth += 1
        elif character in ')]}': depth = max(0, depth - 1)
        elif character == ',' and depth == 0: arguments.append(raw[start:index].strip()); start = index + 1
    if raw[start:].strip(): arguments.append(raw[start:].strip())
    return arguments


def rewrite_references(expression: str, rewrite) -> str:
    """Normalize references while preserving quoted string constants verbatim."""
    result = []; index = 0; quote = None; escaped = False
    while index < len(expression):
        char = expression[index]
        if quote:
            result.append(char)
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == quote: quote = None
        elif char in ('"', "'"):
            quote = char; result.append(char)
        elif expression[index:index + 2] == '${':
            end = expression.find('}', index + 2)
            if end < 0: result.append(expression[index:]); break
            result.append(rewrite(expression[index:end + 1])); index = end
        else: result.append(char)
        index += 1
    return ''.join(result)


def evaluate_condition(expression: Any, resolve) -> bool:
    """Evaluate conditions without splitting literals, references or function arguments.

    Logical operators have conventional precedence (not, and, or). The caller
    resolves operands in its own document or repeating-element scope.
    """
    text = str(expression or '').strip()
    if not text: return False
    tokens = []
    depth = 0
    quote = None
    escaped = False
    reference = False
    for index, char in enumerate(text):
        if quote:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == quote: quote = None
            continue
        if reference:
            if char == '}': reference = False
            continue
        if char in ('"', "'"): quote = char; continue
        if text[index:index + 2] == '${': reference = True; continue
        if char in '([': depth += 1; continue
        if char in ')]':
            depth -= 1
            if depth < 0: raise ValueError('Unbalanced condition parentheses')
            continue
        if depth == 0: tokens.append(index)
    if quote or reference or depth: raise ValueError('Unclosed condition literal, reference or parentheses')
    # No top-level tokens means an enclosing pair of parentheses, provided it
    # spans the whole expression rather than a function call.
    if text.startswith('(') and text.endswith(')') and not tokens:
        return evaluate_condition(text[1:-1], resolve)
    for keyword, reducer in (('or', any), ('and', all)):
        cuts = [index for index in tokens if text[index:index + len(keyword)].lower() == keyword
                and (index == 0 or text[index - 1].isspace())
                and (index + len(keyword) == len(text) or text[index + len(keyword)].isspace())]
        if cuts:
            parts = []; start = 0
            for index in cuts:
                parts.append(text[start:index]); start = index + len(keyword)
            parts.append(text[start:])
            if any(not part.strip() for part in parts): raise ValueError('Missing logical condition operand')
            return reducer(evaluate_condition(part, resolve) for part in parts)
    if re.match(r'^not\s*\(', text, re.I) or re.match(r'^not\s+', text, re.I):
        return not evaluate_condition(text[3:].strip(), resolve)
    for index in tokens:
        operator = next((op for op in ('!=', '>=', '<=', '==', '=', '>', '<') if text.startswith(op, index)), None)
        if not operator: continue
        left_text, right_text = text[:index].strip(), text[index + len(operator):].strip()
        if not left_text or not right_text: raise ValueError('Missing comparison operand')
        left, right = resolve(left_text), resolve(right_text)
        if operator in ('=', '=='): return left == right
        if operator == '!=': return left != right
        if left is None or right is None: return False
        try:
            if operator == '>': return left > right
            if operator == '<': return left < right
            if operator == '>=': return left >= right
            return left <= right
        except TypeError: return False
    return bool(resolve(text))


def validate_mapping_rules(mappings: Any, schema: Any = None, input_types: dict | None = None, custom_functions: list | None = None) -> list[str]:
    """Reject invalid literal mappings before compiling a deployable archive.

    References and function results remain dynamic and are checked at execution.
    Legacy untyped mappings are retained; schema/targetType metadata is authoritative.
    """
    types = {field['path']: field['type'] for field in flatten_schema(schema)} if schema else {}
    types.update(input_types or {})
    rules = [{'target': key, **(value if isinstance(value, dict) and '$rule' in value else {'source': value})}
             for key, value in mappings.items()] if isinstance(mappings, dict) else mappings or []
    if not rules: return []
    errors = []
    string_types = {'string', 'binary', 'normalizedstring', 'token', 'date', 'datetime', 'time', 'anyuri', 'language', 'name', 'ncname', 'id', 'idref', 'hexbinary', 'base64binary'}
    numeric_types = {'number', 'decimal', 'double', 'float'}
    integer_types = {'integer', 'int', 'long', 'short', 'byte', 'nonnegativeinteger', 'positiveinteger'}
    import inspect
    function_tree = ast.parse(inspect.getsource(apply_function))
    functions = {'true', 'false', 'currentgroup'}
    for node in ast.walk(function_tree):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == 'key':
            for comparator in node.comparators:
                for item in ast.walk(comparator):
                    if isinstance(item, ast.Constant) and isinstance(item.value, str): functions.add(item.value)

    functions.update(('custom:' + item['name']).lower().replace('-', '').replace('_', '') for item in custom_functions or [] if item.get('name'))

    def syntax(value, label):
        if not isinstance(value, str): return True
        stack, quote, escaped, unquoted = [], '', False, ''
        for char in value:
            if quote:
                if escaped: escaped = False
                elif char == '\\': escaped = True
                elif char == quote: quote = ''
                unquoted += ' '
            elif char in ('"', "'"): quote = char; unquoted += ' '
            else:
                unquoted += char
                if char in '([{': stack.append(char)
                elif char in ')]}' and (not stack or stack.pop() != {')':'(', ']':'[', '}':'{'}[char]):
                    errors.append(f'{label}: mismatched expression brackets'); return False
        if quote or stack:
            errors.append(f'{label}: close the expression quotes and brackets'); return False
        for name in re.findall(r'([\w:-]+)\s*\(', unquoted):
            if name.lower() in ('and', 'or'): continue
            if name.lower().replace('-', '').replace('_', '') not in functions:
                errors.append(f'{label}: unsupported mapper function {name}'); return False
        return True

    def check(value, kind, label, constant=False):
        if (value is None or value == '') and not constant: return
        variants = kind if isinstance(kind, list) else str(kind or 'any').split('|')
        if len(variants) > 1:
            failures = []
            for variant in variants:
                before = len(errors)
                check(value, variant, label, constant)
                if len(errors) == before: return
                failures.extend(errors[before:]); del errors[before:]
            errors.append(failures[0]); return
        expected = str(kind or 'any').lower().replace('xsd:', '').replace('xs:', '')
        quoted = False
        parsed = value
        if isinstance(value, str) and not constant:
            text = value.strip()
            if not syntax(text, label): return
            if text[:1] in ('"', "'"):
                try:
                    parsed = ast.literal_eval(text)
                    quoted = isinstance(parsed, str)
                except (SyntaxError, ValueError):
                    errors.append(f'{label}: close the string with matching single or double quotes')
                    return
            elif '${' in text or re.fullmatch(r'[\w:-]+\(.*\)', text, re.S) or re.fullmatch(r'[A-Za-z_@][\w@-]*(?:\.[\w@-]+|\[\d+\])+', text):
                return
            else:
                try: parsed = json.loads(text)
                except (ValueError, TypeError): parsed = text
        valid = True
        if expected in string_types: valid = isinstance(parsed, str) and (constant or quoted)
        elif expected in numeric_types: valid = isinstance(parsed, (int, float)) and not isinstance(parsed, bool) and not quoted
        elif expected in integer_types:
            valid = isinstance(parsed, int) and not isinstance(parsed, bool) and not quoted
            if valid and expected == 'nonnegativeinteger': valid = parsed >= 0
            if valid and expected == 'positiveinteger': valid = parsed > 0
        elif expected in ('boolean', 'bool'): valid = isinstance(parsed, bool) and not quoted
        elif expected == 'null': valid = parsed is None
        elif expected in ('object', 'json', 'complex'): valid = isinstance(parsed, dict)
        elif expected == 'array' or expected.endswith('[]'): valid = isinstance(parsed, list)
        elif expected in ('any', 'anytype'): return
        if not valid:
            guidance = 'string literals require matching single or double quotes' if expected in string_types else f'expected {kind} literal without quotes' if expected in numeric_types | integer_types | {'boolean', 'bool'} else f'expected {kind}'
            errors.append(f'{label}: {guidance}')

    for rule in rules:
        if not isinstance(rule, dict) or rule.get('enabled') is False: continue
        target = rule.get('target', '')
        kind = types.get(target) or rule.get('targetType') or 'any'
        operator = rule.get('operator') or rule.get('$rule')
        for function in rule.get('functions') or []:
            name = function if isinstance(function, str) else function.get('name', '')
            if str(name).lower().replace('-', '').replace('_', '') not in functions:
                errors.append(f'{target}: unsupported mapper function {name}')
        if operator in ('for-each', 'for-each-group'):
            syntax(rule.get('select') or rule.get('source'), target)
            continue
        if 'constant' in rule: check(rule['constant'], kind, target, constant=True)
        elif operator == 'choose':
            branches = rule.get('whens')
            if branches is None:
                try: branches = json.loads(rule.get('source') or '[]')
                except (ValueError, TypeError): branches = []
            if not isinstance(branches, list) or not branches:
                errors.append(f'{target}: at least one When condition is required')
                continue
            for index, branch in enumerate(branches):
                if not str(branch.get('condition') or '').strip(): errors.append(f'{target} When {index + 1}: condition is empty')
                syntax(branch.get('condition'), f'{target} When {index + 1} condition')
                check(branch.get('source'), kind, f'{target} When {index + 1}')
            check(rule.get('otherwise'), kind, f'{target} Otherwise')
        else:
            if operator in ('if', 'when-otherwise') and not str(rule.get('condition') or '').strip(): errors.append(f'{target}: condition is empty')
            if operator in ('if', 'when-otherwise'): syntax(rule.get('condition'), f'{target} condition')
            check(rule.get('select') or rule.get('source'), kind, target)
            if 'otherwise' in rule: check(rule['otherwise'], kind, f'{target} Otherwise')
    return errors


def execute(document: Any, mappings: Any, options: dict | None = None) -> dict:
    """Execute BW-style mapping statements, including nested repeating targets."""
    if isinstance(document, dict) and isinstance(document.get('activities'), dict):
        document = dict(document)
        for activity_id, record in document['activities'].items():
            if not isinstance(record, dict) or 'output' not in record: continue
            name = re.sub(r'[^A-Za-z0-9_-]+', '-', str(record.get('name') or activity_id).strip())
            name = re.sub(r'-+', '-', name).strip('-') or 'Activity'
            for alias in (activity_id, name): document.setdefault(alias, record['output'])
    options = options or {}
    started = clock.monotonic(); steps = 0
    maximum_steps = int(options.get('maxIterations') or 100000)
    maximum_ms = int(options.get('maxExecutionMs') or 30000)
    if maximum_steps < 1 or maximum_ms < 1: raise ValueError('Execution limits must be positive')
    def tick():
        nonlocal steps
        steps += 1
        cancelled = options.get('_cancelled')
        if callable(cancelled) and cancelled(): raise ValueError('Transformation cancelled')
        if steps > maximum_steps: raise ValueError(f'Transformation exceeds {maximum_steps} evaluation steps')
        if (clock.monotonic() - started) * 1000 > maximum_ms: raise ValueError('Transformation execution deadline exceeded')
    loop_contexts = []
    custom_functions = {item['name']: item for item in options.get('customFunctions', []) if item.get('name')}
    result: dict[str, Any] = {}
    raw_rules = [{'target': key, 'source': value} for key, value in mappings.items()] if isinstance(mappings, dict) else mappings or []
    rules = [dict(rule) for rule in raw_rules if rule.get('enabled', True) and rule.get('target')]
    loops = [rule for rule in rules if str(rule.get('operator', '')).lower() in ('for-each', 'for-each-group')]
    loop_ids = {id(rule) for rule in loops}
    loop_plans = {}

    def under(path: str, parent: str) -> bool:
        return path.startswith(parent + '.')

    def resolve_value(rule: dict, scope: Any = None, scope_source: str = ''):
        tick()
        if 'constant' in rule: return rule['constant']
        def evaluate_source(expression: Any, bindings=None, depth=0):
            if not isinstance(expression, str): return expression
            text = expression.strip()
            if depth > 32: raise ValueError('Custom function recursion exceeded 32 calls')
            if bindings and text in bindings: return bindings[text]
            if not text: return None
            if text == 'current-group()': return loop_contexts[-1][1] if loop_contexts else []
            if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
                try: return ast.literal_eval(text)
                except (SyntaxError, ValueError): return text[1:-1]
            if text.lower() in ('true', 'true()'): return True
            if text.lower() in ('false', 'false()'): return False
            if text.lower() in ('null', '()'): return None
            if re.fullmatch(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?', text): return float(text) if any(char in text for char in '.eE') else int(text)
            if text.startswith(('{', '[')):
                try: return json.loads(text)
                except ValueError: pass
            call = re.fullmatch(r'([\w:-]+)\((.*)\)', text, re.S)
            if call:
                values = [evaluate_source(argument, bindings, depth + 1) for argument in _function_arguments(call.group(2))]
                if call.group(1).startswith('custom:'):
                    name = call.group(1).split(':', 1)[1]
                    definition = custom_functions.get(name)
                    if not definition: raise ValueError(f'Custom function {name!r} was not found in this project')
                    parameters = definition.get('parameters') or []
                    if len(values) != len(parameters): raise ValueError(f'Custom function {name!r} expects {len(parameters)} arguments, received {len(values)}')
                    return evaluate_source(definition.get('expression', ''), dict(zip(('$' + param for param in parameters), values)), depth + 1)
                if call.group(1).lower().replace('-', '') == 'lookuptable' and len(values) > 1 and isinstance(values[1], str):
                    if values[1] not in options.get('lookupTables', {}): raise ValueError(f'Lookup table {values[1]!r} was not found')
                    values[1] = options['lookupTables'][values[1]]
                return apply_function(call.group(1), values[0] if values else None, values[1:])
            source_path = _clean_path(text)
            if loop_contexts and source_path.startswith('vars.currentGroup'):
                return get_path(loop_contexts[-1][1], source_path[len('vars.currentGroup'):].lstrip('.'))
            if loop_contexts and (source_path == 'vars.current' or source_path.startswith('vars.current.')):
                return get_path(loop_contexts[-1][0], source_path[len('vars.current'):].lstrip('.'))
            relative = _relative_path(source_path, scope_source) if scope is not None else None
            return get_path(scope, relative) if relative is not None else get_path(document, source_path)
        return evaluate_source(rule.get('select') or rule.get('source', ''))

    def condition_passes(rule: dict, scope: Any = None, scope_source: str = '') -> bool:
        return evaluate_condition(rule.get('condition'), lambda text: resolve_value({'source': text}, scope, scope_source))

    def conditional_value(rule: dict, scope: Any = None, scope_source: str = ''):
        operator = str(rule.get('operator', '')).lower()
        if operator == 'choose':
            def branch_value(value: Any):
                return resolve_value({'source': value}, scope, scope_source)
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
            value = resolve_value({'source': rule.get('otherwise')}, scope, scope_source)
        return value, True

    def mapped_value(rule: dict, value: Any):
        try:
            value = transform_value(value, rule.get('functions', []), options.get('lookupTables', {}))
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
                tick()
                grouped.setdefault(str(get_path(item, group_by) if group_by else item), []).append(item)
            iterations = [(items[0] if items else {}, items) for items in grouped.values()]

        target = str(loop['target']).strip('.')
        occurrence_id = loop.get('occurrenceId')
        if id(loop) not in loop_plans:
            descendants = [rule for rule in rules if under(str(rule['target']).strip('.'), target) and rule.get('occurrenceId') == occurrence_id]
            descendant_ids = {id(rule) for rule in descendants}
            nested_loops = [candidate for candidate in loops if id(candidate) in descendant_ids and not any(
                other is not candidate and id(other) in descendant_ids and under(str(candidate['target']), str(other['target']))
                for other in loops
            )]
            nested_ids = {id(rule) for rule in nested_loops}
            nested_targets = [str(candidate['target']).strip('.') for candidate in nested_loops]
            direct = [rule for rule in descendants if id(rule) not in nested_ids and not any(under(str(rule['target']).strip('.'), nested) for nested in nested_targets)]
            loop_plans[id(loop)] = (descendants, nested_loops, direct)
        descendants, nested_loops, direct = loop_plans[id(loop)]
        output: list[Any] = []
        if options.get('inputMappingSemantics') and not descendants:
            if operator == 'for-each-group':
                return [{'key': str(get_path(current, group_by) if group_by else current), 'items': group} for current, group in iterations]
            return values
        for current, current_group in iterations:
            tick()
            loop_contexts.append((current, current_group or [current]))
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
            loop_contexts.pop()
        return output

    top_loops = [loop for loop in loops if not any(other is not loop and under(str(loop['target']), str(other['target'])) for other in loops)]
    loop_targets = [str(loop['target']).strip('.') for loop in top_loops]
    for rule in rules:
        target = str(rule['target']).strip('.')
        if id(rule) in loop_ids or any(under(target, loop_target) for loop_target in loop_targets): continue
        value, present = conditional_value(rule)
        if not present: continue
        value = mapped_value(rule, value)
        if value is not _OMIT: set_path(result, target, value)
    for loop in top_loops:
        target = str(loop['target'])
        generated = render_loop(loop)
        existing = get_path(result, target)
        set_path(result, target, ([*existing, *generated] if isinstance(existing, list) else generated))
    tick()
    if options.get('removeEmptyStructures'): result = _clean_empty(result)
    schema = options.get('targetSchema') or options.get('targetSchemaText')
    validation_errors = validate_output(result, schema, tick) if options.get('validateOutput', True) else []
    if validation_errors: raise ValueError('Target schema validation failed: ' + '; '.join(validation_errors))
    maximum_kb = int(options.get('maxOutputSizeKb') or 0)
    if maximum_kb and len(str(result).encode('utf-8')) > maximum_kb * 1024: raise ValueError(f'Mapped output exceeds {maximum_kb} KB limit')
    return result
