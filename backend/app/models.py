from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator

ActivityKind = Literal[
    'start', 'http', 'http_listener', 'http_response', 'rest', 'soap',
    'file', 'ftp', 'sftp', 'jdbc', 'snowflake', 'amqp', 'excel', 'xml', 'json', 'flat',
    'mapper', 'dataweave', 'transform', 'ai_transform', 'log', 'confirm', 'catch', 'throw', 'rethrow', 'timer', 'call_task', 'ems', 'jms', 'kafka', 'pubsub', 'sap', 'java', 'python', 'basic', 'end'
]

class SharedResource(BaseModel):
    id: str
    type: Literal['jdbc', 'snowflake', 'amqp', 'ftp', 'sftp', 'http', 'ems', 'jms', 'kafka', 'pubsub', 'sap', 'sap_tid'] = 'jdbc'
    name: str
    config: dict[str, Any] = Field(default_factory=dict)

class Activity(BaseModel):
    id: str
    type: ActivityKind
    name: str
    position: dict[str, float] = Field(default_factory=lambda: {'x': 100, 'y': 100})
    config: dict[str, Any] = Field(default_factory=dict)

class GroupDefinition(BaseModel):
    id: str
    type: Literal['if', 'while', 'for_each', 'iterate', 'repeat', 'repeat_on_error', 'scope', 'none', 'critical_section', 'transaction_jdbc', 'pick_first']
    name: str
    member_activity_ids: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=lambda: {'x': 100, 'y': 100})
    size: dict[str, float] = Field(default_factory=lambda: {'width': 420, 'height': 220})
    parent_group_id: str | None = None

class Transition(BaseModel):
    id: str
    source: str
    target: str
    label: str = ''
    type: Literal['success', 'success_condition', 'success_no_match', 'error'] = 'success'
    condition: str = ''
    color: str = Field(default='', pattern=r'^(#[0-9a-fA-F]{6})?$')

class EnvironmentProperty(BaseModel):
    key: str
    value: Any = ''
    data_type: Literal['string', 'integer', 'long', 'number', 'boolean', 'dateTime', 'password', 'json'] = 'string'

    @model_validator(mode='after')
    def coerce_typed_value(self):
        if self.data_type in ('integer','long') and isinstance(self.value, str) and self.value.strip(): self.value = int(self.value)
        elif self.data_type == 'number' and isinstance(self.value, str) and self.value.strip(): self.value = float(self.value)
        elif self.data_type == 'boolean' and isinstance(self.value, str): self.value = self.value.lower() in ('true','1','yes','on')
        elif self.data_type == 'json' and isinstance(self.value, str) and self.value.strip():
            import json
            self.value = json.loads(self.value)
        return self

def default_environment_properties() -> list[EnvironmentProperty]:
    """Project-global defaults available to every task and shared resource."""
    values = [
        ('runtime.logDirectory', '', 'string'),
        ('advanced.logPayload', False, 'boolean'),
        ('advanced.retryEnabled', False, 'boolean'),
        ('advanced.retryCount', 3, 'integer'),
        ('advanced.retryIntervalSeconds', 60, 'integer'),
        ('advanced.groupMaxIterations', 10000, 'integer'),
    ]
    return [EnvironmentProperty(key=key, value=value, data_type=data_type) for key, value, data_type in values]

class SchemaAsset(BaseModel):
    id: str
    name: str
    content: str

def is_event_activity(activity: Activity) -> bool:
    operation = activity.config.get('operation', '')
    return activity.type in ('start', 'timer', 'http_listener') or \
        (activity.type == 'rest' and operation == 'receiver') or \
        (activity.type == 'soap' and operation == 'service') or \
        (activity.type == 'file' and operation == 'poll') or \
        (activity.type == 'amqp' and operation == 'receive') or \
        (activity.type == 'ems' and operation in ('queue_receiver', 'topic_subscriber')) or \
        (activity.type == 'jms' and operation == 'receive_message') or \
        (activity.type == 'kafka' and operation in ('receive', 'get')) or \
        (activity.type == 'pubsub' and operation == 'subscribe') or \
        (activity.type == 'sap' and operation in ('idoc_listener', 'rfc_bapi_listener'))

def effective_event_activities(activities: list[Activity], transitions: list[Transition] | None = None) -> list[Activity]:
    """Return event activities that are actual task entry points.

    Receiver/get activities may also be used deliberately in the middle of a
    task. Those remain ordinary blocking/polling activities and must not replace
    an explicit root Start activity as the deployed event source.
    """
    incoming = {transition.target for transition in (transitions or [])}
    roots = [activity for activity in activities if activity.id not in incoming]
    candidates = roots if transitions is not None else activities
    external = [activity for activity in candidates if activity.type != 'start' and is_event_activity(activity)]
    return external or [activity for activity in candidates if activity.type == 'start']

class ProcessDefinition(BaseModel):
    id: str = 'main'
    name: str = 'Main Process'
    activities: list[Activity] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    groups: list[GroupDefinition] = Field(default_factory=list)

    @model_validator(mode='after')
    def enforce_single_event_activity(self):
        events = effective_event_activities(self.activities, self.transitions)
        if len(events) > 1:
            raise ValueError(f'A Task can contain only one event activity; found: {", ".join(activity.name for activity in events)}')
        catch_ids = {activity.id for activity in self.activities if activity.type == 'catch'}
        if any(transition.target in catch_ids for transition in self.transitions):
            raise ValueError('Transitions cannot target a Catch activity; Catch is entered only by an unhandled exception')
        activity_ids = {activity.id for activity in self.activities}
        if len(activity_ids) != len(self.activities):
            raise ValueError('Activity identifiers must be unique within a Task')
        transition_ids = {transition.id for transition in self.transitions}
        if len(transition_ids) != len(self.transitions):
            raise ValueError('Transition identifiers must be unique within a Task')
        for transition in self.transitions:
            if transition.source not in activity_ids or transition.target not in activity_ids:
                raise ValueError(f'Transition {transition.id} references a missing activity')
        group_ids = {group.id for group in self.groups}
        if len(group_ids) != len(self.groups):
            raise ValueError('Group identifiers must be unique within a Task')
        owners: dict[str, str] = {}
        for group in self.groups:
            missing = set(group.member_activity_ids) - activity_ids
            if missing:
                raise ValueError(f'Group {group.name} references missing activities: {", ".join(sorted(missing))}')
            if group.parent_group_id and group.parent_group_id not in group_ids:
                raise ValueError(f'Group {group.name} references a missing parent group')
            if group.parent_group_id == group.id:
                raise ValueError(f'Group {group.name} cannot contain itself')
            for activity_id in group.member_activity_ids:
                if activity_id in owners:
                    raise ValueError(f'Activity {activity_id} belongs directly to more than one group')
                owners[activity_id] = group.id
                member = next(activity for activity in self.activities if activity.id == activity_id)
                if member.type in ('start', 'end', 'catch') or is_event_activity(member):
                    raise ValueError(f'Group {group.name} cannot directly contain starter, End, or Catch activity {member.name}')
        parents = {group.id: group.parent_group_id for group in self.groups}
        for group_id in group_ids:
            visited: set[str] = set()
            current: str | None = group_id
            while current:
                if current in visited:
                    raise ValueError('Nested groups contain a parent cycle')
                visited.add(current); current = parents.get(current)
        return self

class TaskDefinition(ProcessDefinition):
    kind: Literal['starter', 'subtask'] = 'starter'
    description: str = ''
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

def find_subtask(tasks: list[TaskDefinition], reference: str) -> TaskDefinition | None:
    subtasks = [task for task in tasks if task.kind == 'subtask']
    exact = next((task for task in subtasks if task.id == reference), None)
    if exact:
        return exact
    exact = next((task for task in subtasks if task.name.casefold() == reference.casefold()), None)
    if exact:
        return exact
    # Existing dynamic inputs may still contain spaces from before Studio normalized display names.
    key = '-'.join(reference.split()).casefold()
    matches = [task for task in subtasks if '-'.join(task.name.split()).casefold() == key]
    return matches[0] if len(matches) == 1 else None

class CustomFunction(BaseModel):
    id: str
    name: str
    parameters: list[str] = Field(default_factory=list)
    expression: str
    description: str = ''

class Project(BaseModel):
    id: str
    name: str
    description: str = ''
    resources: list[SharedResource] = Field(default_factory=list)
    packaging: dict[str, Any] = Field(default_factory=lambda: {
        'artifact_name': '', 'version': '1.0.0', 'format': 'mpkg',
        'target': 'on-prem', 'environment': 'production'
    })
    schemas: list[SchemaAsset] = Field(default_factory=list)
    custom_functions: list[CustomFunction] = Field(default_factory=list)
    properties: dict[str, list[EnvironmentProperty]] = Field(default_factory=lambda: {
        name: default_environment_properties() for name in ('local', 'dev', 'qa', 'pre', 'production')
    })
    active_environment: str = 'local'
    tasks: list[TaskDefinition] = Field(default_factory=list)
    active_task_id: str = ''
    # Retained in exported JSON for compatibility with projects created before Tasks.
    process: ProcessDefinition | None = None

    @model_validator(mode='after')
    def migrate_process_to_tasks(self):
        defaults = default_environment_properties()
        for environment in ('local', 'dev', 'qa', 'pre', 'production'):
            current = self.properties.setdefault(environment, [])
            existing = {item.key for item in current}
            current.extend(item.model_copy(deep=True) for item in defaults if item.key not in existing)
        if not self.tasks and self.process:
            self.tasks = [TaskDefinition(**self.process.model_dump(), kind='starter')]
        if not self.tasks:
            self.tasks = [TaskDefinition(
                id='main', name='Main Subtask', kind='subtask',
                activities=[
                    Activity(id='Start', name='Start', type='start', position={'x': 70, 'y': 150}),
                    Activity(id='End', name='End', type='end', position={'x': 350, 'y': 150}),
                ],
                transitions=[Transition(id='main-edge', source='Start', target='End')],
            )]
        if not self.active_task_id or not any(task.id == self.active_task_id for task in self.tasks):
            self.active_task_id = self.tasks[0].id
        active = next(task for task in self.tasks if task.id == self.active_task_id)
        self.process = ProcessDefinition(**active.model_dump(include={'id','name','activities','transitions','groups'}))
        return self

class RunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    environment: str = 'local'
    task_id: str | None = None

class AIBuildRequest(BaseModel):
    requirement: str = Field(min_length=10, max_length=20000)
    scope: Literal['task', 'project'] = 'task'
    current_task: dict[str, Any] | None = None

class DebugRequest(RunRequest):
    test_mode: bool = False
    breakpoints: list[str] = Field(default_factory=list)
    breakpoint_conditions: dict[str, str] = Field(default_factory=dict)
    watches: list[str] = Field(default_factory=list)
    pause_on_error: bool = True

class DebugAction(BaseModel):
    action: Literal['continue', 'pause', 'step_in', 'step_over', 'step_out', 'jump_in', 'jump_out', 'run_to', 'configure', 'evaluate', 'set_value', 'preview_activity', 'test_activity', 'mock_step', 'stop']
    activity_id: str | None = None
    task_id: str | None = None
    expression: str | None = None
    path: str | None = None
    value: Any = None
    fields: dict[str, Any] = Field(default_factory=dict)
    assertion: str = ''
    timeout_seconds: float = Field(default=10, ge=0.1, le=60)
    breakpoints: list[str] | None = None
    breakpoint_conditions: dict[str, str] | None = None
    watches: list[str] | None = None
    pause_on_error: bool | None = None

class RunResult(BaseModel):
    run_id: str
    correlation_id: str = ''
    started_at: str = ''
    ended_at: str = ''
    duration_ms: float = 0
    status: Literal['completed', 'failed']
    output: dict[str, Any]
    logs: list[dict[str, Any]]
    activity_outputs: dict[str, Any] = Field(default_factory=dict)
    task_outputs: dict[str, Any] = Field(default_factory=dict)
