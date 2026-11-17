from __future__ import annotations

"""A safe, executable DataWeave-compatible integration subset.

This deliberately does not execute Python and does not claim to be Mule's
proprietary DataWeave engine.  It implements the expressions most useful in an
integration flow: selectors, objects/arrays, defaults, conditionals, common
functions, and collection transforms.
"""

import csv
import ast
import io
import json
import operator as comparison_ops
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from xml.etree import ElementTree as ET


class DataWeaveError(ValueError):
    pass


TOKEN = re.compile(
    r'''\s*(?:(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|'''
    r'''(?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<operator>->|\+\+|==|!=|>=|<=|&&|\|\||[{}\[\](),:.+*/%<>!-])|'''
    r'''(?P<identifier>[A-Za-z_$][A-Za-z0-9_$-]*(?:::[A-Za-z_$][A-Za-z0-9_$-]*)*))'''
)


@lru_cache(maxsize=128)
def _tokens(text: str) -> tuple[tuple[str, str], ...]:
    if len(text) > 65536: raise DataWeaveError('Transform expression exceeds the 64 KiB limit')
    result, position = [], 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if not match:
            if not text[position:].strip(): break
            if text[position:].strip().startswith('//'):
                position = text.find('\n', position)
                if position < 0: break
                continue
            raise DataWeaveError(f'Unexpected token near {text[position:position + 24]!r}')
        kind, value = next((key, value) for key, value in match.groupdict().items() if value is not None)
        result.append((kind, value)); position = match.end()
    result.append(('eof', ''))
    return tuple(result)


def _equal(left: Any, right: Any) -> bool:
    # Python treats True and 1 as equal, including inside containers.
    if isinstance(left, bool) != isinstance(right, bool): return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


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
        self.evaluating = True

    def selected(self, method, enabled):
        prior = self.evaluating
        self.evaluating = prior and enabled
        try: return method()
        finally: self.evaluating = prior

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
            selected = self.selected(self.expression, bool(condition)); self.take('else')
            alternative = self.selected(self.expression, not bool(condition))
            return selected if condition else alternative
        value = self.logical_or()
        while self.peek('default'):
            self.take(); fallback = self.selected(self.logical_or, value is None)
            value = fallback if value is None else value
        return value

    def logical_or(self):
        value = self.logical_and()
        while self.peek('or') or self.peek('||'):
            self.take(); right = self.selected(self.logical_and, not bool(value)); value = bool(value) or bool(right)
        return value

    def logical_and(self):
        value = self.compare()
        while self.peek('and') or self.peek('&&'):
            self.take(); right = self.selected(self.compare, bool(value)); value = bool(value) and bool(right)
        return value

    def compare(self):
        value = self.concat()
        while self.peek()[1] in ('==', '!=', '>', '<', '>=', '<=', 'is'):
            operator = self.take()[1]
            right = self.take()[1] if operator == 'is' and self.peek()[0] == 'identifier' else self.concat()
            if not self.evaluating: value = None
            elif operator == 'is':
                expected = str(right or '').lower()
                value = {'string': isinstance(value, str), 'number': isinstance(value, (int, float)) and not isinstance(value, bool), 'boolean': isinstance(value, bool), 'object': isinstance(value, dict), 'array': isinstance(value, list), 'null': value is None}.get(expected, False)
            elif operator in ('==', '!='):
                value = _equal(value, right) if operator == '==' else not _equal(value, right)
            else: value = {'>': comparison_ops.gt, '<': comparison_ops.lt,
                          '>=': comparison_ops.ge, '<=': comparison_ops.le}[operator](value, right)
        return value

    def concat(self):
        value = self.term()
        while self.peek()[1] in ('++', '+', '-'):
            operator = self.take()[1]; right = self.term()
            if not self.evaluating: value = None
            elif operator == '++':
                if isinstance(value, dict) and isinstance(right, dict): value = {**value, **right}
                elif isinstance(value, list) and isinstance(right, list): value = value + right
                else: value = f'{"" if value is None else value}{"" if right is None else right}'
            elif operator == '+': value = value + right
            else: value = value - right
        return value

    def term(self):
        value = self.unary()
        while self.peek()[1] in ('*', '/', '%', 'mod'):
            operator = self.take()[1]; right = self.unary()
            value = None if not self.evaluating else value * right if operator == '*' else value / right if operator == '/' else value % right
        return value

    def unary(self):
        if self.peek('not') or self.peek('!'): self.take(); return not bool(self.unary())
        if self.peek('-'):
            self.take(); value = self.unary(); return -value if self.evaluating else None
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
                if not self.evaluating: continue
                if target == 'string': value = '' if value is None else str(value).lower() if isinstance(value, bool) else str(value)
                elif target in ('number', 'decimal'): value = None if value in (None, '') else float(value)
                elif target in ('integer', 'int'): value = None if value in (None, '') else int(value)
                elif target in ('boolean', 'bool'): value = value if isinstance(value, bool) else str(value).lower() in ('true', '1', 'yes', 'on')
                elif target == 'array': value = value if isinstance(value, list) else ([] if value is None else [value])
                elif target == 'object':
                    if not isinstance(value, dict): raise DataWeaveError(f'Cannot coerce {type(value).__name__} to Object')
                else: raise DataWeaveError(f'Unsupported coercion type {target!r}')
            elif self.peek()[1] in ('map', 'flatMap', 'filter', 'filterObject', 'groupBy', 'orderBy', 'distinctBy', 'pluck', 'mapObject', 'minBy', 'maxBy'):
                operation = self.take()[1]; self.take('('); name = self.take()[1]
                index_name = ordinal_name = None
                if self.peek(','): self.take(); index_name = self.take()[1]
                if self.peek(','): self.take(); ordinal_name = self.take()[1]
                self.take(')'); self.take('->')
                object_input = isinstance(value, dict)
                if self.evaluating and value is not None:
                    expected = dict if operation in ('filterObject', 'mapObject', 'pluck') else list
                    if not isinstance(value, expected): raise DataWeaveError(f'{operation} requires {expected.__name__} or null')
                items = list(value.items()) if object_input and self.evaluating else list(value or []) if self.evaluating else []
                results = []
                start = self.index
                for index, item in enumerate(items):
                    self.index = start
                    item_value, item_key = (item[1], item[0]) if object_input else (item, index)
                    child = dict(self.environment); child[name] = item_value; child['$'] = item_value
                    child['$$'] = item_key; child['$$$'] = index
                    if index_name: child[index_name] = item_key
                    if ordinal_name: child[ordinal_name] = index
                    prior = self.environment; self.environment = child
                    try: transformed = self.expression()
                    finally: self.environment = prior
                    results.append((item_value, item_key, transformed))
                if not items:
                    self.selected(self.expression, False)
                if not self.evaluating or value is None:
                    value = None
                    continue
                if operation in ('map', 'pluck'): value = [result for _, _, result in results]
                elif operation == 'flatMap': value = [nested for _, _, result in results for nested in (result if isinstance(result, list) else [result])]
                elif operation == 'mapObject':
                    value = {}
                    for _, key, result in results:
                        if isinstance(result, dict): value.update(result)
                        else: raise DataWeaveError('mapObject mapper must return an object')
                elif operation == 'filter': value = [item for item, _, result in results if result]
                elif operation == 'filterObject': value = {key: item for item, key, result in results if result}
                elif operation in ('minBy', 'maxBy'):
                    value = (min if operation == 'minBy' else max)(results, key=lambda row: row[2])[0] if results else None
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
                if self.peek('('):
                    self.take(); key = self.expression(); self.take(')')
                else:
                    key_kind, key = self.take()
                    if key_kind == 'string': key = ast.literal_eval(key)
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
            return ast.literal_eval(value)
        if kind == 'number': self.take(); return float(value) if any(c in value.lower() for c in ('.', 'e')) else int(value)
        if kind == 'identifier':
            self.take()
            if value in ('true', 'false', 'null'): return {'true': True, 'false': False, 'null': None}[value]
            if self.peek('('):
                self.take(); args = []
                while not self.peek(')'):
                    args.append(self.expression())
                    if not self.peek(','): break
                    self.take(',')
                self.take(')'); return self.call(value, args) if self.evaluating else None
            if self.evaluating and value not in self.environment:
                raise DataWeaveError(f'Unknown transform identifier {value!r}')
            return self.environment.get(value)
        raise DataWeaveError(f'Expected expression, found {value!r}')

    def call(self, name: str, args: list[Any]):
        custom = (self.environment.get('__functions__') or {}).get(name)
        if custom:
            parameters, expression = custom[:2]
            if len(args) != len(parameters): raise DataWeaveError(f'Function {name} expects {len(parameters)} arguments, received {len(args)}')
            child = dict(custom[2] if len(custom) > 2 else self.environment); child.update(dict(zip(parameters, args)))
            return Parser(expression, child).parse()
        library = (self.environment.get('__library_functions__') or {}).get(name)
        if library: return library(*args)
        value = args[0] if args else None
        functions = {
            'upper': lambda: None if value is None else str(value).upper(), 'lower': lambda: None if value is None else str(value).lower(),
            'trim': lambda: None if value is None else str(value).strip(), 'sizeOf': lambda: len(value or []),
            'isEmpty': lambda: value in (None, '', [], {}), 'flatten': lambda: [nested for item in (value or []) for nested in (item if isinstance(item, list) else [item])],
            'keysOf': lambda: list((value or {}).keys()), 'valuesOf': lambda: list((value or {}).values()),
            'distinctBy': lambda: list(dict.fromkeys(value or [])), 'sum': lambda: sum(value or []),
            'min': lambda: min(value) if value else None, 'max': lambda: max(value) if value else None, 'avg': lambda: sum(value) / len(value) if value else None,
            'joinBy': lambda: str(args[1] if len(args) > 1 else '').join(map(str, value or [])),
            'splitBy': lambda: str(value or '').split(str(args[1] if len(args) > 1 else '')),
            'replace': lambda: str(value or '').replace(str(args[1]), str(args[2])),
            'contains': lambda: args[1] in (value or []), 'startsWith': lambda: str(value or '').startswith(str(args[1])),
            'endsWith': lambda: str(value or '').endswith(str(args[1])),
            'substring': lambda: str(value or '')[int(args[1]):int(args[2]) if len(args) > 2 else None],
            'capitalize': lambda: str(value or '').capitalize(),
            'abs': lambda: abs(value), 'floor': lambda: int(float(value) // 1), 'ceil': lambda: int(-(-float(value) // 1)),
            'mod': lambda: value % args[1], 'pow': lambda: value ** args[1],
            'zip': lambda: [list(pair) for pair in zip(value, args[1])],
            'unzip': lambda: [list(column) for column in zip(*(value or []))],
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


def _header_statements(header):
    current = ''; depth = 0
    lex = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//[^\n]*|[(){}\[\]]''')
    for raw in header.splitlines():
        line = raw.strip()
        if not line or line.startswith('//'): continue
        if current and depth == 0 and not current.rstrip().endswith('='):
            yield current
            current = ''
        current += ('\n' if current else '') + line
        for match in lex.finditer(line):
            token = match[0]
            if token in ('(', '{', '['): depth += 1
            elif token in (')', '}', ']'): depth -= 1
        if depth < 0: raise DataWeaveError('Unbalanced transform header')
    if depth: raise DataWeaveError('Unbalanced transform header')
    if current: yield current


def parse_script(script: str) -> tuple[dict[str, Any], str]:
    if '---' not in script: raise DataWeaveError('A DataWeave script requires the --- header/body separator')
    header, body = script.split('---', 1)
    metadata: dict[str, Any] = {'version': '2.0', 'outputMimeType': 'application/json', 'variables': [], 'functions': {}}
    for raw in _header_statements(header):
        line = raw.strip()
        if not line or line.startswith('//'): continue
        if line.startswith('%dw '):
            metadata['version'] = line[4:].strip()
            if metadata['version'] != '2.0': raise DataWeaveError('Only the %dw 2.0 language header is supported')
        elif line.startswith('module '):
            if not re.fullmatch(r'module\s+[\w$]+', line): raise DataWeaveError('Invalid module declaration')
        elif line.startswith('output '):
            parts = line[7:].split()
            if len(parts) != 1: raise DataWeaveError('Output writer properties are not supported by the embedded transform engine')
            metadata['outputMimeType'] = parts[0]
        elif line.startswith('input '):
            parts = line.split();
            if len(parts) >= 3: metadata.setdefault('inputs', {})[parts[1]] = parts[2]
        elif line.startswith('var '):
            match = re.match(r'var\s+([A-Za-z_$][\w$-]*)\s*=\s*(.+)', line, re.S)
            if not match: raise DataWeaveError(f'Invalid variable declaration: {line}')
            metadata['variables'].append((match.group(1), match.group(2)))
        elif line.startswith('fun '):
            match = re.match(r'fun\s+([A-Za-z_$][\w$-]*)\s*\(([^)]*)\)\s*=\s*(.+)', line, re.S)
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
                if key.startswith('@'): element.set(key[1:], '' if child is None else str(child).lower() if isinstance(child, bool) else str(child))
                elif key == '#text': element.text = '' if child is None else str(child)
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
    parts = (mime_type or '').split(';')
    charset = next((p.split('=', 1)[1].strip().strip('"') for p in parts[1:] if p.strip().lower().startswith('charset=')), 'utf-8')
    text = value.decode(charset) if isinstance(value, bytes) else value
    mime = parts[0].strip().lower()
    if mime == 'application/json': return json.loads(text)
    if mime in ('application/xml', 'text/xml'):
        def convert(element):
            children = list(element)
            result = {f'@{name}': item for name, item in element.attrib.items()}
            if not children:
                if not result: return element.text or ''
                if element.text: result['#text'] = element.text
                return result
            for child in children:
                item = convert(child)
                if child.tag in result: result[child.tag] = result[child.tag] if isinstance(result[child.tag], list) else [result[child.tag]]; result[child.tag].append(item)
                else: result[child.tag] = item
            return result
        if len(text.encode('utf-8')) > 8 * 1024 * 1024: raise DataWeaveError('XML input exceeds the 8 MiB limit')
        from lxml import etree
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
                                 huge_tree=False, remove_comments=True, remove_pis=True, encoding='UTF-8')
        try: root = etree.fromstring(text.encode('utf-8'), parser)
        except etree.XMLSyntaxError as exc: raise DataWeaveError(f'Invalid XML input: {exc}') from exc
        if root.getroottree().docinfo.doctype: raise DataWeaveError('XML DTDs are disabled in transforms')
        return {root.tag: convert(root)}
    if mime in ('text/csv', 'application/csv'): return list(csv.DictReader(io.StringIO(text)))
    return text


def _execute_details(script: str, *, payload: Any = None, attributes: Any = None, variables: dict[str, Any] | None = None, input_mime_type: str = '', libraries=None) -> dict[str, Any]:
    metadata, body = parse_script(script)
    payload = _decode_payload(payload, input_mime_type or (metadata.get('inputs') or {}).get('payload', ''))
    environment = {'payload': payload, 'attributes': attributes or {}, 'vars': variables or {}, '__functions__': {}}
    from .transform_libraries import install_imports
    install_imports(metadata, environment, libraries or {}, parse_script, Parser, DataWeaveError)
    environment['__functions__'].update(metadata.get('functions', {}))
    environment.update(variables or {})
    for name, expression in metadata['variables']:
        environment[name] = Parser(expression, environment).parse()
    result = Parser(body, environment).parse()
    mime = metadata['outputMimeType'].lower()
    if mime not in ('application/json', 'application/java', 'application/xml', 'text/xml', 'text/plain', 'text/csv', 'application/csv'):
        raise DataWeaveError(f'Unsupported transform output MIME type {mime!r}')
    if mime in ('application/xml', 'text/xml'): result = _xml(result)
    elif mime in ('application/csv', 'text/csv'): result = _csv(result)
    elif mime.startswith('text/'): result = '' if result is None else str(result)
    return {'output': result, 'mimeType': metadata['outputMimeType'], 'version': metadata['version']}


def execute_details(script: str, **kwargs) -> dict[str, Any]:
    try:
        return _execute_details(script, **kwargs)
    except DataWeaveError:
        raise
    except (ArithmeticError, TypeError, ValueError, LookupError, RecursionError, SyntaxError, ET.ParseError) as exc:
        raise DataWeaveError(f'Transform evaluation failed: {exc}') from exc


def execute(script: str, *, payload: Any = None, attributes: Any = None, variables: dict[str, Any] | None = None, input_mime_type: str = '', libraries=None) -> Any:
    return execute_details(script, payload=payload, attributes=attributes, variables=variables, input_mime_type=input_mime_type, libraries=libraries)['output']
