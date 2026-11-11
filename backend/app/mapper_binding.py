"""Generate and reopen editable, standalone XML Mapper bindings."""
import ast
import json
import math
import re

from .mapper import flatten_schema
from .mapper_xml import XSL, etree, parse_xml


META = 'urn:mina:mapper:binding:1'
XSD = '{http://www.w3.org/2001/XMLSchema}'
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*')
LOOP = object()
FUNCTIONS = {'trim': r'replace(string({}), "^\s+|\s+$", "")',
             'normalizeSpace': 'normalize-space({})',
             'upperCase': 'upper-case({})', 'lowerCase': 'lower-case({})'}
CONDITION_TOKEN = re.compile(r'''\s*(\$\{[\w.-]+\}|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[+-]?\d+(?:\.\d+)?|[A-Za-z_][\w.-]*|!=|>=|<=|==|[()=<>])''')


def _segments(path):
    parts = path.split('.') if isinstance(path, str) else []
    if not parts or any(not NAME.fullmatch(part) for part in parts):
        raise ValueError(f'Expected an unqualified XML field path: {path!r}')
    return parts


def _literal(value):
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, bool):
        return 'true()' if value else 'false()'
    if isinstance(value, int) or isinstance(value, float) and math.isfinite(value):
        return str(value)
    raise ValueError('A generated XML binding supports string, boolean and finite number constants')


def _contract(schema, side):
    if not schema:
        return {}, '', False
    document = parse_xml(schema)
    if document.tag != XSD + 'schema' or any(document.findall(XSD + name) for name in ('include', 'import', 'redefine')):
        raise ValueError(f'Select a standalone {side} XSD for binding generation')
    fields = {field['path']: field for field in flatten_schema(schema)}
    if (len(document.findall(XSD + 'element')) != 1 or not fields
            or any(node.get('form') or node.get('ref') for node in document.iter(XSD + 'element'))):
        raise ValueError(f'The {side} XSD needs one root and uniform element qualification')
    return fields, document.get('targetNamespace', ''), document.get('elementFormDefault') == 'qualified'


def _predicate(condition, select):
    remaining = str(condition or '').strip()
    if len(remaining) > 4096:
        raise ValueError('Generated condition exceeds 4096 characters')
    tokens = []
    while remaining:
        match = CONDITION_TOKEN.match(remaining)
        if not match:
            raise ValueError('Generated conditions require XML paths, scalar literals, and comparison or logical operators')
        tokens.append(match[1])
        remaining = remaining[match.end():]
    if not tokens:
        raise ValueError('Generated conditional mappings require a condition')
    if len(tokens) > 128:
        raise ValueError('Generated condition exceeds 128 tokens')
    tokens.reverse()

    def take(*choices):
        return tokens.pop() if tokens and tokens[-1] in choices else ''

    def atom():
        if take('('):
            expression = parse_or()
            if not take(')'):
                raise ValueError('Missing closing parenthesis in generated condition')
            return '(' + expression + ')'
        if not tokens or tokens[-1] in {'and', 'or', 'not', ')', '=', '==', '!=', '<', '>', '<=', '>='}:
            raise ValueError('Missing operand in generated condition')
        token = tokens.pop()
        if token in {'true', 'false'}:
            if take('(') and not take(')'):
                raise ValueError('Boolean constants take no arguments')
            return token + '()'
        if token.startswith(('"', "'")):
            return _quoted_literal(token)
        if re.fullmatch(r'[+-]?\d+(?:\.\d+)?', token):
            return token
        return select(token)

    def comparison():
        if take('not'):
            return 'not(' + comparison() + ')'
        left = atom()
        operator = take('=', '==', '!=', '<', '>', '<=', '>=')
        return left + (' ' + ('=' if operator == '==' else operator) + ' ' + atom() if operator else '')

    def parse_and():
        operands = [comparison()]
        while take('and'):
            operands.append(comparison())
        return ' and '.join(operands)

    def parse_or():
        operands = [parse_and()]
        while take('or'):
            operands.append(parse_and())
        return ' or '.join(operands)

    result = parse_or()
    if tokens:
        raise ValueError('Unexpected token in generated condition')
    return result


def _quoted_literal(value):
    try:
        return _literal(ast.literal_eval(value))
    except (ValueError, SyntaxError) as exc:
        raise ValueError('Invalid quoted string in generated binding') from exc


def generate_binding(mappings, schema='', source_schema='', *, preferences=None, _legacy=False):
    if not isinstance(mappings, list) or not mappings or len(mappings) > 5000:
        raise ValueError('A generated binding needs 1 to 5000 mapping rules')
    fields, namespace, qualified = _contract(schema, 'target')
    source_fields, source_namespace, source_qualified = _contract(source_schema, 'source')
    nsmap = {'xsl': XSL[1:-1], 'mina': META}
    if preferences is not None:
        if not isinstance(preferences, dict) or any(key not in {'implicitExistence', 'omitOptionalNil', 'copyNil'}
                                                    or not isinstance(value, bool) for key, value in preferences.items()):
            raise ValueError('Invalid XML binding preferences')
        nsmap['xsi'] = 'http://www.w3.org/2001/XMLSchema-instance'
    if source_namespace:
        nsmap['source'] = source_namespace
    formulae = [str(rule.get('source', '')) for rule in mappings
                if isinstance(rule, dict) and str(rule.get('source', '')).startswith(('xpath(', 'xpath2('))]
    if formulae:
        nsmap['xs'] = XSD[1:-1]
        from .mapper_xml import BW_FUNCTIONS, BW_RUNTIME_FUNCTIONS
        for prefix, uri in {'tib': BW_FUNCTIONS, 'bw': BW_RUNTIME_FUNCTIONS}.items():
            if any(prefix + ':' in formula for formula in formulae):
                nsmap[prefix] = uri
    binding = etree.Element(XSL + 'stylesheet', nsmap=nsmap, version='2.0',
                            attrib={'exclude-result-prefixes': ' '.join(prefix for prefix in nsmap if prefix != 'xsl')})
    metadata = etree.SubElement(binding, f'{{{META}}}rules')
    metadata.text = json.dumps({'mappings': mappings, 'schema': schema, 'sourceSchema': source_schema,
                               **({'preferences': preferences} if preferences is not None else {})},
                               ensure_ascii=True, allow_nan=False)
    template = etree.SubElement(binding, XSL + 'template', match='/')
    active = []
    for rule in mappings:
        if not isinstance(rule, dict):
            raise ValueError('Expected a mapping object')
        if rule.get('enabled') is not False and not rule.get('pending'):
            active.append(rule)
    empty = {rule['occurrenceId'] for rule in active if rule.get('duplicateOf') and rule.get('occurrenceId')
             and not str(rule.get('select') or rule.get('source') or '').strip()}
    if empty:
        parents = {}
        for rule in active:
            if rule.get('parentOccurrenceId') and rule.get('occurrenceId'):
                parents.setdefault(rule['parentOccurrenceId'], []).append(rule['occurrenceId'])
        pending = list(empty)
        for occurrence in pending:
            for child in parents.get(occurrence, []):
                if child not in empty:
                    empty.add(child)
                    pending.append(child)
        active = [rule for rule in active if rule.get('occurrenceId') not in empty]

    def source_path(path):
        if isinstance(path, str) and path.startswith('${') and path.endswith('}'):
            path = path[2:-1]
        if isinstance(path, str) and path.startswith('coerced.'):
            raise ValueError('Named source coercions require visual mapping execution')
        return _segments(path)

    def selector(parts, start=0, alias=''):
        selected = ('/' if not start else '') + '/'.join(
            'source:' + name if source_namespace and (index == 0 or source_qualified) else name
            for index, name in enumerate(parts) if index >= start)
        # Without an XSD, input/last may be either a context alias or the XML root.
        if not _legacy and not start and alias and not source_fields:
            return '(' + selected + ' | /' + alias + selected + ')'
        return selected

    def unwrap_source(path):
        if path[0] in ('input', 'last') and not any(
                field == '.'.join(path) or field.startswith('.'.join(path) + '.') for field in source_fields):
            return path[1:], path[0]
        return path, ''

    tree = {}
    def subtree(path, branch=tree):
        for name in path:
            if None in branch:
                raise ValueError(f'{".".join(path)}: target overlaps another mapping')
            branch = branch.setdefault(name, {})
        return branch

    loops = {}
    def enclosing(parts, occurrence):
        for index in range(len(parts) - 1, 0, -1):
            target = '.'.join(parts[:index])
            if (target, occurrence) in loops:
                return target, loops[target, occurrence]
        return '', None

    loop_rules = sorted((rule for rule in active if rule.get('operator') in {'for-each', 'for-each-group', 'copy-of'}),
                        key=lambda rule: (str(rule.get('target', '')).count('.'), bool(rule.get('duplicateOf'))))
    for rule in loop_rules:
        target = rule.get('target')
        target_parts = _segments(target)
        occurrence = rule.get('occurrenceId')
        copy = rule['operator'] == 'copy-of'
        if len(target_parts) < 2 or (target, occurrence) in loops or rule.get('functions') or copy and 'constant' in rule:
            raise ValueError(f'{target}: loop generation requires a unique repeating child element')
        if fields and not any(field.get('repeating') and field['path'].startswith(target + '.') for field in fields.values()):
            raise ValueError(f'{target}: select a repeating element from the target XSD')
        parent_target, parent = enclosing(target_parts, rule.get('parentOccurrenceId') if rule.get('duplicateOf') else occurrence)
        raw_path = rule.get('source') if copy else rule.get('select') or rule.get('source')
        if raw_path == 'current-group()':
            if not parent or not parent[2]:
                raise ValueError(f'{target}: current-group() needs a grouped parent')
            path, selection = parent[0], raw_path
        else:
            path, alias = unwrap_source(source_path(raw_path))
            if not path:
                raise ValueError(f'{target}: select a repeating source XML element')
            if parent and path[:len(parent[0])] != parent[0] and not alias:
                path = parent[0] + path
            depth = len(parent[0]) if parent and path[:len(parent[0])] == parent[0] else 0
            if depth == len(path):
                raise ValueError(f'{target}: nested loops need a child source or current-group()')
            selection = selector(path, depth, alias)
        if source_fields and not any(field.get('repeating') and field['path'].startswith('.'.join(path) + '.') for field in source_fields.values()):
            raise ValueError(f'{target}: select a repeating source XML element')
        grouped = rule['operator'] == 'for-each-group'
        variant = {}
        if not copy:
            loops[target, occurrence] = (path, variant, grouped)
        grouping = None
        if grouped:
            key = source_path(rule['groupBy']) if rule.get('groupBy') else []
            grouping = 'string(' + (selector(path + key, len(path)) if key else '.') + ')'
        relative_target = target_parts[len(parent_target.split('.')):] if parent else target_parts
        variants = subtree(relative_target, parent[1] if parent else tree).setdefault(LOOP, [])
        if variants and not rule.get('duplicateOf'):
            raise ValueError(f'{target}: repeated mapping occurrences require an explicit duplicate')
        variants.append((selection, grouping, None if copy else variant))

    for rule in active:
        if rule.get('operator') in {'for-each', 'for-each-group', 'copy-of'}:
            continue
        target = rule.get('target', '')
        target_parts = _segments(target)
        loop_target, loop = enclosing(target_parts, rule.get('occurrenceId'))
        operator = rule.get('operator') or ''
        if (operator not in {'', 'if', 'when-otherwise', 'choose'} or rule.get('duplicateOf')
                or rule.get('occurrenceId') and not loop):
            raise ValueError(f'{target}: this mapping statement needs handwritten XSLT')
        if fields and (target not in fields or fields[target]['repeating'] != bool(loop)):
            raise ValueError(f'{target}: expected a scalar element in the selected target XSD')
        relative_target = target_parts[len(loop_target.split('.')):] if loop else target_parts
        destination = subtree(relative_target, loop[1] if loop else tree)
        if destination:
            raise ValueError(f'{target}: target overlaps another mapping')
        def field_expression(source):
            parts, alias = unwrap_source(source_path(source))
            relative_start = 0
            if loop:
                loop_source = loop[0]
                if parts[:len(loop_source)] != loop_source:
                    if alias:
                        raise ValueError(f'{target}: loop child source must be inside its repeating source element')
                    parts = loop_source + parts
                relative_start = len(loop_source)
            source_field = '.'.join(parts)
            if len(parts) <= relative_start or source_fields and (
                    source_field not in source_fields or source_fields[source_field]['repeating'] != bool(loop)):
                raise ValueError(f'{source_field}: expected a scalar element in the selected source XSD')
            return 'zero-or-one(' + selector(parts, relative_start, alias) + ')'

        def value(source):
            if source is None or source in ('', 'null', '()'):
                return '()'
            if isinstance(source, (bool, int, float)):
                return _literal(source)
            if source in ('true', 'false', 'true()', 'false()'):
                return source if source.endswith('()') else source + '()'
            if isinstance(source, str) and source[:1] in {"'", '"'}:
                return _quoted_literal(source)
            if isinstance(source, str) and re.fullmatch(r'[+-]?\d+(?:\.\d+)?', source):
                return source
            if isinstance(source, str) and source.startswith('xpath1('):
                raise ValueError(f'{target}: an XPath 1.0 quick fix requires visual mapping execution')
            if isinstance(source, str) and source.startswith(('xpath(', 'xpath2(')) and source.endswith(')'):
                try:
                    formula = ast.literal_eval(source.split('(', 1)[1][:-1])
                except (ValueError, SyntaxError) as exc:
                    raise ValueError(f'{target}: XPath requires a quoted formula') from exc
                if not isinstance(formula, str) or not formula.strip() or len(formula) > 4096:
                    raise ValueError(f'{target}: XPath requires a formula of at most 4096 characters')
                return '(' + formula + ')'
            return field_expression(source)

        if operator == 'choose':
            branches = rule.get('whens') or []
            if not branches:
                raise ValueError(f'{target}: Choose requires at least one When')
            expression = value(rule.get('otherwise'))
            for branch in reversed(branches):
                test = _predicate(branch.get('condition'), field_expression)
                expression = f'if ({test}) then ({value(branch.get("source"))}) else ({expression})'
        else:
            expression = _literal(rule['constant']) if 'constant' in rule else value(rule.get('select') or rule.get('source'))
            if operator in {'if', 'when-otherwise'}:
                test = _predicate(rule.get('condition'), field_expression)
                otherwise = value(rule.get('otherwise')) if operator == 'when-otherwise' else '()'
                expression = f'if ({test}) then ({expression}) else ({otherwise})'
        raw_expression = expression
        if preferences is not None:
            expression = '$mina:value'
        guard = 'exists(' + expression + ')'
        if _legacy and not operator:
            guard = expression[len('zero-or-one('):-1] if expression.startswith('zero-or-one(') else None
        for function in rule.get('functions', []):
            if not isinstance(function, str) or function not in FUNCTIONS:
                raise ValueError(f'{target}: unsupported binding function {function!r}')
            expression = FUNCTIONS[function].format(expression)
        destination[None] = (expression, guard, raw_expression, operator)
    if len(tree) != 1:
        raise ValueError('Map elements under a single XML document root')

    order = {}
    for index, path in enumerate(fields or ([] if _legacy else [rule['target'] for rule in active])):
        parts = path.split('.')
        for depth in range(1, len(parts) + 1):
            order.setdefault('.'.join(parts[:depth]), index)

    variable_number = 0
    def append(parent, children, prefix=''):
        nonlocal variable_number
        ordered = sorted((name for name in children if name is not LOOP), key=lambda name: order.get(prefix + name, len(order)))
        for name in ordered:
            branch = children[name]
            uri = namespace if qualified or not prefix else ''
            if None in branch:
                expression, guard, raw_expression, operator = branch[None]
                nil_test = None
                copy_nil = False
                if preferences is not None:
                    variable_number += 1
                    variable = f'mina:value{variable_number}'
                    expression = expression.replace('$mina:value', '$' + variable)
                    guard = guard.replace('$mina:value', '$' + variable)
                    etree.SubElement(parent, XSL + 'variable', name=variable, select=raw_expression)
                    nil_test = f"if (${variable} instance of element()) then ${variable}/@xsi:nil = ('true', '1') else false()"
                    contract = fields.get(prefix + name, {})
                    copy_nil = contract.get('nillable', False) and preferences.get('copyNil', True)
                    if not operator and (contract.get('required') or not preferences.get('implicitExistence', True)):
                        guard = None
                    if contract and not contract['required'] and not contract.get('nillable') and preferences.get('omitOptionalNil'):
                        present = f'not({nil_test})'
                        guard = f'({guard}) and {present}' if guard else present
                if guard and prefix:
                    parent_for_element = etree.SubElement(parent, XSL + 'if', test=guard)
                else:
                    parent_for_element = parent
                node = etree.SubElement(parent_for_element, f'{{{uri}}}{name}' if uri else name)
                if nil_test:
                    choose = etree.SubElement(node, XSL + 'choose')
                    when = etree.SubElement(choose, XSL + 'when', test=nil_test)
                    if copy_nil:
                        etree.SubElement(when, XSL + 'attribute', name='xsi:nil', select="'true'")
                    node = etree.SubElement(choose, XSL + 'otherwise')
                etree.SubElement(node, XSL + 'value-of', select=expression)
            else:
                if LOOP in branch:
                    if len(branch) != 1:
                        raise ValueError(f'{prefix}{name}: loop child mappings must belong to an occurrence')
                    for selection, grouping, variant in branch[LOOP]:
                        if variant == {}:
                            raise ValueError(f'{prefix}{name}: map at least one child of the loop')
                        if grouping:
                            container = etree.SubElement(parent, XSL + 'for-each-group', select=selection, attrib={'group-by': grouping})
                        else:
                            container = etree.SubElement(parent, XSL + 'for-each', select=selection)
                        node = etree.SubElement(container, f'{{{uri}}}{name}' if uri else name)
                        if variant is None:
                            etree.SubElement(node, XSL + 'copy-of', select='@* | node()')
                        else:
                            append(node, variant, prefix + name + '.')
                else:
                    node = etree.SubElement(parent, f'{{{uri}}}{name}' if uri else name)
                    append(node, branch, prefix + name + '.')
    append(template, tree)
    return etree.tostring(binding, encoding='unicode')


def reopen_binding(stylesheet):
    binding = parse_xml(stylesheet)
    if binding.tag not in (XSL + 'stylesheet', XSL + 'transform') or binding.get('version') not in ('1.0', '2.0'):
        raise ValueError('Select an XSLT 1.0 or 2.0 binding')
    metadata = binding.find(f'{{{META}}}rules')
    if metadata is None:
        return {'xmlStylesheet': stylesheet}
    data = json.loads(metadata.text or '')
    if (not isinstance(data, dict) or not isinstance(data.get('mappings'), list)
            or not isinstance(data.get('schema'), str) or not isinstance(data.get('sourceSchema'), str)):
        raise ValueError('Invalid editable binding metadata')
    canonical = etree.tostring(binding, method='c14n')
    for legacy in (False, True):
        generated = parse_xml(generate_binding(data['mappings'], data['schema'], data['sourceSchema'],
                                               preferences=data.get('preferences'), _legacy=legacy))
        if canonical == etree.tostring(generated, method='c14n'):
            break
    else:
        raise ValueError('The generated stylesheet was edited and no longer matches its editable mappings')
    return {'mappings': data['mappings'], 'targetSchemaText': data['schema'],
            'sourceSchemaText': data['sourceSchema'], 'xmlStylesheet': stylesheet,
            **({'xmlBindingPreferences': data['preferences']} if 'preferences' in data else {})}
