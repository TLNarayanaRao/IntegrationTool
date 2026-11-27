"""Resolve explicitly supplied design assets and compile reviewed mapping rules."""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
from zipfile import BadZipFile, ZipFile

from lxml import etree

from .data_formats import DataFormats, xsd_shape
from .faults import MinaFault
from .mapper import validate_mapping_rules
from .mapper_assistant import fields, plan
from .xsd_catalog import SELECTION, SchemaGraph, asset_path
from .xsd_openapi import XsdProjection


MAX_ASSET = 2 * 1024 * 1024
EXTENSIONS = {'.xsd', '.json', '.schema', '.xlsx'}
REFERENCE = re.compile(r'''["'`]([^"'`\r\n]+?\.(?:xsd|json|schema|xlsx))["'`]|(?<![\w./\\:-])([^\s"'`(),;]+?\.(?:xsd|json|schema|xlsx))(?=$|[\s),;.])''', re.IGNORECASE)


def _key(path):
    return PurePosixPath(str(path).replace('\\', '/')).name.casefold()


def references(text):
    result = []
    for match in REFERENCE.finditer(text):
        name = match.group(1) or match.group(2)
        prefix = text[max(0, match.start()-45):match.start()]
        schema_label = re.search(r'\b(?:schema|contract)(?:\s+(?:file|path))?(?:\s+(?:is|at|from))?\s*[:=]?\s*$', prefix, re.I)
        if name.lower().endswith('.json') and not name.lower().endswith('.schema.json') and not schema_label:
            continue
        result.append((name, match.start()))
    return result


def _load_asset(name, files, project_root):
    if _key(name) in files:
        return files[_key(name)]
    relative = PurePosixPath(name.replace('\\', '/'))
    if not project_root or relative.is_absolute() or ':' in name or '..' in relative.parts:
        raise ValueError(f'Attach {relative.name} in AI Build or use a path relative to the saved MINA project.')
    root = Path(project_root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'Could not find {relative.name} in the saved project. Attach it in AI Build.')
    with path.open('rb') as stream:
        content = stream.read(MAX_ASSET + 1)
    if len(content) > MAX_ASSET:
        raise ValueError(f'{relative.name} exceeds the 2 MiB design asset limit.')
    return content


def _schema_document(name, content):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ValueError(f'{name} must be a UTF-8 schema document.') from exc
    identifier = 'ai-schema-' + sha256(name.encode() + b'\0' + content).hexdigest()[:20]
    return {'id': identifier, 'name': PurePosixPath(name.replace('\\', '/')).name,
            'source_path': name, 'package_path': 'AI-Build', 'content': text}


def _contract(asset, root_name, schemas):
    text, path = asset['content'], asset['source_path']
    if not path.lower().endswith('.xsd'):
        shape = json.loads(text)
        if not isinstance(shape, dict) or not ('properties' in shape or '$ref' in shape):
            raise ValueError(f'{asset["name"]} must be a JSON Schema with an object root.')
        pending = [shape]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if any(not isinstance(node[key], str) or not node[key].startswith('#')
                       for key in ('$ref', '$dynamicRef', '$recursiveRef') if key in node):
                    raise ValueError(f'{asset["name"]} must use local JSON Schema references.')
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        return shape, '', '', 'json', set()
    assets = tuple((item['source_path'], item['content']) for item in schemas if item['source_path'].lower().endswith('.xsd'))
    try:
        graph = SchemaGraph(text, path, assets, DataFormats.safe_xml)
        graph.compile()
        projection = XsdProjection(graph.root, graph).describe()
    except (MinaFault, etree.Error, ValueError) as exc:
        raise ValueError(f'{asset["name"]} is not a valid XSD or has unavailable imports: {exc}') from exc
    roots = (projection[0].get('oneOf') or [projection[0]]) if projection else []
    names = [item['xml']['name'] for item in roots]
    if not root_name and len(names) != 1:
        raise ValueError(f'{asset["name"]} has multiple or no global roots. Specify the root to use ({", ".join(names)}).')
    try:
        shape = xsd_shape(text, root_name or names[0], (path, assets))
    except MinaFault as exc:
        raise ValueError(str(exc)) from exc
    name = shape['xml']['name']
    namespace = shape['xml'].get('namespace', '')
    qualified = '{' + namespace + '}' + name
    document = etree.fromstring(DataFormats.safe_xml(text), etree.XMLParser(resolve_entities=False, no_network=True))
    document.set(SELECTION + 'structure', 'element|' + qualified)
    document.set(SELECTION + 'element', qualified)
    return ({'type': 'object', 'properties': {name: shape}, 'required': [name]},
            etree.tostring(document, encoding='unicode'), qualified if namespace else name, 'xml', set(graph.documents))


def _workbook(content, sheet_name):
    from openpyxl import load_workbook

    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 128 or sum(info.file_size for info in members) > 12 * 1024 * 1024:
                raise ValueError('The mapping workbook expands beyond the design limit.')
            for info in members:
                if info.filename.endswith(('.xml', '.rels')):
                    xml = archive.read(info)
                    if b'\0' in xml or re.search(rb'<!\s*(DOCTYPE|ENTITY)\b', xml, re.I):
                        raise ValueError('The workbook contains unsupported XML declarations or encoding.')
        book = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, OSError, KeyError, etree.Error) as exc:
        raise ValueError('Select a readable .xlsx mapping workbook.') from exc
    try:
        if sheet_name and sheet_name not in book.sheetnames:
            raise ValueError(f'Mapping worksheet {sheet_name} was not found.')
        sheet = book[sheet_name] if sheet_name else book.worksheets[0]
        if sheet.max_row and sheet.max_row > 5001 or sheet.max_column and sheet.max_column > 64:
            raise ValueError('A mapping worksheet supports up to 5,000 rows and 64 columns.')
        rows = sheet.iter_rows(max_col=64)
        normals = [re.sub(r'[^a-z]', '', str(cell.value or '').lower()) for cell in next(rows, ())]
        columns = []
        for role in ('source', 'target'):
            matches = [idx for idx, label in enumerate(normals) if label in (role, role+'field', role+'path', role+'element', role+'xpath')]
            if len(matches) != 1:
                raise ValueError('Use one Source Field and one Target Field column in the mapping worksheet.')
            columns.append(matches[0])
        transforms = [idx for idx, label in enumerate(normals) if label in ('transformation', 'transform', 'function')]
        if len(transforms) > 1:
            raise ValueError('Use at most one Transformation column in the mapping worksheet.')
        for index, row in enumerate(rows, 2):
            if index > 5001:
                raise ValueError('A mapping worksheet supports up to 5,000 rows.')
            cells = [row[column] for column in columns]
            if all(cell.value in (None, '') for cell in cells):
                continue
            if any(not isinstance(cell.value, str) or cell.data_type == 'f' or not cell.value.strip() for cell in cells):
                raise ValueError(f'Workbook row {index} needs literal source and target field paths.')
            transform = row[transforms[0]] if transforms else None
            if transform and (transform.data_type == 'f' or transform.value is not None and not isinstance(transform.value, str)):
                raise ValueError(f'Workbook row {index} needs a literal transformation name.')
            names = {'trim': 'trim', 'uppercase': 'upperCase', 'lowercase': 'lowerCase'}
            operation = re.sub(r'[^a-z]', '', str(transform.value or '').lower()) if transform else ''
            if operation and operation not in names:
                raise ValueError(f'Workbook row {index} uses an unsupported transformation. Supported names are Trim, Uppercase and Lowercase.')
            yield index, *(cell.value.strip() for cell in cells), names.get(operation)
    finally:
        book.close()


def _field(path, known, row, role):
    path = path.removeprefix('$.').strip('/').replace('/', '.').replace('[*]', '').replace('[]', '')
    if path in known:
        return path
    path = re.sub(r'(^|\.)[\w-]+:', r'\1', path) if ':' in path else path
    if path in known:
        return path
    matches = [name for name in known if name.endswith('.'+path)]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f'Workbook row {row} has an unknown or ambiguous {role} field: {path}.')


def prepare_assets(requirement, uploads=(), workspace_schemas=(), project_root=None):
    mentioned = references(requirement)
    if not uploads and not mentioned:
        return None
    files = {}
    schema_paths = {}
    for item in workspace_schemas:
        path = item.source_path or item.name
        key = _key(path)
        if key in files:
            files[key] = None
        else:
            files[key] = item.content.encode()
            schema_paths[key] = path
    selected = []
    for item in uploads:
        key = _key(item.name)
        if key in selected or Path(key).suffix not in EXTENSIONS:
            raise ValueError('Attach distinct XSD, JSON Schema or XLSX filenames.')
        content = base64.b64decode(item.content, validate=True)
        if len(content) > MAX_ASSET:
            raise ValueError(f'{key} exceeds the 2 MiB design asset limit.')
        files[key] = content
        schema_paths[key] = item.name
        selected.append(key)
    names = list(dict.fromkeys(_key(name) for name, _ in mentioned)) or selected
    paths = {_key(name): name for name, _ in mentioned}
    schema_names = [name for name in names if Path(name).suffix != '.xlsx']
    books = [name for name in names if name.endswith('.xlsx')]
    if not books:
        books = [name for name in selected if name.endswith('.xlsx')]
    roles = {}
    for name, position in mentioned:
        prefix = requirement[max(0, position-65):position]
        role = re.search(r'\b(source|target)(?:\s+(?:xsd|schema|contract)(?:\s+(?:file|path))?)?(?:\s+(?:is|at|from))?\s*[:=]?\s*$', prefix, re.I)
        if role and _key(name) in schema_names:
            key = role[1].lower()
            if key in roles and roles[key] != _key(name):
                raise ValueError(f'Identify exactly one {key} schema per mapping stage.')
            roles[key] = _key(name)
    if len(roles) == 2:
        primary = [roles['source'], roles['target']]
    elif len(schema_names) == 2:
        primary = list(schema_names)
        if roles.get('source') == primary[1] or roles.get('target') == primary[0]:
            primary.reverse()
    else:
        raise ValueError('Identify one source schema and one target schema in the requirement.')
    if len(books) > 1:
        raise ValueError('Select one XLSX mapping workbook per mapping stage.')
    def load(name):
        if name in files and files[name] is None:
            raise ValueError(f'{name} matches more than one workspace schema. Attach the intended file.')
        data = _load_asset(paths.get(name, name), files, project_root)
        if len(data) > MAX_ASSET:
            raise ValueError(f'{name} exceeds the 2 MiB design asset limit.')
        return data
    named_schemas = {name: _schema_document(schema_paths.get(name) or paths.get(name, name).replace('\\', '/'), load(name))
                     for name in dict.fromkeys([*primary, *(key for key in [*schema_names, *selected] if key.endswith('.xsd'))])}
    schemas = list(named_schemas.values())
    catalog = {asset_path(item['source_path']): item for item in schemas if item['source_path'].lower().endswith('.xsd')}
    for item in workspace_schemas:
        path = item.source_path or item.name
        if not path.lower().endswith('.xsd') or len(item.content.encode()) > MAX_ASSET:
            continue
        try:
            key = asset_path(path)
        except ValueError:
            continue
        if key not in catalog:
            catalog[key] = _schema_document(key, item.content.encode())
    roots = [re.search(r'\b'+role+r'\s+root\s*[:=]?\s*["`\']?([\w.-]+)', requirement, re.I) for role in ('source', 'target')]
    contracts = [named_schemas[name] for name in primary]
    source, target = [_contract(asset, root[1] if root else '', list(catalog.values())) for asset, root in zip(contracts, roots)]
    existing_ids = {item['id'] for item in schemas}
    schemas.extend(catalog[key] for key in sorted(source[-1] | target[-1]) if catalog[key]['id'] not in existing_ids)
    choices, transforms = {}, {}
    if books:
        sheet = re.search(r'\b(?:mapping\s+)?sheet\s*[:=]\s*["`\']([^"`\']+)["`\']', requirement, re.I)
        known_source, known_target = ({item['path'] for item in fields(contract[0])} for contract in (source, target))
        for row, raw_source, raw_target, transform in _workbook(load(books[0]), sheet[1] if sheet else ''):
            src, dst = _field(raw_source, known_source, row, 'source'), _field(raw_target, known_target, row, 'target')
            if dst in choices:
                raise ValueError(f'Workbook row {row} maps target {dst} more than once.')
            choices[dst] = src
            if transform:
                transforms[dst] = transform
        if not choices:
            raise ValueError('The mapping workbook has no field mappings.')
    result = plan(source[0], target[0], choices=choices, threshold=85 if not choices else 100, exact_names=not choices)
    rules = result['rules']
    if choices:
        rules = [rule for rule in rules if rule['target'] in choices or
                 rule.get('operator') == 'for-each' and any(path.startswith(rule['target']+'.') for path in choices)]
        for rule in rules:
            if rule['target'] in transforms:
                if rule.get('targetType') != 'string':
                    raise ValueError(f'Transformation for {rule["target"]} requires a scalar string field.')
                rule['functions'] = [transforms[rule['target']]]
    if not rules:
        raise ValueError('No unambiguous field mappings were found. Supply a mapping workbook with explicit paths.')
    errors = validate_mapping_rules(rules, target[0])
    if errors:
        raise ValueError('Generated mapping is invalid: ' + errors[0])
    findings = [f"Review target field {item['target']} ({item['status']})." for item in result['recommendations']
                if item['required'] and (item['status'] in ('ambiguous', 'unmatched') or choices and item['target'] not in choices)]
    return {'schemas': schemas, 'contracts': contracts, 'source': source, 'target': target, 'rules': rules,
            'workbookRows': len(choices), 'findings': findings}


def _step(identifier, kind, config, position):
    return {'id': identifier, 'name': identifier, 'type': kind, 'config': config,
            'position': {'x': 80 + 200 * position, 'y': 120}}


SOURCES = {('file', 'read'): 'content', ('ftp', 'get'): 'content', ('sftp', 'get'): 'content',
           ('rest', 'receiver'): 'body', ('http_listener', 'listen'): 'body',
           ('kafka', 'receive'): 'data', ('pubsub', 'subscribe'): 'data', ('ems', 'queue_receiver'): 'data'}
DESTINATIONS = {('file', 'write'), ('ftp', 'put'), ('sftp', 'put'), ('rest', 'invoke'), ('http', 'request'),
                ('kafka', 'publish'), ('pubsub', 'publish'), ('ems', 'queue_sender'), ('http_response', 'response')}


def _wire_document(activity, expression, media):
    kind, config = activity['type'], activity['config']
    if kind in ('http_response', 'http', 'rest'):
        field = 'body'
        config['contentType'] = media
    else:
        field = 'content' if kind in ('file', 'ftp', 'sftp') else 'payload'
    config['inputMappings'] = {**config.get('inputMappings', {}), field: expression}


def _isolate_delivery(tasks, main, operation, first_ids, media):
    """Factor a linear multi-activity delivery stage, preserving its input/output."""
    if len(first_ids) != 1:
        return
    nodes, edges = main['activities'], main['transitions']
    by_id = {item['id']: item for item in nodes}
    chain, boundary, visited = [], [], set()
    current = next(iter(first_ids))
    while current not in visited and operation(by_id[current]) in DESTINATIONS - {('http_response', 'response')}:
        visited.add(current)
        incoming = [edge for edge in edges if edge['target'] == current]
        outgoing = [edge for edge in edges if edge['source'] == current]
        if len(incoming) != 1 or len(outgoing) != 1 or any(edge.get('type', 'success') != 'success' for edge in incoming + outgoing):
            return
        chain.append(by_id[current])
        boundary = outgoing
        current = outgoing[0]['target']
    if len(chain) < 2 or current in visited or any(task['id'] == 'ai-delivery' for task in tasks):
        return
    first = chain[0]['id']
    if any(item['id'] in ('Start', 'End') for item in chain):
        return
    for item in chain:
        _wire_document(item, '${input.document}', media)
    child_steps = [_step('Start', 'start', {}, 0), *chain, _step('End', 'end', {}, len(chain) + 1)]
    main['activities'] = [item if item['id'] != first else {
        **item, 'type': 'call_task', 'config': {'taskId': 'ai-delivery', 'inputMappings': {'payload': '${last}'}}
    } for item in nodes if item['id'] == first or item['id'] not in visited]
    main['transitions'] = [edge for edge in edges if edge['source'] not in visited]
    main['transitions'].append({**boundary[0], 'source': first})
    tasks.append({'id': 'ai-delivery', 'name': 'Deliver-Mapped-Document', 'kind': 'subtask', 'package_path': 'AI-Build',
                  'activities': child_steps,
                  'transitions': [{'id': f'deliver-{index}', 'source': a['id'], 'target': b['id'], 'type': 'success'}
                                  for index, (a, b) in enumerate(zip(child_steps, child_steps[1:]))]})


def attach_mapping(proposal, assets):
    project = proposal['project']
    tasks = project['tasks']
    matches = [(task, activity) for task in tasks for activity in task['activities']
               if activity['type'] in ('mapper', 'native_map', 'transform', 'ai_transform')]
    if len(matches) > 1:
        raise ValueError('This set of assets defines one mapping. Identify one transform stage, or generate independent mappings separately.')
    if matches:
        main, marker = matches[0]
    elif len(tasks) == 1:
        main, marker = tasks[0], None
    else:
        raise ValueError('Name the transform stage where the source and target schemas should be used.')

    def operation(node):
        return node['type'], node['config'].get('operation', '')

    activities, edges = main['activities'], main['transitions']
    child_id = 'ai-contract-mapping'
    if any(task['id'] == child_id for task in tasks):
        raise ValueError('The generated design uses a reserved mapping task identifier.')
    if marker is None:
        target_node = next((node for node in activities if operation(node) in DESTINATIONS or node['type'] == 'end'), None)
        if target_node is None:
            raise ValueError('The mapping needs a success continuation.')
        marker = _step('Map-Source-to-Target', 'mapper', {}, len(activities))
        incoming = [edge for edge in edges if edge['target'] == target_node['id'] and edge.get('type', 'success') == 'success']
        if len(incoming) != 1:
            raise ValueError('The mapping needs a single source path. Name a transform at the intended point in the flow.')
        incoming[0]['target'] = marker['id']
        activities.insert(activities.index(target_node), marker)
        for index, node in enumerate(activities):
            if node['position']['y'] < 200:
                node['position']['x'] = 80 + 200 * index
        edges.append({'id': 'ai-mapping-output', 'source': marker['id'], 'target': target_node['id'], 'type': 'success'})
    predecessors = {edge['source'] for edge in edges if edge['target'] == marker['id']}
    if len(predecessors) != 1:
        raise ValueError('The mapping step needs one upstream document.')
    prior = next(node for node in activities if node['id'] in predecessors)
    if prior['type'] == 'log':
        roots = [node for node in activities if operation(node) in SOURCES and activities.index(node) < activities.index(marker)]
        prior = roots[-1] if roots else prior
    source_field = SOURCES.get(operation(prior))
    source_expression = '${last.' + source_field + '}' if source_field else '${last}'
    source_shape, source_xsd, source_root, source_kind, _ = assets['source']
    target_shape, target_xsd, _, target_kind, _ = assets['target']
    source_schema, target_schema = assets['contracts']
    if operation(prior) == ('xml', 'parse'):
        source_expression = '${last.xmlString}'
    marker.update(type='call_task', config={'taskId': child_id, 'inputMappings': {'payload': source_expression}})

    parse_config = {'operation': 'parse', 'schemaId': source_schema['id'], 'validateOutput': True}
    if source_xsd:
        parse_config.update(schemaText=source_xsd, rootElement=source_root)
    map_config = {'mappings': assets['rules'], 'sourceSchema': source_shape, 'validateOutput': True}
    if target_xsd:
        map_config.update(targetSchemaId=target_schema['id'], targetSchemaText=target_xsd, nativeXmlOutput=True)
    else:
        map_config.update(targetSchema=target_shape)
    finish = {'inputMappings': {'document': '${last.xmlString}' if target_xsd else '${last}'}}
    child = [_step('Start', 'start', {}, 0), _step('Parse-Source', source_kind, parse_config, 1),
             _step('Map-Fields', 'native_map', map_config, 2), _step('End', 'end', finish, 3)]
    tasks.append({'id': child_id, 'name': 'Map-Source-to-Target', 'kind': 'subtask', 'package_path': 'AI-Build',
                  'activities': child, 'transitions': [{'id': f'map-{index}', 'source': a['id'], 'target': b['id'], 'type': 'success'}
                                                       for index, (a, b) in enumerate(zip(child, child[1:]))]})
    successors = {edge['target'] for edge in edges if edge['source'] == marker['id'] and edge.get('type', 'success') == 'success'}
    passthrough = {node['id'] for node in activities if node['type'] == 'log'}
    while successors and successors <= passthrough:
        passthrough.difference_update(successors)
        successors = {edge['target'] for edge in edges if edge['source'] in successors and edge.get('type', 'success') == 'success'}
    media = 'application/xml' if target_kind == 'xml' else 'application/json'
    for item in activities:
        if item['id'] not in successors:
            continue
        if operation(item) in DESTINATIONS:
            _wire_document(item, '${last.document}', media)
        elif item['type'] == 'end':
            item['config']['inputMappings'] = {'result': '${last.document}'}
    if proposal.get('provider') == 'local-blueprint':
        _isolate_delivery(tasks, main, operation, successors, media)
    project['schemas'] = [*project.get('schemas', []), *assets['schemas']]
    proposal['summary'] += f' Added one schema mapping subtask using {assets["workbookRows"]} workbook rows.' if assets['workbookRows'] else ' Added one schema mapping subtask using high-confidence field matches.'
    proposal['assetFindings'] = assets['findings']
    return proposal
