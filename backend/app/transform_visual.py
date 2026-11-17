"""Lossless expression boundaries for the script editor's object mapping view."""
import ast
import json
from .dataweave import DataWeaveError, Parser, _tokens, parse_script


def script_to_visual(script):
    parse_script(script)
    header, body = script.split('---', 1)
    tokens = _tokens(body.strip())[:-1]
    rows = []
    def object_rows(items, prefix):
        if not items or items[0][1] != '{' or items[-1][1] != '}': return False
        if prefix and len(items) == 2: return False
        position = 1
        names = set()
        while position < len(items) - 1:
            kind, name = items[position]
            if kind not in ('identifier', 'string') or position + 1 >= len(items) or items[position + 1][1] != ':': return False
            name = ast.literal_eval(name) if kind == 'string' else name
            # Dotted literal keys cannot safely be flattened into path segments.
            if '.' in name or not name or name in names: return False
            names.add(name)
            position += 2
            start = position; depth = 0
            while position < len(items) - 1:
                token = items[position][1]
                if token == ',' and depth == 0: break
                if token in ('{', '[', '('): depth += 1
                elif token in ('}', ']', ')'): depth -= 1
                position += 1
            value = items[start:position]
            target = '.'.join((*prefix, name))
            checkpoint = len(rows)
            if not object_rows(value, (*prefix, name)):
                del rows[checkpoint:]
                rows.append({'target': target, 'expression': ' '.join(token for _, token in value)})
            if position < len(items) - 1: position += 1
        return True
    parser = Parser(body.strip(), {}); parser.evaluating = False; parser.parse()
    if not object_rows(tokens, ()):
        rows = [{'target': '$payload', 'expression': body.strip()}]
    return {'header': header.rstrip(), 'mappings': rows, 'mode': 'expression' if any(r['target'] == '$payload' for r in rows) else 'object'}


def visual_to_script(header, mappings):
    if not isinstance(mappings, list) or any(not isinstance(item, dict) for item in mappings):
        raise DataWeaveError('Visual mappings must be an array of field definitions')
    if len(mappings) == 1 and mappings[0].get('target') == '$payload':
        body = str(mappings[0].get('expression') or '')
    else:
        tree = {}
        for mapping in mappings:
            path = str(mapping.get('target') or '').split('.')
            if any(not part or part == '$payload' for part in path): raise DataWeaveError('A visual mapping requires a target path')
            branch = tree
            for part in path[:-1]:
                branch = branch.setdefault(part, {})
                if not isinstance(branch, dict): raise DataWeaveError('Conflicting visual target paths')
            if path[-1] in branch: raise DataWeaveError('Duplicate visual target path')
            branch[path[-1]] = str(mapping.get('expression') or 'null')
        def render(node):
            return '{' + ', '.join(json.dumps(name, ensure_ascii=False) + ': ' + (render(value) if isinstance(value, dict) else value) for name, value in node.items()) + '}'
        body = render(tree)
    parser = Parser(body, {}); parser.evaluating = False; parser.parse()
    script = str(header or '%dw 2.0\noutput application/json') + '\n---\n' + body
    parse_script(script)
    return script
