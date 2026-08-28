from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from .models import Project, RunRequest
from .store import get_project, list_projects, save_project
from .runtime import WorkflowRuntime

app = FastAPI(title='Integration Fabric Runtime', version='0.1.0')
runtime = WorkflowRuntime()

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

@app.post('/api/projects/{project_id}/run')
async def run(project_id: str, request: RunRequest):
    item = get_project(project_id)
    if not item: raise HTTPException(404, 'Project not found')
    return await runtime.run(item.process, request.input)

static_dir = Path(__file__).parents[2] / 'frontend' / 'dist'
if static_dir.exists(): app.mount('/', StaticFiles(directory=static_dir, html=True), name='studio')
