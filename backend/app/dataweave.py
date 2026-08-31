from __future__ import annotations

"""A safe, executable DataWeave-compatible integration subset.

This deliberately does not execute Python and does not claim to be Mule's
proprietary DataWeave engine.  It implements the expressions most useful in an
integration flow: selectors, objects/arrays, defaults, conditionals, common
functions, and collection transforms.
"""

import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET


class DataWeaveError(ValueError):
    pass


TOKEN = re.compile(
    r'''\s*(?:(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|'''
    r'''(?P<number>-?\d+(?:\.\d+)?)|(?P<operator>->|\+\+|==|!=|>=|<=|&&|\|\||[{}\[\](),:.+*/%<>!-])|'''
    r'''(?P<identifier>[A-Za-z_$][A-Za-z0-9_$-]*))'''
)


def _tokens(text: str) -> list[tuple[str, str]]:
    result, position = [], 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if not match:
            if text[position:].strip().startswith('//'):
                position = text.find('\n', position)
                if position < 0: break
                continue
            raise DataWeaveError(f'Unexpected token near {text[position:position + 24]!r}')
        kind, value = next((key, value) for key, value in match.groupdict().items() if value is not None)
        result.append((kind, value)); position = match.end()
    result.append(('eof', ''))
    return result


def _select(value: Any, key: Any) -> Any:
    if value is None: return None
    if key == '*' and isinstance(value, dict): return list(value.values())
    if key == '*' and isinstance(value, (list, tuple)): return list(value)
    if isinstance(value, dict): return value.get(str(key))
    if isinstance(value, (list, tuple)):
        if isinstance(key, int): return value[key] if -len(value) <= key < len(value) else None
        return [_select(item, key) for item in value]
    return getattr(value, str(key), None)


class Parser:
    def __init__(self, text: str, environment: dict[str, Any]):
        self.tokens, self.index, self.environment = _tokens(text), 0, environment

    def peek(self, value: str | None = None):
        token = self.tokens[self.index]
        return token[1] == value if value is not None else token

    def take(self, value: str | None = None):
        token = self.peek()
        if value is not None and token[1] != value: raise DataWeaveError(f'Expected {value!r}, found {token[1]!r}')
        self.index += 1
        return token

    def parse(self):
        value = self.expression()
        if self.peek()[0] != 'eof': raise DataWeaveError(f'Unexpected token {self.peek()[1]!r}')
        return value

    def expression(self):
        if self.peek('if'):
            self.take('if'); self.take('('); condition = self.expression(); self.take(')')
            selected = self.expression(); self.take('else'); alternative = self.expression()
            return selected if condition else alternative
        value = self.logical_or()
        while self.peek('default'):
            self.take(); fallback = self.logical_or()
            value = fallback if value is None else value
        return value

    def logical_or(self):
        value = self.logical_and()
        while self.peek('or') or self.peek('||'):
            self.take(); right = self.logical_and(); value = bool(value) or bool(right)
        return value

    def logical_and(self):
        value = self.compare()
        while self.peek('and') or self.peek('&&'):
            self.take(); right = self.compare(); value = bool(value) and bool(right)
        return value

    def compare(self):
        value = self.concat()
        while self.peek()[1] in ('==', '!=', '>', '<', '>=', '<=', 'is'):
            operator = self.take()[1]
            right = self.take()[1] if operator == 'is' and self.peek()[0] == 'identifier' else self.concat()
            if operator == 'is':
                expected = str(right or '').lower()
                value = {'string': isinstance(value, str), 'number': isinstance(value, (int, float)) and not isinstance(value, bool), 'boolean': isinstance(value, bool), 'object': isinstance(value, dict), 'array': isinstance(value, list), 'null': value is None}.get(expected, False)
            else: value = {'==': value == right, '!=': value != right, '>': value > right, '<': value < right, '>=': value >= right, '<=': value <= right}[operator]
        return value

    def concat(self):
        value = self.term()
        while self.peek()[1] in ('++', '+', '-'):
            operator = self.take()[1]; right = self.term()
            if operator == '++':
                if isinstance(value, dict) and isinstance(right, dict): value = {**value, **right}
                elif isinstance(value, list) and isinstance(right, list): value = value + right
                else: value = f'{"" if value is None else value}{"" if right is None else right}'
            elif operator == '+': value = value + right
            else: value = value - right
        return value

    def term(self):
        value = self.unary()
        while self.peek()[1] in ('*', '/', '%'):
            operator = self.take()[1]; right = self.unary()
            value = value * right if operator == '*' else value / right if operator == '/' else value % right
        return value

    def unary(self):
        if self.peek('not') or self.peek('!'): self.take(); return not bool(self.unary())
        if self.peek('-'): self.take(); return -self.unary()
        return self.postfix()

    def postfix(self):
        value = self.primary()
        while True:
            if self.peek('.'):
                self.take(); value = _select(value, self.take()[1])
            elif self.peek('['):
                self.take(); key = self.expression(); self.take(']'); value = _select(value, key)
            elif self.peek('as'):
                self.take(); target = self.take()[1].lower()
                if target == 'string': value = '' if value is None else str(value)
                elif target in ('number', 'decimal'): value = None if value in (None, '') else float(value)
                elif target in ('integer', 'int'): value = None if value in (None, '') else int(value)
                elif target in ('boolean', 'bool'): value = value if isinstance(value, bool) else str(value).lower() in ('true', '1', 'yes', 'on')
                elif target == 'array': value = value if isinstance(value, list) else ([] if value is None else [value])
                elif target == 'object' and not isinstance(value, dict): raise DataWeaveError(f'Cannot coerce {type(value).__name__} to Object')
            elif self.peek()[1] in ('map', 'flatMap', 'filter', 'groupBy', 'orderBy', 'distinctBy', 'pluck', 'mapObject'):
                operation = self.take()[1]; self.take('('); name = self.take()[1]
                index_name = None
                if self.peek(','): self.take(); index_name = self.take()[1]
                self.take(')'); self.take('->')
                object_input = isinstance(value, dict)
                items = list((value or {}).items()) if object_input else list(value or [])
                results = []
                start = self.index
                for index, item in enumerate(items):
                    self.index = start
                    item_value, item_key = (item[1], item[0]) if object_input else (item, index)
                    child = dict(self.environment); child[name] = item_value; child['$'] = item_value
                    if index_name: child[index_name] = item_key
                    prior = self.environment; self.environment = child
                    try: transformed = self.expression()
                    finally: self.environment = prior
                    results.append((item_value, item_key, transformed))
                if not items:
                    self.expression()
                if operation in ('map', 'pluck'): value = [result for _, _, result in results]
                elif operation == 'flatMap': value = [nested for _, _, result in results for nested in (result if isinstance(result, list) else [result])]
                elif operation == 'mapObject':
                    value = {}
                    for _, key, result in results:
                        if isinstance(result, dict): value.update(result)
                        else: value[str(key)] = result
                elif operation == 'filter': value = [item for item, _, result in results if result]
                elif operation == 'orderBy': value = [item for item, _, _ in sorted(results, key=lambda row: (row[2] is None, row[2]))]
                elif operation == 'distinctBy':
                    seen = set(); unique = []
                    for item, _, result in results:
                        marker = json.dumps(result, sort_keys=True, default=str)
                        if marker not in seen: seen.add(marker); unique.append(item)
                    value = unique
                else:
                    grouped: dict[str, list[Any]] = {}
                    for item, _, result in results: grouped.setdefault(str(result), []).append(item)
                    value = grouped
            else: break
        return value

    def primary(self):
        kind, value = self.peek()
        if value == '(':
            self.take(); result = self.expression(); self.take(')'); return result
        if value == '{':
            self.take(); result = {}
            while not self.peek('}'):
                key_kind, key = self.take()
                if key_kind == 'string': key = json.loads(key) if key.startswith('"') else bytes(key[1:-1], 'utf-8').decode('unicode_escape')
                self.take(':'); result[str(key)] = self.expression()
                if not self.peek(','): break
                self.take(',')
            self.take('}'); return result
        if value == '[':
            self.take(); result = []
            while not self.peek(']'):
                result.append(self.expression())
                if not self.peek(','): break
                self.take(',')
            self.take(']'); return result
        if kind == 'string':
            self.take()
            return json.loads(value) if value.startswith('"') else bytes(value[1:-1], 'utf-8').decode('unicode_escape')
        if kind == 'number': self.take(); return float(value) if '.' in value else int(value)
        if kind == 'identifier':
            self.take()
            if value in ('true', 'false', 'null'): return {'true': True, 'false': False, 'null': None}[value]
            if self.peek('('):
                self.take(); args = []
                while not self.peek(')'):
                    args.append(self.expression())
                    if not self.peek(','): break
                    self.take(',')
                self.take(')'); return self.call(value, args)
            return self.environment.get(value)
        raise DataWeaveError(f'Expected expression, found {value!r}')

    def call(self, name: str, args: list[Any]):
        custom = (self.environment.get('__functions__') or {}).get(name)
        if custom:
            parameters, expression = custom
            if len(args) != len(parameters): raise DataWeaveError(f'Function {name} expects {len(parameters)} arguments, received {len(args)}')
            child = dict(self.environment); child.update(dict(zip(parameters, args)))
            return Parser(expression, child).parse()
        value = args[0] if args else None
        functions = {
            'upper': lambda: str(value or '').upper(), 'lower': lambda: str(value or '').lower(),
            'trim': lambda: str(value or '').strip(), 'sizeOf': lambda: len(value or []),
            'isEmpty': lambda: value in (None, '', [], {}), 'flatten': lambda: [nested for item in (value or []) for nested in (item if isinstance(item, list) else [item])],
            'keysOf': lambda: list((value or {}).keys()), 'valuesOf': lambda: list((value or {}).values()),
            'distinctBy': lambda: list(dict.fromkeys(value or [])), 'sum': lambda: sum(value or []),
            'min': lambda: min(value or []), 'max': lambda: max(value or []), 'avg': lambda: sum(value or []) / len(value or []) if value else None,
            'joinBy': lambda: str(args[1] if len(args) > 1 else '').join(map(str, value or [])),
            'splitBy': lambda: str(value or '').split(str(args[1] if len(args) > 1 else '')),
            'replace': lambda: str(value or '').replace(str(args[1]), str(args[2])),
            'contains': lambda: args[1] in (value or []), 'startsWith': lambda: str(value or '').startswith(str(args[1])),
            'endsWith': lambda: str(value or '').endswith(str(args[1])),
            'substring': lambda: str(value or '')[int(args[1]):int(args[2]) if len(args) > 2 else None],
            'capitalize': lambda: str(value or '').capitalize(),
            'abs': lambda: abs(value), 'floor': lambda: int(float(value) // 1), 'ceil': lambda: int(-(-float(value) // 1)),
            'uuid': lambda: str(uuid.uuid4()), 'now': lambda: datetime.now(timezone.utc).isoformat(),
            'typeOf': lambda: 'Null' if value is None else 'Object' if isinstance(value, dict) else 'Array' if isinstance(value, list) else 'Boolean' if isinstance(value, bool) else 'Number' if isinstance(value, (int, float)) else 'String',
            'read': lambda: _decode_payload(value, str(args[1] if len(args) > 1 else 'application/json')),
            'write': lambda: _xml(value) if len(args) > 1 and str(args[1]).lower() in ('application/xml', 'text/xml') else _csv(value) if len(args) > 1 and str(args[1]).lower() in ('text/csv', 'application/csv') else json.dumps(value, separators=(',', ':')),
        }
        if name in ('asString', 'string'): return '' if value is None else str(value)
        if name in ('asNumber', 'number'): return float(value) if value not in (None, '') else None
        if name in ('asBoolean', 'boolean'): return value if isinstance(value, bool) else str(value).lower() in ('true', '1', 'yes')
        if name not in functions: raise DataWeaveError(f'Unsupported DataWeave function {name!r}')
        return functions[name]()


def parse_script(script: str) -> tuple[dict[str, Any], str]:
    if '---' not in script: raise DataWeaveError('A DataWeave script requires the --- header/body separator')
    header, body = script.split('---', 1)
    metadata: dict[str, Any] = {'version': '2.0', 'outputMimeType': 'application/json', 'variables': [], 'functions': {}}
    for raw in header.splitlines():
        line = raw.strip()
        if not line or line.startswith('//'): continue
        if line.startswith('%dw '): metadata['version'] = line[4:].strip()
        elif line.startswith('output '): metadata['outputMimeType'] = line[7:].split()[0]
        elif line.startswith('input '):
            parts = line.split();
            if len(parts) >= 3: metadata.setdefault('inputs', {})[parts[1]] = parts[2]
        elif line.startswith('var '):
            match = re.match(r'var\s+([A-Za-z_$][\w$-]*)\s*=\s*(.+)', line)
            if not match: raise DataWeaveError(f'Invalid variable declaration: {line}')
            metadata['variables'].append((match.group(1), match.group(2)))
        elif line.startswith('fun '):
            match = re.match(r'fun\s+([A-Za-z_$][\w$-]*)\s*\(([^)]*)\)\s*=\s*(.+)', line)
            if not match: raise DataWeaveError(f'Invalid function declaration: {line}')
            parameters = [value.strip().split(':', 1)[0].strip() for value in match.group(2).split(',') if value.strip()]
            metadata['functions'][match.group(1)] = (parameters, match.group(3).strip())
        elif line.startswith('import '):
            metadata.setdefault('imports', []).append(line[7:].strip())
        elif line.startswith(('ns ', 'type ')):
            raise DataWeaveError(f'{line.split()[0]} declarations require the Mule DataWeave runtime and are not supported by the embedded engine')
        else: raise DataWeaveError(f'Unsupported header directive: {line}')
    return metadata, body.strip()


def _xml(value: Any) -> str:
    if not isinstance(value, dict) or len(value) != 1: raise DataWeaveError('XML output requires one root object, for example { order: { id: payload.id } }')
    def build(name: str, item: Any):
        element = ET.Element(name)
        if isinstance(item, dict):
            for key, child in item.items():
                if key.startswith('@'): element.set(key[1:], '' if child is None else str(child))
                elif isinstance(child, list):
                    for entry in child: element.append(build(key, entry))
                else: element.append(build(key, child))
        elif item is not None: element.text = str(item).lower() if isinstance(item, bool) else str(item)
        return element
    name, item = next(iter(value.items()))
    return ET.tostring(build(name, item), encoding='unicode')


def _csv(value: Any) -> str:
    rows = value if isinstance(value, list) else [value]
    if not rows: return ''
    if not all(isinstance(row, dict) for row in rows):
        raise DataWeaveError('CSV output requires an object or an array of objects')
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields: fields.append(str(key))
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()


def _decode_payload(value: Any, mime_type: str) -> Any:
    if not isinstance(value, (str, bytes)): return value
    text = value.decode() if isinstance(value, bytes) else value
    mime = (mime_type or '').lower()
    if mime == 'application/json': return json.loads(text)
    if mime in ('application/xml', 'text/xml'):
        def convert(element):
            children = list(element)
            if not children: return element.text or ''
            result = {f'@{name}': item for name, item in element.attrib.items()}
            for child in children:
                item = convert(child)
                if child.tag in result: result[child.tag] = result[child.tag] if isinstance(result[child.tag], list) else [result[child.tag]]; result[child.tag].append(item)
                else: result[child.tag] = item
            return result
        root = ET.fromstring(text)
        return {root.tag: convert(root)}
    if mime in ('text/csv', 'application/csv'): return list(csv.DictReader(io.StringIO(text)))
    return text


def execute_details(script: str, *, payload: Any = None, attributes: Any = None, variables: dict[str, Any] | None = None, input_mime_type: str = '') -> dict[str, Any]:
    metadata, body = parse_script(script)
    payload = _decode_payload(payload, input_mime_type or (metadata.get('inputs') or {}).get('payload', ''))
    environment = {'payload': payload, 'attributes': attributes or {}, 'vars': variables or {}, '__functions__': metadata.get('functions', {})}
    environment.update(variables or {})
    for name, expression in metadata['variables']:
        environment[name] = Parser(expression, environment).parse()
    result = Parser(body, environment).parse()
    mime = metadata['outputMimeType'].lower()
    if mime in ('application/xml', 'text/xml'): result = _xml(result)
    elif mime in ('application/csv', 'text/csv'): result = _csv(result)
    elif mime.startswith('text/'): result = '' if result is None else str(result)
    return {'output': result, 'mimeType': metadata['outputMimeType'], 'version': metadata['version']}


def execute(script: str, *, payload: Any = None, attributes: Any = None, variables: dict[str, Any] | None = None, input_mime_type: str = '') -> Any:
    return execute_details(script, payload=payload, attributes=attributes, variables=variables, input_mime_type=input_mime_type)['output']
