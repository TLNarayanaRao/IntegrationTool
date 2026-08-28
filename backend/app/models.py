from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator

ActivityKind = Literal[
    'start', 'http', 'http_listener', 'http_response', 'rest', 'soap',
    'file', 'ftp', 'sftp', 'jdbc', 'xml', 'json', 'flat',
    'transform', 'log', 'timer', 'call_task', 'ems', 'kafka', 'pubsub', 'sap', 'java', 'end'
]

class SharedResource(BaseModel):
    id: str
    type: Literal['jdbc', 'ftp', 'sftp', 'http', 'ems', 'kafka', 'pubsub', 'sap', 'sap_tid'] = 'jdbc'
    name: str
    config: dict[str, Any] = Field(default_factory=dict)

class Activity(BaseModel):
    id: str
    type: ActivityKind
    name: str
    position: dict[str, float] = Field(default_factory=lambda: {'x': 100, 'y': 100})
    config: dict[str, Any] = Field(default_factory=dict)

class Transition(BaseModel):
    id: str
    source: str
    target: str
    label: str = ''
    type: Literal['success', 'success_condition', 'success_no_match', 'error'] = 'success'
    condition: str = ''

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
        ('advanced.logPayload', False, 'boolean'),
        ('advanced.retryEnabled', False, 'boolean'),
        ('advanced.retryCount', 3, 'integer'),
        ('advanced.retryIntervalSeconds', 60, 'integer'),
        ('connections.http.baseUrl', 'https://api.example.com', 'string'),
        ('connections.http.connectTimeoutSeconds', 30, 'integer'),
        ('connections.http.timeoutSeconds', 60, 'integer'),
        ('connections.http.username', '', 'string'),
        ('connections.http.password', '', 'password'),
        ('connections.http.proxyHost', '', 'string'),
        ('connections.http.proxyPort', 8080, 'integer'),
        ('connections.http.verifyTls', True, 'boolean'),
        ('connections.ftp.host', 'ftp.example.com', 'string'),
        ('connections.ftp.port', 21, 'integer'),
        ('connections.ftp.username', '', 'string'),
        ('connections.ftp.password', '', 'password'),
        ('connections.ftp.workingDirectory', '/', 'string'),
        ('connections.ftp.passiveMode', True, 'boolean'),
        ('connections.ftp.timeoutSeconds', 60, 'integer'),
        ('connections.sftp.host', 'sftp.example.com', 'string'),
        ('connections.sftp.port', 22, 'integer'),
        ('connections.sftp.username', '', 'string'),
        ('connections.sftp.password', '', 'password'),
        ('connections.sftp.workingDirectory', '/', 'string'),
        ('connections.sftp.privateKeyFile', '', 'string'),
        ('connections.sftp.privateKeyPassphrase', '', 'password'),
        ('connections.sftp.knownHostsFile', '', 'string'),
        ('connections.sftp.strictHostKeyChecking', True, 'boolean'),
        ('connections.sftp.timeoutSeconds', 60, 'integer'),
        ('connections.jdbc.driver', 'postgresql', 'string'),
        ('connections.jdbc.url', 'jdbc:postgresql://localhost:5432/integration', 'string'),
        ('connections.jdbc.host', 'localhost', 'string'),
        ('connections.jdbc.port', 5432, 'integer'),
        ('connections.jdbc.database', 'integration', 'string'),
        ('connections.jdbc.schema', 'public', 'string'),
        ('connections.jdbc.username', '', 'string'),
        ('connections.jdbc.password', '', 'password'),
        ('connections.jdbc.timeoutSeconds', 30, 'integer'),
        ('connections.jdbc.minimumPoolSize', 1, 'integer'),
        ('connections.jdbc.maximumPoolSize', 10, 'integer'),
        ('connections.ems.host', 'localhost', 'string'),
        ('connections.ems.port', 7222, 'integer'),
        ('connections.ems.serverUrl', 'tcp://localhost:7222', 'string'),
        ('connections.ems.username', '', 'string'),
        ('connections.ems.password', '', 'password'),
        ('connections.ems.clientId', 'integration-fabric', 'string'),
        ('connections.ems.connectionFactory', 'ConnectionFactory', 'string'),
        ('connections.ems.reconnectAttempts', 3, 'integer'),
        ('connections.kafka.bootstrapServers', 'localhost:9092', 'string'),
        ('connections.kafka.clientId', 'integration-fabric', 'string'),
        ('connections.kafka.groupId', 'integration-fabric', 'string'),
        ('connections.kafka.securityProtocol', 'PLAINTEXT', 'string'),
        ('connections.kafka.saslMechanism', 'PLAIN', 'string'),
        ('connections.kafka.username', '', 'string'),
        ('connections.kafka.password', '', 'password'),
        ('connections.kafka.requestTimeoutMilliseconds', 30000, 'integer'),
        ('connections.pubsub.projectId', 'my-gcp-project', 'string'),
        ('connections.pubsub.credentialsFile', '', 'string'),
        ('connections.pubsub.endpoint', 'pubsub.googleapis.com:443', 'string'),
        ('connections.pubsub.emulatorHost', '', 'string'),
        ('connections.pubsub.ackDeadlineSeconds', 60, 'integer'),
        ('connections.sap.applicationServerHost', 'sap-ecc.example.com', 'string'),
        ('connections.sap.systemNumber', '00', 'string'),
        ('connections.sap.client', '100', 'string'),
        ('connections.sap.language', 'EN', 'string'),
        ('connections.sap.username', '', 'string'),
        ('connections.sap.password', '', 'password'),
        ('connections.sap.messageServerHost', '', 'string'),
        ('connections.sap.systemId', '', 'string'),
        ('connections.sap.logonGroup', 'PUBLIC', 'string'),
        ('connections.sap.sapRouter', '', 'string'),
        ('connections.sap.programId', '', 'string'),
        ('connections.sap.gatewayHost', '', 'string'),
        ('connections.sap.gatewayService', '', 'string'),
        ('connections.sap.maximumConnections', 8, 'integer'),
        ('connections.sap.timeoutMilliseconds', 30000, 'integer'),
        ('connections.sapTid.storageFile', 'data/sap-tids.json', 'string'),
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
        (activity.type == 'ems' and operation in ('queue_receiver', 'topic_subscriber')) or \
        (activity.type == 'kafka' and operation in ('receive', 'get')) or \
        (activity.type == 'pubsub' and operation == 'subscribe') or \
        (activity.type == 'sap' and operation in ('idoc_listener', 'rfc_bapi_listener'))

def effective_event_activities(activities: list[Activity]) -> list[Activity]:
    """Treat Start as the manual trigger only when no external listener exists."""
    external = [activity for activity in activities if activity.type != 'start' and is_event_activity(activity)]
    return external or [activity for activity in activities if activity.type == 'start']

class ProcessDefinition(BaseModel):
    id: str = 'main'
    name: str = 'Main Process'
    activities: list[Activity] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)

    @model_validator(mode='after')
    def enforce_single_event_activity(self):
        events = effective_event_activities(self.activities)
        if len(events) > 1:
            raise ValueError(f'A Task can contain only one event activity; found: {", ".join(activity.name for activity in events)}')
        return self

class TaskDefinition(ProcessDefinition):
    kind: Literal['starter', 'subtask'] = 'starter'
    description: str = ''
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

class Project(BaseModel):
    id: str
    name: str
    description: str = ''
    resources: list[SharedResource] = Field(default_factory=list)
    packaging: dict[str, Any] = Field(default_factory=lambda: {
        'artifact_name': '', 'version': '1.0.0', 'format': 'zip'
    })
    schemas: list[SchemaAsset] = Field(default_factory=list)
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
            self.tasks = [TaskDefinition(id='main', name='Main Task', kind='starter')]
        if not self.active_task_id or not any(task.id == self.active_task_id for task in self.tasks):
            self.active_task_id = self.tasks[0].id
        active = next(task for task in self.tasks if task.id == self.active_task_id)
        self.process = ProcessDefinition(**active.model_dump(include={'id','name','activities','transitions'}))
        return self

class RunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    environment: str = 'local'
    task_id: str | None = None

class DebugRequest(RunRequest):
    breakpoints: list[str] = Field(default_factory=list)

class DebugAction(BaseModel):
    action: Literal['continue', 'pause', 'step_in', 'step_over', 'step_out', 'jump_in', 'jump_out', 'stop']

class RunResult(BaseModel):
    run_id: str
    status: Literal['completed', 'failed']
    output: dict[str, Any]
    logs: list[dict[str, Any]]
