"""Portable transformation assets, regression tests and bounded batch execution."""
import copy
import hashlib
import json
import time
from itertools import islice
from .mapper import execute, flatten_schema, rewrite_references, validate_output


def normalize_rules(mappings):
    def path(value):
        text = value[2:-1] if value.startswith('${') and value.endswith('}') else value
        if text.startswith('activities.') and '.output.' in text: return text.split('.output.', 1)[1]
        if text in ('input', 'last') or text.startswith('activities.') and text.endswith('.output'): return ''
        if text.startswith(('input.', 'last.')): return text.split('.', 1)[1]
        if '.' in text and not text.startswith(('properties.', 'vars.', 'context.', 'tasks.')): return text.split('.', 1)[1]
        return text
    def expression(value): return rewrite_references(value, path) if isinstance(value, str) else value
    output = []
    for rule in mappings or []:
        item = copy.deepcopy(rule)
        for key in ('source', 'select', 'otherwise', 'condition'):
            if key in item: item[key] = expression(item[key])
        if isinstance(item.get('whens'), list):
            for branch in item['whens']:
                for key in ('source', 'condition'):
                    if key in branch: branch[key] = expression(branch[key])
        output.append(item)
    return output


def test_mapping(config, value):
    # Tests emulate the selected upstream output, without invoking connectors.
    document = {**(value if isinstance(value, dict) else {}), 'input': value, 'last': value}
    options = {**config, 'validateOutput': False}
    result = execute(document, normalize_rules(config.get('mappings', [])), options)
    schema = config.get('targetSchema') or config.get('targetSchemaText')
    errors = validate_output(result, schema) if config.get('validateOutput', True) else []
    return {'output': result, 'valid': not errors, 'validationErrors': errors}


def differences(expected, actual, path='$', limit=100):
    """JSON-pointer-like field differences; absent is distinct from null."""
    result = []
    def add(kind, current, wanted=None, received=None):
        if len(result) < limit: result.append({'path': current, 'kind': kind, 'expected': wanted, 'actual': received})
    def walk(wanted, received, current):
        if len(result) >= limit: return
        if isinstance(wanted, dict) and isinstance(received, dict):
            for key in sorted(wanted.keys() | received.keys()):
                child = current + '/' + str(key).replace('~', '~0').replace('/', '~1')
                if key not in received: add('missing', child, wanted[key])
                elif key not in wanted: add('unexpected', child, received=received[key])
                else: walk(wanted[key], received[key], child)
        elif isinstance(wanted, list) and isinstance(received, list):
            for index in range(max(len(wanted), len(received))):
                child = f'{current}/{index}'
                if index >= len(received): add('missing', child, wanted[index])
                elif index >= len(wanted): add('unexpected', child, received=received[index])
                else: walk(wanted[index], received[index], child)
        elif type(wanted) is not type(received) and not (type(wanted) in (int, float) and type(received) in (int, float)) or wanted != received:
            add('changed', current, wanted, received)
    walk(expected, actual, path)
    return result


def run_cases(config, cases=None):
    cases = config.get('testCases', []) if cases is None else cases
    if not isinstance(cases, list) or len(cases) > 200: raise ValueError('A suite supports up to 200 test cases')
    results = []
    deadline = time.monotonic() + min(300, max(1, float(config.get('maxSuiteMs') or 30000) / 1000))
    for index, case in enumerate(cases):
        if time.monotonic() >= deadline: raise ValueError('Transformation suite deadline exceeded')
        if not isinstance(case, dict): raise ValueError('Each test case must be an object')
        name = case.get('name') or f'Case {index + 1}'
        if 'expected' not in case: raise ValueError(f'{name}: expected output is required')
        try:
            mapped = test_mapping(config, case.get('input'))
            changes = differences(case['expected'], mapped['output'])
            results.append({'name': name, **mapped, 'differences': changes, 'passed': mapped['valid'] and not changes})
        except Exception as error:
            results.append({'name': name, 'passed': False, 'differences': [], 'error': str(error)})
    return {'passed': all(result['passed'] for result in results), 'count': len(results), 'results': results}


def schema_impact(previous, current, mappings=None):
    old, new = ({field['path']: field for field in flatten_schema(schema)} for schema in (previous, current))
    removed = sorted(old.keys() - new.keys())
    changed = [{'path': path, 'before': old[path], 'after': new[path]} for path in sorted(old.keys() & new.keys())
               if any(old[path].get(key) != new[path].get(key) for key in ('type', 'required', 'repeating'))]
    changed_paths = set(removed) | {field['path'] for field in changed}
    affected = [rule['target'] for rule in mappings or [] if rule.get('target') in changed_paths]
    def contract(value):
        if isinstance(value, str):
            try: return json.loads(value)
            except ValueError: return value
        return value
    contract_changes = differences(contract(previous), contract(current), path='schema', limit=100)
    return {'added': sorted(new.keys() - old.keys()), 'removed': removed, 'changed': changed,
            'affectedTargets': sorted(set(affected)), 'contractChanges': contract_changes}


ASSET_KEYS = ('mappings', 'targetSchema', 'targetSchemaText', 'sourceSchema', 'sourceSchemaText', 'lookupTables', 'testCases', 'maxIterations', 'maxExecutionMs', 'maxOutputSizeKb', 'nullPolicy', 'typeCoercion', 'customFunctions', 'copyNil', 'removeEmptyStructures', 'trimStrings', 'defaultValue', 'onMappingError', 'validateOutput', 'maxSuiteMs', 'maxBatchSizeKb')


def template(config, name, version):
    if not isinstance(name, str) or not isinstance(version, str) or not name.strip() or not version.strip(): raise ValueError('Template name and version are required')
    content = {key: copy.deepcopy(config[key]) for key in ASSET_KEYS if key in config}
    encoded = json.dumps(content, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(encoded) > 2 * 1024 * 1024: raise ValueError('Transformation template exceeds 2 MB')
    return {'format': 'mina-transformation-template', 'formatVersion': 1, 'name': name, 'version': version,
            'sha256': hashlib.sha256(encoded).hexdigest(), 'config': content}


def read_template(asset):
    if not isinstance(asset, dict): raise ValueError('Template must be an object')
    if asset.get('format') != 'mina-transformation-template' or asset.get('formatVersion') != 1: raise ValueError('Unsupported transformation template')
    config = asset.get('config')
    if not isinstance(config, dict) or set(config) - set(ASSET_KEYS): raise ValueError('Invalid template configuration')
    expected = template(config, asset.get('name'), asset.get('version'))
    if asset.get('sha256') != expected['sha256']: raise ValueError('Transformation template checksum does not match')
    return copy.deepcopy(config)


def execute_batches(records, config, batch_size=100):
    """Consume an iterator lazily, retaining at most one batch of mapped records."""
    if not 1 <= batch_size <= 10000: raise ValueError('Batch size must be between 1 and 10000')
    iterator = iter(records)
    maximum_bytes = int(config.get('maxBatchSizeKb') or 16384) * 1024
    if maximum_bytes < 1024: raise ValueError('Batch memory limit must be at least 1 KB')
    config = {**config, 'maxOutputSizeKb': config.get('maxOutputSizeKb') or 1024}
    while True:
        batch = []; consumed = 0
        for value in islice(iterator, batch_size):
            consumed += len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
            if consumed > maximum_bytes: raise ValueError('Batch input exceeds memory limit; reduce batch size')
            batch.append(value)
        if not batch: return
        result = []
        for value in batch:
            mapped = test_mapping(config, value)
            consumed += len(json.dumps(mapped, ensure_ascii=False, allow_nan=False).encode())
            if consumed > maximum_bytes: raise ValueError('Batch input/output exceeds memory limit; reduce batch size')
            result.append(mapped)
        yield result
