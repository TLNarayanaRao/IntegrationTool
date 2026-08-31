from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator

ActivityKind = Literal[
    'start', 'http', 'http_listener', 'http_response', 'rest', 'soap',
    'file', 'ftp', 'sftp', 'jdbc', 'snowflake', 'xml', 'json', 'flat',
    'mapper', 'dataweave', 'transform', 'ai_transform', 'log', 'confirm', 'catch', 'throw', 'rethrow', 'timer', 'call_task', 'ems', 'kafka', 'pubsub', 'sap', 'java', 'python', 'basic', 'end'
]

class SharedResource(BaseModel):
    id: str
    type: Literal['jdbc', 'snowflake', 'ftp', 'sftp', 'http', 'ems', 'kafka', 'pubsub', 'sap', 'sap_tid'] = 'jdbc'
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
        ('connections.http.host', 'localhost', 'string'),
        ('connections.http.port', 8080, 'integer'),
        ('connections.http.basePath', '', 'string'),
        ('connections.http.scheme', 'http', 'string'),
        ('connections.http.connectorMode', 'both', 'string'),
        ('connections.http.authentication', 'None', 'string'),
        ('connections.http.bearerToken', '', 'password'),
        ('connections.http.tlsEnabled', False, 'boolean'),
        ('connections.http.certificateFile', '', 'string'),
        ('connections.http.privateKeyFile', '', 'string'),
        ('connections.http.privateKeyPassword', '', 'password'),
        ('connections.http.certificateAuthorityFile', '', 'string'),
        ('connections.http.clientAuthentication', 'none', 'string'),
        ('connections.http.tlsVersion', 'TLSv1.2', 'string'),
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
        ('connections.snowflake.mode', 'external', 'string'),
        ('connections.snowflake.authenticationType', 'Username/Password', 'string'),
        ('connections.snowflake.provider', 'Snowflake', 'string'),
        ('connections.snowflake.account', '', 'string'),
        ('connections.snowflake.username', '', 'string'),
        ('connections.snowflake.password', '', 'password'),
        ('connections.snowflake.warehouse', '', 'string'),
        ('connections.snowflake.database', '', 'string'),
        ('connections.snowflake.schema', 'PUBLIC', 'string'),
        ('connections.snowflake.role', '', 'string'),
        ('connections.snowflake.loginTimeoutSeconds', 60, 'integer'),
        ('connections.snowflake.minimumConnections', 2, 'integer'),
        ('connections.snowflake.maximumConnections', 8, 'integer'),
        ('connections.snowflake.maximumConnectionWaitSeconds', 300, 'integer'),
        ('connections.snowflake.serviceThreads', 8, 'integer'),
        ('connections.ems.host', 'localhost', 'string'),
        ('connections.ems.port', 7222, 'integer'),
        ('connections.ems.serverUrl', 'tcp://localhost:7222', 'string'),
        ('connections.ems.username', '', 'string'),
        ('connections.ems.password', '', 'password'),
        ('connections.ems.clientId', 'integration-fabric', 'string'),
        ('connections.ems.connectionFactory', 'ConnectionFactory', 'string'),
        ('connections.ems.reconnectAttempts', 3, 'integer'),
        ('connections.ems.connectionFactoryType', 'Direct', 'string'),
        ('connections.ems.messagingStyle', 'Generic', 'string'),
        ('connections.ems.queueConnectionFactory', 'QueueConnectionFactory', 'string'),
        ('connections.ems.topicConnectionFactory', 'TopicConnectionFactory', 'string'),
        ('connections.ems.jndiContextFactory', 'com.tibco.tibjms.naming.TibjmsInitialContextFactory', 'string'),
        ('connections.ems.jndiProviderUrl', 'tcp://localhost:7222', 'string'),
        ('connections.ems.jndiUsername', '', 'string'), ('connections.ems.jndiPassword', '', 'password'),
        ('connections.ems.useXa', False, 'boolean'), ('connections.ems.useUfo', False, 'boolean'),
        ('connections.ems.sslEnabled', False, 'boolean'), ('connections.ems.sslTrustedCertificates', '', 'string'),
        ('connections.ems.reconnectDelayMs', 5000, 'integer'), ('connections.ems.heartbeatOutgoingMs', 0, 'integer'), ('connections.ems.heartbeatIncomingMs', 0, 'integer'),
        ('connections.kafka.bootstrapServers', 'localhost:9092', 'string'),
        ('connections.kafka.clientId', 'integration-fabric', 'string'),
        ('connections.kafka.groupId', 'integration-fabric', 'string'),
        ('connections.kafka.securityProtocol', 'PLAINTEXT', 'string'),
        ('connections.kafka.saslMechanism', 'PLAIN', 'string'),
        ('connections.kafka.username', '', 'string'),
        ('connections.kafka.password', '', 'password'),
        ('connections.kafka.requestTimeoutMilliseconds', 30000, 'integer'),
        ('connections.kafka.connectionTimeoutMilliseconds', 10000, 'integer'),
        ('connections.kafka.sslCaLocation', '', 'string'), ('connections.kafka.sslCertificateLocation', '', 'string'),
        ('connections.kafka.sslKeyLocation', '', 'string'), ('connections.kafka.sslKeyPassword', '', 'password'),
        ('connections.kafka.schemaRegistryUrl', '', 'string'), ('connections.kafka.schemaRegistryUsername', '', 'string'), ('connections.kafka.schemaRegistryPassword', '', 'password'),
        ('connections.pubsub.projectId', 'my-gcp-project', 'string'),
        ('connections.pubsub.credentialsFile', '', 'string'),
        ('connections.pubsub.endpoint', 'pubsub.googleapis.com:443', 'string'),
        ('connections.pubsub.emulatorHost', '', 'string'),
        ('connections.pubsub.ackDeadlineSeconds', 60, 'integer'),
        ('connections.pubsub.connectionTimeoutSeconds', 30, 'integer'),
        ('connections.pubsub.maxInboundMessageBytes', 20971520, 'integer'), ('connections.pubsub.keepAliveSeconds', 60, 'integer'),
        ('connections.sap.applicationServerHost', 'sap-ecc.example.com', 'string'),
        ('connections.sap.release', 'current', 'string'),
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
        catch_ids = {activity.id for activity in self.activities if activity.type == 'catch'}
        if any(transition.target in catch_ids for transition in self.transitions):
            raise ValueError('Transitions cannot target a Catch activity; Catch is entered only by an unhandled exception')
        return self

class TaskDefinition(ProcessDefinition):
    kind: Literal['starter', 'subtask'] = 'starter'
    description: str = ''
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

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
        'artifact_name': '', 'version': '1.0.0', 'format': 'ifpkg',
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

class AIBuildRequest(BaseModel):
    requirement: str = Field(min_length=10, max_length=20000)
    scope: Literal['task', 'project'] = 'task'
    current_task: dict[str, Any] | None = None

class DebugRequest(RunRequest):
    breakpoints: list[str] = Field(default_factory=list)

class DebugAction(BaseModel):
    action: Literal['continue', 'pause', 'step_in', 'step_over', 'step_out', 'jump_in', 'jump_out', 'stop']

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
