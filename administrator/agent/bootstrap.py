"""Verify and unpack one Python deployment inside an isolated work directory."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_BYTES = 250 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_FILES = 10000


def extract_python_package(body: bytes, destination: Path, expected_sha256: str = '') -> dict:
    if len(body) > MAX_ARCHIVE_BYTES:
        raise ValueError('Python package exceeds the agent archive size limit')
    digest = hashlib.sha256(body).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ValueError('Python package digest mismatch')
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(body)) as bundle:
        members = [member for member in bundle.infolist() if not member.is_dir()]
        if len(members) > MAX_FILES or sum(member.file_size for member in members) > MAX_EXPANDED_BYTES:
            raise ValueError('Python package exceeds the agent expansion limit')
        names: set[str] = set()
        for member in members:
            raw = member.filename.replace('\\', '/')
            path = PurePosixPath(raw)
            if not raw or path.is_absolute() or '..' in path.parts or ':' in path.parts[0]:
                raise ValueError(f'Unsafe Python package path: {raw}')
            if raw in names: raise ValueError(f'Duplicate Python package path: {raw}')
            names.add(raw)
            if raw.startswith('application/') and not raw.endswith('.py'):
                raise ValueError(f'Raw Python application contains a non-Python file: {raw}')
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f'Symbolic links are not allowed in a Python package: {raw}')
        if 'manifest.json' not in names or 'application/main.py' not in names:
            raise ValueError('Python package is missing its manifest or entry point')
        manifest = json.loads(bundle.read('manifest.json'))
        if (manifest.get('pythonSource') or {}).get('entrypoint') != 'application/main.py':
            raise ValueError('The package is not a Raw Python deployment')
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.filename.replace('\\', '/')).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(member))
    return manifest


def main() -> int:
    base = os.environ['FABRIC_CONTROL_PLANE_URL'].rstrip('/')
    plane_id = os.environ['FABRIC_DATA_PLANE_ID']
    deployment_id = os.environ['FABRIC_DEPLOYMENT_ID']
    credential_file = Path(os.environ['FABRIC_AGENT_KEY_FILE'])
    key = credential_file.read_text(encoding='utf-8').strip()
    request = urllib.request.Request(
        f'{base}/api/data-planes/{plane_id}/agent/deployments/{deployment_id}/package',
        headers={'x-control-plane-key': key},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        digest = response.headers.get('x-fabric-package-sha256', '')
        body = response.read(MAX_ARCHIVE_BYTES + 1)
    manifest = extract_python_package(body, Path(os.environ.get('FABRIC_APPLICATION_WORKDIR', '/work')), digest)
    if manifest.get('applicationId') != os.environ.get('FABRIC_APPLICATION_ID'):
        raise ValueError('Package application identity does not match the deployment')
    print(f"Python application staged: {manifest.get('applicationName')}", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
