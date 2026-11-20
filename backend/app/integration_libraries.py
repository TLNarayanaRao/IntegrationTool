"""Versioned MINA Integration Libraries. Releases are data, never extracted or executed."""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import posixpath
import re
import zipfile
import zlib
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from pydantic import BaseModel, Field, model_validator

from .models import EnvironmentProperty, LibraryPin, Project, SchemaAsset, SharedResource, TaskDefinition, find_subtask

FORMAT = 'mina-integration-library'
PREFIX = 'mina-library-'
MAX_LIBRARY_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_LIBRARY_BYTES + 64 * 1024
ARCHIVE_KEY_ENV = 'MINA_LIBRARY_ARCHIVE_KEY'
IDENTITY = r'^[a-z][a-z0-9-]{0,47}$'
VERSION = r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
PROPERTY = re.compile(r'\$\{properties\.([^}]+)\}')
REFERENCE = re.compile(r'\$\{([^}]+)\}')
SECRET = re.compile(r'(?i)(password|passwd|secret|token|privatekey|credentials?|authorization|apikey)$')
ASSETS = ('tasks', 'resources', 'schemas')


class LibrarySetting(EnvironmentProperty):
    value: None = Field(default=None, exclude=True)
    required: bool = True


class LibraryRelease(BaseModel):
    id: str = Field(pattern=IDENTITY)
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(pattern=VERSION, max_length=32)
    description: str = Field(default='', max_length=2000)
    tasks: list[TaskDefinition] = Field(default_factory=list, max_length=500)
    resources: list[SharedResource] = Field(default_factory=list, max_length=500)
    schemas: list[SchemaAsset] = Field(default_factory=list, max_length=500)
    exports: dict[str, list[str]] = Field(default_factory=dict)
    settings: list[LibrarySetting] = Field(default_factory=list, max_length=500)
    dependencies: list[dict[str, str]] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_release(self):
        if not any(self.exports.get(category) for category in ASSETS):
            raise ValueError('Select at least one public task, connection, or schema.')
        if self.exports.keys() - set(ASSETS):
            raise ValueError('Invalid library export category.')
        for category in ASSETS:
            assets = getattr(self, category)
            ids = {asset.id for asset in assets}
            if len(ids) != len(assets) or len({item.casefold() for item in ids}) != len(assets):
                raise ValueError(f'Library {category} contain duplicate identifiers.')
            for asset in assets:
                if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,159}', asset.id):
                    raise ValueError(f'Invalid library asset identifier {asset.id!r}.')
                if asset.package_path.count('/') >= 14 or len(asset.package_path) > 960:
                    raise ValueError('A library asset package path is too deeply nested or too long.')
            if set(self.exports.get(category, [])) - ids:
                raise ValueError(f'Library exports contain an unknown {category} identifier.')
        schema_paths = set()
        for schema in self.schemas:
            source = relative_schema_path(schema.source_path or schema.name).casefold()
            relative_schema_path(schema.name)
            if source in schema_paths:
                raise ValueError('Library schemas must have unique source paths.')
            schema_paths.add(source)
        if any(task.kind != 'subtask' for task in self.tasks):
            raise ValueError('Libraries can contain callable Sub Tasks. Starter Tasks belong in consuming projects.')
        task_ids = {task.id for task in self.tasks}
        for task in self.tasks:
            for activity in task.activities:
                if activity.type != 'call_task':
                    continue
                targets = [str(activity.config[key]) for key in ('taskId', 'dynamicTaskId') if activity.config.get(key)]
                if not targets or any(target not in task_ids for target in targets):
                    raise ValueError(f'{task.name} / {activity.name} needs a fixed Sub Task included in this library.')
        keys = [setting.key for setting in self.settings]
        if len(keys) != len(set(keys)) or any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', key) for key in keys):
            raise ValueError('Library settings must have unique property keys.')
        documents = [document for schema in self.schemas if (document := data_format_document(schema))]
        for config in [*configs(self.tasks, self.resources), *documents]:
            validate_credentials(config)
        if property_keys(self.tasks, self.resources, documents) - set(keys):
            raise ValueError('Library references undeclared properties.')
        return self


def relative_schema_path(value: str) -> str:
    path = PurePosixPath(value.replace('\\', '/'))
    if path.is_absolute() or ':' in value or '..' in path.parts or str(path) == '.':
        raise ValueError('Library schemas must use relative paths.')
    return path.as_posix()


def configs(tasks, resources):
    for task in tasks:
        yield task.input_schema
        yield task.output_schema
        yield from (activity.config for activity in task.activities)
        yield from (group.config for group in task.groups)
        yield from (edge.condition for edge in task.transitions)
    yield from (resource.config for resource in resources)


def strings(value, key=''):
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, list):
        for child in value:
            yield from strings(child, key)
    elif isinstance(value, dict):
        for field, child in value.items():
            yield from strings(child, field)


def data_format_document(schema: SchemaAsset) -> dict | None:
    if not schema.content.lstrip().startswith('{'):
        return None
    try:
        content = json.loads(schema.content)
    except ValueError:
        return None
    return content if isinstance(content, dict) and isinstance(content.get('dataFormat'), dict) else None


def schema_references(text: str):
    if 'schemaLocation' in text and text.lstrip().startswith('<'):
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            return
        namespace = '{http://www.w3.org/2001/XMLSchema}'
        tags = {namespace + kind for kind in ('include', 'import', 'redefine', 'override')}
        yield from (element.get('schemaLocation', '') for element in root.iter() if element.tag in tags)
    elif '$ref' in text and text.lstrip().startswith('{'):
        try:
            document = json.loads(text)
        except ValueError:
            return
        yield from (reference for field, reference in strings(document) if field == '$ref')


def resolved_schema_reference(reference: str, source: str, paths: dict, names: dict):
    path = unquote(reference.split('#', 1)[0]).replace('\\', '/')
    if not path or path.startswith('/') or ':' in path:
        return None
    relative = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
    return paths.get(relative) or names.get(path)


def asset_category(field: str) -> str | None:
    field = field.rsplit('.', 1)[-1].lower()
    if field in ('taskid', 'dynamictaskid'):
        return 'tasks'
    if field.endswith(('resourceid', 'connectionid', 'managerid')):
        return 'resources'
    if field.endswith(('schemaid', 'formatassetid', 'dataformatid')):
        return 'schemas'
    return None


def property_keys(tasks, resources, documents=()):
    from itertools import chain
    return {match for config in chain(configs(tasks, resources), documents)
            for _, text in strings(config) for match in PROPERTY.findall(text)}


def validate_credentials(config):
    sensitive_keys = set()

    def require_setting(value, message):
        if value in (None, ''):
            return
        match = PROPERTY.fullmatch(value) if isinstance(value, str) else None
        if not match:
            raise ValueError(message)
        sensitive_keys.add(match[1])

    def check(value, field=''):
        if isinstance(value, str):
            if SECRET.search(field):
                require_setting(value, f'Configure {field} through a project property before publishing.')
            if '://' in value and not value.startswith('${'):
                try:
                    has_userinfo = urlsplit(value).username is not None
                except ValueError:
                    return
                if has_userinfo:
                    raise ValueError('Replace credentials embedded in a URL with a library setting before publishing.')
        elif isinstance(value, list):
            for item in value:
                check(item, field)
        elif isinstance(value, dict):
            check_fields(value)

    def check_fields(config):
        lower = {key.lower(): value for key, value in config.items()}
        for key in ('serviceaccountjson', 'serviceaccount', 'oauthclientsecret', 'privatekeypem'):
            value = lower.get(key)
            if value != {}:
                require_setting(value, f'Configure {key} through a project property before publishing.')
        key_secrets = lower.get('openapiapikeysecrets')
        if key_secrets:
            message = 'Configure OpenAPI API key values through project properties before publishing.'
            if not isinstance(key_secrets, dict):
                raise ValueError(message)
            for value in key_secrets.values():
                require_setting(value, message)
        header = lower.get('headername', lower.get('name'))
        if isinstance(header, str) and (SECRET.search(header) or header.lower() == 'proxy-authorization'):
            value = lower.get('headervalue', lower.get('value'))
            require_setting(value, 'Configure authentication headers through project properties before publishing.')
        for key, item in config.items():
            check(item, key)
    check(config)
    return sensitive_keys


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(release: LibraryRelease) -> str:
    return hashlib.sha256(canonical(release.model_dump(mode='json'))).hexdigest()


def summary(release: LibraryRelease) -> dict:
    return {
        'id': release.id, 'name': release.name, 'version': release.version, 'description': release.description,
        'sha256': digest(release), 'dependencies': release.dependencies,
        'settings': [item.model_dump() for item in release.settings],
        'exports': {category: [{'id': asset.id, 'name': asset.name} for asset in getattr(release, category)
                               if asset.id in release.exports.get(category, [])] for category in ASSETS},
    }


def archive_key() -> bytes | None:
    value = os.getenv(ARCHIVE_KEY_ENV, '').strip()
    if not value:
        return None
    try:
        key = base64.b64decode(value, altchars=b'-_', validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f'{ARCHIVE_KEY_ENV} must encode a 32-byte key in Base64.') from error
    if len(key) != 32:
        raise ValueError(f'{ARCHIVE_KEY_ENV} must encode a 32-byte key in Base64.')
    return key


def archive_bytes(release: LibraryRelease) -> bytes:
    payload = canonical(release.model_dump(mode='json'))
    if len(payload) > MAX_LIBRARY_BYTES:
        raise ValueError('Integration Library exceeds the maximum size.')
    manifest = {'format': FORMAT, 'formatVersion': 1, 'sha256': hashlib.sha256(payload).hexdigest()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        if key := archive_key():
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            manifest.update(formatVersion=2, id=release.id, name=release.name, version=release.version)
            nonce = os.urandom(12)
            encrypted = nonce + AESGCM(key).encrypt(nonce, zlib.compress(payload), canonical(manifest))
            manifest['ciphertextSha256'] = hashlib.sha256(encrypted).hexdigest()
            archive.writestr('library.aes', encrypted, compress_type=zipfile.ZIP_STORED)
        else:
            archive.writestr('library.json', payload)
        archive.writestr('manifest.json', canonical(manifest))
    return buffer.getvalue()


def read_archive(raw: bytes) -> LibraryRelease:
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError('Integration Library exceeds the maximum size.')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        names = sorted(member.filename for member in members)
        if names not in (['library.json', 'manifest.json'], ['library.aes', 'manifest.json']):
            raise ValueError('Invalid Integration Library archive contents.')
        sizes = {member.filename: member.file_size for member in members}
        if sizes.get('library.json', 0) > MAX_LIBRARY_BYTES or sizes.get('library.aes', 0) > MAX_ARCHIVE_BYTES or sizes['manifest.json'] > 4096:
            raise ValueError('Integration Library exceeds the maximum uncompressed size.')
        manifest = json.loads(archive.read('manifest.json'))
        version = 2 if 'library.aes' in sizes else 1
        if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or type(manifest.get('formatVersion')) is not int or manifest['formatVersion'] != version:
            raise ValueError('Unsupported Integration Library format.')
        if version == 1:
            payload = archive.read('library.json')
        else:
            from cryptography.exceptions import InvalidTag
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = archive_key()
            if key is None:
                raise ValueError(f'This protected Integration Library requires {ARCHIVE_KEY_ENV} on the Studio backend.')
            encrypted = archive.read('library.aes')
            if len(encrypted) < 28 or manifest.pop('ciphertextSha256', None) != hashlib.sha256(encrypted).hexdigest():
                raise ValueError('Integration Library ciphertext checksum did not match.')
            try:
                compressed = AESGCM(key).decrypt(encrypted[:12], encrypted[12:], canonical(manifest))
                unzip = zlib.decompressobj()
                payload = unzip.decompress(compressed, MAX_LIBRARY_BYTES + 1)
                if len(payload) > MAX_LIBRARY_BYTES or not unzip.eof or unzip.unused_data:
                    raise ValueError('Invalid or oversized Integration Library payload.')
            except (InvalidTag, zlib.error) as error:
                raise ValueError('Unable to authenticate the protected Integration Library. Check the configured key.') from error
    if manifest.get('sha256') != hashlib.sha256(payload).hexdigest():
        raise ValueError('Integration Library checksum did not match.')
    release = LibraryRelease.model_validate_json(payload)
    if canonical(release.model_dump(mode='json')) != payload:
        raise ValueError('Integration Library descriptor differs from the published format.')
    if version == 2 and (manifest.get('id'), manifest.get('version'), manifest.get('name')) != (release.id, release.version, release.name):
        raise ValueError('Integration Library manifest does not match the release.')
    return release


def publish(project: Project, identity: str, name: str, version: str, description: str, exports: dict) -> LibraryRelease:
    if exports.keys() - set(ASSETS):
        raise ValueError('Invalid library export category.')
    selected = {category: set(exports.get(category, [])) for category in ASSETS}
    by_id = {category: {asset.id: asset for asset in getattr(project, category)} for category in ASSETS}
    public = {category: sorted(selected[category]) for category in ASSETS}
    for category in ASSETS:
        if selected[category] - by_id[category].keys():
            raise ValueError(f'The selected {category} no longer exist in the project.')
        if any(by_id[category][key].library_origin for key in selected[category]):
            raise ValueError('Publish project-owned assets. Referenced library assets are included as private dependencies.')
    pending = list(selected['tasks'])
    while pending:
        task = by_id['tasks'][pending.pop()]
        if task.kind != 'subtask':
            raise ValueError(f'{task.name} is a Starter Task. Publish a Sub Task instead.')
        for activity in task.activities:
            if activity.type != 'call_task':
                continue
            for field in ('taskId', 'dynamicTaskId'):
                value = str(activity.config.get(field) or '')
                if not value:
                    continue
                if '${' in value:
                    raise ValueError(f'{activity.name} needs a fixed library task target before publishing.')
                target = find_subtask(project.tasks, value)
                if not target:
                    raise ValueError(f'{activity.name} references an unknown Sub Task.')
                if target.id not in selected['tasks']:
                    selected['tasks'].add(target.id)
                    pending.append(target.id)
    tasks = [by_id['tasks'][key].model_copy(deep=True) for key in sorted(selected['tasks'])]
    project_functions = {item.name for item in project.custom_functions}
    for config in configs(tasks, []):
        for _, text in strings(config):
            used_functions = project_functions.intersection(re.findall(r'\bcustom:([\w:-]+)\s*\(', text))
            if used_functions:
                raise ValueError(f'Library uses project custom functions that are unavailable to consumers: {", ".join(sorted(used_functions))}.')
    for task in tasks:
        for activity in task.activities:
            if activity.type == 'call_task':
                for field in ('taskId', 'dynamicTaskId'):
                    target = find_subtask(project.tasks, str(activity.config.get(field) or ''))
                    if target:
                        activity.config[field] = target.id
    pending_configs = list(configs(tasks, []))
    pending_configs.extend(by_id['resources'][key].config for key in selected['resources'])
    while pending_configs:
        for field, value in strings(pending_configs.pop()):
            category = asset_category(field)
            if category == 'resources' and value in by_id['resources']:
                if value not in selected['resources']:
                    selected['resources'].add(value)
                    pending_configs.append(by_id['resources'][value].config)
            elif category == 'schemas':
                if value in by_id['schemas']:
                    selected['schemas'].add(value)
                else:
                    schema = next((item for item in project.schemas if item.name == value), None)
                    if schema:
                        selected['schemas'].add(schema.id)
    # Only include the schemas reached by exports or local include/import paths.
    schema_paths = {}
    for item in project.schemas:
        try:
            schema_paths[relative_schema_path(item.source_path or item.name)] = item.id
        except ValueError:
            if item.id in selected['schemas']:
                raise
    schema_names = {item.name: item.id for item in project.schemas}
    pending_schemas = list(selected['schemas'])

    def include_schema(identity):
        if identity and identity not in selected['schemas']:
            selected['schemas'].add(identity)
            pending_schemas.append(identity)

    def include_reference(reference: str, source: str):
        include_schema(resolved_schema_reference(reference, source, schema_paths, schema_names))

    def include_schema_references(text: str, source: str = ''):
        for reference in schema_references(text):
            include_reference(reference, source)

    for config in configs(tasks, []):
        for field, reference in strings(config):
            if field == '$ref':
                include_reference(reference, '')
        for _, text in strings(config):
            include_schema_references(text)
    while pending_schemas:
        item = by_id['schemas'][pending_schemas.pop()]
        include_schema_references(item.content, relative_schema_path(item.source_path or item.name))
        if document := data_format_document(item):
            for field, reference in strings(document):
                if asset_category(field) == 'schemas':
                    include_schema(reference if reference in by_id['schemas'] else schema_names.get(reference))
    resources = [by_id['resources'][key] for key in sorted(selected['resources'])]
    schemas = [by_id['schemas'][key] for key in sorted(selected['schemas'])]
    profile = {value.key: value.data_type for values in project.properties.values() for value in values}
    settings = []
    documents = [document for schema in schemas if (document := data_format_document(schema))]
    sensitive = set().union(*(validate_credentials(config) for config in [*configs(tasks, resources), *documents]))
    for key in sorted(property_keys(tasks, resources, documents)):
        settings.append({'key': key, 'data_type': 'password' if key in sensitive else profile.get(key, 'string'), 'required': True})
    dependencies = [pin_info(pin) for pin in project.libraries if any(
        asset.library_origin and asset.library_origin['alias'] == pin.alias for asset in [*tasks, *resources, *schemas]
    )]
    return LibraryRelease(id=identity, name=name, version=version, description=description, exports=public,
                          tasks=[task.model_copy(update={'library_origin': None}) for task in tasks],
                          resources=[item.model_copy(update={'library_origin': None}) for item in resources],
                          schemas=[item.model_copy(update={'library_origin': None}) for item in schemas],
                          settings=settings, dependencies=dependencies)


def pin_info(pin: LibraryPin) -> dict[str, str]:
    return {'alias': pin.alias, 'id': pin.library['id'], 'version': pin.library['version'], 'sha256': pin.sha256}


def pin_reference(pin: LibraryPin) -> dict:
    return {'alias': pin.alias, 'sha256': pin.sha256, 'library': {
        key: pin.library[key] for key in ('id', 'name', 'version', 'description') if key in pin.library
    }}


def task_interface(task, activity_type, direction, schema_lookup, schema_documents):
    activity = next((node for node in task.activities if node.type == activity_type), None)
    config = activity.config if activity else {}
    selected = schema_lookup.get(str(config.get('interfaceSchemaId') or ''))
    schema = config.get('interfaceSchemaText') or getattr(task, f'{direction}_schema')
    from lxml.etree import XMLSyntaxError
    from .faults import MinaFault
    from .xsd_catalog import inherit_schema_selection, schema_selection
    try:
        if selected:
            schema = inherit_schema_selection(selected.content, schema)
        if isinstance(schema, str) and schema.lstrip().startswith('<') and any(schema_references(schema)):
            from .data_formats import xsd_shape
            base = selected.source_path or selected.name if selected else f"Libraries/{task.library_origin['alias']}/interface.xsd"
            shape = xsd_shape(schema, schema_selection(schema)[1], (base, schema_documents))
            if root := shape.get('xml', {}).get('name'):
                return {'type': 'object', 'properties': {root: shape}, 'required': [root]}
        return schema
    except (ValueError, XMLSyntaxError, MinaFault):
        # A stale interface selection should not prevent the workspace opening.
        return getattr(task, f'{direction}_schema')


def studio_project(project: Project, *, workspace=False) -> dict:
    """Expose the consuming application's assets and the library interface only."""
    if not project.libraries and not any(asset.library_origin for asset in (*project.tasks, *project.resources, *project.schemas)):
        return project.model_dump()
    view = project.model_dump(exclude={'process', 'tasks', 'resources', 'schemas', 'libraries'})
    view['libraries'] = [pin_reference(pin) for pin in project.libraries]
    view['tasks'] = [task.model_dump() for task in project.tasks if not task.library_origin]
    view['resources'] = [asset.model_dump() for asset in project.resources if not asset.library_origin or (
        not workspace and asset.library_origin['public'])]
    view['schemas'] = [asset.model_dump() for asset in project.schemas if not asset.library_origin or (
        not workspace and asset.library_origin['public'])]
    if view['active_task_id'] not in {task['id'] for task in view['tasks']}:
        view['active_task_id'] = view['tasks'][0]['id'] if view['tasks'] else ''
    if not workspace:
        schema_lookup = {key: asset for asset in project.schemas for key in (asset.name, asset.id)}
        schema_documents = tuple((asset.source_path or asset.name, asset.content) for asset in project.schemas
                                 if (asset.source_path or asset.name).lower().endswith('.xsd'))
        for task in project.tasks:
            if not task.library_origin or not task.library_origin['public']:
                continue
            contract = {
                direction: task_interface(task, activity_type, direction, schema_lookup, schema_documents)
                for activity_type, direction in (('start', 'input'), ('end', 'output'))
            }
            view['tasks'].append({
                'id': task.id, 'name': task.name, 'kind': task.kind, 'package_path': task.package_path,
                'library_origin': task.library_origin, 'library_contract': contract,
                'activities': [], 'transitions': [], 'groups': [],
            })
    return view


def resolve_pin(raw: dict, project_id: str = '') -> LibraryPin:
    pin = LibraryPin.model_validate(raw)
    if any(field in pin.library for field in ASSETS):
        return pin  # Legacy source-bearing workspace; Project validation checks its checksum.
    identity, version = pin.library.get('id'), pin.library.get('version')
    if not isinstance(identity, str) or not isinstance(version, str):
        raise ValueError('Integration Library reference is missing an ID or version.')
    release = catalog_release(identity, version)
    if release is not None and digest(release) == pin.sha256:
        return pin.model_copy(update={'library': release.model_dump(mode='json')})
    if isinstance(project_id, str) and project_id:
        from .store import project_dir
        descriptor = project_dir(project_id) / 'project.json'
        if descriptor.is_file():
            for previous in json.loads(descriptor.read_bytes()).get('libraries', []):
                library = previous.get('library', {})
                if (library.get('id'), library.get('version'), previous.get('sha256')) == (identity, version, pin.sha256):
                    return pin.model_copy(update={'library': library})
    raise ValueError(f'Install Integration Library {identity} {version} with the pinned checksum before opening this project.')


def studio_project_input(payload: dict) -> Project:
    pins = payload.get('libraries', [])
    if not isinstance(pins, list) or len(pins) > 32:
        raise ValueError('A project can contain up to 32 Integration Library pins.')
    if not pins:
        return Project.model_validate(payload)
    return Project.model_validate({**payload, 'libraries': [
        resolve_pin(pin, payload.get('id', '')).model_dump() for pin in pins
    ]})


def asset_id(alias: str, identity: str) -> str:
    return f'{PREFIX}{alias}--{identity}'


def setting_key(alias: str, key: str) -> str:
    return f'library.{alias}.{key}'


def normalize_project_references(project: Project) -> None:
    """Store stable identifiers for references to installed public assets."""
    schema_ids = {asset.id for asset in project.schemas}
    schema_names = {asset.name: asset.id for asset in project.schemas if asset.library_origin and asset.name not in schema_ids}

    def normalize(value, field=''):
        if isinstance(value, dict):
            for key, child in value.items():
                value[key] = normalize(child, key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                value[index] = normalize(child, field)
        elif isinstance(value, str):
            category = asset_category(field)
            if category == 'tasks':
                target = find_subtask(project.tasks, value.strip())
                if target and target.library_origin:
                    return target.id
            elif category == 'schemas':
                return schema_names.get(value, value)
        return value

    for config in configs([task for task in project.tasks if not task.library_origin],
                          [resource for resource in project.resources if not resource.library_origin]):
        normalize(config)


def pinned_project(project: Project, pins: list[LibraryPin]) -> Project:
    project = project.model_copy(deep=True)
    normalize_project_references(project)
    payload = project.model_dump()
    payload['libraries'] = [pin.model_dump() for pin in pins]
    for category in ASSETS:
        payload[category] = [asset for asset in payload[category] if not asset.get('library_origin')]
    payload['process'] = None
    return Project.model_validate(payload)


def materialize(project: Project) -> None:
    for category in ASSETS:
        setattr(project, category, [asset for asset in getattr(project, category) if not asset.library_origin])
    used_aliases = set()
    for pin in project.libraries:
        if pin.alias in used_aliases:
            raise ValueError(f'Library alias {pin.alias!r} is already in use.')
        used_aliases.add(pin.alias)
        release = LibraryRelease.model_validate(pin.library)
        if digest(release) != pin.sha256:
            raise ValueError(f'Library {pin.alias!r} does not match its pinned checksum.')
        details = pin_info(pin)
        ids = {category: {asset.id: asset_id(pin.alias, asset.id) for asset in getattr(release, category)}
               for category in ASSETS}
        schema_names = {schema.name: ids['schemas'][schema.id] for schema in release.schemas}
        scope = f'Libraries/{pin.alias}'
        task_activities = {
            task.id: {activity.id: 'lib-' + hashlib.sha256(
                f'{ids["tasks"][task.id]}/{activity.id}'.encode()).hexdigest()[:20]
                for activity in task.activities}
            for task in release.tasks
        }

        def rewrite(value: Any, active: dict[str, str], field: str = '') -> Any:
            if isinstance(value, dict):
                return {key: rewrite(child, active, key) for key, child in value.items()}
            if isinstance(value, list):
                return [rewrite(child, active, field) for child in value]
            if not isinstance(value, str):
                return value
            category = asset_category(field)
            if category == 'tasks':
                value = ids['tasks'].get(value, value)
            elif category == 'resources':
                value = ids['resources'].get(value, value)
            elif category == 'schemas':
                value = ids['schemas'].get(value, schema_names.get(value, value))
            def reference(match):
                parts = match[1].split('.')
                if parts[0] == 'properties':
                    return '${properties.' + setting_key(pin.alias, '.'.join(parts[1:])) + '}'
                if parts[0] == 'tasks' and len(parts) >= 2:
                    if len(parts) >= 4 and parts[2] == 'activities':
                        parts[3] = task_activities.get(parts[1], {}).get(parts[3], parts[3])
                    parts[1] = ids['tasks'].get(parts[1], parts[1])
                elif parts[0] == 'activities' and len(parts) >= 2:
                    parts[1] = active.get(parts[1], parts[1])
                elif parts[0] not in ('last', 'input', 'vars', 'context', 'attributes'):
                    parts[0] = active.get(parts[0], parts[0])
                return '${' + '.'.join(parts) + '}'
            return REFERENCE.sub(reference, value)

        for category in ASSETS:
            collection = getattr(project, category)
            existing = {asset.id.casefold() for asset in collection}
            for original in getattr(release, category):
                identity = ids[category][original.id]
                if identity.casefold() in existing:
                    raise ValueError(f'Library {pin.alias!r} conflicts with an existing asset identifier.')
                asset = original.model_copy(deep=True)
                asset.id = identity
                asset.package_path = f'{scope}/{asset.package_path}'
                asset.library_origin = {**details, 'public': original.id in release.exports.get(category, [])}
                if category == 'tasks':
                    activity_ids = task_activities[original.id]
                    aliases = {**{activity.name: activity_ids[activity.id] for activity in asset.activities}, **activity_ids}
                    for activity in asset.activities:
                        activity.id = activity_ids[activity.id]
                        activity.config = rewrite(activity.config, aliases)
                    for group in asset.groups:
                        group.config = rewrite(group.config, aliases)
                        group.member_activity_ids = [activity_ids[key] for key in group.member_activity_ids]
                    for edge in asset.transitions:
                        edge.condition = rewrite(edge.condition, aliases)
                        edge.source, edge.target = activity_ids[edge.source], activity_ids[edge.target]
                        if edge.bw_xpath and 'variables' in edge.bw_xpath:
                            edge.bw_xpath['variables'] = {
                                key: aliases.get(value, value) if isinstance(value, str) else value
                                for key, value in edge.bw_xpath['variables'].items()
                            }
                    asset.input_schema = rewrite(asset.input_schema, aliases)
                    asset.output_schema = rewrite(asset.output_schema, aliases)
                elif category == 'resources':
                    asset.config = rewrite(asset.config, {})
                else:
                    asset.source_path = f'{scope}/{relative_schema_path(asset.source_path or asset.name)}'
                    asset.name = f'{scope}/{relative_schema_path(asset.name)}'
                    if document := data_format_document(asset):
                        asset.content = canonical(rewrite(document, {})).decode('utf-8')
                collection.append(asset)
        for profile in project.properties.values():
            existing = {item.key: index for index, item in enumerate(profile)}
            for setting in release.settings:
                key = setting_key(pin.alias, setting.key)
                if key not in existing:
                    profile.append(EnvironmentProperty(key=key, data_type=setting.data_type))
                else:
                    index = existing[key]
                    if profile[index].data_type != setting.data_type:
                        profile[index] = EnvironmentProperty(key=key, value=profile[index].value, data_type=setting.data_type)


def unbound_settings(project: Project, environment: str, task_id: str | None = None) -> list[str]:
    values = {value.key: value.value for value in project.properties.get(environment, [])}
    tasks = {task.id: task for task in project.tasks}
    selected = set(tasks) if task_id is None else ({task_id} if task_id in tasks else set())
    pending = list(selected) if task_id else []
    while pending:
        for activity in tasks[pending.pop()].activities:
            if activity.type != 'call_task':
                continue
            for field in ('taskId', 'dynamicTaskId'):
                reference = str(activity.config.get(field) or '')
                if match := PROPERTY.fullmatch(reference):
                    reference = str(values.get(match[1]) or '')
                target = find_subtask(project.tasks, reference.strip())
                if target and target.id not in selected:
                    selected.add(target.id)
                    pending.append(target.id)
    selected_tasks = [tasks[key] for key in sorted(selected)]
    available = {'resources': {resource.id: resource for resource in project.resources},
                 'schemas': {key: schema for schema in project.schemas for key in (schema.name, schema.id)}}
    used = {'resources': {}, 'schemas': {}}
    documents = []
    pending_configs = list(configs(selected_tasks, []))
    while pending_configs:
        for key, value in strings(pending_configs.pop()):
            category = asset_category(key)
            if category not in available:
                continue
            if match := PROPERTY.fullmatch(value):
                value = str(values.get(match[1]) or '')
            asset = available[category].get(value)
            if not asset or asset.id in used[category]:
                continue
            used[category][asset.id] = asset
            if category == 'resources':
                pending_configs.append(asset.config)
            elif document := data_format_document(asset):
                documents.append(document)
                pending_configs.append(document)
    refs = property_keys(selected_tasks, used['resources'].values(), documents)
    return [key for pin in project.libraries for item in pin.library.get('settings', [])
            if item.get('required', True) and (key := setting_key(pin.alias, item['key'])) in refs
            and values.get(key) in (None, '')]


def broken_exports(previous: LibraryRelease, current: LibraryRelease) -> list[str]:
    changes = []
    def contracts(release):
        assets = {item.id: item for item in release.schemas}
        paths = {relative_schema_path(item.source_path or item.name): item.id for item in release.schemas}
        names = {item.name: item.id for item in release.schemas}

        def closure(roots):
            pending = list(roots)
            bodies = {}
            while pending:
                identity = pending.pop()
                if identity not in assets or identity in bodies:
                    continue
                asset = assets[identity]
                source = relative_schema_path(asset.source_path or asset.name)
                bodies[identity] = (source, asset.content)
                pending.extend(resolved_schema_reference(ref, source, paths, names) for ref in schema_references(asset.content))
                if document := data_format_document(asset):
                    selector = document['dataFormat'].get('schemaId')
                    if isinstance(selector, str):
                        pending.append(selector if selector in assets else names.get(selector))
            return bodies

        def task_contract(task):
            boundary = sorted(
                (activity.type, str(activity.config.get('interfaceSchemaId') or ''), str(activity.config.get('interfaceSchemaText') or ''))
                for activity in task.activities if activity.type in ('start', 'end')
            )
            schema_ids = []
            for _, selector, text in boundary:
                if selector in assets or selector in names:
                    schema_ids.append(selector if selector in assets else names[selector])
                else:
                    schema_ids.extend(resolved_schema_reference(ref, '', paths, names) for ref in schema_references(text))
            return task.input_schema, task.output_schema, boundary, closure(schema_ids)

        return {'tasks': task_contract, 'resources': lambda item: item.type, 'schemas': lambda item: closure([item.id])}

    old_contracts, new_contracts = contracts(previous), contracts(current)
    for category in ASSETS:
        incoming = {item.id: item for item in getattr(current, category) if item.id in current.exports.get(category, [])}
        for old in getattr(previous, category):
            if old.id not in previous.exports.get(category, []):
                continue
            item = incoming.get(old.id)
            if not item:
                changes.append(f'{old.name} was removed from {category}.')
            elif old_contracts[category](old) != new_contracts[category](item):
                changes.append(f'{old.name} has a changed {category} contract.')
    old_settings = {item.key: (item.data_type, item.required) for item in previous.settings}
    for item in current.settings:
        if old_settings.get(item.key) != (item.data_type, item.required) and (item.required or item.key in old_settings):
            changes.append(f'{item.key} has a new or changed binding.')
    return changes


def validate_project_references(project: Project, previous: Project | None = None) -> None:
    normalize_project_references(project)
    available = {category: {asset.id: asset for asset in getattr(project, category)} for category in ASSETS}
    values: dict[str, set[str]] = {}
    for profile in project.properties.values():
        for item in profile:
            if isinstance(item.value, str) and item.value:
                values.setdefault(item.key, set()).add(item.value)
    tasks = [task for task in project.tasks if not task.library_origin]
    resources = [resource for resource in project.resources if not resource.library_origin]
    for config in configs(tasks, resources):
        for field, value in strings(config):
            category = asset_category(field)
            if not category:
                continue
            selectors = values.get(match[1], ()) if (match := PROPERTY.fullmatch(value)) else (value,)
            for reference in selectors:
                reference = reference.strip()
                if category == 'tasks':
                    target = find_subtask((previous or project).tasks, reference)
                    if target and target.library_origin:
                        if reference != target.id and previous and match:
                            current = find_subtask(project.tasks, reference)
                            if not current or current.id != target.id:
                                raise ValueError(f'Update the library task name used by {match[1]} to the stable task ID {target.id}.')
                        reference = target.id
                if not reference.startswith(PREFIX):
                    continue
                asset = available[category].get(reference)
                if not asset or (asset.library_origin and not asset.library_origin['public']):
                    raise ValueError(f'Project references an unavailable library asset: {reference}.')


def catalog_location():
    from .store import DATA_DIR
    return DATA_DIR / 'libraries'


def catalog() -> list[LibraryRelease]:
    stored = [LibraryRelease.model_validate_json(path.read_bytes())
              for path in sorted(catalog_location().glob('*/*.json'))]
    return [*sample_libraries(), *stored]


def catalog_release(identity: str, version: str) -> LibraryRelease | None:
    if not re.fullmatch(IDENTITY, identity) or not re.fullmatch(VERSION, version):
        return None
    for release in sample_libraries():
        if (release.id, release.version) == (identity, version):
            return release
    path = catalog_location() / identity / f'{version}.json'
    return LibraryRelease.model_validate_json(path.read_bytes()) if path.is_file() else None


def save_release(release: LibraryRelease) -> LibraryRelease:
    from .store import STORE_LOCK, write_json
    payload = release.model_dump(mode='json')
    if len(canonical(payload)) > MAX_LIBRARY_BYTES:
        raise ValueError('Integration Library exceeds the maximum size.')
    with STORE_LOCK:
        previous = catalog_release(release.id, release.version)
        if previous:
            if digest(previous) != digest(release):
                raise ValueError('This library version already exists with different content. Publish a new version.')
            return previous
        write_json(catalog_location() / release.id / f'{release.version}.json', payload)
    return release


def sample_libraries() -> list[LibraryRelease]:
    def task(identity, name, activities, fields):
        return {
            'id': identity, 'name': name, 'kind': 'subtask',
            'input_schema': {'type': 'object', 'properties': {field: {'type': 'string'} for field in fields}},
            'output_schema': {'type': 'object', 'properties': {field: {'type': 'string'} for field in fields}},
            'activities': activities,
            'transitions': [{'id': f'edge-{index}', 'source': left['id'], 'target': right['id']}
                            for index, (left, right) in enumerate(zip(activities, activities[1:]))],
        }

    def node(identity, name, kind, x, config=None):
        return {'id': identity, 'name': name, 'type': kind, 'position': {'x': x, 'y': 120}, 'config': config or {}}

    log_fields = ('message', 'correlationId')
    fault_fields = ('code', 'message', 'correlationId')
    logging = task('write-log', 'WriteLog', [
        node('Ops-Log-Start', 'Ops-Log-Start', 'start', 70),
        node('Ops-Log-Write', 'Ops-Log-Write', 'log', 300, {
            'operation': 'write', 'level': 'INFO', 'includePayload': False,
            'inputMappings': {'message': '${input.message}'},
        }),
        node('Ops-Log-End', 'Ops-Log-End', 'end', 530),
    ], log_fields)
    fault = task('handle-exception', 'HandleException', [
        node('Ops-Fault-Start', 'Ops-Fault-Start', 'start', 70),
        node('Ops-Fault-Log', 'Ops-Fault-Log', 'log', 300, {
            'operation': 'write', 'level': 'ERROR', 'includePayload': False,
            'inputMappings': {'message': '${input.message}'},
        }),
        node('Ops-Fault-End', 'Ops-Fault-End', 'end', 530, {
            'inputMappings': {f'result.{field}': '${input.' + field + '}' for field in fault_fields},
        }),
    ], fault_fields)
    return [
        LibraryRelease(id='operations', name='Operations', version='1.0.0',
                       description='Structured logging and a callable exception handler.',
                       tasks=[logging, fault], exports={'tasks': ['write-log', 'handle-exception'], 'schemas': ['fault-contract']},
                       schemas=[{'id': 'fault-contract', 'name': 'Fault.xsd', 'content':
                           '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
                           '<xs:element name="Fault"><xs:complexType><xs:sequence>'
                           '<xs:element name="code" type="xs:string"/><xs:element name="message" type="xs:string"/>'
                           '<xs:element name="correlationId" type="xs:string"/></xs:sequence></xs:complexType></xs:element>'
                           '</xs:schema>'}]),
        LibraryRelease(id='enterprise-connections', name='Enterprise Connections', version='1.0.0',
                       description='Reusable database and messaging connection definitions for local qualification.',
                       resources=[
                           {'id': 'database', 'type': 'jdbc', 'name': 'Database', 'config': {
                               'driver': 'sqlite', 'url': '${properties.database-path}'}},
                           {'id': 'ems-memory', 'type': 'ems', 'name': 'Local-EMS', 'config': {'mode': 'memory'}},
                       ], exports={'resources': ['database', 'ems-memory']},
                       settings=[{'key': 'database-path', 'data_type': 'string', 'required': True}]),
    ]
