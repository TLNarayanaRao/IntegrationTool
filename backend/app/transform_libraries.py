"""Explicit, portable script modules. No Python imports or filesystem resolution."""
import math
import re
from .mapping_documents import json_pointer, json_patch, json_merge_patch, json_diff, join_records, deduplicate_records, redact_keys, mask_text, reconcile_records, aggregate_records


def words(value):
    return re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', str(value)).replace('_', ' ').replace('-', ' ').split()


MODULES = {
    'mina::Documents': {'jsonPointer': json_pointer, 'jsonPatch': json_patch, 'jsonMergePatch': json_merge_patch, 'jsonDiff': json_diff},
    'mina::Records': {'joinRecords': join_records, 'deduplicateRecords': deduplicate_records,
                      'reconcileRecords': reconcile_records, 'aggregateRecords': aggregate_records},
    'mina::Privacy': {'redactKeys': redact_keys, 'maskText': mask_text},
    'dw::core::Strings': {
        'capitalize': lambda value: None if value is None else ' '.join(word.capitalize() for word in str(value).split(' ')),
        'camelize': lambda value: None if value is None else ''.join(word.lower() if index == 0 else word.capitalize() for index, word in enumerate(words(value))),
        'underscore': lambda value: None if value is None else '_'.join(words(value)).lower(),
        'dasherize': lambda value: None if value is None else '-'.join(words(value)).lower(),
        'padLeft': lambda value, size, char=' ': str(value).rjust(int(size), str(char)),
        'padRight': lambda value, size, char=' ': str(value).ljust(int(size), str(char)),
        'substringBefore': lambda value, separator: str(value).partition(str(separator))[0],
        'substringAfter': lambda value, separator: str(value).partition(str(separator))[2],
        'reverse': lambda value: value[::-1],
    },
    'dw::core::Arrays': {
        'divideBy': lambda values, size: divide_by(values, size),
        'take': lambda values, count: values[:max(0, int(count))],
        'drop': lambda values, count: values[max(0, int(count)):],
    },
    'dw::core::Numbers': {
        'fromBinary': lambda value: int(str(value), 2), 'fromHex': lambda value: int(str(value), 16),
        'fromRadixNumber': lambda value, radix: int(str(value), int(radix)),
        'toBinary': lambda value: radix_number(value, 2), 'toHex': lambda value: radix_number(value, 16),
        'toRadixNumber': lambda value, radix: radix_number(value, radix),
    },
    'dw::util::Coercions': {
        'toNumber': lambda value: float(value),
        'toBoolean': lambda value: boolean(value),
        'toArray': lambda value: list(str(value)),
    },
    'dw::util::Math': {
        'acos': lambda value: math.acos(value) if -1 <= value <= 1 else None,
        'asin': lambda value: math.asin(value) if -1 <= value <= 1 else None,
        'atan': math.atan, 'cos': math.cos, 'sin': math.sin, 'tan': math.tan,
        'log10': lambda value: math.log10(value) if value > 0 else None,
        'logn': lambda value: math.log(value) if value > 0 else None,
        'toDegrees': math.degrees, 'toRadians': math.radians,
    },
}

CORE_NAMES = ('upper', 'lower', 'trim', 'sizeOf', 'isEmpty', 'flatten', 'keysOf', 'valuesOf',
              'sum', 'min', 'max', 'avg', 'joinBy', 'splitBy', 'contains', 'startsWith', 'endsWith',
              'abs', 'floor', 'ceil', 'mod', 'pow', 'zip', 'unzip', 'uuid', 'now', 'typeOf', 'read', 'write')


def divide_by(values, size):
    size = int(size)
    if size <= 0: raise ValueError('divideBy size must be positive')
    return [values[index:index + size] for index in range(0, len(values), size)]


def radix_number(value, radix):
    radix = int(radix)
    if not 2 <= radix <= 36 or isinstance(value, bool) or int(value) != value:
        raise ValueError('Radix conversion requires an integer and a base from 2 to 36')
    number = abs(int(value)); output = ''
    while number:
        number, digit = divmod(number, radix)
        output = '0123456789abcdefghijklmnopqrstuvwxyz'[digit] + output
    return ('-' if value < 0 else '') + (output or '0')


def boolean(value):
    if str(value).lower() not in ('true', 'false'): raise ValueError('toBoolean requires true or false')
    return str(value).lower() == 'true'


def install_imports(metadata, environment, libraries, parse_script, parser, error, stack=(), budget=None):
    """Bind functions into a fresh lexical environment for this evaluation only."""
    functions = environment.setdefault('__functions__', {})
    aliases = environment.setdefault('__library_functions__', {})
    budget = budget if budget is not None else [128]
    for directive in metadata.get('imports', []):
        budget[0] -= 1
        if budget[0] < 0: raise error('Script library import budget exceeded')
        match = re.fullmatch(r'(?:(\*|[\w$]+(?:\s*,\s*[\w$]+)*)\s+from\s+)?([\w$]+(?:::[\w$]+)*)(?:\s+as\s+([\w$]+))?', directive)
        if not match: raise error('Invalid module import: ' + directive)
        names, module, alias = match.groups()
        if module in stack: raise error('Cyclic script library import: ' + ' -> '.join((*stack, module)))
        if len(stack) >= 16: raise error('Script library import depth exceeds 16')
        if module == 'dw::Core':
            exports = {name: (lambda *args, name=name: parser('', {}).call(name, list(args))) for name in CORE_NAMES}
            custom = False
        elif module in MODULES:
            exports = MODULES[module]
            custom = False
        elif module in libraries:
            source = libraries[module]
            if not isinstance(source, str) or len(source) > 65536: raise error('Invalid script library source: ' + module)
            info, body = parse_script(source if '---' in source else source + '\n---\nnull')
            if body.strip() not in ('', 'null'): raise error('A script library exports declarations; move mapping bodies into a function: ' + module)
            scope = {'__functions__': {}, '__library_functions__': {}}
            install_imports(info, scope, libraries, parse_script, parser, error, (*stack, module), budget)
            for name, (parameters, expression) in info['functions'].items():
                scope['__functions__'][name] = (parameters, expression, scope)
            for name, expression in info['variables']:
                scope[name] = parser(expression, scope).parse()
            exports = {name: scope['__functions__'][name] for name in info['functions']}
            constants = {name: scope[name] for name, _ in info['variables']}
            exports.update(constants)
            custom = True
        else:
            raise error('Unknown script library ' + module + '; add it to Libraries or use a listed built-in module')
        selected = list(exports) if names == '*' or not names else [item.strip() for item in names.split(',')]
        for name in selected:
            if name not in exports: raise error(f'Library {module} does not export {name}')
            key = name if names else (alias or module.rsplit('::', 1)[-1]) + '::' + name
            target = environment if custom and name in constants else functions if custom else aliases
            if key in target: raise error('Duplicate imported function: ' + key)
            target[key] = exports[name]
