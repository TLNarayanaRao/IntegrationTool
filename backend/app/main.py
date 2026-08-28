import io, json, socket, zipfile
import re
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from .models import DebugAction, DebugRequest, Project, RunRequest, SharedResource, effective_event_activities
from .store import delete_project, get_project, list_projects, project_dir, save_project
from .runtime import WorkflowRuntime
from .debugger import DebugManager
from .mapper import execute as execute_mapping, recommend
from .sap import sap_adapter

app = FastAPI(title='Integration Fabric Runtime', version='0.1.0')
runtime = WorkflowRuntime()
debugger = DebugManager(runtime)

@app.get('/api/health')
def health(): return {'status': 'ok', 'runtime': 'python'}

@app.get('/api/projects', response_model=list[Project])
def projects(): return list_projects()

@app.get('/api/projects/{project_id}', response_model=Project)
def project(project_id: str):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    return item

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
async def run(project_id: str, request: RunRequest):
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
    return await runtime.run(task, request.input, resources, properties, project=item)

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
    if resource.type == 'sap_tid' and cfg.get('mode','none') == 'none': return {'ok':True,'message':'SAP TID duplicate management is disabled'}
    if resource.type == 'sap_tid' and cfg.get('driver','sqlite') == 'sqlite':
        import sqlite3
        conn = sqlite3.connect(cfg.get('url','sap-tid.db')); conn.execute('CREATE TABLE IF NOT EXISTS sap_tid (tid TEXT PRIMARY KEY, state TEXT, updated_at TEXT)'); conn.close(); return {'ok':True,'message':'SAP TID Manager database is ready'}
    if resource.type == 'http':
        import httpx
        async with httpx.AsyncClient(timeout=float(cfg.get('timeout',5))) as client: response = await client.get(cfg.get('baseUrl') or cfg.get('url'))
        return {'ok': response.status_code < 500, 'message': f'HTTP endpoint returned {response.status_code}'}
    if resource.type == 'sap':
        try: return await __import__('asyncio').to_thread(sap_adapter.test, cfg)
        except Exception as exc: return {'ok':False,'message':str(exc)}
    host = cfg.get('host') or cfg.get('bootstrapServers','').split(',')[0].split(':')[0] or cfg.get('emulatorHost','').split(':')[0]
    port = cfg.get('port') or (cfg.get('bootstrapServers','').split(',')[0].split(':')[1] if ':' in cfg.get('bootstrapServers','') else None) or (cfg.get('emulatorHost','').split(':')[1] if ':' in cfg.get('emulatorHost','') else None)
    if host and port:
        await __import__('asyncio').to_thread(lambda: socket.create_connection((host, int(port)), timeout=float(cfg.get('timeout',5))).close())
        return {'ok':True,'message':f'Connected to {host}:{port}'}
    return {'ok':False,'message':'Save the required host/URL fields before testing'}

@app.post('/api/mapper/suggest')
def mapper_suggest(payload: dict):
    return {'recommendations': recommend(payload.get('sourceSchema',{}), payload.get('targetSchema',{}), float(payload.get('threshold',70))/100, payload.get('weights'))}

@app.post('/api/mapper/test')
def mapper_test(payload: dict):
    try: return {'output':execute_mapping(payload.get('input',{}), payload.get('mappings',[])), 'valid':True}
    except Exception as exc: raise HTTPException(400, f'Mapping failed: {exc}')

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
def start_debug(project_id: str, request: DebugRequest):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    task_id = request.task_id or item.active_task_id
    properties = {prop.key: prop.value for prop in item.properties.get(request.environment, [])}
    try: return debugger.start(item, task_id, request.input, {resource.id:resource for resource in item.resources}, properties, request.breakpoints)
    except ValueError as exc: raise HTTPException(400, str(exc))

@app.post('/api/debug/{session_id}/action')
async def debug_action(session_id: str, request: DebugAction):
    try: return await debugger.action(session_id, request.action)
    except ValueError as exc: raise HTTPException(404, str(exc))

@app.api_route('/api/listeners/{project_id}/{listener_path:path}', methods=['GET','POST','PUT','PATCH','DELETE'])
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
    matched = next(((task, activity, match_path(activity.config.get('path', '/'))) for task, activity in candidates if match_path(activity.config.get('path', '/')) is not None and (request.method in str(activity.config.get('methods', activity.config.get('method', request.method))).replace(' ', '').split(',') or (activity.type == 'soap' and request.method == 'GET' and 'wsdl' in request.query_params))), None)
    task, listener, path_parameters = matched if matched else (None, None, {})
    if not listener: raise HTTPException(404, f'No listener configured for {request.method} {request_path}')
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
    resources = {resource.id: resource for resource in item.resources}; properties = {prop.key: prop.value for prop in item.properties.get(environment, [])}
    result = await runtime.run(task, payload, resources, properties, listener.id, item)
    if result.status == 'failed': return JSONResponse({'status': result.status, 'logs': result.logs}, status_code=500)
    output = result.output
    if output.get('__httpResponse'):
        body = output.get('body'); headers = output.get('headers', {}); status = output.get('statusCode', 200)
        return JSONResponse(body, status_code=status, headers=headers) if isinstance(body, (dict, list)) else Response(str(body or ''), status_code=status, headers=headers)
    return JSONResponse(output)

static_dir = Path(__file__).parents[2] / 'frontend' / 'dist'
if static_dir.exists(): app.mount('/', StaticFiles(directory=static_dir, html=True), name='studio')
