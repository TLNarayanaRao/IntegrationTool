"""Deploy the synthetic EAR to a temporary loopback Control Plane and test it."""

import argparse
import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def wait_until_ready(url, process, headers=None):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Control Plane exited with code {process.returncode}')
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=2)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            time.sleep(.2)
    raise RuntimeError(f'Endpoint did not become ready: {url}')


def check_fixture(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        if (manifest.get('applicationId'), manifest.get('target'), manifest.get('environment')) != ('mina-ear-qa', 'on-prem', 'qa'):
            raise ValueError('Temporary QA requires the synthetic fixtures/ear-qa.json EAR in the qa profile')
        if b'synthetic-placeholder' in archive.read('application/project.json'):
            raise ValueError('The fixture password was not redacted by the EAR builder')


def smoke(artifact_dir: Path) -> None:
    archives = sorted(artifact_dir.glob('*.ear'))
    if len(archives) != 1:
        raise ValueError('Expected exactly one EAR in the artifact directory')
    check_fixture(archives[0])
    owner_key, password = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    admin_port, flow_port = unused_port(), unused_port()
    while flow_port == admin_port:
        flow_port = unused_port()
    control_plane = f'http://127.0.0.1:{admin_port}'
    flow = f'http://127.0.0.1:{flow_port}/mina/ear-qa'
    worker = ROOT / 'backend/run_deployment.py'
    auth = {'X-Admin-Key': owner_key}
    with tempfile.TemporaryDirectory(prefix='mina-ear-qa-') as temporary:
        work = Path(temporary)
        deployment_id = work / 'deployment-id'
        environment = {
            **os.environ,
            'PYTHONPATH': os.pathsep.join([str(ROOT), str(ROOT / 'backend')]),
            'MINA_ADMIN_DATA_DIR': str(work / 'control-plane'),
            'MINA_DATA_DIR': str(work / 'runtime'),
            'MINA_ADMIN_API_KEY': owner_key,
            'MINA_ADMIN_SECRET_KEY': secrets.token_urlsafe(32),
            'MINA_ADMIN_RUNTIME_COMMAND': f'"{sys.executable}" "{worker}" --application "{{application}}" --environment "{{environment}}"',
            'MINA_CONTROL_PLANE_URL': control_plane,
            'MINA_CONTROL_PLANE_KEY': owner_key,
            'MINA_DATA_PLANE': 'localhost',
            'MINA_NAMESPACE': 'default',
            'MINA_TEAM_ID': '',
            'MINA_CONFIG_FILE': (ROOT / 'scripts/linux/mina-control-plane.ini').as_posix(),
            'MINA_PYTHON': sys.executable,
            'MINA_DEPLOYMENT_ID_FILE': deployment_id.as_posix(),
            'MINA_DEPLOYMENT_SECRETS_JSON': json.dumps({'qa.port': str(flow_port), 'qa.password': password}),
        }
        log = work / 'control-plane.log'
        with log.open('wb') as out, subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'administrator.app.main:app', '--host', '127.0.0.1', '--port', str(admin_port)],
            cwd=ROOT, env=environment, stdout=out, stderr=subprocess.STDOUT,
        ) as server:
            try:
                with wait_until_ready(control_plane + '/api/capabilities?dataPlaneId=localhost', server, auth) as reply:
                    capabilities = json.load(reply)
                capability = next((item for item in capabilities if item.get('type') == 'integration-runtime'
                                   and item.get('namespace') == 'default'), None)
                if not capability:
                    raise RuntimeError('No Integration Runtime capability was provisioned for the QA worker')
                environment['MINA_CAPABILITY_ID'] = capability['id']
                subprocess.run(['bash', 'scripts/ci/deploy-ear.sh', artifact_dir.as_posix(), 'qa'],
                               cwd=ROOT, env=environment, check=True, timeout=240)
                authorization = 'Basic ' + base64.b64encode(f'mina-qa:{password}'.encode()).decode()
                with wait_until_ready(flow, server, {'Authorization': authorization}) as result:
                    if result.status != 200 or json.load(result) != {'result': 'mina-ear-qa-ok'}:
                        raise RuntimeError('The deployed flow returned an unexpected response')
                try:
                    with urllib.request.urlopen(flow, timeout=4):
                        raise RuntimeError('The deployed flow allowed an unauthenticated request')
                except urllib.error.HTTPError as error:
                    if error.code != 401:
                        raise
                print('Verified EAR deployment, authenticated flow response, and HTTP 401 without credentials.')
            finally:
                try:
                    if deployment_id.is_file():
                        identifier = deployment_id.read_text(encoding='utf-8').strip()
                        request = urllib.request.Request(f'{control_plane}/api/deployments/{identifier}/stop', headers=auth, method='POST')
                        with urllib.request.urlopen(request, timeout=10):
                            pass
                finally:
                    if server.poll() is None:
                        server.terminate()
                        server.wait(timeout=15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact_dir', type=Path)
    smoke(parser.parse_args().artifact_dir.resolve())
