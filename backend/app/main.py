import asyncio, io, json, os, socket, sys, tarfile, zipfile
import re
import httpx
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from .models import AIBuildRequest, DebugAction, DebugRequest, Project, RunRequest, SharedResource, effective_event_activities
from .store import delete_project, get_project, list_projects, project_dir, save_project
from .runtime import WorkflowRuntime
from .debugger import DebugManager
from .mapper import execute as execute_mapping, recommend, validate_output
from .dataweave import DataWeaveError, execute_details as execute_dataweave
from .sap import sap_adapter
from .snowflake import snowflake_adapter
from .ai_builder import generate as generate_ai_design

app = FastAPI(title='Integration Fabric Runtime', version='0.1.0')
runtime = WorkflowRuntime()
debugger = DebugManager(runtime)
runtime_states: dict[str, dict] = {}
active_runs: dict[str, asyncio.Task] = {}

INBOUND_OPERATIONS = {None, 'listen', 'receiver', 'service'}

def _resolved_resource_config(item: Project, activity, properties: dict) -> dict:
    resource = next((value for value in item.resources if value.id == activity.config.get('resourceId')), None)
    if not resource: return {}
    context = {'properties': properties, 'input': {}, 'last': {}, 'vars': {}, 'context': {}}
    return {key: runtime.resolve(value, context) for key, value in resource.config.items()}

def _listener_endpoints(item: Project, task, environment: str, base_url: str = '') -> list[dict]:
    properties = {prop.key: prop.value for prop in item.properties.get(environment, [])}
    endpoints = []
    for activity in task.activities:
        if activity.type not in ('http_listener', 'rest', 'soap') or activity.config.get('operation') not in INBOUND_OPERATIONS: continue
        cfg = _resolved_resource_config(item, activity, properties)
        path = str(runtime.resolve(activity.config.get('path', '/'), {'properties': properties, 'input': {}, 'last': {}, 'vars': {}, 'context': {}}) or '/')
        if not path.startswith('/'): path = '/' + path
        base_path = str(cfg.get('basePath') or '').strip('/')
        deployment_path = ('/' + base_path if base_path else '') + path
        tls = str(cfg.get('tlsEnabled', cfg.get('scheme') == 'https')).lower() in ('true', '1', 'yes', 'on')
        scheme = 'https' if tls else str(cfg.get('scheme') or 'http')
        host = str(cfg.get('host') or 'localhost')
        port = int(cfg.get('port') or (443 if scheme == 'https' else 80))
        default_port = (scheme == 'https' and port == 443) or (scheme == 'http' and port == 80)
        configured_url = f'{scheme}://{host}{"" if default_port else f":{port}"}{deployment_path}'
        relative_url = f'/api/listeners/{item.id}{path}'
        methods = str(activity.config.get('methods', activity.config.get('method', 'POST'))).replace(' ', '').split(',')
        endpoints.append({'taskId': task.id, 'activityId': activity.id, 'name': activity.name, 'type': activity.type,
                          'methods': methods, 'path': path, 'url': base_url.rstrip('/') + relative_url if base_url else relative_url,
                          'relativeUrl': relative_url, 'configuredUrl': configured_url, 'tlsEnabled': tls,
                          'authentication': cfg.get('authentication', 'None')})
    return endpoints

def _lifecycle_logs(item: Project, endpoints: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    logs = [
        {'time': now, 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Deploying application {item.name}', 'startedAt': now},
        {'time': now, 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Application {item.name} started', 'startedAt': now},
    ]
    logs.extend({'time': now, 'level': 'INFO', 'kind': 'endpoint', 'message': f'{", ".join(endpoint["methods"])} listener ready at {endpoint["url"]}'} for endpoint in endpoints)
    return logs

def _publish_runtime_state(project_id: str, *, status: str, logs: list[dict], endpoints=None, result=None):
    previous = runtime_states.get(project_id, {})
    executions = list(previous.get('executions', []))
    if result is not None:
        execution = {
            'runId': result.run_id, 'correlationId': result.correlation_id, 'status': result.status,
            'startedAt': result.started_at, 'endedAt': result.ended_at, 'durationMs': result.duration_ms,
            'activityOutputs': result.activity_outputs, 'taskOutputs': result.task_outputs,
        }
        executions = ([execution] + executions)[:100]
    state = {
        'status': status, 'updatedAt': datetime.now(timezone.utc).isoformat(),
        'logs': logs, 'endpoints': endpoints if endpoints is not None else previous.get('endpoints', []),
        'activityOutputs': result.activity_outputs if result is not None else previous.get('activityOutputs', {}),
        'taskOutputs': result.task_outputs if result is not None else previous.get('taskOutputs', {}),
        'lastExecution': executions[0] if executions else None, 'executions': executions,
    }
    runtime_states[project_id] = state
    return state

@app.get('/api/health')
def health(): return {'status': 'ok', 'runtime': 'python'}

@app.get('/api/ai/status')
def ai_status():
    return {'available': True, 'provider': 'openai' if os.getenv('OPENAI_API_KEY') else 'local-blueprint', 'model': os.getenv('INTEGRATION_FABRIC_AI_MODEL', 'gpt-5') if os.getenv('OPENAI_API_KEY') else None, 'credentialsStoredInProject': False}

@app.post('/api/ai/generate')
async def ai_generate(request: AIBuildRequest):
    try: return await generate_ai_design(request.requirement, request.scope, request.current_task)
    except httpx.HTTPStatusError as exc: raise HTTPException(502, f'AI provider rejected the design request: {exc.response.text[:500]}')
    except (ValueError, json.JSONDecodeError) as exc: raise HTTPException(422, f'AI design did not pass Studio validation: {exc}')

@app.get('/api/projects', response_model=list[Project])
def projects(): return list_projects()

@app.get('/api/projects/{project_id}', response_model=Project)
def project(project_id: str):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    return item

@app.get('/api/projects/{project_id}/runtime-state')
def runtime_state(project_id: str):
    if not get_project(project_id): raise HTTPException(404, 'Project not found')
    return runtime_states.get(project_id, {'status': 'stopped', 'logs': [], 'endpoints': [], 'activityOutputs': {}, 'taskOutputs': {}, 'lastExecution': None, 'executions': []})

@app.post('/api/projects', response_model=Project)
def create_project(item: Project): return save_project(item)

@app.put('/api/projects/{project_id}', response_model=Project)
def update_project(project_id: str, item: Project):
    if project_id != item.id: raise HTTPException(400, 'Project id mismatch')
    return save_project(item)

@app.delete('/api/projects/{project_id}')
def remove_project(project_id: str):
    if not delete_project(project_id): raise HTTPException(404, 'Project not found')
    return {'deleted': True, 'projectId': project_id}

@app.get('/api/projects/{project_id}/json')
def project_json(project_id: str):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    filename = re.sub(r'[^A-Za-z0-9_.-]+','-',item.name).strip('-') or item.id
    return Response(item.model_dump_json(indent=2), media_type='application/json', headers={'Content-Disposition':f'attachment; filename="{filename}.json"','X-Project-Storage':str(project_dir(project_id))})

@app.post('/api/projects/{project_id}/run')
async def run(project_id: str, http_request: Request, request: RunRequest):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    resources = {resource.id: resource for resource in item.resources}
    selected = item.properties.get(request.environment, [])
    properties = {prop.key: prop.value for prop in selected}
    task_id = request.task_id or item.active_task_id
    task = next((task for task in item.tasks if task.id == task_id), None)
    if not task: raise HTTPException(404, 'Task not found')
    if task.kind != 'starter': raise HTTPException(400, 'Sub Tasks are invoked by a Call Sub Task activity; run a Starter Task')
    events = effective_event_activities(task.activities)
    if len(events) != 1: raise HTTPException(400, f'Starter Task requires exactly one event activity; found {len(events)}')
    endpoints = _listener_endpoints(item, task, request.environment, str(http_request.base_url).rstrip('/'))
    if endpoints:
        lifecycle = _lifecycle_logs(item, endpoints)
        _publish_runtime_state(project_id, status='listening', logs=lifecycle, endpoints=endpoints)
        return {'status': 'listening', 'output': {}, 'logs': lifecycle,
                'activity_outputs': {}, 'task_outputs': {}, 'endpoints': endpoints, 'executions': []}
    current_run = asyncio.current_task()
    if current_run: active_runs[project_id] = current_run
    try:
        result = await runtime.run(task, request.input, resources, properties, project=item)
    except asyncio.CancelledError:
        now = datetime.now(timezone.utc).isoformat()
        logs = list(runtime_states.get(project_id, {}).get('logs', [])) + [{'time': now, 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Application {item.name} stopped by user', 'endedAt': now}]
        state = _publish_runtime_state(project_id, status='stopped', logs=logs[-500:], endpoints=[])
        return {'status': 'stopped', 'output': {}, 'logs': state['logs'], 'activity_outputs': state['activityOutputs'], 'task_outputs': state['taskOutputs'], 'endpoints': []}
    finally:
        if active_runs.get(project_id) is current_run: active_runs.pop(project_id, None)
    payload = result.model_dump()
    payload['logs'] = _lifecycle_logs(item, []) + payload.get('logs', [])
    payload['endpoints'] = []
    _publish_runtime_state(project_id, status=result.status, logs=payload['logs'], endpoints=[], result=result)
    return payload

@app.post('/api/projects/{project_id}/stop')
async def stop_project(project_id: str):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    active = active_runs.get(project_id)
    if active and not active.done(): active.cancel()
    previous = runtime_states.get(project_id, {})
    now = datetime.now(timezone.utc).isoformat()
    logs = list(previous.get('logs', []))
    if not logs or logs[-1].get('message') != f'Application {item.name} stopped by user':
        logs.append({'time': now, 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Application {item.name} stopped by user', 'endedAt': now})
    state = _publish_runtime_state(project_id, status='stopped', logs=logs[-500:], endpoints=[])
    return state

@app.get('/api/projects/{project_id}/export')
def export_project(project_id: str):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps({'format':'integration-fabric-project','version':1,'projectId':item.id,'name':item.name}, indent=2))
        archive.writestr('project.json', item.model_dump_json(indent=2))
        for task in item.tasks: archive.writestr(f'tasks/{task.id}.json', task.model_dump_json(indent=2))
        for resource in item.resources: archive.writestr(f'resources/{resource.type}/{resource.id}.json', resource.model_dump_json(indent=2))
        for schema in item.schemas: archive.writestr(f'schemas/{schema.name}', schema.content)
        for environment, values in item.properties.items(): archive.writestr(f'environments/{environment}.json', json.dumps([value.model_dump() for value in values], indent=2))
        archive.writestr('packaging.json', json.dumps(item.packaging, indent=2))
    stream.seek(0)
    filename = re.sub(r'[^A-Za-z0-9_.-]+','-',item.name).strip('-') or item.id
    return StreamingResponse(stream, media_type='application/zip', headers={'Content-Disposition':f'attachment; filename="{filename}.ifproject"'})

def deployment_package_files(item: Project, target: str, environment: str) -> dict[str, bytes]:
    if target not in {'on-prem', 'cloud'}:
        raise HTTPException(400, 'Target must be on-prem or cloud')
    if environment not in item.properties:
        raise HTTPException(400, f'Unknown environment: {environment}')
    artifact = item.packaging.get('artifact_name') or item.id
    version = item.packaging.get('version') or '1.0.0'
    properties = [value.model_dump() for value in item.properties[environment]]
    secret_keys = [value['key'] for value in properties if value.get('data_type') == 'password']
    for value in properties:
        if value.get('data_type') == 'password': value['value'] = ''
    sensitive = re.compile(r'(password|passwd|secret|token|private.?key|credential)', re.I)
    def scrub(value, path=''):
        if isinstance(value, dict):
            output = {}
            for key, child in value.items():
                child_path = f'{path}.{key}'.strip('.')
                if sensitive.search(str(key)) and isinstance(child, (str, bytes)) and not str(child).startswith('${properties.'):
                    output[key] = ''
                    if child: secret_keys.append(child_path)
                else: output[key] = scrub(child, child_path)
            return output
        if isinstance(value, list): return [scrub(child, f'{path}[{index}]') for index, child in enumerate(value)]
        return value
    sanitized_project = item.model_dump()
    sanitized_project['properties'] = {environment: properties}
    sanitized_project = scrub(sanitized_project)
    sanitized_project['properties'] = {environment: properties}
    sanitized_resources = [scrub(resource.model_dump(), f'resources.{resource.id}') for resource in item.resources]
    secret_keys = sorted(set(secret_keys))
    manifest = {
        'format': 'integration-fabric-deployment', 'formatVersion': 1,
        'applicationId': item.id, 'applicationName': item.name,
        'artifact': artifact, 'version': version, 'target': target,
        'environment': environment, 'runtime': 'integration-fabric-python',
        'secretKeys': secret_keys,
    }
    files: dict[str, bytes] = {
        'manifest.json': json.dumps(manifest, indent=2).encode(),
        'application/project.json': json.dumps(sanitized_project, indent=2).encode(),
        f'environments/{environment}.json': json.dumps(properties, indent=2).encode(),
        'deployment/secrets.required.json': json.dumps({'required': secret_keys}, indent=2).encode(),
    }
    for task in item.tasks: files[f'application/tasks/{task.id}.json'] = task.model_dump_json(indent=2).encode()
    for resource, payload in zip(item.resources, sanitized_resources): files[f'application/resources/{resource.type}/{resource.id}.json'] = json.dumps(payload, indent=2).encode()
    for schema in item.schemas: files[f'application/schemas/{schema.name}'] = schema.content.encode()
    if target == 'cloud':
        image = f'integration-fabric/{artifact}:{version}'
        files['deployment/cloud/Dockerfile'] = ('FROM integration-fabric-runtime:latest\nCOPY application /opt/integration-fabric/application\nCOPY environments /opt/integration-fabric/environments\n').encode()
        files['deployment/cloud/kubernetes.yaml'] = f'''apiVersion: apps/v1
kind: Deployment
metadata:
  name: {artifact}
spec:
  replicas: 1
  selector:
    matchLabels: {{app: {artifact}}}
  template:
    metadata:
      labels: {{app: {artifact}}}
    spec:
      containers:
        - name: runtime
          image: {image}
          env:
            - name: FABRIC_ENVIRONMENT
              value: {environment}
            - name: FABRIC_APPLICATION_DIR
              value: /opt/integration-fabric/application
          envFrom:
            - secretRef:
                name: {artifact}-secrets
'''.encode()
    else:
        files['deployment/on-prem/application.json'] = json.dumps({
            'application': artifact, 'version': version, 'environment': environment,
            'engine': 'isolated', 'instances': 1, 'startOnBoot': False,
            'gracefulShutdownSeconds': 60, 'secretProvider': 'administrator'
        }, indent=2).encode()
        files['deployment/on-prem/README.txt'] = f'Deploy {artifact} {version} through Integration Fabric Administrator.\nTarget environment: {environment}\n'.encode()
    return files

@app.get('/api/projects/{project_id}/package')
def package_project(project_id: str, target: str = 'on-prem', environment: str = 'local', archive: str = 'ifpkg'):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    files = deployment_package_files(item, target, environment)
    artifact = re.sub(r'[^A-Za-z0-9_.-]+', '-', item.packaging.get('artifact_name') or item.id).strip('-')
    version = re.sub(r'[^A-Za-z0-9_.-]+', '-', item.packaging.get('version') or '1.0.0').strip('-')
    stream = io.BytesIO()
    if archive == 'tar.gz':
        with tarfile.open(fileobj=stream, mode='w:gz') as bundle:
            for name, body in files.items():
                info = tarfile.TarInfo(name); info.size = len(body); bundle.addfile(info, io.BytesIO(body))
        extension, media = 'tar.gz', 'application/gzip'
    else:
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name, body in files.items(): bundle.writestr(name, body)
        extension = 'ear' if archive == 'ear' else 'ifpkg'
        media = 'application/java-archive' if archive == 'ear' else 'application/zip'
    stream.seek(0)
    filename = f'{artifact}-{version}-{target}.{extension}'
    return StreamingResponse(stream, media_type=media, headers={'Content-Disposition': f'attachment; filename="{filename}"'})

@app.post('/api/projects/import', response_model=Project)
async def import_project(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        if raw[:2] == b'PK':
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                if manifest.get('format') != 'integration-fabric-project': raise ValueError('Unsupported project package')
                payload = archive.read('project.json')
        else: payload = raw
        item = Project.model_validate_json(payload)
    except Exception as exc: raise HTTPException(400, f'Invalid Integration Fabric project: {exc}')
    return save_project(item)

@app.post('/api/connections/test')
async def test_connection(resource: SharedResource):
    cfg = resource.config
    if cfg.get('mode') == 'memory': return {'ok': True, 'message': 'Local in-memory broker is ready'}
    if resource.type == 'jdbc' and cfg.get('driver','sqlite') == 'sqlite':
        import sqlite3
        conn = sqlite3.connect(cfg.get('url','integration.db')); conn.execute('SELECT 1'); conn.close(); return {'ok':True,'message':'SQLite connection succeeded'}
    if resource.type == 'snowflake':
        try: return await __import__('asyncio').to_thread(snowflake_adapter.test, cfg)
        except Exception as exc: return {'ok':False,'message':str(exc)}
    if resource.type == 'sap_tid' and cfg.get('mode','none') == 'none': return {'ok':True,'message':'SAP TID duplicate management is disabled'}
    if resource.type == 'sap_tid' and cfg.get('driver','sqlite') == 'sqlite':
        import sqlite3
        conn = sqlite3.connect(cfg.get('url','sap-tid.db')); conn.execute('CREATE TABLE IF NOT EXISTS sap_tid (tid TEXT PRIMARY KEY, state TEXT, updated_at TEXT)'); conn.close(); return {'ok':True,'message':'SAP TID Manager database is ready'}
    if resource.type == 'http':
        if cfg.get('connectorMode', 'both') in ('server', 'both'):
            host, port = cfg.get('host', 'localhost'), int(cfg.get('port', 80))
            if not 1 <= port <= 65535: return {'ok': False, 'message': 'Listener port must be between 1 and 65535'}
            if str(cfg.get('tlsEnabled', 'false')).lower() in ('true','1','yes','on') and (not cfg.get('certificateFile') or not cfg.get('privateKeyFile')):
                return {'ok': False, 'message': 'HTTPS listener requires a certificate file and private key file'}
            return {'ok': True, 'message': f'HTTP listener configuration is valid for {host}:{port}'}
        import httpx
        async with httpx.AsyncClient(timeout=float(cfg.get('timeoutSeconds',5)), verify=str(cfg.get('verifyTls', 'true')).lower() in ('true','1','yes','on')) as client: response = await client.get(cfg.get('baseUrl') or cfg.get('url'))
        return {'ok': response.status_code < 500, 'message': f'HTTP endpoint returned {response.status_code}'}
    if resource.type == 'sap':
        try: return await __import__('asyncio').to_thread(sap_adapter.test, cfg)
        except Exception as exc: return {'ok':False,'message':str(exc)}
    if resource.type == 'ems':
        try:
            import stomp
            connection = stomp.Connection12([(cfg.get('host','localhost'), int(cfg.get('port',7222)))]); connection.connect(cfg.get('username',''), cfg.get('password',''), wait=True); connection.disconnect()
            return {'ok':True,'message':'TIBCO EMS STOMP connection succeeded'}
        except ImportError: return {'ok':False,'message':'External EMS testing requires stomp.py and an enabled EMS STOMP service'}
        except Exception as exc: return {'ok':False,'message':f'TIBCO EMS connection failed: {exc}'}
    if resource.type == 'kafka':
        try:
            from confluent_kafka.admin import AdminClient
            settings = {'bootstrap.servers':cfg['bootstrapServers']}
            if cfg.get('securityProtocol'): settings['security.protocol'] = cfg['securityProtocol']
            if cfg.get('saslMechanism'): settings['sasl.mechanism'] = cfg['saslMechanism']
            if cfg.get('username'): settings['sasl.username'] = cfg['username']
            if cfg.get('password'): settings['sasl.password'] = cfg['password']
            metadata = await __import__('asyncio').to_thread(AdminClient(settings).list_topics, None, float(cfg.get('requestTimeoutMilliseconds',30000))/1000)
            return {'ok':True,'message':f'Kafka connection succeeded; {len(metadata.brokers)} broker(s) and {len(metadata.topics)} topic(s) discovered'}
        except ImportError: return {'ok':False,'message':'External Kafka testing requires confluent-kafka'}
        except Exception as exc: return {'ok':False,'message':f'Kafka connection failed: {exc}'}
    if resource.type == 'pubsub':
        try:
            from google.cloud import pubsub_v1
            kwargs = {}
            if cfg.get('credentialsFile'):
                from google.oauth2 import service_account
                kwargs['credentials'] = service_account.Credentials.from_service_account_file(cfg['credentialsFile'])
            endpoint = cfg.get('emulatorHost') or cfg.get('endpoint')
            if endpoint: kwargs['client_options'] = {'api_endpoint':endpoint}
            publisher = pubsub_v1.PublisherClient(**kwargs); iterator = publisher.list_topics(request={'project':f"projects/{cfg['projectId']}", 'page_size':1}); next(iter(iterator), None); publisher.transport.close()
            return {'ok':True,'message':'Google Pub/Sub connection succeeded'}
        except ImportError: return {'ok':False,'message':'External Google Pub/Sub testing requires google-cloud-pubsub'}
        except Exception as exc: return {'ok':False,'message':f'Google Pub/Sub connection failed: {exc}'}
    host = cfg.get('host') or cfg.get('bootstrapServers','').split(',')[0].split(':')[0] or cfg.get('emulatorHost','').split(':')[0]
    port = cfg.get('port') or (cfg.get('bootstrapServers','').split(',')[0].split(':')[1] if ':' in cfg.get('bootstrapServers','') else None) or (cfg.get('emulatorHost','').split(':')[1] if ':' in cfg.get('emulatorHost','') else None)
    if host and port:
        await __import__('asyncio').to_thread(lambda: socket.create_connection((host, int(port)), timeout=float(cfg.get('timeout',5))).close())
        return {'ok':True,'message':f'Connected to {host}:{port}'}
    return {'ok':False,'message':'Save the required host/URL fields before testing'}

@app.post('/api/sap/idocs')
def sap_idocs(payload: dict):
    try:
        resource = SharedResource.model_validate(payload.get('resource') or {})
        if resource.type != 'sap': raise ValueError('An SAP ECC shared connection is required')
        idoc_type = str(payload.get('idocType') or '').strip()
        if idoc_type:
            return {'idoc': sap_adapter.idoc_metadata(resource.config, idoc_type, str(payload.get('extensionType') or ''), str(payload.get('release') or ''))}
        return {'idocs': sap_adapter.list_idocs(resource.config, str(payload.get('search') or ''), int(payload.get('limit', 250)))}
    except Exception as exc: raise HTTPException(400, f'Unable to fetch SAP IDoc metadata: {exc}')

@app.post('/api/snowflake/entities')
async def snowflake_entities(payload: dict):
    try:
        resource = SharedResource.model_validate(payload.get('resource') or {})
        if resource.type != 'snowflake': raise ValueError('A Snowflake JDBC shared connection is required')
        entity = str(payload.get('entity') or '').strip()
        if entity:
            metadata = await __import__('asyncio').to_thread(snowflake_adapter.entity_metadata, resource.config, str(payload.get('database') or resource.config.get('database') or ''), str(payload.get('schema') or resource.config.get('schema') or 'PUBLIC'), entity)
            return {'entity': metadata}
        entities = await __import__('asyncio').to_thread(snowflake_adapter.list_entities, resource.config, str(payload.get('database') or ''), str(payload.get('schema') or ''), str(payload.get('pattern') or ''))
        return {'entities': entities}
    except Exception as exc: raise HTTPException(400, f'Unable to retrieve Snowflake metadata: {exc}')

@app.post('/api/mapper/suggest')
def mapper_suggest(payload: dict):
    return {'recommendations': recommend(payload.get('sourceSchema',{}), payload.get('targetSchema',{}), float(payload.get('threshold',70))/100, payload.get('weights'))}

@app.post('/api/mapper/test')
def mapper_test(payload: dict):
    try:
        mappings = payload.get('mappings', []) or []
        def test_path(value: str) -> str:
            path = value[2:-1] if value.startswith('${') and value.endswith('}') else value
            if path.startswith('activities.') and '.output.' in path:
                return path.split('.output.', 1)[1]
            if path.endswith('.output') and path.startswith('activities.'):
                return ''
            if path.startswith('input.'):
                return path[6:]
            if path.startswith('last.'):
                return path[5:]
            return '' if path in ('input', 'last') else path
        normalized = []
        for mapping in mappings:
            rule = dict(mapping)
            for key in ('source', 'select'):
                value = rule.get(key)
                if not isinstance(value, str) or not value.startswith('${'):
                    continue
                rule[key] = test_path(value)
            if isinstance(rule.get('condition'), str):
                rule['condition'] = re.sub(r'\$\{[^}]+\}', lambda match: test_path(match.group(0)), rule['condition'])
            normalized.append(rule)
        options = payload.get('options') or {}
        if payload.get('targetSchema'): options = {**options, 'targetSchema': payload.get('targetSchema')}
        output = execute_mapping(payload.get('input', {}), normalized, options)
        errors = validate_output(output, payload.get('targetSchema')) if payload.get('targetSchema') and not options.get('validateOutput', True) else []
        return {'output': output, 'valid': not errors, 'validationErrors': errors, 'mappingCount': len([rule for rule in normalized if rule.get('enabled', True)])}
    except Exception as exc: raise HTTPException(400, f'Mapping failed: {exc}')

@app.post('/api/dataweave/test')
def dataweave_test(payload: dict):
    try:
        return execute_dataweave(
            str(payload.get('script') or ''), payload=payload.get('input'),
            attributes=payload.get('attributes') or {}, variables=payload.get('variables') or {},
            input_mime_type=str(payload.get('inputMimeType') or ''),
        )
    except DataWeaveError as exc:
        raise HTTPException(400, f'DataWeave validation failed: {exc}')

@app.post('/api/dataweave/generate')
def dataweave_generate(payload: dict):
    """Generate a reviewable starter script from mapper recommendations."""
    source, target = payload.get('sourceSchema') or {}, payload.get('targetSchema') or {}
    recommendations = recommend(source, target, float(payload.get('threshold', 70)) / 100, payload.get('weights'))
    tree: dict = {}
    for item in recommendations:
        target_path, source_path = str(item.get('target') or ''), str(item.get('selected') or '')
        if not target_path or not source_path: continue
        current = tree
        for part in target_path.split('.'): current = current.setdefault(part, {})
        current['__mapping__'] = item
    def key(value: str): return value if re.fullmatch(r'[A-Za-z_$][\w$-]*', value) else json.dumps(value)
    def selector(base: str, path: str):
        value = base
        for part in path.split('.') if path else []:
            value += f'.{part}' if re.fullmatch(r'[A-Za-z_$][\w$-]*', part) else f'[{json.dumps(part)}]'
        return value
    def render(nodes: dict, indent=0, source_repeat='', target_prefix=''):
        lines = []
        for name, child in nodes.items():
            if name == '__mapping__': continue
            target_path = f'{target_prefix}.{name}'.strip('.')
            mapping = child.get('__mapping__')
            children = {item_name:item for item_name,item in child.items() if item_name != '__mapping__'}
            if children:
                repeated = next((item for item in recommendations if item.get('targetRepeatPath') == target_path and item.get('selected')), None)
                if repeated and repeated.get('sourceRepeatPath'):
                    nested = render(children, indent + 2, str(repeated['sourceRepeatPath']), target_path)
                    value = f"{selector('payload', str(repeated['sourceRepeatPath']))} map (item) -> {{\n{nested}\n{' ' * (indent + 2)}}}"
                else: value = "{\n" + render(children, indent + 2, source_repeat, target_path) + "\n" + ' ' * (indent + 2) + "}"
            elif mapping:
                selected = str(mapping.get('selected') or '')
                relative = selected[len(source_repeat):].lstrip('.') if source_repeat and selected.startswith(source_repeat) else ''
                value = selector('item', relative) if relative else selector('payload', selected)
            else: value = 'null'
            lines.append(' ' * (indent + 2) + f'{key(name)}: {value}')
        return ',\n'.join(lines)
    body = '{\n' + (render(tree) if tree else '  result: payload') + '\n}'
    return {
        'script': '%dw 2.0\noutput application/json\n---\n' + body,
        'recommendations': recommendations,
        'reviewRequired': True,
    }

@app.post('/api/conditions/evaluate')
def evaluate_condition(payload: dict):
    expression, supplied = str(payload.get('expression','')), payload.get('context') or {}
    context = {
        'last': supplied.get('last', {}), 'input': supplied.get('input', {}),
        'properties': supplied.get('properties', {}), 'vars': supplied.get('vars', {}),
    }
    try: return {'result': bool(runtime.condition(expression, context)), 'expression': expression}
    except Exception as exc: raise HTTPException(400, f'Condition evaluation failed: {exc}')

@app.post('/api/projects/{project_id}/debug')
def start_debug(project_id: str, http_request: Request, request: DebugRequest):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    task_id = request.task_id or item.active_task_id
    properties = {prop.key: prop.value for prop in item.properties.get(request.environment, [])}
    try:
        view = debugger.start(item, task_id, request.input, {resource.id:resource for resource in item.resources}, properties, request.breakpoints)
        task = next(value for value in item.tasks if value.id == task_id)
        endpoints = _listener_endpoints(item, task, request.environment, str(http_request.base_url).rstrip('/'))
        state = debugger.sessions[view['sessionId']]
        state['endpoints'] = endpoints
        state['logs'].extend(_lifecycle_logs(item, endpoints))
        return debugger.view(state)
    except ValueError as exc: raise HTTPException(400, str(exc))

@app.post('/api/debug/{session_id}/action')
async def debug_action(session_id: str, request: DebugAction):
    try: return await debugger.action(session_id, request.action)
    except ValueError as exc: raise HTTPException(404, str(exc))

HTTP_LISTENER_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE', 'CONNECT']

def _configured_http_methods(activity) -> set[str]:
    configured = activity.config.get('methods', activity.config.get('method', ''))
    if isinstance(configured, list):
        values = configured
    else:
        values = str(configured).split(',')
    return {str(value).strip().upper() for value in values if str(value).strip()}

@app.api_route('/api/listeners/{project_id}/{listener_path:path}', methods=HTTP_LISTENER_METHODS)
async def invoke_listener(project_id: str, listener_path: str, request: Request, environment: str = 'local'):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    request_path = '/' + listener_path
    starter_tasks = [task for task in item.tasks if task.kind == 'starter']
    candidates = [(task, activity) for task in starter_tasks for activity in task.activities if activity.type in ('http_listener', 'rest', 'soap') and activity.config.get('operation') in (None, 'listen', 'receiver', 'service')]
    def match_path(template: str):
        names = re.findall(r'\{([^}]+)\}', template)
        pattern = '^' + re.sub(r'\{[^}]+\}', r'([^/]+)', template.rstrip('/')) + '/?$'
        match = re.match(pattern, request_path)
        return dict(zip(names, match.groups())) if match else None
    matched = next(((task, activity, match_path(activity.config.get('path', '/'))) for task, activity in candidates if match_path(activity.config.get('path', '/')) is not None and (request.method.upper() in _configured_http_methods(activity) or (activity.type == 'soap' and request.method == 'GET' and 'wsdl' in request.query_params))), None)
    task, listener, path_parameters = matched if matched else (None, None, {})
    if not listener: raise HTTPException(404, f'No listener configured for {request.method} {request_path}')
    properties = {prop.key: prop.value for prop in item.properties.get(environment, [])}
    listener_cfg = _resolved_resource_config(item, listener, properties)
    authentication = str(listener_cfg.get('authentication', 'None')).lower()
    authorization = request.headers.get('authorization', '')
    if authentication == 'basic':
        import base64, hmac
        try: supplied = base64.b64decode(authorization.removeprefix('Basic ').strip()).decode()
        except Exception: supplied = ''
        expected = f'{listener_cfg.get("username", "")}:{listener_cfg.get("password", "")}'
        if not authorization.startswith('Basic ') or not hmac.compare_digest(supplied, expected):
            return JSONResponse({'detail': 'HTTP Basic authentication failed'}, status_code=401, headers={'WWW-Authenticate': 'Basic'})
    elif authentication == 'bearer':
        import hmac
        expected = f'Bearer {listener_cfg.get("bearerToken", "")}'
        if not hmac.compare_digest(authorization, expected):
            return JSONResponse({'detail': 'Bearer authentication failed'}, status_code=401, headers={'WWW-Authenticate': 'Bearer'})
    if listener.type == 'soap' and request.method == 'GET' and 'wsdl' in request.query_params:
        wsdl = listener.config.get('wsdlContent', '')
        wsdl_path = listener.config.get('wsdl', '')
        if not wsdl and wsdl_path and Path(wsdl_path).is_file(): wsdl = Path(wsdl_path).read_text()
        if not wsdl: raise HTTPException(404, 'WSDL is not configured for this SOAP service')
        return Response(wsdl, media_type='text/xml')
    raw = await request.body()
    try: body = json.loads(raw) if raw else None
    except (ValueError, UnicodeDecodeError): body = raw.decode(errors='replace')
    payload = {'body': body, 'method': request.method, 'path': request_path, 'query': dict(request.query_params), 'headers': dict(request.headers), 'pathParameters': path_parameters}
    resources = {resource.id: resource for resource in item.resources}
    result = await runtime.run(task, payload, resources, properties, listener.id, item)
    deployment = runtime_states.get(project_id, {})
    combined_logs = list(deployment.get('logs', [])) + result.logs
    _publish_runtime_state(project_id, status='listening' if result.status == 'completed' else 'failed', logs=combined_logs[-500:], result=result)
    if result.status == 'failed': return JSONResponse({'status': result.status, 'logs': result.logs}, status_code=500)
    output = result.output
    if output.get('__httpResponse'):
        body = output.get('body'); headers = output.get('headers', {}); status = output.get('statusCode', 200)
        return JSONResponse(body, status_code=status, headers=headers) if isinstance(body, (dict, list)) else Response(str(body or ''), status_code=status, headers=headers)
    return JSONResponse(output)

static_candidates = [
    Path(os.environ['FABRIC_STATIC_DIR']).expanduser() if os.environ.get('FABRIC_STATIC_DIR') else None,
    Path(getattr(sys, '_MEIPASS', '')) / 'frontend' / 'dist' if getattr(sys, '_MEIPASS', None) else None,
    Path(__file__).parents[2] / 'frontend' / 'dist',
]
static_dir = next((candidate for candidate in static_candidates if candidate and candidate.exists()), Path('__missing_frontend_dist__'))
if static_dir.exists(): app.mount('/', StaticFiles(directory=static_dir, html=True), name='studio')
