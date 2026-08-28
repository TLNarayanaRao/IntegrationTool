import json, sqlite3
from pathlib import Path
from .models import Project

DB_PATH = Path(__file__).parents[1] / 'data' / 'fabric.db'

def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
    return conn

def list_projects() -> list[Project]:
    with connection() as conn:
        return [Project.model_validate_json(row['body']) for row in conn.execute('SELECT body FROM projects ORDER BY id')]

def get_project(project_id: str) -> Project | None:
    with connection() as conn:
        row = conn.execute('SELECT body FROM projects WHERE id = ?', (project_id,)).fetchone()
        return Project.model_validate_json(row['body']) if row else None

def save_project(project: Project) -> Project:
    with connection() as conn:
        conn.execute('INSERT INTO projects(id, body) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (project.id, project.model_dump_json()))
    return project
