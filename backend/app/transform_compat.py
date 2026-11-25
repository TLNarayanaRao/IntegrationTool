"""Read persisted Transformer identifiers from earlier MINA releases."""

LEGACY_SCRIPT_KIND = 'data' + 'weave'
LEGACY_FAULTS = {
    LEGACY_SCRIPT_KIND.upper() + '_' + suffix: 'SCRIPT_TRANSFORM_' + suffix
    for suffix in ('SYNTAX', 'EXECUTION', 'OUTPUT')
}


def normalize_transform_activity(activity):
    if not isinstance(activity, dict):
        return activity
    normalized = activity
    if activity.get('type') == LEGACY_SCRIPT_KIND:
        normalized = {**activity, 'type': 'script_transform'}
    config = activity.get('config')
    fault = config.get('errorType') if isinstance(config, dict) else None
    if isinstance(fault, str) and fault in LEGACY_FAULTS:
        normalized = {**normalized, 'config': {**config, 'errorType': LEGACY_FAULTS[fault]}}
    return normalized


def normalize_transform_project(project):
    tasks = project.get('tasks')
    if not isinstance(tasks, list):
        return project
    return {**project, 'tasks': [
        {**task, 'activities': [normalize_transform_activity(activity) for activity in task.get('activities', [])]}
        for task in tasks
    ]}
