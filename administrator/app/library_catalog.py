"""Read the portable library envelope without loading Studio or application code."""
import hashlib
import io
import json
import re
from zipfile import ZipFile

MAX_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_BYTES + 64 * 1024
IDENTITY = re.compile(r'[a-z][a-z0-9-]{0,47}')
VERSION = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)')


def describe(body: bytes) -> dict:
    if len(body) > MAX_ARCHIVE_BYTES:
        raise ValueError('Integration Library exceeds the maximum size.')
    with ZipFile(io.BytesIO(body)) as archive:
        files = archive.infolist()
        names = sorted(member.filename for member in files)
        if names not in (['library.json', 'manifest.json'], ['library.aes', 'manifest.json']):
            raise ValueError('Invalid Integration Library archive contents.')
        sizes = {member.filename: member.file_size for member in files}
        if sizes.get('library.json', 0) > MAX_BYTES or sizes.get('library.aes', 0) > MAX_ARCHIVE_BYTES or sizes['manifest.json'] > 4096:
            raise ValueError('Integration Library exceeds the maximum uncompressed size.')
        manifest = json.loads(archive.read('manifest.json'))
        protected = 'library.aes' in sizes
        if not isinstance(manifest, dict) or manifest.get('format') != 'mina-integration-library' or type(manifest.get('formatVersion')) is not int or manifest['formatVersion'] != (2 if protected else 1):
            raise ValueError('Unsupported Integration Library format.')
        if protected:
            payload = archive.read('library.aes')
            checksum = manifest.get('sha256')
            if (not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum)
                    or len(payload) < 28 or manifest.get('ciphertextSha256') != hashlib.sha256(payload).hexdigest()):
                raise ValueError('Protected Integration Library checksum did not match.')
            library = manifest
        else:
            payload = archive.read('library.json')
            checksum = hashlib.sha256(payload).hexdigest()
            if manifest.get('sha256') != checksum:
                raise ValueError('Integration Library checksum did not match.')
            library = json.loads(payload)
            if not isinstance(library, dict):
                raise ValueError('Invalid Integration Library descriptor.')
            if json.dumps(library, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8') != payload:
                raise ValueError('Integration Library descriptor differs from the published format.')
    identity, version = library.get('id'), library.get('version')
    if not isinstance(identity, str) or not IDENTITY.fullmatch(identity) or not isinstance(version, str) or len(version) > 32 or not VERSION.fullmatch(version):
        raise ValueError('Invalid Integration Library ID or version.')
    name, description = library.get('name'), library.get('description', '')
    if not isinstance(name, str) or not 1 <= len(name) <= 120 or not isinstance(description, str) or len(description) > 2000:
        raise ValueError('Invalid Integration Library display metadata.')
    return {'id': identity, 'version': version, 'name': name, 'description': description, 'sha256': checksum,
            'protected': protected}
