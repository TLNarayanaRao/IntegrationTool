"""Bounded project-package reading; importing never extracts archive members."""
import io
import json
import os
import zipfile
from pathlib import PurePosixPath
from uuid import uuid4
from .bw_data_format import SUFFIXES as BW_DATA_FORMAT_SUFFIXES


MAX_IMPORT_BYTES = int(os.environ.get('MINA_MAX_IMPORT_MB', '64')) * 1024 * 1024
MAX_IMPORT_FILES = 10000


def project_payload(raw: bytes, filename: str = '') -> bytes:
    if len(raw) > MAX_IMPORT_BYTES: raise ValueError('Project upload exceeds the configured size limit')
    if raw[:2] != b'PK':
        if filename.lower().endswith(('.bwp', '.xsd', *BW_DATA_FORMAT_SUFFIXES)):
            return bw_project({PurePosixPath(filename).name: raw}, filename)
        return raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > MAX_IMPORT_FILES: raise ValueError('Project archive contains too many files')
        names = [member.filename for member in members]
        if len(set(names)) != len(names): raise ValueError('Project archive contains duplicate file names')
        def read(name):
            member = archive.getinfo(name)
            if member.file_size > MAX_IMPORT_BYTES: raise ValueError(f'{name} exceeds the configured size limit')
            with archive.open(member) as stream:
                value = stream.read(MAX_IMPORT_BYTES + 1)
            if len(value) > MAX_IMPORT_BYTES: raise ValueError(f'{name} exceeds the configured size limit')
            return value
        if 'manifest.json' not in names and any(name.lower().endswith(('.bwp', '.xsd', *BW_DATA_FORMAT_SUFFIXES)) for name in names):
            property_suffix = ('.substvar',) if any(name.lower().endswith(BW_DATA_FORMAT_SUFFIXES) for name in names) else ()
            relevant = [member for member in members if member.filename.lower().endswith(('.bwp', '.xsd', '.httpclientresource', '.httpconnresource', '.jdbcresource', '.jmsresource', '.jmsconnresource', *property_suffix, *BW_DATA_FORMAT_SUFFIXES))]
            if sum(member.file_size for member in relevant) > MAX_IMPORT_BYTES:
                raise ValueError('BusinessWorks process and schema files exceed the configured size limit')
            return bw_project({member.filename: read(member.filename) for member in relevant}, filename)
        manifest = json.loads(read('manifest.json'))
        if not isinstance(manifest, dict): raise ValueError('Project manifest must be an object')
        package_format = manifest.get('format')
        if package_format in {'mina-project', 'integration-fabric-project'}: return read('project.json')
        if package_format in {'mina-deployment', 'integration-fabric-deployment'}: return read('application/project.json')
        raise ValueError('Unsupported project package')


def bw_project(files: dict[str, bytes], filename: str) -> bytes:
    from .bw_process import BW, BW_ACTIVITY, XML_JSON_FORMATS, ProcessConverter, bindings, http_resource, http_server_resource, jdbc_resource, jms_resource, mapper_config
    from .bw_data_format import PROFILES, layout_assets, profile_values
    from .mapper_xml import etree, parse_xml

    tasks, schemas, resources, diagnostics = [], [], {}, []
    processes = {}
    resource_properties = {}
    formats, pending_layouts, paths, schema_names = {}, [], set(), set()
    bw_profiles, format_mappings, format_properties = [], {}, {}
    schema_declarations = {}
    for name, content in sorted(files.items()):
        path = PurePosixPath(name.replace('\\', '/'))
        if path.is_absolute() or '..' in path.parts or ':' in path.as_posix() or path.as_posix() in paths:
            raise ValueError('BusinessWorks archive contains an invalid asset path')
        paths.add(path.as_posix())
        if path.suffix.lower() == '.substvar':
            profile = path.stem.lower()
            if profile in ('default', *PROFILES):
                bw_profiles.append((path.as_posix(), profile, list(profile_values(parse_xml(content)))))
            continue
        document = parse_xml(content)
        if path.suffix.lower() == '.xsd':
            if document.tag != '{http://www.w3.org/2001/XMLSchema}schema':
                raise ValueError(f'{name} is not an XML Schema')
            start = next((index + 1 for index, part in enumerate(path.parts) if part.lower() == 'schemas'), len(path.parts) - 1)
            display_name = '/'.join(path.parts[start:])
            if display_name in schema_names: display_name = path.as_posix()
            schema_names.add(display_name)
            asset = {'id': f'bw-xsd-{uuid4().hex}', 'name': display_name, 'source_path': path.as_posix(),
                     'content': etree.tostring(document, encoding='unicode')}
            schemas.append(asset)
            for child in document.findall('{http://www.w3.org/2001/XMLSchema}element'):
                schema_declarations.setdefault((document.get('targetNamespace'),child.get('name')), []).append(asset)
            continue
        if path.suffix.lower() in BW_DATA_FORMAT_SUFFIXES:
            pending_layouts.append((path.as_posix(), document))
            continue
        if path.suffix.lower() in {'.httpclientresource', '.httpconnresource', '.jdbcresource', '.jmsresource', '.jmsconnresource'}:
            try:
                resource_id = f'bw-resource-{len(resources) + 1}'
                if path.suffix.lower() == '.jdbcresource':
                    item, properties = jdbc_resource(document, path.stem, resource_id)
                elif path.suffix.lower() in {'.jmsresource', '.jmsconnresource'}:
                    item, properties = jms_resource(document, path.stem, resource_id)
                elif path.suffix.lower() == '.httpconnresource':
                    item, properties = http_server_resource(document, path.stem, resource_id)
                else:
                    item, properties = http_resource(document, path.stem, resource_id), []
                resources[path.as_posix()] = item
                resource_properties[resource_id] = properties
            except ValueError as error:
                diagnostics.append(f'{path.as_posix()}: {error}')
            continue
        processes[path.as_posix()] = (f'bw-process-{len(processes) + 1}', document)

    for path, document in pending_layouts:
        try:
            asset, additional, mappings, properties = layout_assets(document, path, schemas, bw_profiles)
            if any(item['name'] in {asset['name'], *(schema['name'] for schema in additional)} for item in schemas):
                raise ValueError('Data Format asset conflicts with another schema')
            formats[path] = asset
            format_mappings[asset['id']] = mappings
            for key, defaults in properties.items():
                prior = format_properties.setdefault(key, defaults)
                for environment, value in defaults.items():
                    if prior[environment] != value:
                        prior[environment] = ''
                        diagnostics.append(f'Set the conflicting Data Format property {key} in {environment}.')
                if any(not value for value in prior.values()):
                    diagnostics.append(f'Set Data Format property {key} in any environment with a blank value.')
            schemas.extend([*additional, asset])
        except ValueError as error:
            diagnostics.append(f'{path}: {error}')

    def resolve_task(name):
        matching = [task_id for path, (task_id, document) in processes.items()
                    if name and name in (document.get('name'), PurePosixPath(path).stem)]
        if len(matching) != 1:
            raise ValueError(f'Call Process target {name!r} is missing or ambiguous')
        return matching[0]

    def resolve_resource(name, resource_type):
        if not name:
            raise ValueError(f'missing {resource_type.upper()} shared resource reference')
        lookup = name.replace('\\', '/').lstrip('/')
        base_type, _, mode = resource_type.partition(':')
        if base_type == 'data_format':
            matches = [asset['id'] for path, asset in formats.items()
                       if lookup.lower() in (path.lower(), PurePosixPath(path).stem.lower())
                       or path.lower().endswith('/' + lookup.lower())
                       or str(PurePosixPath(path).with_suffix('')).lower().endswith('/' + lookup.lower())]
            if len(matches) != 1: raise ValueError(f'Data Format resource {name!r} is missing or ambiguous')
            return matches[0]
        matching = [item['id'] for path, item in resources.items()
                    if item['type'] == base_type and (not mode or item['config'].get('connectorMode') == mode) and
                    (item['name'] == name or lookup.lower() in {path.lower(), PurePosixPath(path).stem.lower()}
                     or path.lower().endswith('/' + lookup.lower()) or
                     str(PurePosixPath(path).with_suffix('')).lower().endswith('/' + lookup.lower()))]
        if len(matching) != 1:
            raise ValueError(f'{resource_type.upper()} shared resource {name!r} is missing or ambiguous')
        return matching[0]

    def schema_resolver(name, document):
        # BW stores generated activity/process interfaces inside tibex:Types.
        # Publish only referenced schemas so internal fault/timer contracts do
        # not clutter the project or introduce unrelated import candidates.
        embedded = document.findall(f"{BW}Types/{{http://www.w3.org/2001/XMLSchema}}schema")
        module = name.split('/Processes/', 1)[0] if '/Processes/' in name else ''
        embedded_assets = {}
        def resolve_schema(qname):
            qname = etree.QName(qname)
            xs = '{http://www.w3.org/2001/XMLSchema}'
            def declares(root):
                return root.get('targetNamespace') == qname.namespace and any(
                    child.get('name') == qname.localname for child in root.findall(xs + 'element'))
            matches = schema_declarations.get((qname.namespace, qname.localname), [])
            scoped = [asset for asset in matches if module and asset.get('source_path','').startswith(module + '/')]
            matches = scoped or matches
            if len(matches) > 1: raise ValueError(f'ambiguous BW schema element {qname}')
            if matches: return matches[0]['id']
            inside = [index for index, root in enumerate(embedded) if declares(root)]
            if len(inside) > 1: raise ValueError(f'ambiguous embedded BW schema element {qname}')
            if not inside: return None
            index = inside[0]
            if index not in embedded_assets:
                path = name + f'-{index}.bw-inline.xsd'
                asset = {'id': f'bw-xsd-{uuid4().hex}', 'name': path, 'source_path': path,
                         'content': etree.tostring(embedded[index],encoding='unicode')}
                embedded_assets[index] = asset
            return embedded_assets[index]['id']
        return resolve_schema, embedded_assets

    converted = {}
    for name, (task_id, document) in processes.items():
        resolve_schema, embedded_assets = schema_resolver(name, document)
        converter = ProcessConverter(document, task_id, PurePosixPath(name).stem, resolve_task, resolve_resource, resolve_schema)
        try:
            task = converter.convert()
            schemas.extend(embedded_assets.values())
            diagnostics.extend(f'{name}: {message}' for message in converter.diagnostics)
            converted[task_id] = (task, converter.dependencies, converter.resources)
        except ValueError as error:
            diagnostics.append(f'{name}: {error}')

    # Exclude callers of failed conversions and recursive invocations. A task is
    # ready only once all its target tasks have themselves been converted.
    ready = set()
    while True:
        next_ready = {task_id for task_id, (_, dependencies, _) in converted.items()
                      if dependencies <= ready and all(converted[target][0]['kind'] == 'subtask' for target in dependencies)}
        if next_ready == ready:
            break
        ready = next_ready
    used_resources = set()
    for task_id, (task, _, linked_resources) in converted.items():
        if task_id in ready:
            for activity in task['activities']:
                cfg = activity.get('config') or {}
                mappings = format_mappings.get(cfg.get('dataFormatId'))
                if activity['type'] == 'flat' and mappings:
                    cfg['inputMappings'] = {**mappings, **cfg.get('inputMappings', {})}
            tasks.append(task)
            used_resources.update(linked_resources)
        else:
            diagnostics.append(f"{task['name']}: a called process was unavailable or recursive")

    for name, (task_id, document) in processes.items():
        if task_id in ready:
            continue
        path = PurePosixPath(name)
        resolve_schema, embedded_assets = schema_resolver(name, document)
        for inputs in document.iter(BW + 'inputBindings'):
            owner = inputs.getparent()
            if owner is None: continue
            design = owner.find(f'{BW}config/{BW_ACTIVITY}')
            kind = ((design.get('activityTypeID') if design is not None else owner.get('type')) or '').lower()
            if kind in XML_JSON_FORMATS or kind in ('bw.generalactivities.mapper', 'bw.generalactivities.map',
                                                    'bw.parse.parsedata', 'bw.parse.renderdata'):
                label = owner.get('name') or kind
                converter = ProcessConverter(document, f'bw-activity-{len(tasks)+1}', f'{path.stem} {label}',
                                             resolve_task, resolve_resource, resolve_schema)
                try:
                    tail = converter.step(owner, [converter.node('start','Start')])
                    converter.connect(tail, converter.node('end','End'))
                except ValueError as error:
                    diagnostics.append(f'{name}/{label}: native activity was not recovered: {error}')
                    continue
                diagnostics.extend(f'{name}: {message}' for message in converter.diagnostics)
                for activity in converter.activities:
                    config = activity.get('config', {})
                    if activity['type'] == 'flat' and config.get('dataFormatId') in format_mappings:
                        config['inputMappings'] = {**format_mappings[config['dataFormatId']], **config.get('inputMappings', {})}
                tasks.append({'id': converter.task_id, 'name': converter.name, 'kind':'subtask',
                              'description': f'Recovered native BW activity from {path.as_posix()}. Supply its original BW input variables by name.',
                              'activities': converter.activities, 'transitions': converter.transitions})
                continue
            for binding in bindings(inputs):
                activity_name = owner.get('name') or 'Mapper'
                try:
                    config = mapper_config(binding)
                    if owner.tag == BW + 'activityExtension':
                        config['bwXmlElementVariables'] = True
                except ValueError as error:
                    diagnostics.append(f'{name}/{activity_name}: {error}')
                    continue
                tasks.append({'id': f'bw-mapping-{len(tasks) + 1}', 'name': f'{path.stem} {activity_name} {len(tasks) + 1}', 'kind': 'subtask',
                              'description': f'Imported XSLT binding from {path.as_posix()}. Supply the original activity variables as task input.',
                              'activities': [{'id': 'Start', 'name': 'Start', 'type': 'start', 'position': {'x': 70, 'y': 100}},
                                             {'id': 'Mapper', 'name': activity_name, 'type': 'mapper', 'config': config, 'position': {'x': 260, 'y': 100}},
                                             {'id': 'End', 'name': 'End', 'type': 'end', 'position': {'x': 450, 'y': 100}}],
                              'transitions': [{'id': 'start-map', 'source': 'Start', 'target': 'Mapper'},
                                              {'id': 'map-end', 'source': 'Mapper', 'target': 'End'}]})
        schemas.extend(embedded_assets.values())
    if not tasks and not formats and (pending_layouts or processes or not schemas):
        raise ValueError('No executable BusinessWorks processes or activity bindings were converted. ' + ' | '.join(diagnostics[:20]))
    description = f'Converted {len(ready)} BusinessWorks processes, imported {len(formats)} Data Formats, and recovered {len(tasks) - len(ready)} independent activities or Mapper bindings.'
    from .models import default_environment_properties
    properties = {item.key: item.model_dump() for item in default_environment_properties()}
    for resource_id in sorted(used_resources):
        for entry in resource_properties[resource_id]:
            previous = properties.get(entry['key'])
            if previous is not None and previous != entry:
                diagnostics.append(f"Set the deployment value for conflicting property {entry['key']}.")
                properties[entry['key']] = {**entry, 'value': 0 if entry['data_type'] == 'integer' else ''}
            else:
                properties[entry['key']] = entry
            if entry['data_type'] == 'password':
                diagnostics.append(f"Set the imported connection credential {entry['key']} before execution.")
    if diagnostics:
        description += '\nReview required:\n' + '\n'.join(diagnostics[:30])
        if len(diagnostics) > 30:
            description += f'\n{len(diagnostics) - 30} additional items require review.'
    return json.dumps({'id': f'bw-{uuid4().hex}', 'name': PurePosixPath(filename.replace('\\', '/')).stem or 'BusinessWorks mappings',
                       'description': description, 'tasks': tasks, 'schemas': schemas,
                       'resources': [item for item in resources.values() if item['id'] in used_resources],
                       'properties': {profile: [*properties.values(), *(
                           {'key': key, 'value': defaults[profile], 'data_type': 'string'}
                           for key, defaults in format_properties.items())] for profile in PROFILES},
                       'active_task_id': tasks[0]['id'] if tasks else ''}).encode()
