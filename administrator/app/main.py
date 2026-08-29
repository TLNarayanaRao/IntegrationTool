import json
import os
import re
import shutil
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DATA_DIR = Path(os.environ.get('FABRIC_ADMIN_DATA_DIR', Path(__file__).parents[1] / 'data')).expanduser().resolve()
PACKAGES_DIR = DATA_DIR / 'packages'
DEPLOYMENTS_FILE = DATA_DIR / 'deployments.json'

app = FastAPI(title='Integration Fabric Enterprise Administrator', version='0.1.0')

def now() -> str: return datetime.now(timezone.utc).isoformat()

def read_json(path: Path, default):
    if not path.exists(): return default
    return json.loads(path.read_text(encoding='utf-8'))

def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)

def safe(value: str) -> str:
    result = re.sub(r'[^A-Za-z0-9_.-]+', '-', value).strip('-')
    if not result: raise HTTPException(400, 'Invalid identifier')
    return result

def packages():
    output = []
    if not PACKAGES_DIR.exists(): return output
    for descriptor in PACKAGES_DIR.glob('*/*/manifest.json'):
        manifest = read_json(descriptor, {})
        manifest['packageId'] = f"{manifest.get('artifact', descriptor.parents[1].name)}:{manifest.get('version', descriptor.parent.name)}"
        manifest['receivedAt'] = datetime.fromtimestamp(descriptor.stat().st_mtime, timezone.utc).isoformat()
        output.append(manifest)
    return sorted(output, key=lambda value: value.get('receivedAt', ''), reverse=True)

class DeploymentRequest(BaseModel):
    package_id: str = Field(alias='packageId')
    environment: str = 'production'
    machine: str = 'localhost'
    instances: int = Field(default=1, ge=1, le=100)

@app.get('/api/health')
def health(): return {'status': 'ok', 'component': 'enterprise-administrator'}

@app.get('/api/packages')
def list_packages(): return packages()

@app.post('/api/packages')
async def upload_package(file: UploadFile = File(...)):
    body = await file.read()
    try:
        memory = __import__('io').BytesIO(body)
        if body[:2] == b'PK':
            with zipfile.ZipFile(memory) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                members = [(member.filename, lambda member=member: archive.read(member)) for member in archive.infolist() if not member.is_dir()]
                if manifest.get('format') != 'integration-fabric-deployment': raise ValueError('Not a deployment package')
                artifact, version = safe(manifest['artifact']), safe(manifest['version'])
                destination = PACKAGES_DIR / artifact / version
                if destination.exists(): shutil.rmtree(destination)
                for name, reader in members:
                    target = (destination / name).resolve()
                    if destination.resolve() not in target.parents: raise ValueError('Package contains an unsafe path')
                    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(reader())
        else:
            with tarfile.open(fileobj=memory, mode='r:*') as archive:
                descriptor = archive.extractfile('manifest.json')
                if not descriptor: raise ValueError('manifest.json is missing')
                manifest = json.load(descriptor)
                if manifest.get('format') != 'integration-fabric-deployment': raise ValueError('Not a deployment package')
                artifact, version = safe(manifest['artifact']), safe(manifest['version'])
                destination = PACKAGES_DIR / artifact / version
                if destination.exists(): shutil.rmtree(destination)
                for member in archive.getmembers():
                    if not member.isfile(): continue
                    target = (destination / member.name).resolve()
                    if destination.resolve() not in target.parents: raise ValueError('Package contains an unsafe path')
                    source = archive.extractfile(member)
                    if source: target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(source.read())
    except Exception as exc:
        raise HTTPException(400, f'Invalid Integration Fabric deployment package: {exc}') from exc
    return {**manifest, 'packageId': f'{artifact}:{version}'}

@app.get('/api/deployments')
def list_deployments(): return read_json(DEPLOYMENTS_FILE, [])

@app.post('/api/deployments')
def create_deployment(request: DeploymentRequest):
    available = {item['packageId']: item for item in packages()}
    if request.package_id not in available: raise HTTPException(404, 'Package not found')
    deployments = read_json(DEPLOYMENTS_FILE, [])
    item = {
        'id': str(uuid4()), 'packageId': request.package_id,
        'application': available[request.package_id].get('applicationName'),
        'environment': request.environment, 'machine': request.machine,
        'instances': request.instances, 'state': 'DEPLOYED',
        'updatedAt': now(), 'message': 'Ready to start through a registered runtime agent.'
    }
    deployments.append(item); write_json(DEPLOYMENTS_FILE, deployments)
    return item

@app.post('/api/deployments/{deployment_id}/{action}')
def lifecycle(deployment_id: str, action: str):
    states = {'start': 'RUNNING', 'stop': 'STOPPED', 'restart': 'RUNNING', 'kill': 'STOPPED', 'undeploy': 'UNDEPLOYED'}
    if action not in states: raise HTTPException(400, 'Unsupported lifecycle action')
    deployments = read_json(DEPLOYMENTS_FILE, [])
    item = next((value for value in deployments if value['id'] == deployment_id), None)
    if not item: raise HTTPException(404, 'Deployment not found')
    item.update(state=states[action], updatedAt=now(), message=f'{action.title()} accepted by the Administrator control plane.')
    write_json(DEPLOYMENTS_FILE, deployments)
    return item

static_candidates = [
    Path(os.environ['FABRIC_ADMIN_WEB']) if os.environ.get('FABRIC_ADMIN_WEB') else None,
    Path(getattr(sys, '_MEIPASS', '')) / 'web' if getattr(sys, '_MEIPASS', None) else None,
    Path(__file__).parents[1] / 'web',
]
WEB_DIR = next((candidate for candidate in static_candidates if candidate and candidate.exists()), None)
if WEB_DIR:
    app.mount('/', StaticFiles(directory=WEB_DIR, html=True), name='administrator')
