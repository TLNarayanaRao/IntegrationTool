"""Bounded JSON document operations and indexed record transformations."""
import json
import math
import re
from decimal import Decimal, localcontext
from urllib.parse import unquote

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 100000
MISSING = object()


class MissingPointer(ValueError):
    pass


class Budget:
    def __init__(self): self.nodes = self.bytes = 0

    def check(self, value):
        active = set()
        def walk(item, depth=0):
            self.nodes += 1
            if depth > 128 or self.nodes > 4000000: raise ValueError('JSON transformation complexity limit exceeded')
            if isinstance(item, str):
                if len(item) > MAX_BYTES: raise ValueError('JSON string exceeds 8 MiB')
                return
            if item is None or isinstance(item, (bool, int)): return
            if isinstance(item, float):
                if not math.isfinite(item): raise ValueError('JSON requires finite numbers')
                return
            if not isinstance(item, (dict, list)): raise ValueError('A JSON value is required')
            if id(item) in active: raise ValueError('Cyclic values are not JSON documents')
            active.add(id(item))
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str): raise ValueError('JSON object keys must be strings')
                    if len(key) > MAX_BYTES: raise ValueError('JSON object key exceeds 8 MiB')
                    walk(child, depth + 1)
            else:
                for child in item: walk(child, depth + 1)
            active.remove(id(item))
        walk(value)
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode())
        self.bytes += size
        if size > MAX_BYTES: raise ValueError('JSON transformation document exceeds 8 MiB')
        if self.bytes > 128 * 1024 * 1024: raise ValueError('JSON transformation work budget exceeded')
        return size


def clone(value):
    # Break shared Python aliases as well as avoiding mutation of caller-owned values.
    if isinstance(value, dict): return {key: clone(child) for key, child in value.items()}
    if isinstance(value, list): return [clone(child) for child in value]
    return value


def equal(left, right):
    if isinstance(left, bool) != isinstance(right, bool): return False
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)):
        # Compare JSON numeric values, not a float's hidden binary expansion.
        # Record keys and portable XSLT use the same lexical decimal semantics.
        return Decimal(str(left)) == Decimal(str(right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return left == right


def pointer_parts(pointer):
    if not isinstance(pointer, str): raise ValueError('JSON Pointer must be a string')
    if len(pointer) > 8192: raise ValueError('JSON Pointer exceeds 8192 characters')
    if pointer.startswith('#'):
        if re.search(r'%(?![0-9a-fA-F]{2})', pointer): raise ValueError('Invalid JSON Pointer fragment encoding')
        pointer = unquote(pointer[1:], encoding='utf-8', errors='strict')
    if pointer == '': return []
    if not pointer.startswith('/'): raise ValueError('JSON Pointer must be empty or start with /')
    if len(pointer) > 8192: raise ValueError('JSON Pointer exceeds 8192 characters')
    result = []
    for token in pointer[1:].split('/'):
        if re.search(r'~(?![01])', token): raise ValueError('Invalid JSON Pointer escape')
        result.append(token.replace('~1', '/').replace('~0', '~'))
    if len(result) > 128: raise ValueError('JSON Pointer depth exceeds 128')
    return result


def array_index(token, length, adding=False):
    if token == '-' and adding: return length
    if token == '-': raise MissingPointer('JSON append position has no readable value')
    if not re.fullmatch(r'0|[1-9][0-9]*', token): raise ValueError('JSON array index must be a nonnegative integer without leading zeros')
    if len(token) > 10: raise MissingPointer('JSON array index is outside the document')
    index = int(token)
    if index > length or index == length and not adding: raise MissingPointer('JSON array index is outside the document')
    return index


def select(document, parts):
    if document is MISSING: raise MissingPointer('JSON document root does not exist')
    current = document
    for part in parts:
        if isinstance(current, dict):
            if part not in current: raise MissingPointer('JSON Pointer member does not exist')
            current = current[part]
        elif isinstance(current, list): current = current[array_index(part, len(current))]
        else: raise MissingPointer('JSON Pointer cannot traverse a scalar')
    return current


def json_pointer(document, pointer, default=MISSING):
    Budget().check(document)
    parts = pointer_parts(pointer)
    try: return clone(select(document, parts))
    except MissingPointer:
        if default is MISSING: raise
        Budget().check(default)
        return clone(default)


def change(document, parts, operation, value=MISSING):
    if not parts:
        if operation != 'add' and document is MISSING: raise MissingPointer('JSON document root does not exist')
        if operation == 'remove': return MISSING
        return clone(value)
    parent = select(document, parts[:-1]); key = parts[-1]
    if isinstance(parent, list):
        index = array_index(key, len(parent), operation == 'add')
        if operation == 'add': parent.insert(index, clone(value))
        elif operation == 'replace': parent[index] = clone(value)
        else: parent.pop(index)
    elif isinstance(parent, dict):
        if operation != 'add' and key not in parent: raise MissingPointer('JSON Patch member does not exist')
        if operation == 'remove': del parent[key]
        else: parent[key] = clone(value)
    else: raise MissingPointer('JSON Patch target parent is not a container')
    return document


def json_patch(document, operations):
    budget = Budget(); budget.check(document); budget.check(operations)
    if not isinstance(operations, list) or len(operations) > 10000: raise ValueError('JSON Patch requires at most 10000 operations')
    result = clone(document)
    for index, item in enumerate(operations):
        try:
            if not isinstance(item, dict) or item.get('op') not in ('add', 'remove', 'replace', 'move', 'copy', 'test'):
                raise ValueError('Unknown JSON Patch operation')
            operation = item['op']
            if 'path' not in item: raise ValueError('JSON Patch path is required')
            # JSON Patch uses pointer strings, not URI fragments.
            if not isinstance(item['path'], str) or item['path'].startswith('#'): raise ValueError('JSON Patch path must be a pointer string')
            path = pointer_parts(item['path'])
            if operation in ('add', 'replace', 'test') and 'value' not in item: raise ValueError('JSON Patch value is required')
            if operation == 'test':
                if not equal(select(result, path), item['value']): raise ValueError('JSON Patch test failed')
            elif operation in ('copy', 'move'):
                if not isinstance(item.get('from'), str) or item['from'].startswith('#'): raise ValueError('JSON Patch from pointer is required')
                origin = pointer_parts(item['from']); value = clone(select(result, origin))
                if operation == 'move':
                    if origin == path: continue
                    if path[:len(origin)] == origin: raise ValueError('Cannot move a value into its descendant')
                    result = change(result, origin, 'remove')
                result = change(result, path, 'add', value)
            else: result = change(result, path, operation, item.get('value', MISSING))
            if result is not MISSING: budget.check(result)
        except (ValueError, KeyError) as error:
            raise ValueError(f'JSON Patch operation {index}: {error}') from error
    return None if result is MISSING else result


def json_merge_patch(document, patch):
    budget = Budget(); budget.check(document); budget.check(patch)
    def merge(target, changes):
        if not isinstance(changes, dict): return clone(changes)
        target = target if isinstance(target, dict) else {}
        for key, value in changes.items():
            if value is None: target.pop(key, None)
            else: target[key] = merge(target.get(key), value)
        return target
    result = merge(clone(document), patch); budget.check(result)
    return result


def json_diff(before, after):
    budget = Budget(); budget.check(before); budget.check(after)
    operations = []
    generated_bytes = 2
    def add(operation):
        nonlocal generated_bytes
        if len(operations) >= 10000: raise ValueError('Generated JSON Patch exceeds 10000 operations')
        generated_bytes += len(json.dumps(operation, ensure_ascii=False, allow_nan=False).encode()) + 1
        if generated_bytes > MAX_BYTES: raise ValueError('Generated JSON Patch exceeds 8 MiB')
        operations.append(operation)
    def walk(left, right, path):
        if equal(left, right): return
        if isinstance(left, dict) and isinstance(right, dict):
            escape = lambda key: key.replace('~', '~0').replace('/', '~1')
            for key in sorted(left.keys() - right.keys()): add({'op': 'remove', 'path': path + '/' + escape(key)})
            for key in sorted(right.keys() - left.keys()): add({'op': 'add', 'path': path + '/' + escape(key), 'value': clone(right[key])})
            for key in sorted(left.keys() & right.keys()): walk(left[key], right[key], path + '/' + escape(key))
        else: add({'op': 'replace', 'path': path, 'value': clone(right)})
    walk(before, after, '')
    budget.check(operations)
    return operations


def key_paths(paths):
    if isinstance(paths, str): paths = [paths]
    if not isinstance(paths, list) or not 1 <= len(paths) <= 16: raise ValueError('Supply one to sixteen JSON Pointer key paths')
    return [pointer_parts(path) for path in paths]


def record_key(row, paths):
    values = []
    for path in paths:
        try: value = select(row, path)
        except MissingPointer: return None
        if value is None: return None
        if isinstance(value, bool): values.append(('boolean', value))
        elif isinstance(value, (int, float)): values.append(('number', Decimal(str(value))))
        elif isinstance(value, str): values.append(('string', value))
        else: raise ValueError('Record join/deduplication keys must be JSON scalars')
    return tuple(values)


def join_records(left, right, left_keys, right_keys, mode='inner'):
    budget = Budget(); budget.check(left); budget.check(right)
    if not isinstance(left, list) or not isinstance(right, list) or max(len(left), len(right)) > MAX_ROWS:
        raise ValueError('joinRecords requires arrays with at most 100000 records each')
    if mode not in ('inner', 'left', 'right', 'full', 'semi', 'anti'): raise ValueError('Unknown record join mode')
    lpaths, rpaths = key_paths(left_keys), key_paths(right_keys)
    if len(lpaths) != len(rpaths): raise ValueError('Join key counts must match')
    index = {}
    for position, row in enumerate(right):
        key = record_key(row, rpaths)
        if key is not None: index.setdefault(key, []).append(position)
    result = []; matched = set(); output_bytes = 2
    def emit(value):
        nonlocal output_bytes
        if len(result) >= MAX_ROWS: raise ValueError('Record join exceeds 100000 result rows')
        output_bytes += budget.check(value) + 1
        if output_bytes > MAX_BYTES: raise ValueError('Record join output exceeds 8 MiB')
        result.append(clone(value))
    for row in left:
        key = record_key(row, lpaths); matches = index.get(key, []) if key is not None else []
        if mode in ('semi', 'anti'):
            if bool(matches) == (mode == 'semi'): emit(row)
            continue
        for position in matches:
            matched.add(position); emit({'left': row, 'right': right[position]})
        if not matches and mode in ('left', 'full'): emit({'left': row, 'right': None})
    if mode in ('right', 'full'):
        for position, row in enumerate(right):
            if position not in matched: emit({'left': None, 'right': row})
    budget.check(result)
    return result


def deduplicate_records(records, keys, keep='first'):
    budget = Budget(); budget.check(records)
    if not isinstance(records, list) or len(records) > MAX_ROWS: raise ValueError('deduplicateRecords requires an array of at most 100000 records')
    if keep not in ('first', 'last'): raise ValueError('Deduplication keep must be first or last')
    paths = key_paths(keys); chosen = {}; unkeyed = []
    for position, row in enumerate(records):
        key = record_key(row, paths)
        if key is None: unkeyed.append(position)
        elif keep == 'last' or key not in chosen: chosen[key] = position
    result = [clone(records[index]) for index in sorted([*chosen.values(), *unkeyed])]
    budget.check(result)
    return result


def redact_keys(document, names, replacement='[REDACTED]'):
    budget = Budget(); output_bytes = budget.check(document); replacement_bytes = budget.check(replacement)
    budget.check(names)
    if not isinstance(names, list) or not 1 <= len(names) <= 1024 or any(not isinstance(name, str) for name in names):
        raise ValueError('redactKeys requires one to 1024 explicit field names')
    names = {name.casefold() for name in names}
    def walk(value):
        nonlocal output_bytes
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                if key.casefold() in names:
                    output_bytes += replacement_bytes - budget.check(child)
                    if output_bytes > MAX_BYTES: raise ValueError('Redacted output exceeds 8 MiB')
                    result[key] = clone(replacement)
                else: result[key] = walk(child)
            return result
        if isinstance(value, list): return [walk(child) for child in value]
        return value
    result = walk(document); budget.check(result)
    return result


def mask_text(value, suffix=4, marker='*'):
    if value is None: return None
    if not isinstance(value, str) or len(value) > 65536: raise ValueError('maskText requires text of at most 65536 characters')
    if isinstance(suffix, bool) or not isinstance(suffix, int) or suffix < 0: raise ValueError('Visible suffix must be a nonnegative integer')
    if not isinstance(marker, str) or len(marker) != 1: raise ValueError('Mask marker must be one character')
    visible = min(suffix, len(value))
    return marker * (len(value) - visible) + (value[-visible:] if visible else '')


def _record_rows(records):
    if not isinstance(records, list) or len(records) > MAX_ROWS or any(not isinstance(row, dict) for row in records):
        raise ValueError('Expected an array of at most 100000 record objects')
    return records


def _required_key(row, paths):
    key = record_key(row, paths)
    if key is None: raise ValueError('Record keys must exist and be non-null scalars')
    return key


def reconcile_records(before, after, keys):
    """Classify snapshots without implying durable CDC state or applying writes."""
    budget = Budget(); budget.check(before); budget.check(after)
    paths = key_paths(keys)
    def index(records):
        result = {}
        for row in _record_rows(records):
            key = _required_key(row, paths)
            if key in result: raise ValueError('Duplicate record key in snapshot')
            result[key] = row
        return result
    old, new = index(before), index(after)
    result = {'inserted': [], 'updated': [], 'deleted': [], 'unchanged': []}
    output_bytes = 64
    def emit(kind, value):
        nonlocal output_bytes
        output_bytes += budget.check(value) + 1
        if output_bytes > MAX_BYTES: raise ValueError('Reconciliation output exceeds 8 MiB')
        result[kind].append(value)
    for key, row in new.items():
        if key not in old: emit('inserted', row)
        elif equal(old[key], row): emit('unchanged', row)
        else: emit('updated', {'key': [select(row, path) for path in paths], 'before': old[key], 'after': row})
    for key, row in old.items():
        if key not in new: emit('deleted', row)
    budget.check(result)
    return clone(result)


def aggregate_records(records, keys, metrics):
    """Stable composite-key rollups; numeric metrics ignore missing/null values."""
    budget = Budget(); budget.check(records); budget.check(metrics)
    paths = key_paths(keys)
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 16:
        raise ValueError('Supply one to sixteen aggregate metrics')
    specs = []; names = set()
    for metric in metrics:
        if not isinstance(metric, dict) or metric.keys() - {'name', 'op', 'path'}:
            raise ValueError('Metric requires name, op and optional path')
        name, op = metric.get('name'), metric.get('op')
        if not isinstance(name, str) or not 1 <= len(name) <= 128 or name in names:
            raise ValueError('Metric names must be unique, nonempty and at most 128 characters')
        if op not in ('count', 'sum', 'average', 'min', 'max'): raise ValueError('Unknown aggregate operation')
        if op != 'count' and 'path' not in metric: raise ValueError('Numeric metric requires a JSON Pointer path')
        specs.append((name, op, pointer_parts(metric['path']) if 'path' in metric else None)); names.add(name)
    groups = {}
    for row in _record_rows(records): groups.setdefault(_required_key(row, paths), []).append(row)
    result = []; output_bytes = 2
    for rows in groups.values():
        values = {}
        for name, op, path in specs:
            selected = []
            if path is not None:
                for row in rows:
                    try: value = select(row, path)
                    except MissingPointer: continue
                    if value is not None: selected.append(value)
            if op == 'count': values[name] = len(rows) if path is None else len(selected); continue
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in selected):
                raise ValueError('Numeric aggregate requires numbers; convert text explicitly')
            if not selected: values[name] = 0 if op == 'sum' else None; continue
            # Enough precision for finite IEEE values and bounded integer inputs;
            # return ordinary JSON numbers, not a monetary/decimal string type.
            with localcontext() as ctx:
                ctx.prec = 2048
                numbers = [Decimal(str(value)) for value in selected]
                if op in ('sum', 'average') and any(len(number.as_tuple().digits) > 1000 for number in numbers):
                    raise ValueError('Aggregate integer exceeds 1000 digits')
                number = (min if op == 'min' else max)(numbers) if op in ('min', 'max') else sum(numbers, Decimal(0))
                if op == 'average': number /= len(numbers)
                value = int(number) if number == number.to_integral_value() else float(number)
                if isinstance(value, float) and not math.isfinite(value): raise ValueError('Aggregate exceeds finite JSON number range')
                values[name] = value
        group = {'key': [select(rows[0], path) for path in paths], 'count': len(rows), 'values': values}
        output_bytes += budget.check(group) + 1
        if output_bytes > MAX_BYTES: raise ValueError('Aggregate output exceeds 8 MiB')
        result.append(group)
    budget.check(result)
    return clone(result)


def _column_name(name):
    return isinstance(name, str) and 1 <= len(name) <= 128


def pivot_records(records, keys, column_path, value_path):
    """Turn named measurements into one sparse object per composite key."""
    budget = Budget()
    budget.check(records)
    keys = key_paths(keys)
    column_path, value_path = pointer_parts(column_path), pointer_parts(value_path)
    groups = {}
    for row in _record_rows(records):
        key = _required_key(row, keys)
        column = select(row, column_path)
        if not _column_name(column):
            raise ValueError('Pivot column names must be nonempty strings of at most 128 characters')
        if key not in groups:
            groups[key] = {'key': [select(row, path) for path in keys], 'values': {}}
        values = groups[key]['values']
        if column in values:
            raise ValueError('Duplicate pivot column for the same record key')
        values[column] = select(row, value_path)
    result = list(groups.values())
    budget.check(result)
    return clone(result)


def unpivot_records(records, keys, values_path, columns):
    """Emit one row per present field, in input row and requested field order."""
    budget = Budget()
    budget.check(records)
    keys = key_paths(keys)
    values_path = pointer_parts(values_path)
    if (not isinstance(columns, list) or not 1 <= len(columns) <= 128
            or not all(map(_column_name, columns)) or len(set(columns)) != len(columns)):
        raise ValueError('Supply one to 128 distinct nonempty unpivot column names of at most 128 characters')
    result = []
    output_bytes = 2
    for row in _record_rows(records):
        _required_key(row, keys)
        key = [select(row, path) for path in keys]
        values = select(row, values_path)
        if not isinstance(values, dict):
            raise ValueError('Unpivot values path must select an object')
        for column in columns:
            if column not in values:
                continue
            mapped = {'key': key, 'column': column, 'value': values[column]}
            output_bytes += budget.check(mapped) + bool(result)
            if len(result) >= MAX_ROWS or output_bytes > MAX_BYTES:
                raise ValueError('Unpivot output exceeds 100000 rows or 8 MiB')
            result.append(mapped)
    budget.check(result)
    return clone(result)


FUNCTIONS = {'jsonpointer': json_pointer, 'jsonpatch': json_patch, 'jsonmergepatch': json_merge_patch,
             'jsondiff': json_diff, 'joinrecords': join_records, 'deduplicaterecords': deduplicate_records,
             'redactkeys': redact_keys, 'masktext': mask_text,
             'reconcilerecords': reconcile_records, 'aggregaterecords': aggregate_records,
             'pivotrecords': pivot_records, 'unpivotrecords': unpivot_records}
