"""Deterministic mediation recipes: no scripts, eval, network or external state."""
from __future__ import annotations

import csv
import io
import json
import math
import re
import xml.etree.ElementTree as ET


class MediationError(ValueError):
    pass


MISSING = object()


def target_contract(text):
    """Load an explicit structural contract, never resolve remote schemas."""
    if not isinstance(text, str): raise MediationError('Target schema must be text')
    if not text or not str(text).strip(): return None
    if len(text) > 500000: raise MediationError('Target schema exceeds 500 KB')
    try:
        if text.lstrip().startswith('<'):
            if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper(): raise MediationError('Schema DTDs/entities are prohibited')
            root = ET.fromstring(text)
            ns = '{http://www.w3.org/2001/XMLSchema}'
            if root.tag != ns+'schema': raise MediationError('Expected an XML Schema document')
            allowed = {'schema','element','complexType','sequence','annotation','documentation'}
            if any(n.tag.removeprefix(ns) not in allowed for n in root.iter()): raise MediationError('XSD supports elements, sequences and complex types only; attributes, imports, choices and restrictions are not supported')
            types = {n.get('name'): n for n in root.findall(ns+'complexType')}
            primitives = {'string':'string','boolean':'boolean','int':'integer','integer':'integer','long':'integer','decimal':'number','double':'number','float':'number','date':'string','dateTime':'string'}
            expanded = 0
            def element(node, seen=()):
                nonlocal expanded
                expanded += 1
                if expanded > 2000 or len(seen) > 32: raise MediationError('Expanded XSD exceeds the supported structural size')
                kind = (node.get('type') or '').split(':')[-1]
                complex_type = node.find(ns+'complexType')
                if kind in types:
                    if kind in seen: raise MediationError('Recursive XSD types are not supported')
                    complex_type = types[kind]; seen = (*seen,kind)
                if complex_type is not None:
                    children = complex_type.findall(ns+'sequence/'+ns+'element')
                    if any(not child.get('name') for child in children): raise MediationError('XSD element references are not supported')
                    result = {'type':'object','properties':{c.get('name'):element(c,seen) for c in children},'required':[c.get('name') for c in children if c.get('minOccurs','1')!='0']}
                elif kind in primitives: result = {'type':primitives[kind]}
                else: raise MediationError('XSD element needs a supported type or inline complex type')
                if node.get('maxOccurs','1') != '1': result = {'type':'array','items':result}
                return result
            roots = root.findall(ns+'element')
            if len(roots)!=1: raise MediationError('Choose an XSD with one root element')
            contract = element(roots[0])
        else: contract = json.loads(text)
        def check(schema, depth=0):
            if depth>32 or not isinstance(schema,dict): raise MediationError('Invalid or excessively nested schema')
            supported = {'type','properties','required','items','description','title','$schema','$id','additionalProperties'}
            unknown = set(schema)-supported
            if unknown: raise MediationError('Unsupported schema keywords: '+', '.join(sorted(unknown)))
            if schema.get('type') not in {'object','array','string','integer','number','boolean','null'}: raise MediationError('Every target schema node needs a supported type')
            if schema.get('additionalProperties',False) not in (True,False): raise MediationError('additionalProperties must be boolean')
            if not isinstance(schema.get('required',[]),list) or not all(isinstance(k,str) for k in schema.get('required',[])): raise MediationError('required must be a list of field names')
            if schema['type']=='object':
                if not isinstance(schema.get('properties',{}),dict): raise MediationError('properties must be an object')
                for child in schema.get('properties',{}).values(): check(child,depth+1)
            if schema['type']=='array': check(schema.get('items'),depth+1)
        check(contract)
        return contract
    except (ET.ParseError,json.JSONDecodeError,RecursionError): raise MediationError('Target schema is invalid') from None


def schema_fields(contract):
    fields=[]
    def visit(schema,path='',required=False):
        if schema['type']=='object':
            for key,value in schema.get('properties',{}).items(): visit(value, f'{path}.{key}' if path else key,key in schema.get('required',[]))
        else: fields.append({'path':path,'type':schema['type'],'required':required})
    visit(contract['items'] if contract['type']=='array' else contract)
    return fields


def validate_target(value,schema,path='$'):
    kind=schema['type']
    valid={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),'boolean':isinstance(value,bool),'integer':isinstance(value,int) and not isinstance(value,bool),'number':isinstance(value,(float,int)) and not isinstance(value,bool),'null':value is None}[kind]
    if not valid: raise MediationError(f'Target {path}: expected {kind}')
    if kind=='object':
        properties=schema.get('properties',{})
        for key in schema.get('required',[]):
            if key not in value: raise MediationError(f'Target {path}.{key}: required field missing')
        for key,child in value.items():
            if key in properties: validate_target(child,properties[key],path+'.'+key)
            elif schema.get('additionalProperties') is False: raise MediationError(f'Target {path}: undeclared field {key}')
    if kind=='array':
        for i,child in enumerate(value): validate_target(child,schema['items'],f'{path}[{i}]')
OPERATIONS = {'copy', 'trim', 'uppercase', 'lowercase', 'integer', 'number', 'boolean', 'lookup'}
PATH = re.compile(r'^[A-Za-z_][\w-]*(?:\.(?:[A-Za-z_][\w-]*|[0-9]+))*$')


def read_path(value, path):
    if path in ('', '$'): return value
    if not isinstance(path, str) or not PATH.fullmatch(path): raise MediationError('Use dotted field paths, numeric array indexes, or $ for the whole record')
    for part in path.split('.'):
        if isinstance(value, dict): value = value.get(part, MISSING)
        elif isinstance(value, list) and part.isdigit(): value = value[int(part)] if int(part) < len(value) else MISSING
        else: return MISSING
    return value


def validate(config):
    if not isinstance(config, dict): raise MediationError('Mediation configuration must be an object')
    rules = config.get('rules', [])
    if not isinstance(rules, list) or not 1 <= len(rules) <= 200: raise MediationError('Add between 1 and 200 mediation rules')
    targets = []
    for index, rule in enumerate(rules, 1):
        if not isinstance(rule, dict): raise MediationError(f'Rule {index}: expected a rule object')
        target = rule.get('target', '')
        if not isinstance(target, str) or not PATH.fullmatch(target) or any(p.isdigit() for p in target.split('.')): raise MediationError(f'Rule {index}: target must be a dotted object field path')
        if any(target == old or target.startswith(old+'.') or old.startswith(target+'.') for old in targets): raise MediationError(f'Rule {index}: target overlaps another rule')
        targets.append(target)
        if rule.get('operation', 'copy') not in OPERATIONS: raise MediationError(f'Rule {index}: unsupported operation')
        if 'constant' not in rule:
            read_path({}, rule.get('source', '$'))
        if rule.get('operation') == 'lookup' and not isinstance(rule.get('values'), dict): raise MediationError(f'Rule {index}: lookup needs a value dictionary')
    for key in ('inputFormat', 'outputFormat'):
        if config.get(key, 'json') not in {'json', 'xml', 'csv'}: raise MediationError(f'Unsupported {key}')
    read_path({}, config.get('collection', '$'))
    if config.get('outputFormat') == 'xml' and not re.fullmatch(r'[A-Za-z_][\w-]*', str(config.get('rootName', 'message'))): raise MediationError('XML root must be a simple element name')


def _xml_value(node, depth=0):
    if depth > 64: raise MediationError('XML nesting exceeds 64 levels')
    if not len(node) and not node.attrib: return node.text or ''
    result = dict(node.attrib)
    for child in node:
        value = _xml_value(child, depth+1)
        if child.tag in result:
            if not isinstance(result[child.tag], list): result[child.tag] = [result[child.tag]]
            result[child.tag].append(value)
        else: result[child.tag] = value
    if node.text and node.text.strip(): result['_text'] = node.text.strip()
    return result


def _convert(value, rule):
    op = rule.get('operation', 'copy')
    if op == 'copy': return value
    if op in {'trim', 'uppercase', 'lowercase'}:
        if not isinstance(value, str): raise ValueError('text required')
        return {'trim': str.strip, 'uppercase': str.upper, 'lowercase': str.lower}[op](value)
    if op in {'integer', 'number'}:
        if isinstance(value, bool): raise ValueError('number required')
        number = float(value)
        if not math.isfinite(number) or (op == 'integer' and not number.is_integer()): raise ValueError('invalid number')
        return int(value) if op == 'integer' and isinstance(value, (str, int)) else int(number) if op == 'integer' else number
    if op == 'boolean':
        if str(value).lower() not in {'true', 'false', '1', '0'}: raise ValueError('true/false or 1/0 required')
        return str(value).lower() in {'true', '1'}
    if op == 'lookup':
        key = str(value)
        if key not in rule['values']: raise ValueError('lookup value not found')
        return rule['values'][key]


def execute_details(payload, config):
    if not isinstance(config, dict): raise MediationError('Mediation configuration must be an object')
    contract = target_contract(config.get('targetSchemaText', ''))
    if config.get('rules'): validate(config)
    # Input mappings have already been resolved by the Studio/exported runtime.
    # Bind them as values, never reinterpret message strings as field paths.
    rules = [dict(rule) for rule in config.get('rules', [])]
    targets = config.get('targetValues', {})
    if not isinstance(targets, dict): raise MediationError('Target input mappings must be an object')
    paths = {r.get('target') for r in rules}
    if contract: paths.update(f['path'] for f in schema_fields(contract))
    def leaves(value, prefix=''):
        for key, child in value.items():
            path = f'{prefix}.{key}' if prefix else key
            if isinstance(child, dict) and path not in paths: yield from leaves(child,path)
            else: yield path
    paths.update(leaves(targets))
    for path in sorted(p for p in paths if p):
        value = read_path(targets,path)
        if value is MISSING: continue
        existing = next((r for r in rules if r.get('target')==path),None)
        if existing is None: rules.append({'target':path,'constant':value})
        else: existing['constant']=value
    config = {**config,'rules':rules}
    validate(config)
    try:
        if isinstance(payload, str):
            if len(payload.encode('utf-8')) > 2_000_000: raise MediationError('Text payload exceeds the 2 MB mediation limit')
            fmt = config.get('inputFormat', 'json')
            if fmt == 'xml':
                if '<!DOCTYPE' in payload.upper() or '<!ENTITY' in payload.upper(): raise MediationError('XML DTDs and entities are not supported')
                root = ET.fromstring(payload); payload = {root.tag: _xml_value(root)}
            elif fmt == 'csv': payload = list(csv.DictReader(io.StringIO(payload)))
            else: payload = json.loads(payload)
        source = read_path(payload, config.get('collection', '$'))
        if source is MISSING: raise MediationError('Source collection was not found')
        many = isinstance(source, list) or config.get('asArray', False)
        records = source if isinstance(source, list) else [source]
        if len(records) > 10000: raise MediationError('Source exceeds 10,000 records; split the batch')
        output, trace = [], []
        for row, record in enumerate(records, 1):
            target = {}
            for index, rule in enumerate(config['rules'], 1):
                value = rule['constant'] if 'constant' in rule else read_path(record, rule.get('source', '$'))
                if value is MISSING or value is None:
                    value = rule.get('default', MISSING)
                if value is MISSING:
                    if rule.get('required'): raise MediationError(f'Record {row}, rule {index} ({rule["target"]}): required source missing')
                    continue
                try: value = _convert(value, rule)
                except (ValueError, TypeError, OverflowError): raise MediationError(f'Record {row}, rule {index} ({rule["target"]}): {rule.get("operation", "copy")} conversion failed') from None
                cursor = target
                parts = rule['target'].split('.')
                for part in parts[:-1]: cursor = cursor.setdefault(part, {})
                cursor[parts[-1]] = value
            output.append(target)
        result = output if many else output[0]
        if contract:
            if contract['type']=='array': validate_target(result,contract)
            else:
                for row in output: validate_target(row,contract)
        fmt = config.get('outputFormat', 'json')
        if fmt == 'xml':
            def append(parent, key, value, depth=0):
                if depth > 64: raise MediationError('Output nesting exceeds 64 levels')
                if not re.fullmatch(r'[A-Za-z_][\w-]*', str(key)): raise MediationError('XML output contains an invalid element name')
                if isinstance(value, list):
                    for item in value: append(parent, key, item, depth+1)
                else:
                    node = ET.SubElement(parent, key)
                    if isinstance(value, dict):
                        for k, v in value.items(): append(node, k, v, depth+1)
                    elif value is not None: node.text = str(value)
            root = ET.Element(config.get('rootName', 'message'))
            if many:
                for item in output: append(root, 'record', item)
            else:
                for key, value in result.items(): append(root, key, value)
            result = ET.tostring(root, encoding='unicode')
        elif fmt == 'csv':
            if any(isinstance(v, (dict, list)) for item in output for v in item.values()): raise MediationError('CSV output requires flat scalar target fields')
            buffer = io.StringIO(); writer = csv.DictWriter(buffer, fieldnames=[r['target'] for r in config['rules']]); writer.writeheader(); writer.writerows(output); result = buffer.getvalue()
        trace = [{'target': r['target'], 'source': r.get('source', 'constant'), 'operation': r.get('operation', 'copy')} for r in config['rules']]
        return {'output': result, 'records': len(records), 'rules': len(config['rules']), 'trace': trace}
    except (json.JSONDecodeError, ET.ParseError, csv.Error, RecursionError) as error:
        raise MediationError('Invalid or excessively nested input document') from error


def execute(payload, config):
    return execute_details(payload, config)['output']
