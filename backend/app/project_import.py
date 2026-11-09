"""Bounded project-package reading; importing never extracts archive members."""
import io
import json
import os
import zipfile
from pathlib import PurePosixPath
from uuid import uuid4


MAX_IMPORT_BYTES = int(os.environ.get('MINA_MAX_IMPORT_MB', '64')) * 1024 * 1024
MAX_IMPORT_FILES = 10000


def project_payload(raw: bytes, filename: str = '') -> bytes:
    if len(raw) > MAX_IMPORT_BYTES: raise ValueError('Project upload exceeds the configured size limit')
    if raw[:2] != b'PK':
        if filename.lower().endswith('.bwp'):
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
        if 'manifest.json' not in names and any(name.lower().endswith('.bwp') for name in names):
            relevant = [member for member in members if member.filename.lower().endswith(('.bwp', '.xsd', '.httpclientresource', '.httpconnresource', '.jdbcresource', '.jmsresource', '.jmsconnresource'))]
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
    from .bw_process import BW, ProcessConverter, bindings, http_resource, http_server_resource, jdbc_resource, jms_resource, mapper_config
    from .mapper_xml import etree, parse_xml

    tasks, schemas, resources, diagnostics = [], [], {}, []
    processes = {}
    resource_properties = {}
    schema_names = set()
    for name, content in sorted(files.items()):
        path = PurePosixPath(name.replace('\\', '/'))
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('BusinessWorks archive contains an invalid asset path')
        document = parse_xml(content)
        if path.suffix.lower() == '.xsd':
            if document.tag != '{http://www.w3.org/2001/XMLSchema}schema':
                raise ValueError(f'{name} is not an XML Schema')
            segments = path.parts
            start = next((index + 1 for index, part in enumerate(segments) if part.lower() == 'schemas'), len(segments) - 1)
            asset_name = '/'.join(segments[start:])
            if asset_name in schema_names:
                asset_name = path.as_posix()
            schema_names.add(asset_name)
            schemas.append({'id': f'bw-xsd-{len(schemas) + 1}', 'name': asset_name,
                            'content': etree.tostring(document, encoding='unicode')})
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
        matching = [item['id'] for path, item in resources.items()
                    if item['type'] == base_type and (not mode or item['config'].get('connectorMode') == mode) and
                    (item['name'] == name or lookup.lower() in {path.lower(), PurePosixPath(path).stem.lower()}
                     or path.lower().endswith('/' + lookup.lower()) or
                     str(PurePosixPath(path).with_suffix('')).lower().endswith('/' + lookup.lower()))]
        if len(matching) != 1:
            raise ValueError(f'{resource_type.upper()} shared resource {name!r} is missing or ambiguous')
        return matching[0]

    converted = {}
    for name, (task_id, document) in processes.items():
        converter = ProcessConverter(document, task_id, PurePosixPath(name).stem, resolve_task, resolve_resource)
        try:
            converted[task_id] = (converter.convert(), converter.dependencies, converter.resources)
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
            tasks.append(task)
            used_resources.update(linked_resources)
        else:
            diagnostics.append(f"{task['name']}: a called process was unavailable or recursive")

    for name, (task_id, document) in processes.items():
        if task_id in ready:
            continue
        path = PurePosixPath(name)
        for inputs in document.iter(BW + 'inputBindings'):
            owner = inputs.getparent()
            if owner is None: continue
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
    if not tasks:
        raise ValueError('No executable BusinessWorks processes or activity bindings were converted. ' + ' | '.join(diagnostics[:20]))
    description = f'Converted {len(ready)} BusinessWorks processes and recovered {len(tasks) - len(ready)} independent Mapper bindings.'
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
                       'properties': {profile: list(properties.values()) for profile in ('local', 'dev', 'qa', 'pre', 'production')},
                       'active_task_id': tasks[0]['id']}).encode()
