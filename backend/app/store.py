import json, os, re, shutil, sqlite3
from pathlib import Path
from .models import Project

DATA_DIR = Path(os.environ.get('FABRIC_DATA_DIR', Path(__file__).parents[1] / 'data')).expanduser().resolve()
PROJECTS_DIR = DATA_DIR / 'projects'
LEGACY_DB = DATA_DIR / 'fabric.db'

def safe_component(value: str) -> str:
    if not value or not re.fullmatch(r'[A-Za-z0-9_.-]+', value) or value in ('.','..'):
        raise ValueError('Identifiers may contain only letters, numbers, dot, dash, and underscore')
    return value

def project_dir(project_id: str) -> Path:
    safe = safe_component(project_id)
    root = PROJECTS_DIR.resolve(); target = (PROJECTS_DIR / safe).resolve()
    if target.parent != root: raise ValueError('Invalid project id')
    return target

def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)

def supports_outbound_retry(activity) -> bool:
    operation = str(activity.config.get('operation') or '')
    if activity.type in ('http', 'jdbc', 'snowflake', 'amqp', 'ftp', 'sftp'): return True
    if activity.type in ('ems', 'jms'): return operation in ('send', 'publish', 'request_reply', 'reply', 'send_message', 'reply_message')
    if activity.type == 'kafka': return operation in ('send', 'publish', 'get')
    if activity.type == 'pubsub': return operation == 'publish'
    if activity.type == 'rest': return operation == 'invoke'
    if activity.type == 'soap': return operation == 'request_reply'
    if activity.type == 'sap': return operation in ('idoc_acknowledgment', 'idoc_confirmation', 'post_idoc', 'invoke_rfc_bapi', 'reply_rfc_bapi', 'read_table')
    return False

def clean_activity_policies(project: Project) -> None:
    for task in project.tasks:
        for activity in task.activities:
            if supports_outbound_retry(activity): continue
            advanced = activity.config.get('advanced')
            if not isinstance(advanced, dict): continue
            for key in ('retryEnabled', 'retryCount', 'retryIntervalSeconds'): advanced.pop(key, None)

def save_project(project: Project) -> Project:
    clean_activity_policies(project)
    folder = project_dir(project.id); tasks_dir = folder / 'tasks'; resources_dir = folder / 'resources'
    metadata = project.model_dump(exclude={'tasks','resources','process'})
    write_json(folder / 'project.json', metadata)
    active_task_files = set()
    for task in project.tasks:
        path = tasks_dir / f'{safe_component(task.id)}.json'; write_json(path, task.model_dump()); active_task_files.add(path.resolve())
    active_resource_files = set()
    for resource in project.resources:
        path = resources_dir / f'{safe_component(resource.id)}.json'; write_json(path, resource.model_dump()); active_resource_files.add(path.resolve())
    for path in tasks_dir.glob('*.json') if tasks_dir.exists() else []:
        if path.resolve() not in active_task_files: path.unlink()
    for path in resources_dir.glob('*.json') if resources_dir.exists() else []:
        if path.resolve() not in active_resource_files: path.unlink()
    return project

def get_project(project_id: str) -> Project | None:
    folder = project_dir(project_id); descriptor = folder / 'project.json'
    if not descriptor.exists():
        migrated = legacy_project(project_id)
        if migrated: save_project(migrated)
        return migrated
    metadata = json.loads(descriptor.read_text(encoding='utf-8'))
    metadata['tasks'] = [json.loads(path.read_text(encoding='utf-8')) for path in sorted((folder/'tasks').glob('*.json'))] if (folder/'tasks').exists() else []
    metadata['resources'] = [json.loads(path.read_text(encoding='utf-8')) for path in sorted((folder/'resources').glob('*.json'))] if (folder/'resources').exists() else []
    return Project.model_validate(metadata)

def list_projects() -> list[Project]:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects = [item for folder in sorted(PROJECTS_DIR.iterdir()) if folder.is_dir() and (item := get_project(folder.name))]
    known = {item.id for item in projects}
    for item in legacy_projects():
        if item.id not in known: save_project(item); projects.append(item)
    return sorted(projects, key=lambda item: item.name.lower())

def delete_project(project_id: str) -> bool:
    folder = project_dir(project_id)
    deleted = folder.exists()
    if deleted: shutil.rmtree(folder)
    if LEGACY_DB.exists():
        try:
            with sqlite3.connect(LEGACY_DB) as conn:
                cursor = conn.execute('DELETE FROM projects WHERE id = ?', (project_id,))
                deleted = deleted or cursor.rowcount > 0
        except sqlite3.Error: pass
    return deleted

def legacy_projects() -> list[Project]:
    if not LEGACY_DB.exists(): return []
    try:
        with sqlite3.connect(LEGACY_DB) as conn:
            return [Project.model_validate_json(row[0]) for row in conn.execute('SELECT body FROM projects')]
    except (sqlite3.Error, ValueError): return []

def legacy_project(project_id: str) -> Project | None:
    return next((item for item in legacy_projects() if item.id == project_id), None)
