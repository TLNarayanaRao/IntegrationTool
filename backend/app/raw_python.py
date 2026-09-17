"""Export a deliberately independent, executable Python application.

This compiler does not serialize the Fabric project model into Python.  Each
task becomes an async state machine and uses only the small generated Python
support library.  Unsupported activity semantics are rejected at build time.
"""
from __future__ import annotations

import re
from pathlib import Path


SUPPORTED = {
    ('start', ''), ('end', ''), ('log', ''), ('mapper', ''),
    ('call_task', ''), ('catch', ''), ('throw', ''), ('rethrow', ''),
    ('basic', 'empty'), ('basic', 'assign'), ('basic', 'sleep'),
    ('kafka', 'publish'), ('kafka', 'receive'),
    ('pubsub', 'publish'), ('pubsub', 'pull'),
}


def _identifier(value: str) -> str:
    result = re.sub(r'[^A-Za-z0-9_]', '_', value).strip('_') or 'task'
    return f'_{result}' if result[0].isdigit() else result


def validate_raw_python(project: dict) -> None:
    failures: list[str] = []
    task_ids = {task['id'] for task in project['tasks']}
    for task in project['tasks']:
        if task.get('groups'):
            failures.append(f"{task['name']}: groups are not yet supported by the independent Python compiler")
        for activity in task.get('activities', []):
            kind = str(activity['type'])
            operation = str(activity.get('config', {}).get('operation') or ('empty' if kind == 'basic' else ''))
            if (kind, operation) not in SUPPORTED:
                failures.append(f"{task['name']} / {activity['name']}: {kind}/{operation or 'default'}")
            if kind == 'call_task' and str(activity.get('config', {}).get('taskId') or '') not in task_ids:
                failures.append(f"{task['name']} / {activity['name']}: Call Sub Task needs a static taskId")
            if kind == 'mapper':
                mappings = activity.get('config', {}).get('mappings') or []
                rules = [{'target': key, 'source': value} for key, value in mappings.items()] if isinstance(mappings, dict) else mappings
                for rule in rules:
                    if not isinstance(rule, dict) or any(rule.get(key) for key in ('operator', 'condition', 'whens', 'select', 'function')):
                        failures.append(f"{task['name']} / {activity['name']}: advanced mapping rules are not yet supported")
                        break
            if kind in {'kafka', 'pubsub'} and operation in {'receive', 'pull'} and task.get('kind') == 'starter' and task['activities'] and task['activities'][0]['id'] == activity['id']:
                failures.append(f"{task['name']} / {activity['name']}: continuous event starters are not yet supported by the independent Python compiler")
        outgoing: dict[str, int] = {}
        for edge in task.get('transitions', []):
            if edge.get('type', 'success') == 'success':
                outgoing[edge['source']] = outgoing.get(edge['source'], 0) + 1
            if edge.get('type') == 'success_condition' and str(edge.get('condition') or '').strip() not in ('true', 'false') and not re.fullmatch(r'\$\{[^}]+\}', str(edge.get('condition') or '')):
                failures.append(f"{task['name']}: conditional transition {edge.get('id', '')} needs a simple boolean field expression")
        if any(count > 1 for count in outgoing.values()):
            failures.append(f"{task['name']}: parallel success branches are not yet supported")
    if failures:
        raise ValueError('Raw Python export cannot preserve these behaviors yet: ' + '; '.join(failures))


def raw_python_files(project: dict, profiles: dict[str, list[dict]]) -> dict[str, bytes]:
    validate_raw_python(project)
    root = Path(__file__).with_name('raw_python_support')
    files = {
        f'application/{name}': (root / name).read_bytes()
        for name in ('__init__.py', 'core.py', 'connectors.py', 'main.py')
    }
    files['application/tasks/__init__.py'] = b'"""Generated async tasks."""\n'
    task_modules: dict[str, str] = {}
    for index, task in enumerate(project['tasks']):
        module = f'task_{index}_{_identifier(str(task["id"]))}'
        task_modules[task['id']] = module
    files['application/config.py'] = (
        '"""Typed, sanitized deployment configuration. Secrets come from environment variables."""\n'
        'from dataclasses import dataclass, field\nfrom typing import Any\nimport json\nimport os\n\n'
        '@dataclass(frozen=True)\nclass Property:\n    key: str\n    value: Any\n    data_type: str = "string"\n\n'
        '@dataclass(frozen=True)\nclass Resource:\n    id: str\n    type: str\n    name: str\n    config: dict[str, Any] = field(default_factory=dict)\n\n'
        '@dataclass(frozen=True)\nclass Schema:\n    name: str\n    content: str\n\n'
        f'PROFILES = {repr(profiles)}\n'
        f'RESOURCES = {repr({r["id"]: r for r in project["resources"]})}\n'
        f'SCHEMAS = {{name: Schema(name, content) for name, content in {repr({s["name"]: s["content"] for s in project.get("schemas", [])})}.items()}}\n\n'
        'def environment(name: str) -> tuple[dict[str, Any], dict[str, Resource]]:\n'
        '    if name not in PROFILES:\n        raise ValueError(f"Unknown environment: {name}")\n'
        '    properties = {}\n'
        '    for item in PROFILES[name]:\n'
        '        prop = Property(**item)\n'
        '        value = os.environ.get(prop.key, prop.value)\n'
        '        if prop.data_type in ("integer", "long") and value not in (None, ""): value = int(value)\n'
        '        elif prop.data_type == "number" and value not in (None, ""): value = float(value)\n'
        '        elif prop.data_type == "boolean" and isinstance(value, str): value = value.lower() in ("true", "1", "yes", "on")\n'
        '        elif prop.data_type == "json" and isinstance(value, str) and value: value = json.loads(value)\n'
        '        properties[prop.key] = value\n'
        '    resources = {}\n'
        '    for key, record in RESOURCES.items():\n'
        '        config = dict(record["config"])\n'
        '        for field in config:\n'
        '            secret_key = f"resources.{key}.config.{field}"\n'
        '            if secret_key in os.environ: config[field] = os.environ[secret_key]\n'
        '        resources[key] = Resource(record["id"], record["type"], record["name"], config)\n'
        '    return properties, resources\n'
    ).encode('utf-8')
    task_imports = '\n'.join(f'from .tasks import {module}' for module in task_modules.values())
    registry = ', '.join(f'{task_id!r}: {module}.run' for task_id, module in task_modules.items())
    files['application/registry.py'] = (
        '"""Generated task registry; callable from notebooks or another Python host."""\n'
        f'{task_imports}\nTASKS = {{{registry}}}\n'
        f'STARTERS = {repr([task["id"] for task in project["tasks"] if task["kind"] == "starter"])}\n'
    ).encode('utf-8')
    for task in project['tasks']:
        activities = {activity['id']: activity for activity in task['activities']}
        incoming = {edge['target'] for edge in task['transitions']}
        starts = [activity['id'] for activity in task['activities'] if activity['type'] == 'start'] or [activity['id'] for activity in task['activities'] if activity['id'] not in incoming and activity['type'] != 'catch']
        if len(starts) != 1:
            raise ValueError(f"Raw Python task {task['name']} needs exactly one entry activity")
        for edge in task['transitions']:
            if edge['source'] not in activities or edge['target'] not in activities:
                raise ValueError(f"Raw Python task {task['name']} contains a dangling transition")
        lines = [
            '"""Direct async implementation of this Integration Fabric task."""',
            'from application.core import Context, execute_with_policy, choose_transition',
            '',
            f'TASK_ID = {task["id"]!r}',
            f'TASK_NAME = {task["name"]!r}',
            f'TRANSITIONS = {repr(task["transitions"])}',
            '',
            'async def run(ctx: Context):',
            f'    current = {starts[0]!r}',
            '    steps = 0',
            '    while current is not None:',
            '        steps += 1',
            '        if steps > 100000:',
            '            raise RuntimeError(f"Task {TASK_NAME} exceeded its execution step limit")',
            '        try:',
        ]
        for index, activity in enumerate(task['activities']):
            prefix = 'if' if index == 0 else 'elif'
            config = activity.get('config') or {}
            lines.extend([
                f'            {prefix} current == {activity["id"]!r}:',
                f'                result = await execute_with_policy({activity["type"]!r}, {repr(config)}, ctx, {activity["id"]!r}, {activity["name"]!r})',
            ])
        lines.extend([
            '            else:',
            '                raise RuntimeError(f"Unknown activity {current!r} in {TASK_NAME}")',
            '        except Exception as error:',
            '            ctx.error = error',
            '            current = choose_transition(TRANSITIONS, current, ctx, error=error)',
            '            if current is None:',
            '                raise',
            '        else:',
            '            ctx.record(current, result)',
            '            if current in END_IDS:',
            '                return result',
            '            current = choose_transition(TRANSITIONS, current, ctx)',
            '    return ctx.last',
            '',
            f'END_IDS = {repr([activity["id"] for activity in task["activities"] if activity["type"] == "end"])}',
            '',
        ])
        files[f'application/tasks/{task_modules[task["id"]]}.py'] = ('\n'.join(lines)).encode('utf-8')
    for name, body in files.items():
        if name.endswith('.py'):
            try:
                compile(body, name, 'exec')
            except SyntaxError as error:
                raise ValueError(f'Generated Python is invalid in {name}: {error}') from error
    return files


ENGINE_MODULES = (
    'models.py', 'runtime.py', 'mapper.py', 'dataweave.py', 'sap.py',
    'snowflake.py', 'jdbc.py', 'amqp.py', 'java_bridge.py',
    'google_pubsub.py', 'time_utils.py',
)


def engine_python_files(project: dict, profiles: dict[str, list[dict]]) -> dict[str, bytes]:
    """Compile every persisted activity/group to Python model constructors.

    The bundled engine is the exact Python execution implementation used by
    Studio, including its SAP JCo and EMS/JMS bridges. Vendor runtimes/JARs
    remain external licensed dependencies of the target data plane.
    """
    source_root = Path(__file__).parent
    support = source_root / 'raw_python_support'
    files: dict[str, bytes] = {
        'application/__init__.py': (support / '__init__.py').read_bytes(),
        'application/main.py': (support / 'engine_main.py').read_bytes(),
        'application/tasks/__init__.py': b'"""Generated task modules."""\n',
        'application/engine/__init__.py': b'"""Bundled Python execution engine."""\n',
    }
    for name in ENGINE_MODULES:
        files[f'application/engine/{name}'] = (source_root / name).read_bytes()
    task_imports: list[str] = []
    task_calls: list[str] = []
    for index, task in enumerate(project['tasks']):
        module = f'task_{index}_{_identifier(str(task["id"]))}'
        task_imports.append(f'from .tasks.{module} import build_task as build_task_{index}')
        task_calls.append(f'build_task_{index}()')
        attributes = {key: value for key, value in task.items() if key not in {'activities', 'transitions', 'groups'}}
        activities = ',\n        '.join(
            f'Activity(**{repr(activity)})' for activity in task['activities'])
        transitions = ',\n        '.join(
            f'Transition(**{repr(edge)})' for edge in task['transitions'])
        groups = ',\n        '.join(
            f'GroupDefinition(**{repr(group)})' for group in task.get('groups', []))
        files[f'application/tasks/{module}.py'] = (
            '"""Generated Python definition and async entry for this task."""\n'
            'from application.engine.models import Activity, GroupDefinition, TaskDefinition, Transition\n'
            'from application.engine.runtime import WorkflowRuntime\n\n'
            'def build_task() -> TaskDefinition:\n'
            f'    return TaskDefinition(**{repr(attributes)},\n'
            f'        activities=[{activities}],\n'
            f'        transitions=[{transitions}],\n'
            f'        groups=[{groups}])\n\n'
            'async def run(initial=None, *, resources=None, properties=None, project=None):\n'
            '    """Run this task directly from a notebook or Python caller."""\n'
            '    return await WorkflowRuntime().run(build_task(), initial or {}, resources or {}, properties or {}, project=project)\n'
        ).encode('utf-8')
    project_fields = {key: value for key, value in project.items()
                      if key not in {'tasks', 'resources', 'schemas', 'properties', 'custom_functions', 'process'}}
    resources = ',\n        '.join(f'SharedResource(**{repr(value)})' for value in project['resources'])
    schemas = ',\n        '.join(f'SchemaAsset(**{repr(value)})' for value in project.get('schemas', []))
    functions = ',\n        '.join(f'CustomFunction(**{repr(value)})' for value in project.get('custom_functions', []))
    profile_lines = ',\n        '.join(
        f'{name!r}: [{", ".join(f"EnvironmentProperty(**{repr(value)})" for value in values)}]'
        for name, values in profiles.items())
    files['application/project.py'] = (
        '"""Python-only, typed project assembly; no project/task/resource JSON."""\n'
        'from .engine.models import CustomFunction, EnvironmentProperty, Project, SchemaAsset, SharedResource\n'
        + '\n'.join(task_imports) + '\n\n'
        'def build_project() -> Project:\n'
        f'    return Project(**{repr(project_fields)},\n'
        f'        resources=[{resources}],\n'
        f'        schemas=[{schemas}],\n'
        f'        custom_functions=[{functions}],\n'
        f'        properties={{ {profile_lines} }},\n'
        f'        tasks=[{", ".join(task_calls)}])\n'
    ).encode('utf-8')
    for name, body in files.items():
        if name.endswith('.py'):
            try: compile(body, name, 'exec')
            except SyntaxError as error:
                raise ValueError(f'Generated Python is invalid in {name}: {error}') from error
    return files
