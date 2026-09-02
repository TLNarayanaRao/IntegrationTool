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
from .jdbc import jdbc_adapter
from .amqp import amqp_adapter
from .java_bridge import JavaBridgeError, test_jms
from .google_pubsub import client_configuration as pubsub_client_configuration, credential_summary as pubsub_credential_summary
from .ai_builder import generate as generate_ai_design
from .project_logging import append_project_logs, project_log_info, read_project_logs

app = FastAPI(title='Integration Fabric Runtime', version='0.1.0')
runtime = WorkflowRuntime()
debugger = DebugManager(runtime)
runtime_states: dict[str, dict] = {}
active_runs: dict[str, asyncio.Task] = {}

INBOUND_OPERATIONS = {None, 'listen', 'receiver', 'service'}
CONTINUOUS_EVENT_OPERATIONS = {
    'timer': {'schedule'},
    'file': {'poll'},
    'ems': {'queue_receiver', 'topic_subscriber'},
    'jms': {'receive_message'},
    'amqp': {'receive'},
    'kafka': {'receive', 'get'},
    'pubsub': {'subscribe'},
}

def _environment_values(item: Project, environment: str) -> dict:
    return {prop.key: prop.value for prop in item.properties.get(environment, [])}

def _project_log_directory(item: Project, environment: str) -> str:
    return str(_environment_values(item, environment).get('runtime.logDirectory') or '').strip()

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
        {'time': now, 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Integration Fabric runtime initializing application {item.name}', 'startedAt': now},
        {'time': now, 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Application module loaded: {item.name} ({len(item.tasks)} task(s), {len(item.resources)} shared resource(s))'},
        {'time': now, 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Application {item.name} started', 'startedAt': now},
    ]
    logs.extend({'time': now, 'level': 'INFO', 'kind': 'endpoint', 'message': (f'{endpoint["name"]} is ready and waiting on {endpoint["url"]}' if endpoint.get('kind') == 'subscription' else f'{", ".join(endpoint["methods"])} listener ready at {endpoint["url"]}')} for endpoint in endpoints)
    return logs

def _publish_runtime_state(project_id: str, *, status: str, logs: list[dict], endpoints=None, result=None, environment: str | None = None):
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
        'environment': environment or previous.get('environment', 'local'),
        'logs': logs, 'endpoints': endpoints if endpoints is not None else previous.get('endpoints', []),
        'activityOutputs': result.activity_outputs if result is not None else previous.get('activityOutputs', {}),
        'taskOutputs': result.task_outputs if result is not None else previous.get('taskOutputs', {}),
        'lastExecution': executions[0] if executions else None, 'executions': executions,
    }
    runtime_states[project_id] = state
    return state

def _is_continuous_event(activity) -> bool:
    return activity.config.get('operation') in CONTINUOUS_EVENT_OPERATIONS.get(activity.type, set())

def _event_subscription(item: Project, task, activity, environment: str) -> dict:
    properties = _environment_values(item, environment)
    context = {'properties': properties, 'input': {}, 'last': {}, 'vars': {}, 'context': {}}
    config = runtime.resolve(activity.config, context)
    destination = config.get('destination') or config.get('queue') or config.get('topic') or config.get('subscription') or config.get('path') or ('configured schedule' if activity.type == 'timer' else 'default')
    resource = next((value for value in item.resources if value.id == config.get('resourceId')), None)
    resource_name = resource.name if resource else str(config.get('resourceId') or 'unconfigured connection')
    technology = activity.type.upper()
    return {
        'taskId': task.id, 'activityId': activity.id, 'name': activity.name, 'type': activity.type,
        'kind': 'subscription', 'methods': ['EVENT'], 'status': 'ready', 'destination': str(destination),
        'resourceName': resource_name, 'url': f'{technology} · {resource_name} · {destination}',
    }

def _event_available(output) -> bool:
    if not isinstance(output, dict): return output is not None
    if 'received' in output: return bool(output.get('received'))
    if 'count' in output: return int(output.get('count') or 0) > 0
    if output.get('messages'): return True
    return bool(output.get('MessageID') or output.get('messageId') or output.get('body') is not None)

def _listener_context(item: Project, task, resources: dict, properties: dict, environment: str) -> dict:
    return {
        'input': {}, 'vars': {}, 'last': {}, 'resources': resources, 'properties': properties,
        'project': item, 'runtime': runtime, 'logs': [], 'activities': {},
        'tasks': {task.id: {'name': task.name, 'activities': {}}},
        'context': {'taskId': task.id, 'activityId': '', 'environment': environment},
    }

async def _continuous_event_loop(item: Project, task, activity, environment: str, debug_session_id: str | None = None):
    project_id = item.id
    resources = {resource.id: resource for resource in item.resources}
    properties = _environment_values(item, environment)
    retry_delay = 1.0
    seen_files: dict[str, str] | None = None
    current = asyncio.current_task()
    try:
        while True:
            if debug_session_id:
                session = debugger.sessions.get(debug_session_id)
                if not session or session.get('status') == 'stopped': return
                if session.get('status') not in ('listening',):
                    await asyncio.sleep(.1)
                    continue
            context = _listener_context(item, task, resources, properties, environment)
            try:
                output = await runtime.execute_with_policy(activity, context)
                retry_delay = 1.0
                resolved_config = runtime.resolve(activity.config, context)
                if activity.type == 'file' and activity.config.get('operation') == 'poll':
                    current_files = {str(value.get('fullName')): str(value.get('lastModified')) for value in output.get('files', []) if value.get('fullName')}
                    include_existing = runtime.as_bool(resolved_config.get('includeExisting', False))
                    event_type = str(resolved_config.get('eventType') or 'Created').lower()
                    if seen_files is None:
                        changed = list(output.get('files', [])) if include_existing else []
                    else:
                        created = [value for value in output.get('files', []) if str(value.get('fullName')) not in seen_files]
                        modified = [value for value in output.get('files', []) if str(value.get('fullName')) in seen_files and seen_files[str(value.get('fullName'))] != str(value.get('lastModified'))]
                        deleted = [{'fullName': name, 'fileName': Path(name).name, 'eventType':'Deleted'} for name in seen_files if name not in current_files]
                        changed = created if event_type == 'created' else modified if event_type == 'modified' else deleted if event_type == 'deleted' else created + modified + deleted
                    seen_files = current_files
                    output = {**output, 'files': changed, 'count': len(changed), 'eventType': resolved_config.get('eventType', 'Created')}
                if not _event_available(output):
                    await asyncio.sleep(max(.1, float(resolved_config.get('pollInterval', 1) or 1)) if activity.type == 'file' else .1)
                    continue
                if debug_session_id:
                    await debugger.trigger_event(debug_session_id, output)
                    session = debugger.sessions.get(debug_session_id)
                    if session:
                        cursor = int(session.get('persistedLogCount', 0))
                        append_project_logs(project_id, item.name, session['logs'][cursor:], _project_log_directory(item, environment))
                        session['persistedLogCount'] = len(session['logs'])
                        _publish_runtime_state(project_id, status=session.get('status', 'listening'), logs=session['logs'][-500:], endpoints=session.get('endpoints', []), environment=environment)
                    if activity.type == 'timer':
                        repeat = runtime.as_bool(resolved_config.get('repeatEnabled', False))
                        cron = str(resolved_config.get('scheduleMode') or '').lower() == 'cron'
                        if not repeat and not cron: return
                        if repeat and not cron:
                            multiplier = {'seconds':1, 'minutes':60, 'hours':3600, 'days':86400}.get(str(resolved_config.get('unit') or 'minutes').lower(), 60)
                            await asyncio.sleep(max(1.0, float(resolved_config.get('interval', 1) or 1) * multiplier))
                    elif activity.type == 'file':
                        await asyncio.sleep(max(.1, float(resolved_config.get('pollInterval', 1) or 1)))
                    continue
                result = await runtime.run(task, output, resources, properties, activity.id, item, event_output=output)
                previous = runtime_states.get(project_id, {})
                combined_logs = list(previous.get('logs', [])) + result.logs
                append_project_logs(project_id, item.name, result.logs, _project_log_directory(item, environment))
                _publish_runtime_state(project_id, status='listening', logs=combined_logs[-500:], result=result, environment=environment)
                if activity.type == 'timer':
                    repeat = runtime.as_bool(resolved_config.get('repeatEnabled', False))
                    cron = str(resolved_config.get('scheduleMode') or '').lower() == 'cron'
                    if not repeat and not cron: return
                    if repeat and not cron:
                        multiplier = {'seconds':1, 'minutes':60, 'hours':3600, 'days':86400}.get(str(resolved_config.get('unit') or 'minutes').lower(), 60)
                        await asyncio.sleep(max(1.0, float(resolved_config.get('interval', 1) or 1) * multiplier))
                elif activity.type == 'file':
                    await asyncio.sleep(max(.1, float(resolved_config.get('pollInterval', 1) or 1)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                now = datetime.now(timezone.utc).isoformat()
                entry = {'time': now, 'level': 'ERROR', 'kind': 'listener', 'message': f'{activity.name} listener error; reconnecting in {retry_delay:g} seconds: {exc}', 'activityId': activity.id, 'taskId': task.id}
                previous = runtime_states.get(project_id, {})
                logs = (list(previous.get('logs', [])) + [entry])[-500:]
                append_project_logs(project_id, item.name, [entry], _project_log_directory(item, environment))
                _publish_runtime_state(project_id, status='listening', logs=logs, environment=environment)
                await asyncio.sleep(retry_delay)
                retry_delay = min(30.0, retry_delay * 2)
    finally:
        if active_runs.get(project_id) is current: active_runs.pop(project_id, None)

def _start_continuous_listener(item: Project, task, activity, environment: str, debug_session_id: str | None = None):
    previous = active_runs.get(item.id)
    if previous and not previous.done(): previous.cancel()
    listener = asyncio.create_task(_continuous_event_loop(item, task, activity, environment, debug_session_id))
    active_runs[item.id] = listener
    return listener

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

@app.get('/api/projects/{project_id}/logs')
def project_logs(project_id: str, limit: int = 1000, environment: str = 'local'):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    if environment not in item.properties: raise HTTPException(400, f'Environment {environment!r} was not found')
    directory = _project_log_directory(item, environment)
    return {**project_log_info(project_id, directory), 'environment': environment, 'propertyKey': 'runtime.logDirectory', 'configuredDirectory': directory, 'entries': read_project_logs(project_id, limit, directory)}

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
    events = effective_event_activities(task.activities, task.transitions)
    if len(events) != 1: raise HTTPException(400, f'Starter Task requires exactly one event activity; found {len(events)}')
    event = events[0]
    endpoints = _listener_endpoints(item, task, request.environment, str(http_request.base_url).rstrip('/'))
    if endpoints:
        lifecycle = _lifecycle_logs(item, endpoints)
        append_project_logs(project_id, item.name, lifecycle, _project_log_directory(item, request.environment))
        _publish_runtime_state(project_id, status='listening', logs=lifecycle, endpoints=endpoints, environment=request.environment)
        return {'status': 'listening', 'output': {}, 'logs': lifecycle,
                'activity_outputs': {}, 'task_outputs': {}, 'endpoints': endpoints, 'executions': []}
    if _is_continuous_event(event):
        subscriptions = [_event_subscription(item, task, event, request.environment)]
        lifecycle = _lifecycle_logs(item, subscriptions)
        append_project_logs(project_id, item.name, lifecycle, _project_log_directory(item, request.environment))
        _publish_runtime_state(project_id, status='listening', logs=lifecycle, endpoints=subscriptions, environment=request.environment)
        _start_continuous_listener(item, task, event, request.environment)
        return {'status': 'listening', 'output': {}, 'logs': lifecycle,
                'activity_outputs': {}, 'task_outputs': {}, 'endpoints': subscriptions, 'executions': []}
    current_run = asyncio.current_task()
    if current_run: active_runs[project_id] = current_run
    runtime_states.setdefault(project_id, {})['environment'] = request.environment
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
    append_project_logs(project_id, item.name, payload['logs'], _project_log_directory(item, request.environment))
    _publish_runtime_state(project_id, status=result.status, logs=payload['logs'], endpoints=[], result=result, environment=request.environment)
    return payload

@app.post('/api/projects/{project_id}/stop')
async def stop_project(project_id: str):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    active = active_runs.get(project_id)
    if active and not active.done(): active.cancel()
    previous = runtime_states.get(project_id, {})
    environment = str(previous.get('environment') or item.active_environment or 'local')
    now = datetime.now(timezone.utc).isoformat()
    logs = list(previous.get('logs', []))
    if not logs or logs[-1].get('message') != f'Application {item.name} stopped by user':
        stopped_entry = {'time': now, 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Application {item.name} stopped by user', 'endedAt': now}
        logs.append(stopped_entry)
        append_project_logs(project_id, item.name, [stopped_entry], _project_log_directory(item, environment))
    state = _publish_runtime_state(project_id, status='stopped', logs=logs[-500:], endpoints=[], environment=environment)
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

DEPLOYMENT_ARTIFACTS = {
    'cloud': {'dockerfile', 'configmap', 'secret', 'deployment', 'service', 'hpa', 'package'},
    'on-prem': {'application', 'environment', 'administrator', 'systemd', 'install', 'readme'},
}

def packaging_task_closure(item: Project, starter_ids: list[str] | None = None) -> tuple[Project, list[str], list[str]]:
    """Select package roots and follow statically determinable Call Process dependencies."""
    tasks = {task.id: task for task in item.tasks}
    names = {task.name.casefold(): task.id for task in item.tasks}
    available_roots = [task.id for task in item.tasks if task.kind == 'starter']
    roots = list(dict.fromkeys(starter_ids or available_roots))
    if not roots: raise HTTPException(400, 'The project has no Starter Tasks to package')
    invalid = [task_id for task_id in roots if task_id not in tasks or tasks[task_id].kind != 'starter']
    if invalid: raise HTTPException(400, f'Packaging roots must be Starter Tasks: {", ".join(invalid)}')
    included: list[str] = []
    visiting: set[str] = set()
    def visit(task_id: str):
        if task_id in visiting: return
        visiting.add(task_id); included.append(task_id)
        for activity in tasks[task_id].activities:
            if activity.type != 'call_task': continue
            configured = str(activity.config.get('taskId') or '').strip()
            dynamic = str(activity.config.get('dynamicTaskId') or '').strip()
            candidates = [configured]
            if dynamic and not dynamic.startswith('${'): candidates.insert(0, dynamic)
            target_id = next((value for value in candidates if value in tasks), '')
            if not target_id: target_id = next((names.get(value.casefold(), '') for value in candidates if value and names.get(value.casefold())), '')
            if not target_id:
                if dynamic.startswith('${') and not configured:
                    raise HTTPException(400, f'{tasks[task_id].name} / {activity.name} uses a dynamic Call Process expression without a static fallback; packaging cannot determine its dependency')
                raise HTTPException(400, f'{tasks[task_id].name} / {activity.name} references missing Sub Task {configured or dynamic!r}')
            if tasks[target_id].kind != 'subtask': raise HTTPException(400, f'{tasks[task_id].name} / {activity.name} must call a Sub Task, not Starter Task {tasks[target_id].name}')
            visit(target_id)
    for root in roots: visit(root)
    selected = item.model_copy(deep=True)
    selected_by_id = {task.id: task for task in selected.tasks}
    selected.tasks = [selected_by_id[task_id] for task_id in included]
    selected.active_task_id = roots[0]
    selected.packaging = {**selected.packaging, 'starterTaskIds': roots, 'includedTaskIds': included}
    return selected, roots, included

def deployment_package_files(item: Project, target: str, environment: str, artifacts: set[str] | None = None) -> dict[str, bytes]:
    if target not in {'on-prem', 'cloud'}:
        raise HTTPException(400, 'Target must be on-prem or cloud')
    if environment not in item.properties:
        raise HTTPException(400, f'Unknown environment: {environment}')
    allowed_artifacts = DEPLOYMENT_ARTIFACTS[target]
    selected_artifacts = set(artifacts) if artifacts is not None else set(allowed_artifacts)
    unknown_artifacts = selected_artifacts - allowed_artifacts
    if unknown_artifacts:
        raise HTTPException(400, f'Unsupported {target} deployment artifacts: {", ".join(sorted(unknown_artifacts))}')
    artifact = item.packaging.get('artifact_name') or item.id
    version = item.packaging.get('version') or '1.0.0'
    properties = [value.model_dump() for value in item.properties[environment]]
    secret_keys = [value['key'] for value in properties if value.get('data_type') == 'password']
    for value in properties:
        if value.get('data_type') == 'password': value['value'] = ''
    sensitive = re.compile(r'(password|passwd|secret|token|private.?key|credential|service.?account)', re.I)
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
        'selectedArtifacts': sorted(selected_artifacts),
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
    deployment_name = re.sub(r'[^a-z0-9-]+', '-', artifact.lower()).strip('-')[:63] or 'integration-fabric-app'
    if target == 'cloud':
        image = str(item.packaging.get('image') or f'integration-fabric/{artifact}:{version}')
        replicas = max(1, int(item.packaging.get('replicas') or 1))
        minimum_replicas = max(1, int(item.packaging.get('minimumReplicas') or replicas))
        maximum_replicas = max(minimum_replicas, int(item.packaging.get('maximumReplicas') or max(3, minimum_replicas)))
        cpu_target = min(100, max(1, int(item.packaging.get('cpuTargetPercent') or 70)))
        service_type = str(item.packaging.get('serviceType') or 'ClusterIP')
        discovered_ports: list[int] = []
        for resource in item.resources:
            if resource.type != 'http': continue
            try:
                port = int(resource.config.get('port') or 0)
                if 1 <= port <= 65535: discovered_ports.append(port)
            except (TypeError, ValueError): pass
        container_port = int(item.packaging.get('containerPort') or (discovered_ports[0] if discovered_ports else 8787))
        public_properties = [value for value in properties if value.get('data_type') != 'password']
        config_data = '\n'.join(f'  {value["key"]}: {json.dumps(str(value.get("value", "")))}' for value in public_properties) or '  {}'
        secret_data = '\n'.join(f'  {key}: ""' for key in secret_keys) or '  {}'
        if 'dockerfile' in selected_artifacts:
            files['deployment/cloud/Dockerfile'] = (f'''FROM integration-fabric-runtime:latest
LABEL org.opencontainers.image.title="{artifact}" org.opencontainers.image.version="{version}"
COPY application /opt/integration-fabric/application
COPY environments /opt/integration-fabric/environments
ENV FABRIC_ENVIRONMENT={environment} FABRIC_APPLICATION_DIR=/opt/integration-fabric/application
EXPOSE {container_port}
USER 10001
ENTRYPOINT ["integration-fabric-runtime"]
''').encode()
        if 'configmap' in selected_artifacts:
            files['deployment/cloud/configmap.yaml'] = f'''apiVersion: v1
kind: ConfigMap
metadata:
  name: {deployment_name}-config
  labels:
    app.kubernetes.io/name: {deployment_name}
    app.kubernetes.io/version: {json.dumps(version)}
data:
{config_data}
'''.encode()
        if 'secret' in selected_artifacts:
            files['deployment/cloud/secret.yaml'] = f'''apiVersion: v1
kind: Secret
metadata:
  name: {deployment_name}-secrets
type: Opaque
stringData:
{secret_data}
'''.encode()
        if 'deployment' in selected_artifacts:
            env_from = ''
            if 'configmap' in selected_artifacts: env_from += f'            - configMapRef:\n                name: {deployment_name}-config\n'
            if 'secret' in selected_artifacts: env_from += f'            - secretRef:\n                name: {deployment_name}-secrets\n'
            # Keep escape sequences outside the replacement field so this
            # module remains valid on the Python 3.11 desktop build runtime.
            env_from_yaml = env_from or '            []\n'
            files['deployment/cloud/deployment.yaml'] = f'''apiVersion: apps/v1
kind: Deployment
metadata:
  name: {deployment_name}
  labels:
    app.kubernetes.io/name: {deployment_name}
spec:
  replicas: {replicas}
  selector:
    matchLabels:
      app.kubernetes.io/name: {deployment_name}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {deployment_name}
    spec:
      containers:
        - name: runtime
          image: {image}
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: {container_port}
          env:
            - name: FABRIC_ENVIRONMENT
              value: {json.dumps(environment)}
            - name: FABRIC_APPLICATION_DIR
              value: /opt/integration-fabric/application
          envFrom:
{env_from_yaml}          readinessProbe:
            tcpSocket:
              port: http
            initialDelaySeconds: 5
          livenessProbe:
            tcpSocket:
              port: http
            initialDelaySeconds: 15
          resources:
            requests: {{cpu: 100m, memory: 256Mi}}
            limits: {{cpu: "1", memory: 1Gi}}
'''.encode()
        if 'service' in selected_artifacts:
            files['deployment/cloud/service.yaml'] = f'''apiVersion: v1
kind: Service
metadata:
  name: {deployment_name}
spec:
  type: {service_type}
  selector:
    app.kubernetes.io/name: {deployment_name}
  ports:
    - name: http
      port: {container_port}
      targetPort: http
'''.encode()
        if 'hpa' in selected_artifacts:
            files['deployment/cloud/hpa.yaml'] = f'''apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {deployment_name}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {deployment_name}
  minReplicas: {minimum_replicas}
  maxReplicas: {maximum_replicas}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {cpu_target}
'''.encode()
        if 'package' in selected_artifacts:
            resources = [f'{name}.yaml' for name in ('configmap', 'secret', 'deployment', 'service', 'hpa') if name in selected_artifacts]
            resource_lines = '\n'.join(f'  - {name}' for name in resources) or '  []'
            files['deployment/cloud/kustomization.yaml'] = f'''apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
{resource_lines}
commonLabels:
  app.kubernetes.io/managed-by: integration-fabric
'''.encode()
            files['deployment/cloud/package.json'] = json.dumps({'image': image, 'environment': environment, 'artifacts': sorted(selected_artifacts)}, indent=2).encode()
    else:
        instances = max(1, int(item.packaging.get('instances') or 1))
        start_on_boot = str(item.packaging.get('startOnBoot') or 'false').lower() in ('true', '1', 'yes', 'on')
        shutdown_seconds = max(1, int(item.packaging.get('gracefulShutdownSeconds') or 60))
        install_root = str(item.packaging.get('installRoot') or f'/opt/integration-fabric/apps/{artifact}')
        if 'application' in selected_artifacts:
            files['deployment/on-prem/application.json'] = json.dumps({
                'application': artifact, 'version': version, 'environment': environment,
                'engine': 'isolated', 'instances': instances, 'startOnBoot': start_on_boot,
                'gracefulShutdownSeconds': shutdown_seconds, 'secretProvider': 'administrator',
                'installRoot': install_root,
            }, indent=2).encode()
        if 'environment' in selected_artifacts:
            files['deployment/on-prem/environment.properties'] = ('\n'.join(f'{value["key"]}={value.get("value", "")}' for value in properties if value.get('data_type') != 'password') + '\n').encode()
        if 'administrator' in selected_artifacts:
            files['deployment/on-prem/deploy.sh'] = f'''#!/usr/bin/env sh
set -eu
fabric-admin deploy --application {artifact} --version {version} --environment {environment} --package "$1"
fabric-admin scale --application {artifact} --instances {instances}
{'fabric-admin start --application ' + artifact if start_on_boot else '# Start manually with: fabric-admin start --application ' + artifact}
'''.encode()
        if 'systemd' in selected_artifacts:
            files[f'deployment/on-prem/{deployment_name}.service'] = f'''[Unit]
Description=Integration Fabric {artifact}
After=network-online.target
[Service]
Type=simple
User=integration-fabric
WorkingDirectory={install_root}
Environment=FABRIC_ENVIRONMENT={environment}
ExecStart=/usr/local/bin/integration-fabric-runtime --application {install_root}/application
TimeoutStopSec={shutdown_seconds}
Restart=on-failure
[Install]
WantedBy=multi-user.target
'''.encode()
        if 'install' in selected_artifacts:
            files['deployment/on-prem/install.sh'] = f'''#!/usr/bin/env sh
set -eu
install -d -m 0750 "{install_root}"
cp -R application environments "{install_root}/"
echo "Install required secrets listed in deployment/secrets.required.json before starting."
'''.encode()
        if 'readme' in selected_artifacts:
            files['deployment/on-prem/README.txt'] = f'''Integration Fabric on-premises deployment
Application: {artifact}
Version: {version}
Environment: {environment}
Instances: {instances}
Install root: {install_root}

1. Supply values listed in deployment/secrets.required.json through Administrator.
2. Run install.sh, or import application.json through Integration Fabric Administrator.
3. Run deploy.sh with this package path and start the application when ready.
'''.encode()
    return files

def multi_environment_package_files(item: Project, target: str, environments: list[str], artifacts: set[str] | None = None) -> dict[str, bytes]:
    """Build one immutable application with independently deployable environment profiles."""
    selected = list(dict.fromkeys(value.strip() for value in environments if value.strip()))
    if not selected: raise HTTPException(400, 'Select at least one packaging environment')
    unknown = [value for value in selected if value not in item.properties]
    if unknown: raise HTTPException(400, f'Unknown environments: {", ".join(unknown)}')
    if len(selected) == 1: return deployment_package_files(item, target, selected[0], artifacts)
    profiles = {environment: deployment_package_files(item, target, environment, artifacts) for environment in selected}
    first = profiles[selected[0]]
    files = {name: body for name, body in first.items() if not name.startswith('deployment/') and not name.startswith('environments/')}
    project_payload = json.loads(files['application/project.json'])
    project_payload['properties'] = {}
    required_by_environment: dict[str, list[str]] = {}
    for environment, generated in profiles.items():
        properties = json.loads(generated[f'environments/{environment}.json'])
        project_payload['properties'][environment] = properties
        files[f'environments/{environment}.json'] = generated[f'environments/{environment}.json']
        required = json.loads(generated['deployment/secrets.required.json']).get('required', [])
        required_by_environment[environment] = required
        profile_root = f'deployment/{target}/profiles/{environment}'
        source_root = f'deployment/{target}/'
        for name, body in generated.items():
            if not name.startswith(source_root): continue
            relative = name[len(source_root):]
            if target == 'cloud' and relative == 'Dockerfile':
                files['deployment/cloud/Dockerfile'] = body
            else: files[f'{profile_root}/{relative}'] = body
        files[f'{profile_root}/secrets.required.json'] = json.dumps({'environment': environment, 'required': required}, indent=2).encode()
    files['application/project.json'] = json.dumps(project_payload, indent=2).encode()
    files['deployment/secrets.required.json'] = json.dumps({'profiles': required_by_environment}, indent=2).encode()
    manifest = json.loads(files['manifest.json'])
    manifest.pop('environment', None); manifest['environments'] = selected; manifest['profileLayout'] = f'deployment/{target}/profiles/<environment>'
    manifest['secretKeysByEnvironment'] = required_by_environment
    files['manifest.json'] = json.dumps(manifest, indent=2).encode()
    return files

@app.get('/api/projects/{project_id}/package')
def package_project(project_id: str, target: str = 'on-prem', environment: str = 'local', environments: str = '', starters: str = '', archive: str = 'ifpkg', artifacts: str = ''):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    selected_starters = [value.strip() for value in starters.split(',') if value.strip()] if starters else None
    item, root_tasks, included_tasks = packaging_task_closure(item, selected_starters)
    selected_artifacts = {value.strip() for value in artifacts.split(',') if value.strip()} if artifacts else None
    selected_environments = [value.strip() for value in environments.split(',') if value.strip()] if environments else [environment]
    files = multi_environment_package_files(item, target, selected_environments, selected_artifacts)
    manifest = json.loads(files['manifest.json']); manifest['starterTaskIds'] = root_tasks; manifest['includedTaskIds'] = included_tasks
    files['manifest.json'] = json.dumps(manifest, indent=2).encode()
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
    if resource.type == 'jdbc':
        try: return await __import__('asyncio').to_thread(jdbc_adapter.test, cfg)
        except Exception as exc: return {'ok':False,'message':str(exc)}
    if resource.type == 'snowflake':
        try: return await __import__('asyncio').to_thread(snowflake_adapter.test, cfg)
        except Exception as exc: return {'ok':False,'message':str(exc)}
    if resource.type == 'amqp':
        try:
            timeout = min(60.0, max(3.0, float(cfg.get('connectionTimeoutMsec') or 30000) / 1000 + 1))
            return await asyncio.wait_for(asyncio.to_thread(amqp_adapter.test, cfg), timeout=timeout)
        except asyncio.TimeoutError: return {'ok':False,'message':'AMQP connection test timed out. Verify the endpoint, port, TLS, and firewall settings.'}
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
    if resource.type in ('ems', 'jms'):
        try:
            required = {'JMS connection URL':cfg.get('serverUrl'), 'Username':cfg.get('username'), 'Password':cfg.get('password')}
            is_jndi = str(cfg.get('connectionFactoryType', 'Direct')).lower() == 'jndi'
            if is_jndi:
                required.update({'JNDI context factory':cfg.get('jndiContextFactory'), 'JNDI provider URL':cfg.get('jndiProviderUrl'), 'JNDI username':cfg.get('jndiUsername'), 'JNDI password':cfg.get('jndiPassword'), 'JNDI connection factory':cfg.get('connectionFactory')})
            missing = [name for name, value in required.items() if not str(value or '').strip()]
            if missing: return {'ok':False,'message':f"Required connection values are missing: {', '.join(missing)}"}
            output = await asyncio.to_thread(test_jms, cfg)
            output['message'] = f'{resource.type.upper()} native JMS connection succeeded'
            return output
        except JavaBridgeError as exc: return {'ok':False,'message':f'{resource.type.upper()} connection failed: {exc}'}
        except Exception as exc: return {'ok':False,'message':f'{resource.type.upper()} connection failed: {exc}'}
    if resource.type == 'kafka':
        try:
            from confluent_kafka.admin import AdminClient
            if not str(cfg.get('bootstrapServers') or '').strip(): return {'ok':False,'message':'Kafka bootstrap servers are required'}
            settings = {'bootstrap.servers':cfg['bootstrapServers'], 'client.id':cfg.get('clientId') or f'integration-fabric-{uuid4()}'}
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
            def test_pubsub():
                kwargs, project_id = pubsub_client_configuration(cfg)
                publisher = pubsub_v1.PublisherClient(**kwargs)
                try:
                    iterator = publisher.list_topics(request={'project':f"projects/{project_id}", 'page_size':1}, timeout=float(cfg.get('connectionTimeoutSeconds') or 30)); next(iter(iterator), None)
                finally: publisher.transport.close()
                return pubsub_credential_summary(cfg)
            timeout = min(60.0, max(3.0, float(cfg.get('connectionTimeoutSeconds') or 30)))
            identity = await asyncio.wait_for(asyncio.to_thread(test_pubsub), timeout=timeout + 1)
            principal = f" as {identity['clientEmail']}" if identity.get('clientEmail') else ''
            return {'ok':True,'message':f"Google Pub/Sub connection succeeded for project {identity['projectId']}{principal}"}
        except asyncio.TimeoutError: return {'ok':False,'message':'Google Pub/Sub connection test timed out. Verify credentials, endpoint, proxy, and firewall settings.'}
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

@app.post('/api/jdbc/metadata')
async def jdbc_metadata(payload: dict):
    try:
        resource = SharedResource.model_validate(payload.get('resource') or {})
        if resource.type != 'jdbc': raise ValueError('A JDBC shared connection is required')
        return await __import__('asyncio').to_thread(jdbc_adapter.metadata, resource.config)
    except Exception as exc: raise HTTPException(400, f'Unable to retrieve JDBC metadata: {exc}')

@app.post('/api/jdbc/test-query')
async def jdbc_test_query(payload: dict):
    try:
        resource = SharedResource.model_validate(payload.get('resource') or {})
        if resource.type != 'jdbc': raise ValueError('A JDBC shared connection is required')
        config = dict(payload.get('config') or {}); config['operation'] = payload.get('operation') or config.get('operation') or 'query'
        return await __import__('asyncio').to_thread(jdbc_adapter.execute, resource.config, config)
    except Exception as exc: raise HTTPException(400, f'JDBC test failed: {exc}')

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
            if isinstance(rule.get('whens'), list):
                rule['whens'] = [{
                    **branch,
                    'condition': re.sub(r'\$\{[^}]+\}', lambda match: test_path(match.group(0)), str(branch.get('condition') or '')),
                    'source': test_path(branch['source']) if isinstance(branch.get('source'), str) and branch['source'].startswith('${') else branch.get('source'),
                } for branch in rule['whens']]
            normalized.append(rule)
        options = {**(payload.get('options') or {}), 'validateOutput': False}
        if payload.get('targetSchema'): options = {**options, 'targetSchema': payload.get('targetSchema')}
        if payload.get('targetSchemaText'): options = {**options, 'targetSchemaText': payload.get('targetSchemaText')}
        output = execute_mapping(payload.get('input', {}), normalized, options)
        schema = payload.get('targetSchema') or payload.get('targetSchemaText')
        errors = validate_output(output, schema) if schema and (payload.get('options') or {}).get('validateOutput', True) else []
        active = [rule for rule in normalized if rule.get('enabled', True)]
        mapped_targets = sorted({str(rule.get('target')) for rule in active if rule.get('target')})
        return {'output': output, 'valid': not errors, 'validationErrors': errors, 'mappingCount': len(active), 'mappedTargets': mapped_targets, 'diagnostics': {'mappedTargetCount': len(mapped_targets), 'loopCount': len([rule for rule in active if rule.get('operator') in ('for-each', 'for-each-group')]), 'conditionalCount': len([rule for rule in active if rule.get('operator') in ('if', 'when-otherwise', 'choose')])}}
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
async def start_debug(project_id: str, http_request: Request, request: DebugRequest):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    task_id = request.task_id or item.active_task_id
    properties = {prop.key: prop.value for prop in item.properties.get(request.environment, [])}
    try:
        view = debugger.start(item, task_id, request.input, {resource.id:resource for resource in item.resources}, properties, request.breakpoints, request.environment)
        task = next(value for value in item.tasks if value.id == task_id)
        endpoints = _listener_endpoints(item, task, request.environment, str(http_request.base_url).rstrip('/'))
        events = effective_event_activities(task.activities, task.transitions)
        event = events[0] if len(events) == 1 else None
        if event and _is_continuous_event(event):
            endpoints = [_event_subscription(item, task, event, request.environment)]
        state = debugger.sessions[view['sessionId']]
        runtime_states.setdefault(project_id, {})['environment'] = request.environment
        state['endpoints'] = endpoints
        state['logs'][:] = _lifecycle_logs(item, endpoints) + state['logs']
        append_project_logs(project_id, item.name, state['logs'], _project_log_directory(item, request.environment))
        state['persistedLogCount'] = len(state['logs'])
        if event and _is_continuous_event(event):
            _start_continuous_listener(item, task, event, request.environment, view['sessionId'])
        return debugger.view(state)
    except ValueError as exc: raise HTTPException(400, str(exc))

@app.post('/api/debug/{session_id}/action')
async def debug_action(session_id: str, request: DebugAction):
    try:
        view = await debugger.action(session_id, request.action)
        state = debugger.sessions[session_id]
        project = state['project']
        if request.action == 'stop':
            active = active_runs.get(project.id)
            if active and not active.done(): active.cancel()
        cursor = int(state.get('persistedLogCount', 0))
        append_project_logs(project.id, project.name, state['logs'][cursor:], _project_log_directory(project, state.get('environment', 'local')))
        state['persistedLogCount'] = len(state['logs'])
        return view
    except ValueError as exc: raise HTTPException(404, str(exc))

@app.get('/api/debug/{session_id}')
def debug_state(session_id: str):
    state = debugger.sessions.get(session_id)
    if not state: raise HTTPException(404, 'Debug session not found')
    return debugger.view(state)

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
    append_project_logs(project_id, item.name, result.logs, _project_log_directory(item, environment))
    _publish_runtime_state(project_id, status='listening' if result.status == 'completed' else 'failed', logs=combined_logs[-500:], result=result, environment=environment)
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
