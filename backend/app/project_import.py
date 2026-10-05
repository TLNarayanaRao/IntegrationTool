"""Bounded project-package reading; importing never extracts archive members."""
import io
import json
import os
import zipfile


MAX_IMPORT_BYTES = int(os.environ.get('MINA_MAX_IMPORT_MB', '64')) * 1024 * 1024
MAX_IMPORT_FILES = 10000


def project_payload(raw: bytes) -> bytes:
    if len(raw) > MAX_IMPORT_BYTES: raise ValueError('Project upload exceeds the configured size limit')
    if raw[:2] != b'PK': return raw
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
        manifest = json.loads(read('manifest.json'))
        if not isinstance(manifest, dict): raise ValueError('Project manifest must be an object')
        package_format = manifest.get('format')
        if package_format in {'mina-project', 'integration-fabric-project'}: return read('project.json')
        if package_format in {'mina-deployment', 'integration-fabric-deployment'}: return read('application/project.json')
        raise ValueError('Unsupported project package')
