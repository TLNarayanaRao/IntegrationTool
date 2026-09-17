"""Reconcile Raw Python applications onto a local host or Kubernetes cluster."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .bootstrap import extract_python_package, MAX_ARCHIVE_BYTES

LOG = logging.getLogger('integrationfabric.agent')


@dataclass(frozen=True)
class Settings:
    control_plane_url: str
    key: str
    plane_id: str
    mode: str = 'local'
    state_dir: Path = Path('agent-state')
    image: str = 'integration-fabric-python-agent:latest'
    poll_seconds: float = 5.0
    namespaces: tuple[str, ...] = ('default',)

    @classmethod
    def from_environment(cls) -> 'Settings':
        return cls(
            control_plane_url=os.environ['FABRIC_CONTROL_PLANE_URL'].rstrip('/'),
            key=os.environ['FABRIC_AGENT_KEY'],
            plane_id=os.environ['FABRIC_DATA_PLANE_ID'],
            mode=os.environ.get('FABRIC_AGENT_MODE', 'local').lower(),
            state_dir=Path(os.environ.get('FABRIC_AGENT_STATE_DIR', 'agent-state')).resolve(),
            image=os.environ.get('FABRIC_PYTHON_RUNTIME_IMAGE', 'integration-fabric-python-agent:latest'),
            poll_seconds=max(1.0, float(os.environ.get('FABRIC_AGENT_POLL_SECONDS', '5'))),
            namespaces=tuple(value.strip() for value in os.environ.get('FABRIC_AGENT_NAMESPACES', 'default').split(',') if value.strip()),
        )


class PythonAgent:
    def __init__(self, settings: Settings):
        if settings.mode not in {'local', 'kubernetes'}: raise ValueError('Agent mode must be local or kubernetes')
        self.settings = settings
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.AsyncClient(base_url=settings.control_plane_url, timeout=httpx.Timeout(120.0, connect=15.0),
                                        headers={'x-control-plane-key': settings.key})
        self.processes: dict[str, list[subprocess.Popen]] = {}
        self.local_revisions: dict[str, str] = {}
        self._k8s = None

    async def close(self):
        await self.client.aclose()
        for deployment_id in list(self.processes): self._stop_local(deployment_id)

    def _endpoint(self, suffix: str) -> str:
        return f'/api/data-planes/{self.settings.plane_id}{suffix}'

    async def _request(self, method: str, path: str, **kwargs):
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    async def _report(self, item: dict, *, state: str, message: str, health: str, instances: list[dict] | None = None,
                      logs: list[dict] | None = None):
        payload = {'state': state, 'message': message, 'instances': instances or [],
                   'health': {'status': health, 'message': message}}
        if logs is not None: payload['logs'] = logs
        await self._request('POST', self._endpoint(f'/agent/deployments/{item["id"]}/report'), json=payload)

    async def _heartbeat(self):
        system: dict[str, Any] = {}
        try:
            import psutil
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(str(self.settings.state_dir))
            system = {
                'cpuPercent': psutil.cpu_percent(interval=None),
                'memoryPercent': memory.percent,
                'memoryUsedBytes': memory.used,
                'memoryAvailableBytes': memory.available,
                'memoryTotalBytes': memory.total,
                'diskPercent': disk.percent,
                'diskFreeBytes': disk.free,
                'loadAverage': os.getloadavg()[0] if hasattr(os, 'getloadavg') else None,
                'processCount': sum(1 for processes in self.processes.values() for process in processes if process.poll() is None),
            }
        except (ImportError, OSError, ValueError) as error:
            LOG.warning('Full host telemetry unavailable: %s', error)
            system = {'processCount': sum(1 for processes in self.processes.values() for process in processes if process.poll() is None)}
            try:
                disk = shutil.disk_usage(self.settings.state_dir)
                system.update(diskPercent=round((disk.total - disk.free) / disk.total * 100, 1) if disk.total else None,
                              diskFreeBytes=disk.free)
            except OSError:
                pass
        await self._request('POST', self._endpoint('/heartbeat'), json={
            'agentVersion': 'python-v1', 'runtimeVersion': sys.version.split()[0],
            **system, 'telemetry': {'system': system},
        })

    async def _package(self, item: dict) -> tuple[bytes, str]:
        response = await self._request('GET', self._endpoint(f'/agent/deployments/{item["id"]}/package'))
        body = response.content
        if len(body) > MAX_ARCHIVE_BYTES: raise ValueError('Deployment package exceeds agent size limit')
        digest = response.headers.get('x-fabric-package-sha256', '')
        if digest and hashlib.sha256(body).hexdigest() != digest: raise ValueError('Deployment package digest mismatch')
        return body, digest

    def _deployment_dir(self, deployment_id: str) -> Path:
        if not re.fullmatch(r'[A-Za-z0-9-]{8,80}', deployment_id): raise ValueError('Unsafe deployment identifier')
        directory = (self.settings.state_dir / deployment_id).resolve()
        if self.settings.state_dir not in directory.parents: raise ValueError('Deployment path escapes agent state directory')
        return directory

    def _stop_local(self, deployment_id: str):
        self.local_revisions.pop(deployment_id, None)
        for process in self.processes.pop(deployment_id, []):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)

    def _local_logs(self, deployment_id: str, count: int) -> list[dict]:
        directory = self._deployment_dir(deployment_id)
        output = []
        for index in range(1, count + 1):
            path = directory / f'instance-{index}.log'
            if not path.is_file(): continue
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 65536))
                lines = stream.read().decode('utf-8', errors='replace').splitlines()[-200:]
            output.append({'instanceId': f'{deployment_id[:8]}-{index}', 'lines': lines})
        return output

    async def _reconcile_local(self, item: dict):
        deployment_id = item['id']
        if item.get('state') not in {'RUNNING', 'DEPLOYED'} or (item.get('state') == 'DEPLOYED' and item.get('target') != 'cloud'):
            self._stop_local(deployment_id)
            return
        current = self.processes.get(deployment_id) or []
        revision = hashlib.sha256(json.dumps({
            'packageId': item.get('packageId'), 'environment': item.get('environment'),
            'secrets': item.get('secrets') or {}, 'starterStates': item.get('starterStates') or {},
            'instances': item.get('desiredInstances') or 1,
        }, sort_keys=True).encode()).hexdigest()
        if (current and self.local_revisions.get(deployment_id) == revision
                and all(process.poll() is None for process in current)
                and len(current) == int(item.get('desiredInstances') or 1)):
            await self._report(item, state='RUNNING', message='Python processes healthy', health='HEALTHY',
                               instances=[{'id': f'{deployment_id[:8]}-{index+1}', 'pid': process.pid, 'state': 'RUNNING'} for index, process in enumerate(current)],
                               logs=self._local_logs(deployment_id, len(current)))
            return
        self._stop_local(deployment_id)
        directory = self._deployment_dir(deployment_id)
        package, digest = await self._package(item)
        manifest = extract_python_package(package, directory, digest)
        if manifest.get('applicationId') != item.get('applicationId'):
            raise ValueError('Deployment application identity does not match package')
        secret_file = directory / '.deployment-secrets.json'
        secret_file.write_text(json.dumps(item.get('secrets') or {}), encoding='utf-8')
        if os.name != 'nt': secret_file.chmod(0o600)
        enabled = [task for task, state in (item.get('starterStates') or {}).items() if state != 'STOPPED']
        environment = {**os.environ, 'FABRIC_DEPLOYMENT_ID': deployment_id,
                       'FABRIC_ENVIRONMENT': item['environment'], 'FABRIC_SECRET_FILE': str(secret_file),
                       'FABRIC_ENABLED_STARTERS': json.dumps(enabled)}
        python = os.environ.get('FABRIC_PYTHON_EXECUTABLE') or sys.executable
        instances = []
        for index in range(max(1, int(item.get('desiredInstances') or 1))):
            log_file = directory / f'instance-{index+1}.log'
            with log_file.open('ab') as handle:
                flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' and hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                instances.append(subprocess.Popen([python, '-m', 'application.main', '--environment', item['environment']],
                                                  cwd=directory, env=environment, stdout=handle, stderr=subprocess.STDOUT,
                                                  creationflags=flags))
        self.processes[deployment_id] = instances
        self.local_revisions[deployment_id] = revision
        await asyncio.sleep(.25)
        failed = [process.returncode for process in instances if process.poll() is not None]
        if failed: raise RuntimeError(f'Python runtime exited during startup: {failed}')
        await self._report(item, state='RUNNING', message='Python application running', health='HEALTHY',
                           instances=[{'id': f'{deployment_id[:8]}-{index+1}', 'pid': process.pid, 'state': 'RUNNING'} for index, process in enumerate(instances)],
                           logs=self._local_logs(deployment_id, len(instances)))

    def _kubernetes(self):
        if self._k8s is None:
            try:
                from kubernetes import client, config
            except ImportError as error:
                raise RuntimeError('Kubernetes mode requires the kubernetes Python client') from error
            try: config.load_incluster_config()
            except config.ConfigException: config.load_kube_config()
            self._k8s = (client.CoreV1Api(), client.AppsV1Api())
        return self._k8s

    @staticmethod
    def _k8s_name(deployment_id: str) -> str:
        return 'fabric-' + re.sub(r'[^a-z0-9-]', '-', deployment_id.lower())[:50].strip('-')

    async def _reconcile_kubernetes(self, item: dict):
        from kubernetes.client.exceptions import ApiException
        core, apps = self._kubernetes()
        namespace = str(item.get('namespace') or '')
        if namespace not in self.settings.namespaces:
            raise ValueError(f'Namespace {namespace!r} is not permitted for this agent')
        name = self._k8s_name(item['id'])
        agent_secret_name, runtime_secret_name = f'{name}-agent', f'{name}-runtime'
        if item.get('state') in {'STOPPED', 'UNDEPLOYED'}:
            for method in (lambda: apps.delete_namespaced_deployment(name, namespace),
                           lambda: core.delete_namespaced_service(name, namespace),
                           lambda: core.delete_namespaced_secret(agent_secret_name, namespace),
                           lambda: core.delete_namespaced_secret(runtime_secret_name, namespace)):
                try: await asyncio.to_thread(method)
                except ApiException as error:
                    if error.status != 404: raise
            return
        if item.get('state') not in {'DEPLOYED', 'RUNNING'}: return
        if (item.get('pythonSource') or {}).get('entrypoint') != 'application/main.py': return
        labels = {'app.kubernetes.io/name': name, 'app.kubernetes.io/managed-by': 'integration-fabric-python-agent',
                  'integration-fabric-deployment': item['id']}
        secret_values = item.get('secrets') or {}
        def apply_secret(secret_name: str, values: dict):
            body = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': secret_name, 'namespace': namespace, 'labels': labels},
                    'type': 'Opaque', 'stringData': values}
            try: core.create_namespaced_secret(namespace, body)
            except ApiException as error:
                if error.status != 409: raise
                core.patch_namespaced_secret(secret_name, namespace, body)
        await asyncio.to_thread(apply_secret, agent_secret_name, {'agentKey': self.settings.key})
        await asyncio.to_thread(apply_secret, runtime_secret_name, {'secrets.json': json.dumps(secret_values)})
        enabled = [task for task, state in (item.get('starterStates') or {}).items() if state != 'STOPPED']
        common_env = [
            {'name': 'FABRIC_CONTROL_PLANE_URL', 'value': self.settings.control_plane_url},
            {'name': 'FABRIC_DATA_PLANE_ID', 'value': self.settings.plane_id},
            {'name': 'FABRIC_DEPLOYMENT_ID', 'value': item['id']},
            {'name': 'FABRIC_APPLICATION_ID', 'value': str(item.get('applicationId') or '')},
            {'name': 'FABRIC_ENVIRONMENT', 'value': item['environment']},
            {'name': 'FABRIC_ENABLED_STARTERS', 'value': json.dumps(enabled)},
        ]
        shared_mount = {'name': 'application', 'mountPath': '/work'}
        auth_mount = {'name': 'agent-credential', 'mountPath': '/run/fabric-agent', 'readOnly': True}
        runtime_mount = {'name': 'runtime-secrets', 'mountPath': '/run/fabric', 'readOnly': True}
        volumes = [{'name': 'application', 'emptyDir': {}},
                   {'name': 'agent-credential', 'secret': {'secretName': agent_secret_name}},
                   {'name': 'runtime-secrets', 'secret': {'secretName': runtime_secret_name}}]
        driver_mounts = []
        driver_pvc = os.environ.get('FABRIC_K8S_DRIVER_PVC', '').strip()
        if driver_pvc:
            volumes.append({'name': 'vendor-drivers', 'persistentVolumeClaim': {'claimName': driver_pvc}})
            driver_mounts.append({'name': 'vendor-drivers', 'mountPath': '/opt/integration-fabric/drivers', 'readOnly': True})
        pod = {'metadata': {'labels': labels}, 'spec': {
            'securityContext': {'runAsNonRoot': True, 'runAsUser': 10001, 'fsGroup': 10001},
            'volumes': volumes,
            'initContainers': [{'name': 'package-fetch', 'image': self.settings.image,
                                'command': ['python', '-m', 'administrator.agent.bootstrap'],
                                'env': common_env + [{'name': 'FABRIC_AGENT_KEY_FILE', 'value': '/run/fabric-agent/agentKey'},
                                                     {'name': 'FABRIC_APPLICATION_WORKDIR', 'value': '/work'}],
                                'volumeMounts': [shared_mount, auth_mount]}],
            'containers': [{'name': 'python-runtime', 'image': self.settings.image,
                            'command': ['python', '-m', 'application.main', '--environment', item['environment']],
                            'workingDir': '/work',
                            'env': common_env + [{'name': 'FABRIC_SECRET_FILE', 'value': '/run/fabric/secrets.json'},
                                                 {'name': 'PYTHONPATH', 'value': '/work:/opt/agent'}],
                            'volumeMounts': [shared_mount, runtime_mount, *driver_mounts],
                            'ports': [{'name': 'http', 'containerPort': 8787}],
                            'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'},
                                          'limits': {'cpu': '1', 'memory': '1Gi'}}}]}}
        revision = hashlib.sha256(json.dumps({'packageId': item['packageId'], 'secrets': secret_values,
                                              'starters': enabled, 'environment': item['environment']}, sort_keys=True).encode()).hexdigest()
        pod['metadata']['annotations'] = {'integration-fabric/revision': revision}
        body = {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': name, 'namespace': namespace, 'labels': labels},
                'spec': {'replicas': max(1, int(item.get('desiredInstances') or 1)),
                         'selector': {'matchLabels': {'integration-fabric-deployment': item['id']}}, 'template': pod}}
        def apply_deployment():
            try: apps.create_namespaced_deployment(namespace, body)
            except ApiException as error:
                if error.status != 409: raise
                apps.patch_namespaced_deployment(name, namespace, body)
            return apps.read_namespaced_deployment(name, namespace)
        deployed = await asyncio.to_thread(apply_deployment)
        service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name, 'namespace': namespace, 'labels': labels},
                   'spec': {'selector': {'integration-fabric-deployment': item['id']},
                            'ports': [{'name': 'http', 'port': 8787, 'targetPort': 'http'}]}}
        def apply_service():
            try: core.create_namespaced_service(namespace, service)
            except ApiException as error:
                if error.status != 409: raise
                core.patch_namespaced_service(name, namespace, service)
        await asyncio.to_thread(apply_service)
        ready = int(getattr(deployed.status, 'ready_replicas', 0) or 0)
        desired = int(body['spec']['replicas'])
        await self._report(item, state='RUNNING' if ready == desired else 'DEPLOYED',
                           message=f'Python Kubernetes replicas ready: {ready}/{desired}',
                           health='HEALTHY' if ready == desired else 'DEGRADED')

    async def once(self):
        await self._heartbeat()
        response = await self._request('GET', self._endpoint('/agent/deployments'))
        deployments = response.json()
        seen = set()
        for item in deployments:
            if (item.get('pythonSource') or {}).get('entrypoint') != 'application/main.py': continue
            seen.add(item['id'])
            try:
                if self.settings.mode == 'kubernetes': await self._reconcile_kubernetes(item)
                else: await self._reconcile_local(item)
            except Exception as error:
                LOG.exception('Deployment reconciliation failed: %s', item.get('id'))
                await self._report(item, state='FAILED', message=str(error), health='UNHEALTHY')
        if self.settings.mode == 'local':
            for deployment_id in set(self.processes) - seen: self._stop_local(deployment_id)

    async def run(self):
        while True:
            try: await self.once()
            except asyncio.CancelledError: raise
            except Exception: LOG.exception('Data-plane reconciliation failed')
            await asyncio.sleep(self.settings.poll_seconds)


async def _main():
    settings = Settings.from_environment()
    agent = PythonAgent(settings)
    try: await agent.run()
    finally: await agent.close()


def main() -> int:
    logging.basicConfig(level=os.environ.get('FABRIC_AGENT_LOG_LEVEL', 'INFO'), format='%(asctime)s %(levelname)s %(message)s')
    try: asyncio.run(_main())
    except KeyboardInterrupt: return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
