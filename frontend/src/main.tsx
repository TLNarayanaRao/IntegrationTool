import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlignHorizontalSpaceAround,
  AlignVerticalSpaceAround,
  ArrowDown,
  ArrowUp,
  Braces,
  Bug,
  Cable,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CirclePlay,
  ClipboardCopy,
  ClipboardPaste,
  Cloud,
  CodeXml,
  Database,
  Download,
  FilePlus2,
  Folder,
  FolderOpen,
  Globe,
  HardDrive,
  MessageSquare,
  Package,
  Pause,
  Plus,
  Radio,
  Save,
  Search,
  Scissors,
  Settings2,
  ShieldCheck,
  SkipBack,
  SkipForward,
  Square,
  Trash2,
  Undo2,
  Upload,
  Redo2,
  Workflow,
} from "lucide-react";
import SchemaStudio, { SchemaDoc } from "./SchemaStudio";
import ActivityEditor from "./ActivityEditor";
import ActivityPicker from "./ActivityPicker";
import "./styles.css";
import "./designer.css";
import "./properties.css";
import "./transition-fix.css";
import "./activity-packs.css";
import "./studio-shell.css";
import "./schema-studio.css";
import "./task-runtime.css";
import "./themes.css";
import "./activity-editor.css";
import "./explorer-enhancements.css";
import "./mapper-studio.css";
import "./popup-enhancements.css";
import "./mapping-fixes.css";
import "./messaging-enhancements.css";
import "./studio-ribbon.css";
import "./packaging-target.css";
type Kind =
  | "start"
  | "timer"
  | "call_task"
  | "http"
  | "http_listener"
  | "http_response"
  | "rest"
  | "soap"
  | "file"
  | "ftp"
  | "sftp"
  | "jdbc"
  | "xml"
  | "json"
  | "flat"
  | "transform"
  | "log"
  | "confirm"
  | "ems"
  | "kafka"
  | "pubsub"
  | "sap"
  | "java"
  | "end";
type Node = {
  id: string;
  type: Kind;
  name: string;
  position: { x: number; y: number };
  config: Record<string, any>;
};
type Edge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  type?: "success" | "success_condition" | "success_no_match" | "error";
  condition?: string;
};
type Task = {
  id: string;
  name: string;
  kind: "starter" | "subtask";
  description?: string;
  activities: Node[];
  transitions: Edge[];
  input_schema?: Record<string, any>;
  output_schema?: Record<string, any>;
};
type Resource = {
  id: string;
  type:
    | "jdbc"
    | "ftp"
    | "sftp"
    | "http"
    | "ems"
    | "kafka"
    | "pubsub"
    | "sap"
    | "sap_tid";
  name: string;
  config: Record<string, any>;
};
type Property = {
  key: string;
  value: any;
  data_type:
    | "string"
    | "integer"
    | "long"
    | "number"
    | "boolean"
    | "dateTime"
    | "password"
    | "json";
};
type Project = {
  id: string;
  name: string;
  description: string;
  resources: Resource[];
  packaging: Record<string, any>;
  schemas: SchemaDoc[];
  properties: Record<string, Property[]>;
  active_environment: string;
  tasks: Task[];
  active_task_id: string;
  process?: any;
};
type Def = { type: Kind; operation?: string; label: string; asset: string };
type ValidationIssue = {
  id: string;
  severity: "error" | "warning" | "mapping";
  category: string;
  message: string;
  remedy: string;
  taskId?: string;
  activityId?: string;
};
const themeOptions = [
  { value: "midnight", label: "Midnight Studio", detail: "Deep blue professional workspace" },
  { value: "aurora", label: "Aurora Glass", detail: "Violet glass with teal highlights" },
  { value: "graphite", label: "Graphite Pro", detail: "Neutral engineering workstation" },
  { value: "arctic", label: "Arctic Light", detail: "Clean light enterprise canvas" },
  { value: "ocean", label: "Oceanic", detail: "Layered blue operations center" },
  { value: "forest", label: "Evergreen", detail: "Low-glare green integration studio" },
  { value: "sunset", label: "Sunset Copper", detail: "Warm copper and plum workspace" },
  { value: "classic", label: "Classic Office", detail: "Square, bright desktop application" },
  { value: "contrast", label: "High Contrast", detail: "Maximum clarity and accessibility" },
];
const isEventActivity = (item: { type: Kind; operation?: string; config?: Record<string, any> }) => {
  const operation = item.operation || item.config?.operation || "";
  return item.type === "start" || item.type === "timer" || item.type === "http_listener" ||
    (item.type === "rest" && operation === "receiver") || (item.type === "soap" && operation === "service") ||
    (item.type === "file" && operation === "poll") ||
    (item.type === "ems" && ["queue_receiver", "topic_subscriber"].includes(operation)) ||
    (item.type === "kafka" && ["receive", "get"].includes(operation)) ||
    (item.type === "pubsub" && operation === "subscribe") ||
    (item.type === "sap" && ["idoc_listener", "rfc_bapi_listener"].includes(operation));
};
const ai = (asset: string) => (
  <img src={`/activity-icons/${asset}.png`} alt="" />
);
const packs: { name: string; icon: any; items: Def[] }[] = [
  {
    name: "Starters & Tasks",
    icon: Workflow,
    items: [
      {
        type: "timer",
        operation: "schedule",
        label: "Timer / Scheduler",
        asset: "timer",
      },
      {
        type: "call_task",
        operation: "call",
        label: "Call Sub Task",
        asset: "call-task",
      },
    ],
  },
  {
    name: "File",
    icon: HardDrive,
    items: [
      ["read", "Read File", "FileRead"],
      ["write", "Write File", "FileWrite"],
      ["list", "List Files", "file-list"],
      ["delete", "Delete File", "file-delete"],
      ["rename", "Rename File", "file-rename"],
      ["copy", "Copy File", "file-copy"],
      ["poll", "File Poller", "file-poller"],
    ].map(
      ([operation, label, asset]) =>
        ({ type: "file", operation, label, asset }) as Def,
    ),
  },
  {
    name: "FTP",
    icon: Globe,
    items: [
      ["get", "FTP Get", "ftp-get"],
      ["put", "FTP Put", "ftp-put"],
      ["delete", "FTP Delete", "ftp-delete"],
      ["dir", "FTP Directory", "ftp-dir"],
      ["change_dir", "FTP Change Directory", "ftp-change-dir"],
    ].map(
      ([operation, label, asset]) =>
        ({ type: "ftp", operation, label, asset }) as Def,
    ),
  },
  {
    name: "SFTP",
    icon: Globe,
    items: [
      ["get", "SFTP Get", "sftp-get"],
      ["put", "SFTP Put", "sftp-put"],
      ["delete", "SFTP Delete", "sftp-delete"],
      ["dir", "SFTP Directory", "sftp-dir"],
      ["change_dir", "SFTP Change Directory", "sftp-change-dir"],
    ].map(
      ([operation, label, asset]) =>
        ({ type: "sftp", operation, label, asset }) as Def,
    ),
  },
  {
    name: "HTTP & APIs",
    icon: Globe,
    items: [
      {
        type: "http_listener",
        operation: "listen",
        label: "HTTP Listener",
        asset: "http-listener",
      },
      {
        type: "http",
        operation: "request",
        label: "HTTP Request",
        asset: "http-request",
      },
      {
        type: "http_response",
        operation: "response",
        label: "HTTP Response",
        asset: "http-response",
      },
      {
        type: "rest",
        operation: "receiver",
        label: "REST API Receiver",
        asset: "rest-receiver",
      },
      {
        type: "rest",
        operation: "invoke",
        label: "REST API Invoke",
        asset: "rest-invoke",
      },
      {
        type: "soap",
        operation: "service",
        label: "SOAP Service",
        asset: "soap-service",
      },
      {
        type: "soap",
        operation: "request_reply",
        label: "SOAP Request Reply",
        asset: "soap-request-reply",
      },
    ],
  },
  {
    name: "TIBCO EMS",
    icon: MessageSquare,
    items: [
      ["queue_receiver", "EMS Queue Receiver"],
      ["topic_subscriber", "EMS Topic Subscriber"],
      ["send", "EMS Queue Sender"],
      ["publish", "EMS Topic Publisher"],
      ["request_reply", "EMS Request Reply"],
      ["reply", "EMS Reply"],
    ].map(
      ([operation, label]) =>
        ({ type: "ems", operation, label, asset: "ems" }) as Def,
    ),
  },
  {
    name: "Kafka",
    icon: Radio,
    items: [
      ["receive", "Kafka Receive Message"],
      ["publish", "Kafka Send Message"],
      ["get", "Kafka Get Messages"],
    ].map(
      ([operation, label]) =>
        ({ type: "kafka", operation, label, asset: "kafka" }) as Def,
    ),
  },
  {
    name: "GCP Pub/Sub",
    icon: Cloud,
    items: [
      ["subscribe", "Pub/Sub Subscriber"],
      ["publish", "Pub/Sub Publisher"],
    ].map(
      ([operation, label]) =>
        ({ type: "pubsub", operation, label, asset: "pubsub" }) as Def,
    ),
  },
  {
    name: "SAP ECC",
    icon: Database,
    items: [
      ["dynamic_connection", "Dynamic Connection", "sap-dynamic-connection"],
      ["idoc_acknowledgment", "IDoc Acknowledgment", "sap-idoc-ack"],
      ["idoc_confirmation", "IDoc Confirmation", "sap-idoc-confirm"],
      ["idoc_converter", "IDoc Converter", "sap-idoc-converter"],
      ["idoc_listener", "IDoc Listener", "sap-idoc-listener"],
      ["idoc_parser", "IDoc Parser", "sap-idoc-parser"],
      ["idoc_reader", "IDoc Reader", "sap-idoc-reader"],
      ["post_idoc", "Post IDoc to SAP", "sap-post-idoc"],
      ["idoc_renderer", "IDoc Renderer", "sap-idoc-renderer"],
      ["rfc_bapi_listener", "RFC BAPI Listener", "sap-rfc-listener"],
      ["invoke_rfc_bapi", "Invoke RFC BAPI in SAP", "sap-rfc-invoke"],
      ["reply_rfc_bapi", "Reply from RFC BAPI in SAP", "sap-rfc-reply"],
      ["read_table", "Read Table", "sap-read-table"],
    ].map(
      ([operation, label, asset]) =>
        ({ type: "sap", operation, label, asset }) as Def,
    ),
  },
  {
    name: "JDBC",
    icon: Database,
    items: [
      ["insert", "JDBC Create", "JDBC-Create"],
      ["update", "JDBC Update", "JDBC-Update"],
      ["query", "JDBC Query", "JDBC-Query"],
      ["truncate", "JDBC Truncate", "JDBC-Delete"],
      ["delete", "JDBC Delete", "JDBC-Delete"],
      ["call", "Stored Procedure", "JDBC-StoredProc"],
      ["dynamic", "Dynamic SQL", "JDBC-Query"],
    ].map(
      ([operation, label, asset]) =>
        ({ type: "jdbc", operation, label, asset }) as Def,
    ),
  },
  {
    name: "Data",
    icon: CodeXml,
    items: [
      { type: "xml", operation: "parse", label: "Parse XML", asset: "xml" },
      { type: "xml", operation: "render", label: "Render XML", asset: "xml" },
      { type: "json", operation: "parse", label: "Parse JSON", asset: "json" },
      {
        type: "json",
        operation: "render",
        label: "Render JSON",
        asset: "json",
      },
      { type: "flat", operation: "parse", label: "Parse Data", asset: "flat" },
      {
        type: "flat",
        operation: "render",
        label: "Render Data",
        asset: "flat",
      },
    ],
  },
  {
    name: "General",
    icon: Activity,
    items: [
      {
        type: "transform",
        operation: "map",
        label: "Transform",
        asset: "transform",
      },
      { type: "log", operation: "write", label: "Log", asset: "log" },
      { type: "confirm", operation: "acknowledge", label: "Confirm Message", asset: "runtime" },
      {
        type: "java",
        operation: "invoke",
        label: "Java Activity",
        asset: "runtime",
      },
    ],
  },
];
const defaultProperties: Property[] = [
  { key: "advanced.logPayload", value: false, data_type: "boolean" },
  { key: "advanced.retryEnabled", value: false, data_type: "boolean" },
  { key: "advanced.retryCount", value: 3, data_type: "integer" },
  { key: "advanced.retryIntervalSeconds", value: 60, data_type: "integer" },
  { key: "connections.http.baseUrl", value: "https://api.example.com", data_type: "string" },
  { key: "connections.http.host", value: "localhost", data_type: "string" },
  { key: "connections.http.port", value: 8080, data_type: "integer" },
  { key: "connections.http.basePath", value: "", data_type: "string" },
  { key: "connections.http.scheme", value: "http", data_type: "string" },
  { key: "connections.http.connectorMode", value: "both", data_type: "string" },
  { key: "connections.http.authentication", value: "None", data_type: "string" },
  { key: "connections.http.bearerToken", value: "", data_type: "password" },
  { key: "connections.http.tlsEnabled", value: false, data_type: "boolean" },
  { key: "connections.http.certificateFile", value: "", data_type: "string" },
  { key: "connections.http.privateKeyFile", value: "", data_type: "string" },
  { key: "connections.http.privateKeyPassword", value: "", data_type: "password" },
  { key: "connections.http.certificateAuthorityFile", value: "", data_type: "string" },
  { key: "connections.http.clientAuthentication", value: "none", data_type: "string" },
  { key: "connections.http.tlsVersion", value: "TLSv1.2", data_type: "string" },
  { key: "connections.http.connectTimeoutSeconds", value: 30, data_type: "integer" },
  { key: "connections.http.timeoutSeconds", value: 60, data_type: "integer" },
  { key: "connections.http.username", value: "", data_type: "string" },
  { key: "connections.http.password", value: "", data_type: "password" },
  { key: "connections.http.proxyHost", value: "", data_type: "string" },
  { key: "connections.http.proxyPort", value: 8080, data_type: "integer" },
  { key: "connections.http.verifyTls", value: true, data_type: "boolean" },
  { key: "connections.ftp.host", value: "ftp.example.com", data_type: "string" },
  { key: "connections.ftp.port", value: 21, data_type: "integer" },
  { key: "connections.ftp.username", value: "", data_type: "string" },
  { key: "connections.ftp.password", value: "", data_type: "password" },
  { key: "connections.ftp.workingDirectory", value: "/", data_type: "string" },
  { key: "connections.ftp.passiveMode", value: true, data_type: "boolean" },
  { key: "connections.ftp.timeoutSeconds", value: 60, data_type: "integer" },
  { key: "connections.sftp.host", value: "sftp.example.com", data_type: "string" },
  { key: "connections.sftp.port", value: 22, data_type: "integer" },
  { key: "connections.sftp.username", value: "", data_type: "string" },
  { key: "connections.sftp.password", value: "", data_type: "password" },
  { key: "connections.sftp.workingDirectory", value: "/", data_type: "string" },
  { key: "connections.sftp.privateKeyFile", value: "", data_type: "string" },
  { key: "connections.sftp.privateKeyPassphrase", value: "", data_type: "password" },
  { key: "connections.sftp.knownHostsFile", value: "", data_type: "string" },
  { key: "connections.sftp.strictHostKeyChecking", value: true, data_type: "boolean" },
  { key: "connections.sftp.timeoutSeconds", value: 60, data_type: "integer" },
  { key: "connections.jdbc.driver", value: "postgresql", data_type: "string" },
  { key: "connections.jdbc.url", value: "jdbc:postgresql://localhost:5432/integration", data_type: "string" },
  { key: "connections.jdbc.host", value: "localhost", data_type: "string" },
  { key: "connections.jdbc.port", value: 5432, data_type: "integer" },
  { key: "connections.jdbc.database", value: "integration", data_type: "string" },
  { key: "connections.jdbc.schema", value: "public", data_type: "string" },
  { key: "connections.jdbc.username", value: "", data_type: "string" },
  { key: "connections.jdbc.password", value: "", data_type: "password" },
  { key: "connections.jdbc.timeoutSeconds", value: 30, data_type: "integer" },
  { key: "connections.jdbc.minimumPoolSize", value: 1, data_type: "integer" },
  { key: "connections.jdbc.maximumPoolSize", value: 10, data_type: "integer" },
  { key: "connections.ems.host", value: "localhost", data_type: "string" },
  { key: "connections.ems.port", value: 7222, data_type: "integer" },
  { key: "connections.ems.serverUrl", value: "tcp://localhost:7222", data_type: "string" },
  { key: "connections.ems.username", value: "", data_type: "string" },
  { key: "connections.ems.password", value: "", data_type: "password" },
  { key: "connections.ems.clientId", value: "integration-fabric", data_type: "string" },
  { key: "connections.ems.connectionFactory", value: "ConnectionFactory", data_type: "string" },
  { key: "connections.ems.reconnectAttempts", value: 3, data_type: "integer" },
  { key: "connections.ems.connectionFactoryType", value: "Direct", data_type: "string" },
  { key: "connections.ems.messagingStyle", value: "Generic", data_type: "string" },
  { key: "connections.ems.queueConnectionFactory", value: "QueueConnectionFactory", data_type: "string" },
  { key: "connections.ems.topicConnectionFactory", value: "TopicConnectionFactory", data_type: "string" },
  { key: "connections.ems.jndiContextFactory", value: "com.tibco.tibjms.naming.TibjmsInitialContextFactory", data_type: "string" },
  { key: "connections.ems.jndiProviderUrl", value: "tcp://localhost:7222", data_type: "string" },
  { key: "connections.ems.jndiUsername", value: "", data_type: "string" },
  { key: "connections.ems.jndiPassword", value: "", data_type: "password" },
  { key: "connections.ems.useXa", value: false, data_type: "boolean" },
  { key: "connections.ems.useUfo", value: false, data_type: "boolean" },
  { key: "connections.ems.sslEnabled", value: false, data_type: "boolean" },
  { key: "connections.ems.sslTrustedCertificates", value: "", data_type: "string" },
  { key: "connections.ems.reconnectDelayMs", value: 5000, data_type: "integer" },
  { key: "connections.ems.heartbeatOutgoingMs", value: 0, data_type: "integer" },
  { key: "connections.ems.heartbeatIncomingMs", value: 0, data_type: "integer" },
  { key: "connections.kafka.bootstrapServers", value: "localhost:9092", data_type: "string" },
  { key: "connections.kafka.clientId", value: "integration-fabric", data_type: "string" },
  { key: "connections.kafka.groupId", value: "integration-fabric", data_type: "string" },
  { key: "connections.kafka.securityProtocol", value: "PLAINTEXT", data_type: "string" },
  { key: "connections.kafka.saslMechanism", value: "PLAIN", data_type: "string" },
  { key: "connections.kafka.username", value: "", data_type: "string" },
  { key: "connections.kafka.password", value: "", data_type: "password" },
  { key: "connections.kafka.requestTimeoutMilliseconds", value: 30000, data_type: "integer" },
  { key: "connections.kafka.connectionTimeoutMilliseconds", value: 10000, data_type: "integer" },
  { key: "connections.kafka.sslCaLocation", value: "", data_type: "string" },
  { key: "connections.kafka.sslCertificateLocation", value: "", data_type: "string" },
  { key: "connections.kafka.sslKeyLocation", value: "", data_type: "string" },
  { key: "connections.kafka.sslKeyPassword", value: "", data_type: "password" },
  { key: "connections.kafka.schemaRegistryUrl", value: "", data_type: "string" },
  { key: "connections.kafka.schemaRegistryUsername", value: "", data_type: "string" },
  { key: "connections.kafka.schemaRegistryPassword", value: "", data_type: "password" },
  { key: "connections.pubsub.projectId", value: "my-gcp-project", data_type: "string" },
  { key: "connections.pubsub.credentialsFile", value: "", data_type: "string" },
  { key: "connections.pubsub.endpoint", value: "pubsub.googleapis.com:443", data_type: "string" },
  { key: "connections.pubsub.emulatorHost", value: "", data_type: "string" },
  { key: "connections.pubsub.ackDeadlineSeconds", value: 60, data_type: "integer" },
  { key: "connections.pubsub.connectionTimeoutSeconds", value: 30, data_type: "integer" },
  { key: "connections.pubsub.maxInboundMessageBytes", value: 20971520, data_type: "integer" },
  { key: "connections.pubsub.keepAliveSeconds", value: 60, data_type: "integer" },
  { key: "connections.sap.applicationServerHost", value: "sap-ecc.example.com", data_type: "string" },
  { key: "connections.sap.release", value: "current", data_type: "string" },
  { key: "connections.sap.systemNumber", value: "00", data_type: "string" },
  { key: "connections.sap.client", value: "100", data_type: "string" },
  { key: "connections.sap.language", value: "EN", data_type: "string" },
  { key: "connections.sap.username", value: "", data_type: "string" },
  { key: "connections.sap.password", value: "", data_type: "password" },
  { key: "connections.sap.messageServerHost", value: "", data_type: "string" },
  { key: "connections.sap.systemId", value: "", data_type: "string" },
  { key: "connections.sap.logonGroup", value: "PUBLIC", data_type: "string" },
  { key: "connections.sap.sapRouter", value: "", data_type: "string" },
  { key: "connections.sap.programId", value: "", data_type: "string" },
  { key: "connections.sap.gatewayHost", value: "", data_type: "string" },
  { key: "connections.sap.gatewayService", value: "", data_type: "string" },
  { key: "connections.sap.maximumConnections", value: 8, data_type: "integer" },
  { key: "connections.sap.timeoutMilliseconds", value: 30000, data_type: "integer" },
  { key: "connections.sapTid.storageFile", value: "data/sap-tids.json", data_type: "string" },
];
const newEnvironmentProperties = () => defaultProperties.map((item) => ({ ...item }));
const envs = Object.fromEntries(
  ["local", "dev", "qa", "pre", "production"].map((name) => [name, newEnvironmentProperties()]),
) as Record<string, Property[]>;
const advancedDefaults = () => ({
  logPayload: "${properties.advanced.logPayload}",
  retryEnabled: "${properties.advanced.retryEnabled}",
  retryCount: "${properties.advanced.retryCount}",
  retryIntervalSeconds: "${properties.advanced.retryIntervalSeconds}",
});
const starter = (id = "main", name = "Main Task"): Task => ({
  id,
  name,
  kind: "starter",
  activities: [
    {
      id: `${id}-start`,
      type: "start",
      name: "Start",
      position: { x: 70, y: 150 },
      config: { advanced: advancedDefaults() },
    },
    {
      id: `${id}-end`,
      type: "end",
      name: "End",
      position: { x: 350, y: 150 },
      config: { advanced: advancedDefaults() },
    },
  ],
  transitions: [
    {
      id: `${id}-edge`,
      source: `${id}-start`,
      target: `${id}-end`,
      type: "success",
    },
  ],
});
const initial: Project = {
  id: "order-integration",
  name: "Order Integration",
  description: "",
  resources: [
    {
      id: "local-db",
      type: "jdbc",
      name: "Local Database",
      config: { driver: "sqlite", url: "${properties.connections.jdbc.url}" },
    },
  ],
  packaging: {
    artifact_name: "order-integration",
    version: "1.0.0",
    format: "ifpkg",
    target: "on-prem",
    environment: "production",
  },
  schemas: [],
  properties: envs,
  active_environment: "local",
  tasks: [starter()],
  active_task_id: "main",
};
const propertyReferences = (value: any) => [...JSON.stringify(value ?? {}).matchAll(/\$\{properties\.([^}]+)\}/g)].map((match) => match[1]);
const validateTaskDefinition = (project: Project, task: Task): ValidationIssue[] => {
  const issues: ValidationIssue[] = [], ids = new Set(task.activities.map((item) => item.id));
  const add = (severity: ValidationIssue["severity"], category: string, message: string, remedy: string, activityId?: string) =>
    issues.push({ id: `${task.id}-${issues.length}`, severity, category, message, remedy, taskId: task.id, activityId });
  const events = task.activities.filter(isEventActivity);
  if (events.length !== 1) add("error", "Flow", `${task.name} has ${events.length} event activities.`, "Each task must contain exactly one starter/event activity.");
  if (!task.activities.some((item) => item.type === "end")) add("error", "Flow", `${task.name} has no End activity.`, "Add an End activity and connect every successful execution path.");
  task.transitions.forEach((transition) => {
    if (!ids.has(transition.source) || !ids.has(transition.target)) add("error", "Transition", "A transition references a missing activity.", "Reconnect or delete the invalid transition.");
    if (transition.source === transition.target) add("warning", "Transition", "A transition connects an activity to itself.", "Connect it to the intended downstream activity.", transition.source);
    if (transition.type === "success_condition" && !transition.condition?.trim()) add("error", "Transition", "A conditional transition has no executable condition.", "Enter and evaluate a boolean condition in the transition editor.", transition.source);
  });
  const startIds = events.map((item) => item.id), reachable = new Set(startIds), queue = [...startIds];
  while (queue.length) {
    const current = queue.shift()!;
    task.transitions.filter((transition) => transition.source === current).forEach((transition) => {
      if (!reachable.has(transition.target)) { reachable.add(transition.target); queue.push(transition.target); }
    });
  }
  task.activities.filter((item) => !reachable.has(item.id)).forEach((item) => add("warning", "Flow", `${item.name} is not on an executable path.`, "Connect it to an upstream activity or remove it.", item.id));
  const connectionTypes = new Set(["jdbc", "ftp", "sftp", "http", "ems", "kafka", "pubsub", "sap"]);
  task.activities.forEach((item) => {
    const operation = item.config.operation || "";
    if (connectionTypes.has(item.type) && !item.config.resourceId && !["http_listener", "start", "end"].includes(item.type)) add("error", "Connection", `${item.name} has no shared connection.`, "Select a compatible shared connection in Configuration.", item.id);
    if (item.config.resourceId && !project.resources.some((resource) => resource.id === item.config.resourceId)) add("error", "Connection", `${item.name} references a missing shared connection.`, "Select an existing connection or create one under Resources.", item.id);
    if (item.type === "call_task" && !project.tasks.some((candidate) => candidate.id === item.config.taskId && candidate.kind === "subtask")) add("error", "Task", `${item.name} has no valid Sub Task.`, "Select an existing Sub Task.", item.id);
    if (item.type === "transform") {
      if (!Object.keys(item.config.targetSchema || {}).length && !item.config.targetSchemaId) add("mapping", "Mapper", `${item.name} has no target schema.`, "Select an XSD from Project Schemas or define an inline target schema.", item.id);
      if (!(item.config.mappings || []).length) add("mapping", "Mapper", `${item.name} has no field mappings.`, "Map execution-path fields to the target schema.", item.id);
    }
    if (item.type === "jdbc" && !String(item.config.sql || "").trim() && !["create", "update", "delete", "truncate"].includes(operation)) add("warning", "Configuration", `${item.name} has no SQL statement.`, "Configure SQL or a stored procedure call.", item.id);
    if ((item.type === "file" || item.type === "ftp" || item.type === "sftp") && !String(item.config.path || item.config.remotePath || "").trim()) add("warning", "Configuration", `${item.name} has no file path.`, "Configure the source or target path.", item.id);
    if (item.type === "sap" && operation.includes("idoc") && !item.config.idocType) add("mapping", "SAP IDoc", `${item.name} has no IDoc type/schema.`, "Retrieve an IDoc type from the SAP shared connection and select it here.", item.id);
  });
  return issues;
};
const validateProjectDefinition = (project: Project) => {
  const issues = project.tasks.flatMap((task) => validateTaskDefinition(project, task));
  const environments = Object.entries(project.properties);
  const canonical = new Set((project.properties.local || environments[0]?.[1] || []).map((item) => item.key));
  environments.forEach(([environment, properties]) => {
    const keys = new Set(properties.map((item) => item.key));
    canonical.forEach((key) => { if (!keys.has(key)) issues.push({ id: `property-${environment}-${key}`, severity: "warning", category: "Properties", message: `${environment}.properties is missing ${key}.`, remedy: "Add the property so mappings behave consistently in every environment." }); });
  });
  const referenced = new Set([
    ...project.tasks.flatMap((task) => task.activities.flatMap((activity) => propertyReferences(activity.config))),
    ...project.resources.flatMap((resource) => propertyReferences(resource.config)),
  ]);
  referenced.forEach((key) => environments.forEach(([environment, properties]) => {
    if (!properties.some((item) => item.key === key)) issues.push({ id: `mapping-${environment}-${key}`, severity: "mapping", category: "Property mapping", message: `${key} is referenced but missing from ${environment}.properties.`, remedy: "Create the property or replace the expression with a valid project property." });
  }));
  if (!project.name.trim()) issues.push({ id: "project-name", severity: "error", category: "Project", message: "Application name is empty.", remedy: "Rename the application." });
  if (!project.packaging?.artifact_name || !project.packaging?.version) issues.push({ id: "packaging", severity: "warning", category: "Packaging", message: "Packaging metadata is incomplete.", remedy: "Configure artifact name and version under Packaging." });
  return issues;
};
function App() {
  const [project, setProject] = useState(initial),
    [selected, setSelected] = useState("main-start"),
    [selectedIds, setSelectedIds] = useState<string[]>(["main-start"]),
    [selectedEdge, setSelectedEdge] = useState<string | null>(null),
    [selectedResource, setSelectedResource] = useState<string | null>(null),
    [logs, setLogs] = useState<any[]>([]),
    [open, setOpen] = useState<Record<string, boolean>>({
      Tasks: true,
      Resources: true,
      "Starters & Tasks": true,
      File: true,
      "TIBCO EMS": true,
      Kafka: true,
      "GCP Pub/Sub": true,
    }),
    [menu, setMenu] = useState<any>(null),
    [taskDialog, setTaskDialog] = useState<"starter" | "subtask" | null>(null),
    [connectionDialog, setConnectionDialog] = useState<Resource["type"] | null>(
      null,
    ),
    [schemaEditor, setSchemaEditor] = useState(false),
    [packageOpen, setPackageOpen] = useState(false),
    [debugState, setDebugState] = useState<any>(null),
    [executionOutputs, setExecutionOutputs] = useState<Record<string, any>>({}),
    [endpoints, setEndpoints] = useState<any[]>([]),
    [breakpoints, setBreakpoints] = useState<string[]>([]),
    [busy, setBusy] = useState(false),
    [zoom, setZoom] = useState(1),
    [validation, setValidation] = useState<{ title: string; issues: ValidationIssue[] } | null>(null),
    [connectionDraft, setConnectionDraft] = useState<{ source: string; x: number; y: number } | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const history = useRef<{
    past: Project[];
    future: Project[];
    current: Project;
    pendingBase: Project | null;
    timer: number | null;
    restoring: boolean;
  }>({ past: [], future: [], current: structuredClone(initial), pendingBase: null, timer: null, restoring: false });
  const latestProject = useRef(project);
  latestProject.current = project;
  const canvas = useRef<HTMLDivElement>(null),
    fileInput = useRef<HTMLInputElement>(null),
    drag = useRef<any>(null),
    activityClipboard = useRef<{ activities: Node[]; transitions: Edge[] } | null>(null),
    projectFileHandle = useRef<any>(null);
  const task =
      project.tasks.find((t) => t.id === project.active_task_id) ||
      project.tasks[0],
    nodes = task.activities,
    edges = task.transitions,
    node = nodes.find((n) => n.id === selected),
    edge = edges.find((e) => e.id === selectedEdge),
    resource = project.resources.find((r) => r.id === selectedResource),
    byId = useMemo(
      () => Object.fromEntries(nodes.map((n) => [n.id, n])),
      [nodes],
    );
  const mutateTask = (fn: (t: Task) => Task) =>
    setProject((p) => ({
      ...p,
      tasks: p.tasks.map((t) => (t.id === p.active_task_id ? fn(t) : t)),
      process: undefined,
    }));
  const [closed, setClosed] = useState(false),
    [theme, setTheme] = useState(
      localStorage.getItem("integration-fabric-theme") || "midnight",
    );
  const [activeTab, setActiveTab] = useState<
      "configuration" | "input" | "output" | "advanced" | "errors" | "documentation"
    >("configuration"),
    [propertyEditor, setPropertyEditor] = useState<string | null>(null),
    [renameOpen, setRenameOpen] = useState(false),
    [helpDialog, setHelpDialog] = useState<"about" | "shortcuts" | null>(null),
    [treeHeight, setTreeHeight] = useState(305),
    [configHeight, setConfigHeight] = useState(285),
    [explorerWidth, setExplorerWidth] = useState(Number(localStorage.getItem("integration-fabric-explorer-width")) || 245),
    [paletteOpen, setPaletteOpen] = useState(true);
  const split = useRef<{ y: number; height: number } | null>(null),
    configSplit = useRef<{ y: number; height: number } | null>(null),
    explorerSplit = useRef<{ x: number; width: number } | null>(null);
  const commitPendingHistory = () => {
    const state = history.current;
    if (state.timer !== null) window.clearTimeout(state.timer);
    state.timer = null;
    if (!state.pendingBase) return;
    if (JSON.stringify(state.pendingBase) !== JSON.stringify(latestProject.current)) {
      state.past.push(structuredClone(state.pendingBase));
      if (state.past.length > 100) state.past.splice(0, state.past.length - 100);
      state.current = structuredClone(latestProject.current);
      state.future = [];
    }
    state.pendingBase = null;
    setHistoryVersion((value) => value + 1);
  };
  const restoreHistorySelection = (snapshot: Project) => {
    const restoredTask = snapshot.tasks.find((item) => item.id === snapshot.active_task_id) || snapshot.tasks[0];
    setSelected((id) => { const next = restoredTask?.activities.some((item) => item.id === id) ? id : restoredTask?.activities[0]?.id || ""; setSelectedIds(next ? [next] : []); return next; });
    setSelectedEdge((id) => id && restoredTask?.transitions.some((item) => item.id === id) ? id : null);
    setSelectedResource((id) => id && snapshot.resources.some((item) => item.id === id) ? id : null);
  };
  const undoStudio = () => {
    commitPendingHistory();
    const state = history.current, previous = state.past.pop();
    if (!previous) { setLogs([{ level: "INFO", message: "Nothing left to undo." }]); return; }
    state.future.push(structuredClone(state.current));
    state.current = structuredClone(previous); state.restoring = true;
    setProject(structuredClone(previous)); restoreHistorySelection(previous);
    setLogs([{ level: "INFO", message: `Undo complete · ${state.past.length} earlier change${state.past.length === 1 ? "" : "s"} available.` }]);
    setHistoryVersion((value) => value + 1);
  };
  const redoStudio = () => {
    commitPendingHistory();
    const state = history.current, next = state.future.pop();
    if (!next) { setLogs([{ level: "INFO", message: "Nothing left to redo." }]); return; }
    state.past.push(structuredClone(state.current));
    if (state.past.length > 100) state.past.splice(0, state.past.length - 100);
    state.current = structuredClone(next); state.restoring = true;
    setProject(structuredClone(next)); restoreHistorySelection(next);
    setLogs([{ level: "INFO", message: `Redo complete · ${state.future.length} later change${state.future.length === 1 ? "" : "s"} available.` }]);
    setHistoryVersion((value) => value + 1);
  };
  useEffect(() => {
    const state = history.current;
    if (state.restoring) { state.restoring = false; state.current = structuredClone(project); return; }
    if (JSON.stringify(state.current) === JSON.stringify(project)) return;
    if (!state.pendingBase) state.pendingBase = structuredClone(state.current);
    if (state.timer !== null) window.clearTimeout(state.timer);
    state.timer = window.setTimeout(commitPendingHistory, 220);
  }, [project]);
  useEffect(() => () => { if (history.current.timer !== null) window.clearTimeout(history.current.timer); }, []);
  useEffect(() => {
    const keyboardHistory = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')) return;
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) { event.preventDefault(); undoStudio(); }
      else if (key === "y" || (key === "z" && event.shiftKey)) { event.preventDefault(); redoStudio(); }
    };
    window.addEventListener("keydown", keyboardHistory);
    return () => window.removeEventListener("keydown", keyboardHistory);
  }, [project, historyVersion]);
  useEffect(() => {
    document.body.dataset.theme = theme;
    localStorage.setItem("integration-fabric-theme", theme);
  }, [theme]);
  useEffect(() => localStorage.setItem("integration-fabric-explorer-width", String(explorerWidth)), [explorerWidth]);
  useEffect(
    () =>
      setOpen((o) => ({
        ...o,
        Connections: true,
        Packaging: true,
        Schemas: true,
        Properties: true,
      })),
    [],
  );
  useEffect(() => {
    fetch("/api/projects/order-integration")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((p: any) => {
        const tasks = p.tasks?.length
          ? p.tasks
          : [{ ...p.process, kind: "starter" }];
        projectFileHandle.current = localStorage.getItem(`integration-fabric-project-path:${p.id}`);
        setProject({
          ...p,
          tasks,
          active_task_id: p.active_task_id || tasks[0].id,
          properties: p.properties || envs,
          schemas: p.schemas || [],
          resources: p.resources || [],
        });
      })
      .catch(() =>
        fetch("/api/projects", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(initial),
        }),
      );
  }, []);
  useEffect(() => {
    const move = (e: PointerEvent) => {
        if (!drag.current || !canvas.current) return;
        const deltaX = (e.clientX - drag.current.startX) / zoom;
        const deltaY = (e.clientY - drag.current.startY) / zoom;
        mutateTask((t) => ({
          ...t,
          activities: t.activities.map((n) =>
            drag.current.positions[n.id]
              ? {
                  ...n,
                  position: {
                    x: Math.max(0, drag.current.positions[n.id].x + deltaX),
                    y: Math.max(0, drag.current.positions[n.id].y + deltaY),
                  },
                }
              : n,
          ),
        }));
      },
      up = () => (drag.current = null);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [zoom, project.active_task_id]);
  useEffect(() => {
    if (!connectionDraft) return;
    const move = (event: PointerEvent) => {
      if (!canvas.current) return;
      const box = canvas.current.getBoundingClientRect();
      setConnectionDraft((draft) => draft ? { ...draft, x: (event.clientX - box.left + canvas.current!.scrollLeft) / zoom, y: (event.clientY - box.top + canvas.current!.scrollTop) / zoom } : null);
    };
    const up = (event: PointerEvent) => {
      const targetElement = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>(".node[data-node-id]");
      const target = targetElement?.dataset.nodeId;
      if (target && target !== connectionDraft.source) {
        const edgeId = `edge-${Date.now()}`;
        mutateTask((current) => current.transitions.some((item) => item.source === connectionDraft.source && item.target === target) ? current : { ...current, transitions: [...current.transitions, { id: edgeId, source: connectionDraft.source, target, type: "success" }] });
        setSelectedEdge(edgeId); setSelected(""); setSelectedResource(null); setActiveTab("configuration");
      }
      setConnectionDraft(null);
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [connectionDraft?.source, project.active_task_id, zoom]);
  useEffect(() => {
    const move = (e: PointerEvent) => {
        if (split.current)
          setTreeHeight(
            Math.max(
              150,
              Math.min(
                window.innerHeight - 190,
                split.current.height + e.clientY - split.current.y,
              ),
            ),
          );
        if (configSplit.current)
          setConfigHeight(
            Math.max(
              180,
              Math.min(
                window.innerHeight - 220,
                configSplit.current.height + configSplit.current.y - e.clientY,
              ),
            ),
          );
        if (explorerSplit.current)
          setExplorerWidth(Math.max(190, Math.min(520, explorerSplit.current.width + e.clientX - explorerSplit.current.x)));
      },
      up = () => {
        split.current = null;
        configSplit.current = null;
        explorerSplit.current = null;
      };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, []);
  const selectTask = (id: string) => {
    const t = project.tasks.find((t) => t.id === id);
    setProject((p) => ({ ...p, active_task_id: id }));
    const first = t?.activities[0]?.id || "";
    setSelected(first);
    setSelectedIds(first ? [first] : []);
    setSelectedEdge(null);
    setSelectedResource(null);
  };
  const addActivity = (d: Def, pos?: { x: number; y: number }) => {
    const id = `${d.type}-${Date.now()}`,
      config: any = {
        operation: d.operation,
        advanced: advancedDefaults(),
      };
    if (d.type === "timer")
      Object.assign(config, {
        startTime: "",
        runOnce: false,
        interval: 1,
        unit: "minutes",
      });
    if (d.type === "call_task")
      Object.assign(config, {
        taskId: project.tasks.find((t) => t.kind === "subtask")?.id || "",
        spawn: false,
        inputMappings: {},
      });
    if (["ems", "kafka", "pubsub"].includes(d.type))
      Object.assign(config, {
        resourceId: project.resources.find((r) => r.type === d.type)?.id || "",
        topic: "",
        queue: "",
        subscription: "",
        message: "${last}",
        attributes: {},
        groupId: "integration-fabric",
        maxMessages: 1,
      });
    if (d.type === "ems") Object.assign(config, { messagingStyle: d.operation?.includes("topic") ? "Topic" : "Queue", messageType: "Text", acknowledgeMode: ["queue_receiver", "topic_subscriber"].includes(d.operation || "") ? "Auto" : undefined, deliveryMode: "Persistent", priority: 4, expiration: 0, maxSessions: 1, receiveTimeout: 30000, dynamicProperties: "{}" });
    if (d.type === "kafka") Object.assign(config, { acknowledgeMode: d.operation === "receive" || d.operation === "get" ? "Auto" : undefined, keySerializer: "String", valueSerializer: "String", keyDeserializer: "String", valueDeserializer: "String", acks: "all", compressionType: "none", retries: 3, batchSize: 16384, lingerMs: 0, enableIdempotence: false, enableAutoCommit: true, autoOffsetReset: "earliest", maxPollRecords: 1, additionalProperties: "{}" });
    if (d.type === "pubsub") Object.assign(config, { acknowledgeMode: d.operation === "subscribe" ? "Auto" : undefined, receiveTimeout: 10, publishTimeout: 60, attributes: {}, data: "${last}" });
    if (d.type === "sap")
      Object.assign(config, {
        resourceId: project.resources.find((r) => r.type === "sap")?.id || "",
        invocationProtocol: "Request/Reply",
        payload: "${last}",
        idocOutputMode: "XML",
        messagingSource: "NoMessaging",
        idocType: project.resources.find((r) => r.type === "sap")?.config?.selectedIdoc?.idocType || "",
      });
    if (d.type === "jdbc")
      Object.assign(config, {
        resourceId: project.resources.find((r) => r.type === "jdbc")?.id || "",
        sql: "",
        parameters: {},
      });
    if (d.type === "transform")
      Object.assign(config, {
        language: "JSONPath / functions",
        sourceSchema: {},
        targetSchema: {},
        mappings: [],
        threshold: 70,
      });
    if (d.type === "log") Object.assign(config, { level: "INFO", message: "", includePayload: true, inputMappings: { payload: "${last}" } });
    if (d.type === "confirm") Object.assign(config, { ackId: "${last.ackId}", failIfMissing: true });
    if (d.type === "file") Object.assign(config, {
      path: "", pattern: "*", encoding: "UTF-8", readAs: "Text", writeAs: "Text",
      includeTimestamp: true, excludeFileContent: false, append: false, overwrite: false,
      createDirectories: true, addLineSeparator: false, compression: "None", recursive: false,
      ignoreMissing: false, preserveAttributes: true, listType: "Files and Directories",
      sortBy: "Name", sortOrder: "Ascending", eventType: "Created", pollInterval: 5,
      includeExisting: false, postAction: "None", moveTo: "",
    });
    if (
      d.type === "http_listener" ||
      (d.type === "rest" && d.operation === "receiver")
    )
      Object.assign(config, { path: "/events", methods: "GET,POST" });
    if (d.type === "http" || (d.type === "rest" && d.operation === "invoke"))
      Object.assign(config, {
        method: "GET",
        url: "https://",
        headers: {},
        body: "${last}",
      });
    const n: Node = {
      id,
      type: d.type,
      name: d.label,
      position: pos || {
        x: 160 + (nodes.length % 4) * 180,
        y: 270 + Math.floor(nodes.length / 4) * 105,
      },
      config,
    };
    if (isEventActivity(n)) {
      const existingEvent = nodes.find(isEventActivity);
      if (existingEvent) {
        if (existingEvent.type !== "start" && !confirm(`Replace the existing event activity “${existingEvent.name}” with “${n.name}”? A Task can have only one event activity.`)) return;
        const replacement = { ...n, id: existingEvent.id, position: existingEvent.position };
        mutateTask((current) => ({ ...current, activities: current.activities.map((activity) => activity.id === existingEvent.id ? replacement : activity) }));
        setSelected(existingEvent.id); setSelectedIds([existingEvent.id]); setSelectedEdge(null); setSelectedResource(null); setMenu(null);
        setLogs([{ level: "INFO", message: `Replaced event activity ${existingEvent.name} with ${n.name}.` }]);
        return;
      }
    }
    mutateTask((t) => ({ ...t, activities: [...t.activities, n] }));
    setSelected(id);
    setSelectedIds([id]);
    setSelectedEdge(null);
    setSelectedResource(null);
    setMenu(null);
  };
  const deleteSelectedActivity = () => {
    const targets = selectedIds.length ? nodes.filter((item) => selectedIds.includes(item.id)) : node ? [node] : [];
    if (!targets.length) return;
    if (targets.some(isEventActivity) && nodes.filter(isEventActivity).every((item) => targets.some((target) => target.id === item.id))) {
      setLogs([{ level: "WARN", message: "A Task must retain one event activity. Add a replacement event to replace this starter." }]);
      return;
    }
    if (!confirm(targets.length === 1 ? `Delete activity “${targets[0].name}” and its connected transitions?` : `Delete ${targets.length} selected activities and their connected transitions?`)) return;
    const targetIds = new Set(targets.map((item) => item.id));
    mutateTask((current) => ({ ...current, activities: current.activities.filter((activity) => !targetIds.has(activity.id)), transitions: current.transitions.filter((transition) => !targetIds.has(transition.source) && !targetIds.has(transition.target)) }));
    const remaining = nodes.filter((activity) => !targetIds.has(activity.id));
    setSelected(remaining[0]?.id || ""); setSelectedIds(remaining[0] ? [remaining[0].id] : []); setSelectedEdge(null); setSelectedResource(null);
  };
  const deleteSelectedTransition = () => {
    if (!edge) return;
    const sourceName = byId[edge.source]?.name || "source activity";
    const targetName = byId[edge.target]?.name || "target activity";
    if (!confirm(`Delete the transition from “${sourceName}” to “${targetName}”?`)) return;
    mutateTask((current) => ({ ...current, transitions: current.transitions.filter((transition) => transition.id !== edge.id) }));
    setSelectedEdge(null);
    setSelected(nodes[0]?.id || ""); setSelectedIds(nodes[0] ? [nodes[0].id] : []);
    setSelectedResource(null);
  };
  const alignSelection = (axis: "vertical" | "horizontal") => {
    const chosen = nodes.filter((item) => selectedIds.includes(item.id));
    if (chosen.length < 2) { setLogs([{ level: "WARN", message: "Select at least two activities with Ctrl/Shift-click before aligning." }]); return; }
    const ordered = [...chosen].sort((left, right) => axis === "vertical" ? left.position.y - right.position.y || left.position.x - right.position.x : left.position.x - right.position.x || left.position.y - right.position.y);
    const anchorX = Math.min(...chosen.map((item) => item.position.x)), anchorY = Math.min(...chosen.map((item) => item.position.y));
    const arranged = Object.fromEntries(ordered.map((item, index) => [item.id, axis === "vertical" ? { x: anchorX, y: anchorY + index * 125 } : { x: anchorX + index * 180, y: anchorY }]));
    mutateTask((current) => ({ ...current, activities: current.activities.map((item) => arranged[item.id] ? { ...item, position: arranged[item.id] } : item) }));
    setLogs([{ level: "INFO", message: `Arranged ${chosen.length} activities in a ${axis === "vertical" ? "vertical column" : "horizontal row"}.` }]);
  };
  const moveSelection = (dy: number) => {
    if (!selectedIds.length) return;
    mutateTask((current) => ({ ...current, activities: current.activities.map((item) => selectedIds.includes(item.id) ? { ...item, position: { ...item.position, y: Math.max(0, item.position.y + dy) } } : item) }));
  };
  const copySelection = () => {
    const activities = nodes.filter((item) => selectedIds.includes(item.id));
    if (!activities.length) { setLogs([{ level: "WARN", message: "Select one or more activities to copy." }]); return; }
    const ids = new Set(activities.map((item) => item.id));
    activityClipboard.current = { activities: structuredClone(activities), transitions: structuredClone(edges.filter((item) => ids.has(item.source) && ids.has(item.target))) };
    setLogs([{ level: "INFO", message: `Copied ${activities.length} activit${activities.length === 1 ? "y" : "ies"}.` }]);
  };
  const pasteSelection = () => {
    const clipboard = activityClipboard.current;
    if (!clipboard?.activities.length) { setLogs([{ level: "WARN", message: "The Studio activity clipboard is empty." }]); return; }
    if (clipboard.activities.some(isEventActivity) && nodes.some(isEventActivity)) { setLogs([{ level: "WARN", message: "Paste blocked: a Task can contain only one event activity. Copy downstream activities without the starter/event." }]); return; }
    const now = Date.now(), idMap: Record<string, string> = {};
    clipboard.activities.forEach((item, index) => { idMap[item.id] = `${item.type}-${now}-${index}`; });
    const pasted = clipboard.activities.map((item) => ({ ...structuredClone(item), id: idMap[item.id], name: `${item.name} Copy`, position: { x: item.position.x + 34, y: item.position.y + 34 } }));
    const pastedEdges = clipboard.transitions.map((item, index) => ({ ...structuredClone(item), id: `edge-${now}-${index}`, source: idMap[item.source], target: idMap[item.target] }));
    mutateTask((current) => ({ ...current, activities: [...current.activities, ...pasted], transitions: [...current.transitions, ...pastedEdges] }));
    setSelected(pasted[0].id); setSelectedIds(pasted.map((item) => item.id)); setSelectedEdge(null); setSelectedResource(null);
    setLogs([{ level: "INFO", message: `Pasted ${pasted.length} activit${pasted.length === 1 ? "y" : "ies"} with internal transitions.` }]);
  };
  const cutSelection = () => { copySelection(); deleteSelectedActivity(); };
  const runValidation = (scope: "task" | "project") => {
    const issues = scope === "task" ? validateTaskDefinition(project, task) : validateProjectDefinition(project);
    const title = scope === "task" ? `Validate Task · ${task.name}` : `Validate Project · ${project.name}`;
    setValidation({ title, issues });
    setLogs([{ level: issues.some((item) => item.severity === "error") ? "ERROR" : issues.length ? "WARN" : "INFO", message: issues.length ? `${title}: ${issues.length} finding${issues.length === 1 ? "" : "s"}.` : `${title}: no errors or missing mappings.` }]);
  };
  const newProject = () => {
    const name = prompt("New application name", "New Integration Application")?.trim();
    if (!name) return;
    const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || `project-${Date.now()}`;
    const next = structuredClone(initial);
    next.id = id; next.name = name; next.packaging = { ...next.packaging, artifact_name: id }; next.tasks = [starter("main", "Main Task")]; next.active_task_id = "main";
    projectFileHandle.current = null;
    setProject(next); setSelected("main-start"); setSelectedIds(["main-start"]); setSelectedEdge(null); setSelectedResource(null); setClosed(false);
    setLogs([{ level: "INFO", message: `Created new project ${name}. Save to persist it.` }]);
  };
  useEffect(() => {
    const removeSelection = (event: KeyboardEvent) => {
      if (event.key !== "Delete" && event.key !== "Backspace") return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')) return;
      if (!node && !edge) return;
      event.preventDefault();
      if (edge) deleteSelectedTransition();
      else deleteSelectedActivity();
    };
    window.addEventListener("keydown", removeSelection);
    return () => window.removeEventListener("keydown", removeSelection);
  }, [node, edge, nodes, byId]);
  useEffect(() => {
    const shortcuts = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')) return;
      if (event.ctrlKey || event.metaKey) {
        const key = event.key.toLowerCase();
        if (key === "a") { event.preventDefault(); setSelectedIds(nodes.map((item) => item.id)); if (nodes[0]) setSelected(nodes[0].id); }
        else if (key === "c") { event.preventDefault(); copySelection(); }
        else if (key === "x") { event.preventDefault(); cutSelection(); }
        else if (key === "v") { event.preventDefault(); pasteSelection(); }
      } else if (event.key === "ArrowUp" && selectedIds.length > 1) { event.preventDefault(); moveSelection(-12); }
      else if (event.key === "ArrowDown" && selectedIds.length > 1) { event.preventDefault(); moveSelection(12); }
    };
    window.addEventListener("keydown", shortcuts);
    return () => window.removeEventListener("keydown", shortcuts);
  }, [project, selectedIds]);
  const projectFilename = (extension: string) => `${project.name.replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^-|-$/g, "") || project.id}.${extension}`;
  const persistProject = async () => {
    const response = await fetch(`/api/projects/${project.id}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(project) });
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) throw new Error("The project API returned HTML instead of project JSON. Verify the local runtime is running on port 8787.");
    const output = await response.json();
    if (!response.ok) throw new Error(output.detail || "Project save failed");
    setProject(output);
    return output;
  };
  const fetchProjectFile = async (format: "package" | "json") => {
    const response = await fetch(`/api/projects/${project.id}/${format === "package" ? "export" : "json"}`, { headers: { accept: format === "package" ? "application/zip" : "application/json" } });
    const contentType = response.headers.get("content-type") || "";
    if (!response.ok) throw new Error(`Project ${format === "package" ? "export" : "JSON save"} failed (${response.status}).`);
    if (contentType.includes("text/html")) throw new Error("The server returned the Studio HTML page instead of a project file.");
    if (format === "package" && !contentType.includes("zip") && !contentType.includes("octet-stream")) throw new Error(`Unexpected export type: ${contentType || "unknown"}`);
    if (format === "json" && !contentType.includes("json")) throw new Error(`Unexpected project JSON type: ${contentType || "unknown"}`);
    return response.blob();
  };
  const browserDownload = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob), anchor = document.createElement("a");
    anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1500);
  };
  const saveProjectFile = async (format: "package" | "json" = "package", forceNew = false) => {
    const extension = format === "package" ? "ifproject" : "json", filename = projectFilename(extension), picker = (window as any).showSaveFilePicker;
    let handle = format === "package" && !forceNew ? projectFileHandle.current : null;
    try {
      if (picker && !handle) handle = await picker({ suggestedName: filename, types: [{ description: format === "package" ? "Integration Fabric Project" : "Integration Fabric Project JSON", accept: { [format === "package" ? "application/zip" : "application/json"]: [`.${extension}`] } }] });
      await persistProject();
      const blob = await fetchProjectFile(format);
      if (window.fabricDesktop) {
        const existingPath = format === "package" && !forceNew && typeof handle === "string" ? handle : undefined;
        const filePath = await window.fabricDesktop.saveFile({ path: existingPath, filename, bytes: [...new Uint8Array(await blob.arrayBuffer())], filters: [{ name: format === "package" ? "Integration Fabric Project" : "Integration Fabric JSON", extensions: [extension] }] });
        if (!filePath) { setLogs([{ level: "INFO", message: "Project file save cancelled." }]); return; }
        if (format === "package") { projectFileHandle.current = filePath; localStorage.setItem(`integration-fabric-project-path:${project.id}`, filePath); }
        setLogs([{ level: "INFO", message: `Saved complete project to ${filePath}.` }]);
      } else if (handle) {
        const writable = await handle.createWritable(); await writable.write(blob); await writable.close();
        if (format === "package") projectFileHandle.current = handle;
        setLogs([{ level: "INFO", message: `Saved complete project to ${handle.name || filename}. Backend JSON: backend/data/projects/${project.id}/` }]);
      } else {
        browserDownload(blob, filename);
        setLogs([{ level: "INFO", message: `Saved complete project as ${filename}. Backend JSON: backend/data/projects/${project.id}/` }]);
      }
    } catch (error: any) {
      if (error?.name === "AbortError") { setLogs([{ level: "INFO", message: "Project file save cancelled." }]); return; }
      setLogs([{ level: "ERROR", message: error?.message || "Project file save failed" }]);
    }
  };
  const save = () => saveProjectFile("package", false);
  const exportProject = () => saveProjectFile("package", true);
  const saveJsonFile = () => saveProjectFile("json", true);
  const buildDeploymentPackage = async (settings: Record<string, string>) => {
    try {
      const next = { ...project, packaging: { ...project.packaging, ...settings } };
      const saved = await fetch(`/api/projects/${project.id}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(next) });
      if (!saved.ok) throw new Error("Unable to save packaging configuration.");
      setProject(await saved.json());
      const query = new URLSearchParams({ target: settings.target, environment: settings.environment, archive: settings.format });
      const response = await fetch(`/api/projects/${project.id}/package?${query}`);
      if (!response.ok) { const detail = await response.json().catch(() => ({})); throw new Error(detail.detail || "Package generation failed."); }
      const blob = await response.blob(), disposition = response.headers.get("content-disposition") || "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || `${settings.artifact_name}-${settings.version}.${settings.format === "ifpkg" ? "ifpkg" : settings.format}`;
      if (window.fabricDesktop) {
        const filePath = await window.fabricDesktop.saveFile({ filename, bytes: [...new Uint8Array(await blob.arrayBuffer())], filters: [{ name: "Integration Fabric Deployment Package", extensions: [filename.endsWith(".tar.gz") ? "tar.gz" : filename.split(".").pop() || "ifpkg"] }] });
        if (!filePath) return;
        setLogs([{ level: "INFO", message: `Created ${settings.target} deployment package: ${filePath}` }]);
      } else browserDownload(blob, filename);
      setPackageOpen(false);
    } catch (error: any) { setLogs([{ level: "ERROR", message: error?.message || "Package generation failed" }]); }
  };
  const run = async () => {
      setBusy(true);
      try {
        await persistProject();
        const r = await fetch(`/api/projects/${project.id}/run`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            input: { orderId: "10001" },
            environment: project.active_environment,
            task_id: task.id,
          }),
        }),
          out = await r.json();
        setLogs(out.logs || [{ level: "ERROR", message: out.detail }]);
        setExecutionOutputs(out.activity_outputs || {});
        setEndpoints(out.endpoints || []);
      } catch (error: any) {
        setLogs([{ level: "ERROR", message: error?.message || "Run failed" }]);
      } finally { setBusy(false); }
    },
    debug = async () => {
      await persistProject();
      const r = await fetch(`/api/projects/${project.id}/debug`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            input: {},
            environment: project.active_environment,
            task_id: task.id,
            breakpoints,
          }),
        }),
        out = await r.json();
      setDebugState(out);
      setExecutionOutputs(out.activityOutputs || {});
      setLogs(out.logs || [{ level: "ERROR", message: out.detail }]);
      setEndpoints(out.endpoints || []);
    },
    debugAction = async (action: string) => {
      if (!debugState) return;
      const r = await fetch(`/api/debug/${debugState.sessionId}/action`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ action }),
        }),
        out = await r.json();
      setDebugState(out);
      setExecutionOutputs(out.activityOutputs || {});
      setLogs(out.logs || []);
      setEndpoints(out.endpoints || endpoints);
      if (out.currentTaskId && out.currentTaskId !== project.active_task_id)
        selectTask(out.currentTaskId);
    };
  const importProject = async (file: File) => {
      const data = new FormData();
      data.append("file", file);
      const r = await fetch("/api/projects/import", {
          method: "POST",
          body: data,
        });
      const contentType = r.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) { setLogs([{ level: "ERROR", message: "Import failed because the runtime returned HTML instead of project JSON." }]); return; }
      const out = await r.json();
      if (r.ok) {
        setProject(out);
        const first = out.tasks?.[0]?.activities?.[0]?.id || "";
        setSelected(first); setSelectedIds(first ? [first] : []);
        projectFileHandle.current = null;
        setLogs([
          { level: "INFO", message: `Imported complete project ${out.name}.` },
        ]);
        return out;
      } else setLogs([{ level: "ERROR", message: out.detail }]);
      return null;
    };
  const importFromFileSystem = async () => {
    if (window.fabricDesktop) {
      const selectedFile = await window.fabricDesktop.openProject();
      if (!selectedFile) return;
      const imported = await importProject(new File([new Uint8Array(selectedFile.bytes)], selectedFile.name));
      projectFileHandle.current = selectedFile.path;
      if (imported?.id) localStorage.setItem(`integration-fabric-project-path:${imported.id}`, selectedFile.path);
      return;
    }
    const picker = (window as any).showOpenFilePicker;
    if (!picker) { fileInput.current?.click(); return; }
    try {
      const [handle] = await picker({ multiple: false, types: [{ description: "Integration Fabric Project", accept: { "application/zip": [".ifproject", ".zip"], "application/json": [".json"] } }] });
      const file = await handle.getFile();
      await importProject(file);
      projectFileHandle.current = handle;
    } catch (error: any) {
      if (error?.name !== "AbortError") setLogs([{ level: "ERROR", message: error?.message || "Project import failed" }]);
    }
  };
  const openProject = async (id: string) => {
      const r = await fetch(`/api/projects/${id}`),
        out = await r.json();
      if (r.ok) {
        setProject(out);
        setClosed(false);
        const first = out.tasks?.[0]?.activities?.[0]?.id || "";
        setSelected(first); setSelectedIds(first ? [first] : []);
        projectFileHandle.current = localStorage.getItem(`integration-fabric-project-path:${out.id}`);
        setLogs([
          {
            level: "INFO",
            message: `Opened ${out.name} from backend JSON storage.`,
          },
        ]);
      }
    };
  const deleteCurrent = async () => {
      if (
        !confirm(
          `Delete ${project.name} from backend JSON storage? This cannot be undone.`,
        )
      )
        return;
      const r = await fetch(`/api/projects/${project.id}`, {
        method: "DELETE",
      });
      if (r.ok) {
        setClosed(true);
        setLogs([]);
      }
    };
  const closeProject = () => {
      setClosed(true);
      setMenu(null);
    };
  useEffect(() => {
    const projectFileShortcuts = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s") return;
      event.preventDefault();
      if (event.shiftKey) void exportProject();
      else void save();
    };
    window.addEventListener("keydown", projectFileShortcuts);
    return () => window.removeEventListener("keydown", projectFileShortcuts);
  }, [project]);
  if (closed)
    return (
      <ProjectWelcome
        openProject={openProject}
        importProject={(file: File) => {
          importProject(file);
          setClosed(false);
        }}
        theme={theme}
        setTheme={setTheme}
      />
    );
  return (
    <div className="app" style={{ "--explorer-width": `${explorerWidth}px` } as React.CSSProperties} onClick={() => setMenu(null)}>
      <nav className="menu-bar">
        <div className="menu-mark">
          <Workflow /> IF
        </div>
        <div className="menu-root"><button className={menu === "file" ? "active" : ""} onClick={(e) => { e.stopPropagation(); setMenu(menu === "file" ? null : "file"); }}>File</button>
          {menu === "file" && <FileMenu stop={(e: React.MouseEvent) => e.stopPropagation()} save={save} saveJson={saveJsonFile} exportProject={exportProject} importProject={importFromFileSystem} openProjects={() => setClosed(true)} closeProject={closeProject} deleteProject={deleteCurrent}/>}</div>
        <TopMenu label="Edit" open={menu === "edit"} toggle={(e: React.MouseEvent) => { e.stopPropagation(); setMenu(menu === "edit" ? null : "edit"); }} commands={[
          { label: "Undo", detail: "Restore an earlier Studio change · up to 100 levels", icon: Undo2, shortcut: "Ctrl+Z", action: undoStudio, disabled: history.current.past.length === 0 && !history.current.pendingBase },
          { label: "Redo", detail: "Restore the most recently undone change", icon: Redo2, shortcut: "Ctrl+Y", action: redoStudio, disabled: history.current.future.length === 0 },
          { label: "Rename Application", detail: project.name, icon: Settings2, action: () => setRenameOpen(true) },
          { label: "Edit Environment Properties", detail: `${project.active_environment}.properties`, icon: Braces, action: () => setPropertyEditor(project.active_environment) },
          { label: "Save Changes", detail: "Persist the complete project", icon: Save, shortcut: "Ctrl+S", action: save },
        ]}/>
        <TopMenu label="View" open={menu === "view"} toggle={(e: React.MouseEvent) => { e.stopPropagation(); setMenu(menu === "view" ? null : "view"); }} commands={[
          { label: paletteOpen ? "Hide Activity Palette" : "Show Activity Palette", detail: "Toggle the draggable activity library", icon: Activity, action: () => setPaletteOpen((value) => !value) },
          { label: "Expand Project Explorer", detail: "Open every project folder", icon: FolderOpen, action: () => setOpen((value) => Object.fromEntries(Object.keys(value).map((key) => [key, true]))) },
          { label: "Collapse Project Explorer", detail: "Close every project folder", icon: Folder, action: () => setOpen((value) => Object.fromEntries(Object.keys(value).map((key) => [key, false]))) },
          { label: "Reset Canvas Zoom", detail: "Return designer to 100%", icon: Workflow, action: () => setZoom(1) },
          ...themeOptions.map((option) => ({ label: `Theme · ${option.label}`, detail: option.detail, icon: option.value === theme ? CheckCircle2 : Workflow, action: () => setTheme(option.value) })),
        ]}/>
        <TopMenu label="Run" open={menu === "run"} toggle={(e: React.MouseEvent) => { e.stopPropagation(); setMenu(menu === "run" ? null : "run"); }} commands={[
          { label: "Run Active Task", detail: `${task.name} · ${project.active_environment}`, icon: CirclePlay, shortcut: "F5", action: run },
          { label: "Start Debugging", detail: "Honor configured breakpoints", icon: Bug, shortcut: "F6", action: debug },
          { label: "Validate Current Task", detail: "Check flow, mappings, connections, and configuration", icon: ShieldCheck, action: () => runValidation("task") },
          { label: "Validate Project", detail: "Check every task, environment, mapping, and package", icon: ShieldCheck, action: () => runValidation("project") },
          { label: "Continue", detail: "Resume the active debug session", icon: CirclePlay, action: () => debugAction("continue"), disabled: !debugState },
          { label: "Stop Debugging", detail: "End the active debug session", icon: Square, action: () => setDebugState(null), disabled: !debugState },
        ]}/>
        <TopMenu label="Window" open={menu === "window"} toggle={(e: React.MouseEvent) => { e.stopPropagation(); setMenu(menu === "window" ? null : "window"); }} commands={[
          { label: "Project Explorer", detail: "Move focus to the project tree", icon: FolderOpen, action: () => focusStudioPanel(".explorer") },
          { label: "Task Designer", detail: "Move focus to the orchestration canvas", icon: Workflow, action: () => focusStudioPanel(".canvas") },
          { label: "Configuration", detail: "Move focus to activity configuration", icon: Settings2, action: () => focusStudioPanel(".config") },
          { label: "Execution & Debug", detail: "Move focus to runtime output", icon: Bug, action: () => focusStudioPanel(".monitor") },
        ]}/>
        <TopMenu label="Help" open={menu === "help"} toggle={(e: React.MouseEvent) => { e.stopPropagation(); setMenu(menu === "help" ? null : "help"); }} commands={[
          { label: "Keyboard Shortcuts", detail: "Designer and runtime commands", icon: Settings2, action: () => setHelpDialog("shortcuts") },
          { label: "About Integration Fabric", detail: "Product and project information", icon: Workflow, action: () => setHelpDialog("about") },
        ]}/>
        <span className="menu-spacer" />
        <ThemePicker theme={theme} setTheme={setTheme} />
        <button onClick={run}>
          <CirclePlay /> Run
        </button>
        <button onClick={debug}>
          <Bug /> Debug
        </button>
      </nav>
      <StudioRibbon
        selectedCount={selectedIds.length}
        newProject={newProject}
        openProject={() => setClosed(true)}
        importProject={importFromFileSystem}
        save={save}
        exportProject={exportProject}
        packageProject={() => setPackageOpen(true)}
        closeProject={closeProject}
        run={run}
        debug={debug}
        validateTask={() => runValidation("task")}
        validateProject={() => runValidation("project")}
        undo={undoStudio}
        cut={cutSelection}
        copy={copySelection}
        paste={pasteSelection}
        alignVertical={() => alignSelection("vertical")}
        alignHorizontal={() => alignSelection("horizontal")}
        moveUp={() => moveSelection(-24)}
        moveDown={() => moveSelection(24)}
      />
      <header>
        <div className="brand">
          <Workflow />
          <span>
            INTEGRATION <b>FABRIC</b>
          </span>
          <small>STUDIO</small>
        </div>
        <div className="crumb">
          Projects <ChevronRight />
          {project.name}
          <ChevronRight />
          <b>{task.name}</b>
          <span className={`task-kind ${task.kind}`}>{task.kind}</span>
        </div>
        <div className="environment">
          <small>ENVIRONMENT</small>
          <select
            value={project.active_environment}
            onChange={(e) =>
              setProject((p) => ({ ...p, active_environment: e.target.value }))
            }
          >
            {Object.keys(project.properties).map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </div>
        <div className="actions">
          <button onClick={save}>
            <Save /> Save
          </button>
          <button className="run" onClick={run} disabled={busy}>
            <CirclePlay /> {busy ? "Running…" : "Run"}
          </button>
        </div>
      </header>
      <aside className="explorer">
        <div className="explorer-width-splitter" title="Drag left or right to resize Project Explorer" onPointerDown={(event) => { event.preventDefault(); event.stopPropagation(); explorerSplit.current = { x: event.clientX, width: explorerWidth }; }}><span /></div>
        <div className="pane-title">PROJECT EXPLORER</div>
        <div className="tree project-tree" style={{ height: treeHeight }}>
          <button
            className="tree-row application-row"
            title="Double-click or use the edit button to rename the application"
            onDoubleClick={() => setRenameOpen(true)}
          >
            <FolderOpen className="folder" />
            <b>{project.name}</b>
            <i
              onClick={(e) => {
                e.stopPropagation();
                setRenameOpen(true);
              }}
            >
              <Settings2 />
            </i>
          </button>
          <button
            className="tree-row indent"
            onClick={() => setOpen((o) => ({ ...o, Tasks: !o.Tasks }))}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu({ type: "tasks", x: e.clientX, y: e.clientY });
            }}
          >
            {open.Tasks ? <ChevronDown /> : <ChevronRight />}
            <Folder className="folder" /> Tasks{" "}
            <span className="count">{project.tasks.length}</span>
            <i
              onClick={(e) => {
                e.stopPropagation();
                setTaskDialog("starter");
              }}
            >
              <Plus />
            </i>
          </button>
          {open.Tasks &&
            project.tasks.map((t) => (
              <button
                key={t.id}
                className={`tree-row indent2 ${t.id === task.id ? "active" : ""}`}
                onClick={() => selectTask(t.id)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setMenu({ type: "task", x: e.clientX, y: e.clientY });
                }}
              >
                <Workflow />
                {t.name}
                <small>{t.kind}</small>
              </button>
            ))}
          <button
            className="tree-row indent"
            onClick={() => setOpen((o) => ({ ...o, Resources: !o.Resources }))}
          >
            {open.Resources ? <ChevronDown /> : <ChevronRight />}
            <Folder className="folder" /> Resources
          </button>
          {open.Resources && (
            <>
              <button
                className="tree-row indent2"
                onClick={() =>
                  setOpen((o) => ({ ...o, Connections: !o.Connections }))
                }
                onContextMenu={(e) => {
                  e.preventDefault();
                  setMenu({ type: "resources", x: e.clientX, y: e.clientY });
                }}
              >
                {open.Connections ? <ChevronDown /> : <ChevronRight />}
                <Cable /> Connections{" "}
                <span className="count">{project.resources.length}</span>
                <i
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setMenu({ type: "resources", x: e.clientX, y: e.clientY });
                  }}
                >
                  <Plus />
                </i>
              </button>
              {open.Connections &&
                project.resources.map((r) => (
                  <button
                    className={`tree-row indent3 ${selectedResource === r.id ? "active" : ""}`}
                    key={r.id}
                    onClick={() => {
                      setSelectedResource(r.id);
                      setSelected("");
                      setSelectedIds([]);
                      setSelectedEdge(null);
                      setActiveTab("configuration");
                    }}
                  >
                    <Database />
                    {r.name}
                    <small>{r.type}</small>
                  </button>
                ))}
            </>
          )}
          <button
            className="tree-row indent"
            onClick={() => setOpen((o) => ({ ...o, Packaging: !o.Packaging }))}
          >
            {open.Packaging ? <ChevronDown /> : <ChevronRight />}
            <Package /> Packaging
          </button>
          {open.Packaging && (
            <button className="tree-row indent2" onClick={() => setPackageOpen(true)}>
              <Package />
              {project.packaging?.artifact_name || project.id}-
              {project.packaging?.version || "1.0.0"}
            </button>
          )}
          <button
            className="tree-row indent"
            onClick={() => setOpen((o) => ({ ...o, Schemas: !o.Schemas }))}
          >
            {open.Schemas ? <ChevronDown /> : <ChevronRight />}
            <CodeXml /> Schemas{" "}
            <span className="count">{project.schemas.length}</span>
            <i
              onClick={(e) => {
                e.stopPropagation();
                setSchemaEditor(true);
              }}
            >
              <Plus />
            </i>
          </button>
          {open.Schemas &&
            project.schemas.map((s) => (
              <button
                className="tree-row indent2"
                key={s.id}
                onClick={() => setSchemaEditor(true)}
              >
                <CodeXml />
                {s.name}
              </button>
            ))}
          <button
            className="tree-row indent"
            onClick={() =>
              setOpen((o) => ({ ...o, Properties: !o.Properties }))
            }
          >
            {open.Properties ? <ChevronDown /> : <ChevronRight />}
            <Braces /> Properties{" "}
            <span className="count">
              {Object.keys(project.properties).length}
            </span>
            <i
              onClick={(e) => {
                e.stopPropagation();
                const name = prompt("New environment name")
                  ?.trim()
                  .toLowerCase();
                if (name && !project.properties[name])
                  setProject((p) => ({
                    ...p,
                    properties: { ...p.properties, [name]: newEnvironmentProperties() },
                  }));
              }}
            >
              <Plus />
            </i>
          </button>
          {open.Properties &&
            Object.keys(project.properties).map((name) => (
              <button
                className={`tree-row indent2 property-file ${project.active_environment === name ? "environment-active" : ""}`}
                key={name}
                onClick={() => {
                  setProject((p) => ({ ...p, active_environment: name }));
                  setPropertyEditor(name);
                }}
              >
                <Braces />
                {name}.properties
                <small>{project.properties[name].length}</small>
              </button>
            ))}
        </div>
        <div
          className="pane-splitter"
          title="Drag up or down to resize the project tree and activity palette"
          onPointerDown={(e) => {
            e.preventDefault();
            split.current = { y: e.clientY, height: treeHeight };
          }}
        >
          <span />
        </div>
        <div className={`palette ${paletteOpen ? "" : "collapsed"}`}>
          <button
            className="pane-title palette-toggle"
            onClick={() => setPaletteOpen((x) => !x)}
          >
            {paletteOpen ? <ChevronDown /> : <ChevronRight />} ACTIVITY PALETTE{" "}
            <small>{paletteOpen ? "DRAG TO CANVAS" : "OPEN"}</small>
          </button>
          {paletteOpen &&
            packs.map((p) => (
              <div className="activity-group" key={p.name}>
                <button
                  className="group-title"
                  onClick={() =>
                    setOpen((o) => ({ ...o, [p.name]: !o[p.name] }))
                  }
                >
                  {open[p.name] ? <ChevronDown /> : <ChevronRight />}
                  <p.icon />
                  <b>{p.name}</b>
                  <small>{p.items.length}</small>
                </button>
                {open[p.name] && (
                  <div className="activity-grid">
                    {p.items.map((d) => (
                      <button
                        key={d.label}
                        draggable
                        onDragStart={(e) =>
                          e.dataTransfer.setData("activity", JSON.stringify(d))
                        }
                      >
                        <span>{ai(d.asset)}</span>
                        <em>{d.label}</em>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
        </div>
      </aside>
      <main style={{ "--config-height": `${configHeight}px` } as React.CSSProperties}>
        <div className="canvas-toolbar">
          <span>
            <Activity /> Task Designer{" "}
            <small>
              {task.kind === "starter"
                ? "External event starts this flow"
                : "Invoked by Call Sub Task"}
            </small>
          </span>
          <span className="zoom">
            <button onClick={() => setZoom((z) => Math.max(0.6, z - 0.1))}>
              −
            </button>
            {Math.round(zoom * 100)}%
            <button onClick={() => setZoom((z) => Math.min(1.5, z + 0.1))}>
              +
            </button>
          </span>
        </div>
        {debugState && <DebugBar state={debugState} act={debugAction} />}
        <div
          className="canvas"
          ref={canvas}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            const raw = e.dataTransfer.getData("activity");
            if (!raw || !canvas.current) return;
            const r = canvas.current.getBoundingClientRect();
            addActivity(JSON.parse(raw), {
              x: (e.clientX - r.left + canvas.current.scrollLeft) / zoom - 55,
              y: (e.clientY - r.top + canvas.current.scrollTop) / zoom - 40,
            });
          }}
          onContextMenu={(e) => {
            e.preventDefault();
            setMenu({
              type: "canvas",
              x: e.clientX,
              y: e.clientY,
              cx: e.nativeEvent.offsetX / zoom,
              cy: e.nativeEvent.offsetY / zoom,
            });
          }}
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) { setSelectedIds([]); setSelected(""); setSelectedEdge(null); setSelectedResource(null); }
          }}
        >
          <div
            className="canvas-content"
            style={{ transform: `scale(${zoom})` }}
          >
            <svg className="wires">
              {edges.map((e) => {
                const a = byId[e.source],
                  b = byId[e.target];
                if (!a || !b) return null;
                const d = `M${a.position.x + 142},${a.position.y + 38} C${a.position.x + 180},${a.position.y + 38} ${b.position.x - 38},${b.position.y + 38} ${b.position.x},${b.position.y + 38}`;
                return (
                  <g
                    key={e.id}
                    className={`${e.type || "success"} ${selectedEdge === e.id ? "selected" : ""}`}
                    onClick={() => {
                      setSelectedEdge(e.id);
                      setSelected("");
                      setSelectedIds([]);
                      setSelectedResource(null);
                      setActiveTab("configuration");
                    }}
                  >
                    <path className="edge-hit" d={d} />
                    <path d={d} />
                    <text
                      x={(a.position.x + b.position.x + 142) / 2}
                      y={(a.position.y + b.position.y) / 2 + 31}
                    >
                      {e.type || "success"}
                    </text>
                  </g>
                );
              })}
              {connectionDraft && byId[connectionDraft.source] && (
                <path
                  className="draft-connection"
                  d={`M${byId[connectionDraft.source].position.x + 108},${byId[connectionDraft.source].position.y + 39} C${byId[connectionDraft.source].position.x + 165},${byId[connectionDraft.source].position.y + 39} ${connectionDraft.x - 45},${connectionDraft.y} ${connectionDraft.x},${connectionDraft.y}`}
                />
              )}
            </svg>
            {nodes.map((n) => {
              const def = packs
                .flatMap((p) => p.items)
                .find(
                  (d) =>
                    d.type === n.type &&
                    (!d.operation || d.operation === n.config.operation),
                );
              return (
                <button
                  key={n.id}
                  data-node-id={n.id}
                  className={`node ${selectedIds.includes(n.id) ? "selected" : ""} ${selectedIds.length > 1 && selectedIds.includes(n.id) ? "multi-selected" : ""} ${debugState?.currentActivityId === n.id ? "debug-current" : ""}`}
                  style={{ left: n.position.x, top: n.position.y }}
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    const additive = e.ctrlKey || e.metaKey || e.shiftKey;
                    const nextIds = additive ? (selectedIds.includes(n.id) ? selectedIds : [...selectedIds, n.id]) : (selectedIds.includes(n.id) && selectedIds.length > 1 ? selectedIds : [n.id]);
                    const positions = Object.fromEntries(nodes.filter((item) => nextIds.includes(item.id)).map((item) => [item.id, { ...item.position }]));
                    drag.current = {
                      ids: nextIds,
                      positions,
                      startX: e.clientX,
                      startY: e.clientY,
                    };
                    setSelected(n.id);
                    setSelectedIds(nextIds);
                    setSelectedEdge(null);
                    setSelectedResource(null);
                    setActiveTab("configuration");
                  }}
                  onDoubleClick={() =>
                    setBreakpoints((b) =>
                      b.includes(n.id)
                        ? b.filter((x) => x !== n.id)
                        : [...b, n.id],
                    )
                  }
                >
                  <span className="node-icon">
                    {ai(
                      n.type === "start"
                        ? "start-play"
                        : n.type === "end"
                          ? "end-stop"
                          : def?.asset || "start-end",
                    )}
                  </span>
                  {breakpoints.includes(n.id) && <i className="breakpoint" />}
                  <strong>{n.name}</strong>
                  <small>{(n.config.operation || n.type).toUpperCase()}</small>
                  <span
                    className="connect-handle"
                    role="button"
                    aria-label={`Connect ${n.name} to another activity`}
                    title="Drag to another activity to create a transition"
                    onPointerDown={(event) => {
                      event.preventDefault(); event.stopPropagation();
                      setConnectionDraft({ source: n.id, x: n.position.x + 108, y: n.position.y + 39 });
                    }}
                  ><ChevronRight /></span>
                </button>
              );
            })}
          </div>
        </div>
        <div
          className="config-splitter"
          title="Drag up or down to resize configuration"
          onPointerDown={(event) => {
            event.preventDefault();
            configSplit.current = { y: event.clientY, height: configHeight };
          }}
        ><span /></div>
        <section className="config">
          <div className="tabs">
            <b>
              <Settings2 /> {edge ? "Transition" : resource ? "Connection" : "Activity"}
            </b>
            {node ? (["configuration", "input", "output", "advanced", "errors", "documentation"] as const).map(
              (tab) => (
                <button
                  key={tab}
                  className={activeTab === tab ? "active" : ""}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === "configuration"
                    ? "Configuration"
                    : tab[0].toUpperCase() + tab.slice(1)}
                </button>
              ),
            ) : <button className="active">Configuration</button>}
            {node && <button className="delete-selected-activity" title="Delete selected activity (Delete or Backspace)" onClick={deleteSelectedActivity}><Trash2/> Delete Activity</button>}
          </div>
          {node ? (
            <ActivityEditor
              node={node}
              task={task}
              resources={project.resources}
              tasks={project.tasks}
              schemas={project.schemas}
              properties={project.properties[project.active_environment] || []}
              tab={activeTab}
              update={(c: any) =>
                mutateTask((t) => ({
                  ...t,
                  activities: t.activities.map((n) =>
                    n.id === selected ? { ...n, ...c } : n,
                  ),
                }))
              }
            />
          ) : edge ? (
            <EdgeConfig
              edge={edge}
              properties={project.properties[project.active_environment] || []}
              update={(c: any) =>
                mutateTask((t) => ({
                  ...t,
                  transitions: t.transitions.map((e) =>
                    e.id === edge.id ? { ...e, ...c } : e,
                  ),
                }))
              }
              onDelete={deleteSelectedTransition}
            />
          ) : resource ? (
            <ConnectionConfig
              resource={resource}
              update={(c: any) =>
                setProject((p) => ({
                  ...p,
                  resources: p.resources.map((r) =>
                    r.id === resource.id ? { ...r, ...c } : r,
                  ),
                }))
              }
            />
          ) : (
            <div className="empty">
              Select an activity, transition, or shared connection.
            </div>
          )}
        </section>
      </main>
      <aside className="monitor">
        <div className="pane-title">EXECUTION / DEBUG</div>
        <div className="run-state">
          <span />{" "}
          {debugState
            ? `${debugState.status} · stack ${debugState.callStack?.length || 0}`
            : `Runtime: ${project.active_environment}`}
        </div>
        {!!endpoints.length && <section className="runtime-endpoints">
          <strong>LIVE ENDPOINTS</strong>
          {endpoints.map((endpoint: any) => <article key={endpoint.activityId}>
            <span>{endpoint.methods?.join(", ")} · {endpoint.name}</span>
            <code>{endpoint.url}</code>
            <button title="Copy endpoint URL" onClick={() => navigator.clipboard.writeText(endpoint.url)}><ClipboardCopy/> Copy</button>
            {endpoint.configuredUrl && endpoint.configuredUrl !== endpoint.url && <small>Packaged deployment: {endpoint.configuredUrl}</small>}
          </article>)}
        </section>}
        {(() => {
          const visible = Object.values(executionOutputs).filter((record: any) => !["start", "end", "log"].includes(record.type));
          return !!visible.length && <details className="runtime-outputs" open>
          <summary>EXECUTED PATH OUTPUTS <b>{visible.length}</b></summary>
          {visible.map((record: any) => <details key={record.activityId}>
            <summary><span>{record.name}</span><small>{record.type}</small></summary>
            <pre>{JSON.stringify(record.logEvent || record.output, null, 2)}</pre>
          </details>)}
        </details>})()}
        {logs.filter((l) => l.kind !== "trace").map((l, i) => (
          <div className={`log ${(l.level || "info").toLowerCase()}`} key={i}>
            <small>{l.level}</small>
            <p>{l.message}</p>
            {l.payload !== undefined && l.payload !== "" && l.payload !== null && <pre>{JSON.stringify(l.payload, null, 2)}</pre>}
          </div>
        ))}
      </aside>
      <input
        hidden
        ref={fileInput}
        type="file"
        accept=".ifproject,.zip,.json"
        onChange={(e) =>
          e.target.files?.[0] && importProject(e.target.files[0])
        }
      />
      {typeof menu === "object" && menu && (
        <Context
          menu={menu}
          addActivity={addActivity}
          createTask={setTaskDialog}
          createConnection={setConnectionDialog}
          close={() => setMenu(null)}
        />
      )}{" "}
      {taskDialog && (
        <TaskDialog
          kind={taskDialog}
          onClose={() => setTaskDialog(null)}
          onCreate={(
            name: string,
            kind: "starter" | "subtask",
            event: string,
          ) => {
            const id = `task-${Date.now()}`,
              t = { ...starter(id, name), kind };
            if (kind === "starter" && event !== "start")
              t.activities[0] = {
                ...t.activities[0],
                type: event as Kind,
                name:
                  event === "timer"
                    ? "Timer / Scheduler"
                    : event === "sap"
                      ? "SAP IDoc Listener"
                      : event.replaceAll("_", " "),
                config: {
                  advanced: advancedDefaults(),
                  operation:
                    event === "rest"
                      ? "receiver"
                      : event === "file"
                        ? "poll"
                        : event === "ems"
                          ? "queue_receiver"
                          : event === "kafka"
                            ? "receive"
                            : event === "pubsub"
                              ? "subscribe"
                              : event === "sap"
                                ? "idoc_listener"
                                : "listen",
                  resourceId:
                    event === "sap"
                      ? project.resources.find((r) => r.type === "sap")?.id ||
                        ""
                      : undefined,
                  path: "/events",
                },
              };
            setProject((p) => ({
              ...p,
              tasks: [...p.tasks, t],
              active_task_id: id,
            }));
            setSelected(t.activities[0]?.id || "");
            setSelectedIds(t.activities[0] ? [t.activities[0].id] : []);
            setTaskDialog(null);
          }}
        />
      )}
      {connectionDialog && (
        <SharedConnectionDialog
          type={connectionDialog}
          properties={project.properties[project.active_environment] || []}
          onClose={() => setConnectionDialog(null)}
          onCreate={(r: Resource) => {
            setProject((p) => ({ ...p, resources: [...p.resources, r] }));
            setConnectionDialog(null);
            setSelectedResource(r.id);
          }}
        />
      )}
      {schemaEditor && (
        <SchemaStudio
          initialTab="design"
          onClose={() => setSchemaEditor(false)}
          onSave={(s) => {
            setProject((p) => ({
              ...p,
              schemas: [...p.schemas.filter((x) => x.id !== s.id), s],
            }));
            setSchemaEditor(false);
          }}
        />
      )}
      {propertyEditor && (
        <PropertyEditor
          environment={propertyEditor}
          properties={project.properties[propertyEditor] || []}
          onClose={() => setPropertyEditor(null)}
          onSave={(items: Property[]) => {
            setProject((p) => ({
              ...p,
              properties: { ...p.properties, [propertyEditor]: items },
            }));
            setPropertyEditor(null);
          }}
        />
      )}
      {packageOpen && <PackageDialog packaging={project.packaging} environments={Object.keys(project.properties)} onClose={() => setPackageOpen(false)} onPackage={buildDeploymentPackage}/>} 
      {helpDialog && <HelpDialog mode={helpDialog} onClose={() => setHelpDialog(null)}/>} 
      {validation && <ValidationDialog result={validation} onClose={() => setValidation(null)} onOpen={(issue: ValidationIssue) => {
        if (issue.taskId) selectTask(issue.taskId);
        if (issue.activityId) { setSelected(issue.activityId); setSelectedIds([issue.activityId]); setSelectedEdge(null); setSelectedResource(null); }
        setValidation(null);
      }}/>} 
      {renameOpen && (
        <RenameApplication
          name={project.name}
          onClose={() => setRenameOpen(false)}
          onSave={(name: string) => {
            setProject((p) => ({
              ...p,
              name,
              packaging: {
                ...p.packaging,
                artifact_name:
                  p.packaging?.artifact_name ||
                  name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
              },
            }));
            setRenameOpen(false);
          }}
        />
      )}
    </div>
  );
}
function PackageDialog({ packaging, environments, onClose, onPackage }: any) {
  const [draft, setDraft] = useState({
    artifact_name: packaging?.artifact_name || "integration-application",
    version: packaging?.version || "1.0.0",
    target: packaging?.target || "on-prem",
    environment: packaging?.environment || "production",
    format: packaging?.format || "ifpkg",
  });
  const update = (key: string, value: string) => setDraft((current) => ({ ...current, [key]: value }));
  const extension = draft.format === "ifpkg" ? "ifpkg" : draft.format;
  return <div className="modal-backdrop"><div className="package-modal">
    <header><div><Package/><b>Build deployment package</b><small>Choose how this integration will run</small></div><button onClick={onClose}>×</button></header>
    <main>
      <label>Artifact name<input value={draft.artifact_name} onChange={(event) => update("artifact_name", event.target.value)}/></label>
      <label>Version<input value={draft.version} onChange={(event) => update("version", event.target.value)}/></label>
      <div className="package-targets">
        <button className={draft.target === "on-prem" ? "selected" : ""} onClick={() => update("target", "on-prem")}><HardDrive/><span><b>On-premises Linux</b><small>Administrator and runtime-agent deployment without containers</small></span></button>
        <button className={draft.target === "cloud" ? "selected" : ""} onClick={() => update("target", "cloud")}><Cloud/><span><b>Cloud / Kubernetes</b><small>OCI image inputs and Kubernetes deployment descriptor</small></span></button>
      </div>
      <label>Target environment<select value={draft.environment} onChange={(event) => update("environment", event.target.value)}>{environments.map((name: string) => <option key={name}>{name}</option>)}</select></label>
      <label>Archive format<select value={draft.format} onChange={(event) => update("format", event.target.value)}><option value="ifpkg">Integration package (.ifpkg)</option><option value="tar.gz">Compressed TAR (.tar.gz)</option><option value="ear">EAR-compatible ZIP (.ear)</option></select></label>
      <div className="package-preview"><Package/><span><b>{draft.artifact_name}-{draft.version}-{draft.target}.{extension}</b><small>{draft.target === "cloud" ? "Includes Docker build input and Kubernetes manifest" : "Includes the Linux Administrator deployment descriptor"}</small></span></div>
      <p className="package-security"><ShieldCheck/> Password values are removed. The target Administrator or Kubernetes secret provider supplies credentials during deployment.</p>
    </main>
    <footer><button onClick={onClose}>Cancel</button><button className="primary" disabled={!draft.artifact_name.trim() || !draft.version.trim()} onClick={() => onPackage(draft)}>Validate and package</button></footer>
  </div></div>;
}
function StudioRibbon(props: any) {
  const command = (label: string, Icon: any, action: () => void, disabled = false, emphasis = false) =>
    <button type="button" className={emphasis ? "emphasis" : ""} disabled={disabled} onClick={(event) => { event.stopPropagation(); action(); }} title={label}><Icon/><span>{label}</span></button>;
  return <section className="studio-ribbon" aria-label="Studio ribbon">
    <div className="ribbon-group"><b>PROJECT</b><div>{command("New", FilePlus2, props.newProject)}{command("Open", FolderOpen, props.openProject)}{command("Import", Upload, props.importProject)}{command("Save", Save, props.save, false, true)}{command("Export", Download, props.exportProject)}{command("Package", Package, props.packageProject)}{command("Close", Square, props.closeProject)}</div></div>
    <div className="ribbon-group"><b>EXECUTE & VALIDATE</b><div>{command("Run", CirclePlay, props.run, false, true)}{command("Debug", Bug, props.debug)}{command("Validate Task", ShieldCheck, props.validateTask)}{command("Validate Project", CheckCircle2, props.validateProject)}</div></div>
    <div className="ribbon-group"><b>EDIT</b><div>{command("Undo", Undo2, props.undo)}{command("Cut", Scissors, props.cut, !props.selectedCount)}{command("Copy", ClipboardCopy, props.copy, !props.selectedCount)}{command("Paste", ClipboardPaste, props.paste)}</div></div>
    <div className="ribbon-group layout-group"><b>ARRANGE · {props.selectedCount} SELECTED</b><div>{command("Align Vertical", AlignVerticalSpaceAround, props.alignVertical, props.selectedCount < 2)}{command("Align Horizontal", AlignHorizontalSpaceAround, props.alignHorizontal, props.selectedCount < 2)}{command("Move Up", ArrowUp, props.moveUp, !props.selectedCount)}{command("Move Down", ArrowDown, props.moveDown, !props.selectedCount)}</div></div>
  </section>;
}
function ValidationDialog({ result, onClose, onOpen }: any) {
  const counts = result.issues.reduce((value: any, issue: ValidationIssue) => ({ ...value, [issue.severity]: (value[issue.severity] || 0) + 1 }), {});
  return <div className="modal-backdrop"><div className="runtime-modal validation-dialog"><header><span><ShieldCheck/><b>{result.title}</b></span><button aria-label="Close validation" onClick={onClose}>×</button></header><div className="validation-summary"><span className="error">{counts.error || 0} errors</span><span className="warning">{counts.warning || 0} warnings</span><span className="mapping">{counts.mapping || 0} mappings needed</span></div><main>{!result.issues.length ? <div className="validation-clean"><CheckCircle2/><h2>Validation successful</h2><p>No errors or missing mappings were found.</p></div> : result.issues.map((issue: ValidationIssue) => <button key={issue.id} className={`validation-issue ${issue.severity}`} onClick={() => onOpen(issue)}><span>{issue.severity === "error" ? "ERROR" : issue.severity === "mapping" ? "MAPPING" : "WARNING"}</span><div><b>{issue.category}</b><p>{issue.message}</p><small>{issue.remedy}</small></div>{(issue.taskId || issue.activityId) && <ChevronRight/>}</button>)}</main><footer><span>Click a task/activity finding to open it in the designer.</span><button className="primary" onClick={onClose}>Close</button></footer></div></div>;
}
function RenameApplication({ name, onClose, onSave }: any) {
  const [value, setValue] = useState(name);
  return (
    <div className="modal-backdrop">
      <div className="runtime-modal rename-modal">
        <header>
          <b>Rename application</b>
          <button onClick={onClose}>×</button>
        </header>
        <main>
          <label>
            Application name
            <input
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && value.trim()) onSave(value.trim());
              }}
            />
          </label>
          <p>
            This name appears at the root of Project Explorer and in exported
            project metadata.
          </p>
        </main>
        <footer>
          <button onClick={onClose}>Cancel</button>
          <button
            className="primary"
            disabled={!value.trim()}
            onClick={() => onSave(value.trim())}
          >
            Rename
          </button>
        </footer>
      </div>
    </div>
  );
}
function PropertyEditor({ environment, properties, onClose, onSave }: any) {
  const [draft, setDraft] = useState<Property[]>(properties),
    [mode, setMode] = useState<"table" | "json" | "plain">("table"),
    [text, setText] = useState(""),
    [error, setError] = useState("");
  const convertValue = (value: any, type: Property["data_type"]) => {
    if (type === "boolean") return typeof value === "boolean" ? value : ["true", "1", "yes", "on"].includes(String(value).toLowerCase());
    if (["integer", "long"].includes(type)) return value === "" ? "" : Number.parseInt(String(value), 10);
    if (type === "number") return value === "" ? "" : Number(value);
    if (type === "json" && typeof value === "string") { try { return JSON.parse(value); } catch { return value; } }
    return value == null ? "" : value;
  };
  const types: Property["data_type"][] = [
      "string",
      "integer",
      "long",
      "number",
      "boolean",
      "dateTime",
      "password",
      "json",
    ],
    switchMode = (next: "table" | "json" | "plain") => {
      setMode(next);
      setError("");
      setText(
        next === "json"
          ? JSON.stringify(
              Object.fromEntries(
                draft.map((p) => [
                  p.key,
                  { value: p.value, type: p.data_type },
                ]),
              ),
              null,
              2,
            )
          : next === "plain"
            ? draft
                .map(
                  (p) =>
                    `${p.key}:${p.data_type}=${typeof p.value === "object" ? JSON.stringify(p.value) : p.value}`,
                )
                .join("\n")
            : "",
      );
    },
    commit = () => {
      try {
        let result = draft;
        if (mode === "json") {
          const data = JSON.parse(text);
          result = Object.entries(data).map(([key, item]: any) => ({
            key,
            value:
              item && typeof item === "object" && "value" in item
                ? item.value
                : item,
            data_type: (item?.type || "string") as Property["data_type"],
          }));
        }
        if (mode === "plain")
          result = text
            .split(/\r?\n/)
            .filter(Boolean)
            .map((line) => {
              const match = line.match(
                /^([^:=]+)(?::(string|integer|long|number|boolean|dateTime|password|json))?=(.*)$/,
              );
              if (!match) throw new Error(`Invalid line: ${line}`);
              let value: any = match[3],
                data_type = (match[2] || "string") as Property["data_type"];
              if (["integer", "long", "number"].includes(data_type))
                value = Number(value);
              if (data_type === "boolean") value = value === "true";
              if (data_type === "json") value = JSON.parse(value);
              const key = match[1].trim();
              return { key, value, data_type };
            });
        onSave(result);
      } catch (e: any) {
        setError(e.message);
      }
    };
  return (
    <div className="modal-backdrop">
      <div className="runtime-modal property-editor-modal">
        <header>
          <div>
            <Braces />
            <span>
              <b>{environment}.properties</b>
              <small>Application environment properties</small>
            </span>
          </div>
          <button onClick={onClose}>×</button>
        </header>
        <div className="property-mode-tabs">
          <button
            className={mode === "table" ? "active" : ""}
            onClick={() => switchMode("table")}
          >
            Key / Value
          </button>
          <button
            className={mode === "json" ? "active" : ""}
            onClick={() => switchMode("json")}
          >
            JSON
          </button>
          <button
            className={mode === "plain" ? "active" : ""}
            onClick={() => switchMode("plain")}
          >
            Plain text
          </button>
        </div>
        {mode === "table" ? (
          <main className="property-grid">
            <header>
              <b>Key</b>
              <b>Value</b>
              <b>Data type</b>
              <span />
            </header>
            {draft.map((p, i) => (
              <div key={i}>
                <input
                  value={p.key}
                  placeholder="property.name"
                  onChange={(e) =>
                    setDraft((x) =>
                      x.map((v, j) =>
                        j === i ? { ...v, key: e.target.value } : v,
                      ),
                    )
                  }
                />
                <input
                  type={
                    p.data_type === "password"
                      ? "password"
                      : p.data_type === "dateTime"
                        ? "datetime-local"
                        : "text"
                  }
                  value={
                    typeof p.value === "object"
                      ? JSON.stringify(p.value)
                      : String(p.value)
                  }
                  onChange={(e) =>
                    setDraft((x) =>
                      x.map((v, j) =>
                        j === i ? { ...v, value: e.target.value } : v,
                      ),
                    )
                  }
                />
                <select
                  value={p.data_type}
                  onChange={(e) =>
                    setDraft((x) =>
                      x.map((v, j) =>
                        j === i
                          ? {
                              ...v,
                              data_type: e.target
                                .value as Property["data_type"],
                              value: convertValue(v.value, e.target.value as Property["data_type"]),
                            }
                          : v,
                      ),
                    )
                  }
                >
                  {types.map((type) => (
                    <option key={type}>{type}</option>
                  ))}
                </select>
                <button
                  onClick={() => setDraft((x) => x.filter((_, j) => j !== i))}
                >
                  <Trash2 />
                </button>
              </div>
            ))}
            <button
              className="add-property"
              onClick={() =>
                setDraft((x) => [
                  ...x,
                  { key: "", value: "", data_type: "string" },
                ])
              }
            >
              <Plus /> Add property
            </button>
          </main>
        ) : (
          <textarea
            className="property-source"
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
          />
        )}{" "}
        {error && <div className="editor-error">{error}</div>}
        <footer>
          <span>
            Reference as <code>{"${properties.key}"}</code>
          </span>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={commit}>
            Apply
          </button>
        </footer>
      </div>
    </div>
  );
}
function focusStudioPanel(selector: string) {
  const element = document.querySelector<HTMLElement>(selector);
  if (!element) return;
  element.tabIndex = -1;
  element.focus({ preventScroll: false });
  element.scrollIntoView({ behavior: "smooth", block: "nearest" });
  element.classList.add("menu-focus-flash");
  window.setTimeout(() => element.classList.remove("menu-focus-flash"), 700);
}
function TopMenu({ label, open, toggle, commands }: any) {
  return <div className="menu-root"><button className={open ? "active" : ""} onClick={toggle}>{label}</button>{open && <div className="menu-dropdown command-menu glossy-menu" onClick={(event) => event.stopPropagation()}>{commands.map((command: any) => { const Icon = command.icon; return <button key={command.label} disabled={command.disabled} onClick={() => { command.action(); toggle({ stopPropagation() {} }); }}><Icon/><span><b>{command.label}</b><small>{command.detail}</small></span>{command.shortcut && <kbd>{command.shortcut}</kbd>}</button>; })}</div>}</div>;
}
function HelpDialog({ mode, onClose }: any) {
  return <div className="modal-backdrop"><div className="runtime-modal help-dialog"><header><b>{mode === "shortcuts" ? "Keyboard Shortcuts" : "About Integration Fabric"}</b><button onClick={onClose}>×</button></header><main>{mode === "shortcuts" ? <div className="shortcut-grid"><kbd>Ctrl+Z</kbd><span>Undo Studio change (100 levels)</span><kbd>Ctrl+Y</kbd><span>Redo Studio change</span><kbd>Ctrl+Shift+Z</kbd><span>Redo Studio change</span><kbd>Delete</kbd><span>Delete selected activity or transition</span><kbd>Ctrl+S</kbd><span>Save project</span><kbd>F5</kbd><span>Run active task</span><kbd>F6</kbd><span>Start debugging</span><kbd>Right-click</kbd><span>Open context commands or activity search</span><kbd>Drag</kbd><span>Move activities on the canvas</span></div> : <div className="about-panel"><Workflow/><h2>Integration Fabric Studio</h2><p>Lightweight JSON-backed integration design, configuration, execution, and debugging.</p><code>Project: {location.pathname === "/" ? "Local Studio" : location.pathname}</code></div>}</main><footer><button className="primary" onClick={onClose}>Close</button></footer></div></div>;
}
function FileMenu({
  stop,
  save,
  saveJson,
  exportProject,
  importProject,
  openProjects,
  closeProject,
  deleteProject,
}: any) {
  const go = (action: () => void) => () => {
    action();
  };
  return (
    <div className="menu-dropdown project-menu glossy-menu" onClick={stop}>
      <b>PROJECT</b>
      <button onClick={go(save)}>
        <Save />
        <span>
          Save Project<small>Write lightweight JSON to backend</small>
        </span>
        <kbd>Ctrl+S</kbd>
      </button>
      <button onClick={go(saveJson)}>
        <Download />
        <span>
          Save Project to File System<small>Complete readable JSON file</small>
        </span>
      </button>
      <button onClick={go(exportProject)}>
        <Package />
        <span>
          Export Project Package<small>Portable .ifproject archive</small>
        </span>
      </button>
      <button onClick={go(importProject)}>
        <Upload />
        <span>
          Import Project<small>Open .ifproject or JSON</small>
        </span>
      </button>
      <button onClick={go(openProjects)}>
        <FolderOpen />
        <span>
          Open Saved Project<small>Projects stored by the runtime</small>
        </span>
      </button>
      <hr />
      <button onClick={go(closeProject)}>
        <Square />
        <span>
          Close Project<small>Return to project home</small>
        </span>
      </button>
      <button className="danger" onClick={go(deleteProject)}>
        <Trash2 />
        <span>
          Delete Project<small>Remove backend JSON files</small>
        </span>
      </button>
    </div>
  );
}
function ThemePicker({ theme, setTheme }: any) {
  return (
    <label className="theme-picker">
      THEME
      <select
        aria-label="Theme"
        value={theme}
        onChange={(e) => setTheme(e.target.value)}
      >
        {themeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}
function ProjectWelcome({ openProject, importProject, theme, setTheme }: any) {
  const [projects, setProjects] = useState<Project[]>([]),
    input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    fetch("/api/projects")
      .then((r) => r.json())
      .then(setProjects);
  }, []);
  return (
    <div className="project-home">
      <header>
        <div className="brand">
          <Workflow />
          <span>
            INTEGRATION <b>FABRIC</b>
          </span>
          <small>PROJECT HOME</small>
        </div>
        <ThemePicker theme={theme} setTheme={setTheme} />
      </header>
      <main>
        <section className="home-card">
          <div className="home-glow" />
          <Workflow />
          <h1>Projects</h1>
          <p>
            Open a lightweight JSON-backed project or import a portable
            Integration Fabric package.
          </p>
          <button className="primary" onClick={() => input.current?.click()}>
            <Upload /> Import project
          </button>
        </section>
        <section className="project-list">
          <h2>
            Saved projects <small>{projects.length}</small>
          </h2>
          {projects.map((p) => (
            <button key={p.id} onClick={() => openProject(p.id)}>
              <FolderOpen />
              <span>
                <b>{p.name}</b>
                <small>
                  {p.tasks.length} task{p.tasks.length === 1 ? "" : "s"} ·{" "}
                  {p.resources.length} shared connection
                  {p.resources.length === 1 ? "" : "s"}
                </small>
              </span>
              <ChevronRight />
            </button>
          ))}
          {!projects.length && <div className="empty">No saved projects.</div>}
        </section>
      </main>
      <input
        ref={input}
        hidden
        type="file"
        accept=".ifproject,.zip,.json"
        onChange={(e) =>
          e.target.files?.[0] && importProject(e.target.files[0])
        }
      />
    </div>
  );
}
function Context({
  menu,
  addActivity,
  createTask,
  createConnection,
  close,
}: any) {
  if (menu.type === "canvas")
    return (
      <ActivityPicker
        menu={menu}
        packs={packs}
        addActivity={addActivity}
        close={close}
      />
    );
  return (
    <div
      className="canvas-menu resource-menu"
      style={{ left: menu.x, top: menu.y }}
      onClick={(e) => e.stopPropagation()}
    >
      {(menu.type === "tasks" || menu.type === "task") && (
        <>
          <b>Create Task</b>
          <button
            onClick={() => {
              createTask("starter");
              close();
            }}
          >
            <CirclePlay /> Starter Task
          </button>
          <button
            onClick={() => {
              createTask("subtask");
              close();
            }}
          >
            <Workflow /> Sub Task
          </button>
        </>
      )}
      {menu.type === "resources" && (
        <>
          <b>Create shared connection</b>
          {(
            [
              "http",
              "ftp",
              "sftp",
              "ems",
              "kafka",
              "pubsub",
              "jdbc",
              "sap",
              "sap_tid",
            ] as const
          ).map((t) => (
            <button
              key={t}
              onClick={() => {
                createConnection(t);
                close();
              }}
            >
              <Cable />{" "}
              {t === "jdbc"
                ? "Database"
                : t === "sap"
                  ? "SAP ECC"
                  : t === "sap_tid"
                    ? "SAP TID Manager"
                    : t.toUpperCase()}{" "}
              Connection
            </button>
          ))}
        </>
      )}
    </div>
  );
}
function TaskDialog({ kind, onClose, onCreate }: any) {
  const [name, setName] = useState(
      kind === "starter" ? "New Starter Task" : "New Sub Task",
    ),
    [event, setEvent] = useState("http_listener");
  return (
    <div className="modal-backdrop">
      <div className="runtime-modal">
        <header>
          <b>Create {kind === "starter" ? "Starter Task" : "Sub Task"}</b>
          <button onClick={onClose}>×</button>
        </header>
        <main>
          <label>
            Task name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          {kind === "starter" && (
            <label>
              Starting event
              <select value={event} onChange={(e) => setEvent(e.target.value)}>
                <option value="http_listener">HTTP Listener</option>
                <option value="rest">REST API Receiver</option>
                <option value="file">File Poller</option>
                <option value="timer">Timer / Scheduler</option>
                <option value="ems">EMS Queue Receiver</option>
                <option value="kafka">Kafka Receive Message</option>
                <option value="pubsub">GCP Pub/Sub Subscriber</option>
                <option value="sap">SAP IDoc Listener</option>
                <option value="start">Manual Start</option>
              </select>
            </label>
          )}
          <p>
            {kind === "subtask"
              ? "Reusable task invoked directly by Call Sub Task. Input and output return to the parent unless Spawn is enabled."
              : "A runnable entry task triggered by an external event."}
          </p>
        </main>
        <footer>
          <button onClick={onClose}>Cancel</button>
          <button
            className="primary"
            onClick={() => onCreate(name, kind, event)}
          >
            Create
          </button>
        </footer>
      </div>
    </div>
  );
}
const propertyExpression = (key: string) => `\${properties.${key}}`;
const connectionFieldSets: Record<string, any[]> = {
  jdbc: [
    { key: "driver", label: "Database", options: ["sqlite", "postgresql", "mysql", "mariadb", "sqlserver", "oracle", "db2", "snowflake"] },
    { key: "url", label: "JDBC URL" }, { key: "host", label: "Host" }, { key: "port", label: "Port" },
    { key: "database", label: "Database name" }, { key: "schema", label: "Schema" },
    { key: "username", label: "Username" }, { key: "password", label: "Password", password: true },
    { key: "timeoutSeconds", label: "Connection timeout (seconds)" },
    { key: "minimumPoolSize", label: "Minimum pool size" }, { key: "maximumPoolSize", label: "Maximum pool size" },
  ],
  http: [
    { key: "connectorMode", label: "Connector mode", options: ["server", "client", "both"] },
    { key: "scheme", label: "Protocol", options: ["http", "https"] }, { key: "host", label: "Listener host" }, { key: "port", label: "Listener port" },
    { key: "basePath", label: "Listener base path" }, { key: "baseUrl", label: "Outbound base URL" },
    { key: "authentication", label: "Authentication", options: ["None", "Basic", "Bearer", "Certificate"] },
    { key: "username", label: "Basic-auth username" }, { key: "password", label: "Basic-auth password", password: true },
    { key: "bearerToken", label: "Bearer token", password: true }, { key: "tlsEnabled", label: "Enable HTTPS / SSL", options: ["false", "true"] },
    { key: "certificateFile", label: "Server certificate file" }, { key: "privateKeyFile", label: "Server private key file" },
    { key: "privateKeyPassword", label: "Private key password", password: true }, { key: "certificateAuthorityFile", label: "Trusted CA file" },
    { key: "clientAuthentication", label: "Client certificate authentication", options: ["none", "optional", "required"] },
    { key: "tlsVersion", label: "Minimum TLS version", options: ["TLSv1.2", "TLSv1.3"] },
    { key: "connectTimeoutSeconds", label: "Connect timeout (seconds)" }, { key: "timeoutSeconds", label: "Read timeout (seconds)" },
    { key: "proxyHost", label: "Proxy host" }, { key: "proxyPort", label: "Proxy port" }, { key: "verifyTls", label: "Verify outbound TLS", options: ["true", "false"] },
  ],
  ftp: [
    { key: "host", label: "Host" }, { key: "port", label: "Port" }, { key: "username", label: "Username" },
    { key: "password", label: "Password", password: true }, { key: "workingDirectory", label: "Working directory" },
    { key: "passiveMode", label: "Passive mode", options: ["true", "false"] }, { key: "timeoutSeconds", label: "Timeout (seconds)" },
  ],
  sftp: [
    { key: "host", label: "Host" }, { key: "port", label: "Port" }, { key: "username", label: "Username" },
    { key: "password", label: "Password", password: true }, { key: "workingDirectory", label: "Working directory" },
    { key: "privateKeyFile", label: "Private key file" }, { key: "privateKeyPassphrase", label: "Private key passphrase", password: true },
    { key: "knownHostsFile", label: "Known hosts file" }, { key: "strictHostKeyChecking", label: "Strict host-key checking", options: ["true", "false"] },
    { key: "timeoutSeconds", label: "Timeout (seconds)" },
  ],
  ems: [
    { key: "mode", label: "Runtime mode", options: ["memory", "external"] }, { key: "serverUrl", label: "Server URL" },
    { key: "connectionFactoryType", label: "Connection factory type", options: ["Direct", "JNDI"] },
    { key: "messagingStyle", label: "Messaging style", options: ["Generic", "Queue/Topic"] },
    { key: "host", label: "Host" }, { key: "port", label: "Port" }, { key: "username", label: "Username" },
    { key: "password", label: "Password", password: true }, { key: "clientId", label: "Client ID" },
    { key: "connectionFactory", label: "Connection factory", options: ["ConnectionFactory", "QueueConnectionFactory", "TopicConnectionFactory"] },
    { key: "queueConnectionFactory", label: "Queue connection factory" }, { key: "topicConnectionFactory", label: "Topic connection factory" },
    { key: "jndiContextFactory", label: "JNDI context factory" }, { key: "jndiProviderUrl", label: "JNDI provider URL" },
    { key: "jndiUsername", label: "JNDI username" }, { key: "jndiPassword", label: "JNDI password", password: true },
    { key: "useXa", label: "Use XA connection factory", options: ["false", "true"] }, { key: "useUfo", label: "Use EMS unshared failover", options: ["false", "true"] },
    { key: "sslEnabled", label: "Enable SSL", options: ["false", "true"] }, { key: "sslTrustedCertificates", label: "SSL trusted certificates" },
    { key: "reconnectAttempts", label: "Reconnect attempts" }, { key: "reconnectDelayMs", label: "Reconnect delay (ms)" },
    { key: "heartbeatOutgoingMs", label: "Outgoing heartbeat (ms)" }, { key: "heartbeatIncomingMs", label: "Incoming heartbeat (ms)" },
  ],
  kafka: [
    { key: "mode", label: "Runtime mode", options: ["memory", "external"] }, { key: "bootstrapServers", label: "Bootstrap servers" },
    { key: "clientId", label: "Client ID" }, { key: "groupId", label: "Default consumer group" },
    { key: "securityProtocol", label: "Security protocol", options: ["PLAINTEXT", "SASL_PLAINTEXT", "SASL_SSL", "SSL"] },
    { key: "saslMechanism", label: "SASL mechanism", options: ["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"] },
    { key: "username", label: "Username" }, { key: "password", label: "Password", password: true },
    { key: "sslCaLocation", label: "SSL CA location" }, { key: "sslCertificateLocation", label: "SSL certificate location" },
    { key: "sslKeyLocation", label: "SSL key location" }, { key: "sslKeyPassword", label: "SSL key password", password: true },
    { key: "schemaRegistryUrl", label: "Schema Registry URL" }, { key: "schemaRegistryUsername", label: "Schema Registry username" },
    { key: "schemaRegistryPassword", label: "Schema Registry password", password: true },
    { key: "requestTimeoutMilliseconds", label: "Request timeout (ms)" }, { key: "connectionTimeoutMilliseconds", label: "Connection timeout (ms)" },
  ],
  pubsub: [
    { key: "mode", label: "Runtime mode", options: ["memory", "external"] }, { key: "projectId", label: "GCP project ID" },
    { key: "credentialsFile", label: "Credentials file" }, { key: "endpoint", label: "Service endpoint" },
    { key: "emulatorHost", label: "Emulator host" }, { key: "ackDeadlineSeconds", label: "Ack deadline (seconds)" },
    { key: "connectionTimeoutSeconds", label: "Connection timeout (seconds)" }, { key: "maxInboundMessageBytes", label: "Maximum inbound message bytes" },
    { key: "keepAliveSeconds", label: "Keep-alive time (seconds)" },
  ],
  sap: [
    { key: "mode", label: "Runtime adapter", options: ["mock", "external"] },
    { key: "release", label: "SAP release", options: ["current", "720", "730"] },
    { key: "connectionType", label: "Connection type", options: ["dedicated", "logongroup", "snc", "sncwithlogongroup", "websocket"] },
    { key: "applicationServerHost", label: "Application server host" }, { key: "systemNumber", label: "System number" },
    { key: "client", label: "Client number" }, { key: "language", label: "Language" }, { key: "username", label: "Username" },
    { key: "password", label: "Password", password: true }, { key: "messageServerHost", label: "Message server host" },
    { key: "systemId", label: "System ID" }, { key: "logonGroup", label: "Logon group" }, { key: "sapRouter", label: "SAP Router" },
    { key: "programId", label: "Program ID (inbound)" }, { key: "gatewayHost", label: "Gateway host" },
    { key: "gatewayService", label: "Gateway service" }, { key: "maximumConnections", label: "Maximum connections" },
    { key: "timeoutMilliseconds", label: "Timeout (ms)" },
  ],
  sap_tid: [{ key: "storageFile", label: "Transaction ID storage file" }],
};
function connectionDefaults(type: string) {
  const prefix = type === "sap_tid" ? "connections.sapTid" : `connections.${type}`;
  const values: Record<string, any> = {};
  for (const field of connectionFieldSets[type] || []) {
    values[field.key] = propertyExpression(`${prefix}.${field.key}`);
  }
  if (["ems", "kafka", "pubsub"].includes(type)) values.mode = "memory";
  if (type === "http") Object.assign(values, { connectorMode: "both", scheme: "http", authentication: "None", tlsEnabled: "false", clientAuthentication: "none", tlsVersion: "TLSv1.2", verifyTls: "true" });
  if (type === "sap") Object.assign(values, { mode: "mock", release: "current", connectionType: "dedicated" });
  if (type === "jdbc") values.driver = "postgresql";
  return values;
}
function SharedConnectionDialog({ type, properties, onClose, onCreate }: any) {
  const fields = connectionFieldSets[type] || [];
  const testOutputRef = useRef<HTMLDivElement>(null);
  const idocBrowserRef = useRef<HTMLElement>(null);
  const [draft, setDraft] = useState<any>({ id: `${type}-${Date.now()}`, type, name: `${type === "sap" ? "SAP ECC" : type.toUpperCase()} Connection`, config: connectionDefaults(type) });
  const [status, setStatus] = useState(""), [statusOk, setStatusOk] = useState<boolean | null>(null), [copied, setCopied] = useState(false);
  const [target, setTarget] = useState<string | null>(null), [propertySearch, setPropertySearch] = useState("");
  const [idocs, setIdocs] = useState<any[]>([]), [idocSearch, setIdocSearch] = useState(""), [idocLoading, setIdocLoading] = useState(false), [idocError, setIdocError] = useState("");
  const set = (key: string, value: any) => setDraft((current: any) => ({ ...current, config: { ...current.config, [key]: value } }));
  const connectorPrefix = type === "sap_tid" ? "connections.sapTid." : `connections.${type}.`;
  const visibleProperties = [...(properties as Property[])]
    .filter((item) => item.key.toLowerCase().includes(propertySearch.toLowerCase()))
    .sort((left, right) => Number(right.key.startsWith(connectorPrefix)) - Number(left.key.startsWith(connectorPrefix)) || left.key.localeCompare(right.key));
  const runtimeResource = () => {
    const values = Object.fromEntries((properties as Property[]).map((item) => [item.key, item.value]));
    const resolved = Object.fromEntries(Object.entries(draft.config).map(([key, value]) => {
      const match = typeof value === "string" ? value.match(/^\$\{properties\.([^}]+)\}$/) : null;
      return [key, match ? values[match[1]] : value];
    }));
    return { ...draft, config: resolved };
  };
  const fetchIdocs = async () => {
    setIdocLoading(true); setIdocError("");
    requestAnimationFrame(() => idocBrowserRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    try {
      const response = await fetch("/api/sap/idocs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ resource: runtimeResource(), search: idocSearch, limit: 250 }) });
      const output = await response.json();
      if (!response.ok) throw new Error(output.detail || "IDoc discovery failed");
      setIdocs(output.idocs || []);
    } catch (error: any) { setIdocError(error?.message || "IDoc discovery failed"); }
    finally { setIdocLoading(false); }
  };
  const selectIdoc = async (item: any) => {
    setIdocLoading(true); setIdocError("");
    try {
      const configuredRelease = draft.config.release;
      const metadataRelease = configuredRelease && configuredRelease !== "current" ? configuredRelease : item.release;
      const response = await fetch("/api/sap/idocs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ resource: runtimeResource(), idocType: item.idocType, extensionType: item.extensionType, release: metadataRelease }) });
      const output = await response.json();
      if (!response.ok) throw new Error(output.detail || "IDoc metadata download failed");
      const selected = output.idoc;
      setDraft((current: any) => ({ ...current, config: { ...current.config, selectedIdoc: selected, idocCatalog: [...(current.config.idocCatalog || []).filter((entry: any) => entry.idocType !== selected.idocType), selected] } }));
    } catch (error: any) { setIdocError(error?.message || "IDoc metadata download failed"); }
    finally { setIdocLoading(false); }
  };
  const test = async () => {
    setStatus("Testing…"); setStatusOk(null); setCopied(false);
    try {
      const response = await fetch("/api/connections/test", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(runtimeResource()) });
      const output = await response.json();
      setStatus(output.message || output.detail || JSON.stringify(output, null, 2)); setStatusOk(response.ok && output.ok !== false);
    } catch (error: any) { setStatus(error?.message || "Connection test failed"); setStatusOk(false); }
  };
  const copyStatus = () => {
    setCopied(true);
    void navigator.clipboard?.writeText(status).catch(() => {
      const output = document.querySelector<HTMLTextAreaElement>(".connection-test-output textarea"); output?.focus(); output?.select(); document.execCommand("copy");
    });
  };
  useEffect(() => {
    if (!status) return;
    const frame = requestAnimationFrame(() => testOutputRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    return () => cancelAnimationFrame(frame);
  }, [status, statusOk]);
  return <div className="modal-backdrop"><div className="runtime-modal connection-dialog">
    <header><b>Create {type === "sap" ? "SAP ECC" : type.toUpperCase()} shared connection</b><span className="connection-header-actions">{type === "sap" && <button type="button" className="browse-properties retrieve-idocs" onClick={fetchIdocs} disabled={idocLoading}><Download/> {idocLoading ? "Retrieving…" : "Retrieve IDoc types"}</button>}<button aria-label="Close" onClick={onClose}>×</button></span></header>
    <main>
      <label>Name<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })}/></label>
      {target && <section className="connection-property-picker">
        <header><span><b>SELECT PROPERTY</b><small>Map to {fields.find((field: any) => field.key === target)?.label}</small></span><button aria-label="Close property picker" onClick={() => setTarget(null)}>×</button></header>
        <div className="property-picker-search"><Search/><input autoFocus aria-label="Find connection property" value={propertySearch} onChange={(event) => setPropertySearch(event.target.value)} placeholder="Search connector properties…"/></div>
        <div className="property-browser-list">{visibleProperties.map((item) => <button key={item.key} onClick={() => { set(target, propertyExpression(item.key)); setTarget(null); setPropertySearch(""); }}><span><b>{item.key}</b><small>{item.data_type}</small></span><code>{item.data_type === "password" ? "••••••" : String(item.value)}</code></button>)}{!visibleProperties.length && <p>No matching connector properties.</p>}</div>
      </section>}
      {fields.map((field: any) => <label key={field.key}>{field.label}{field.options ? <select value={draft.config[field.key] ?? ""} onChange={(event) => set(field.key, event.target.value)}>{field.options.map((option: string) => <option key={option} value={option}>{option}</option>)}</select> : <span className="property-field-wrap"><input type={field.password && !String(draft.config[field.key] || "").startsWith("${") ? "password" : "text"} value={draft.config[field.key] ?? ""} onChange={(event) => set(field.key, event.target.value)}/><button type="button" title={`Browse properties for ${field.label}`} aria-label={`Browse properties for ${field.label}`} onClick={() => { setTarget(field.key); setPropertySearch(""); }}><Braces/></button></span>}</label>)}
      {type === "sap" && <section ref={idocBrowserRef} className="sap-idoc-browser"><header><span><b>SAP IDOC METADATA</b><small>Target release: {draft.config.release === "720" ? "SAP 7.20" : draft.config.release === "730" ? "SAP 7.30" : "Current / auto-detect"}. Retrieve and store the matching schema in this shared connection.</small></span><button type="button" onClick={fetchIdocs} disabled={idocLoading}><Download/> {idocLoading ? "Retrieving…" : "Retrieve IDoc types"}</button></header><div className="sap-idoc-search"><Search/><input value={idocSearch} onChange={(event) => setIdocSearch(event.target.value)} onKeyDown={(event) => event.key === "Enter" && fetchIdocs()} placeholder="Filter IDoc types, for example ORDERS…"/></div>{idocError && <p className="sap-idoc-error">{idocError}</p>}<div className="sap-idoc-list">{idocs.map((item) => { const selected = draft.config.selectedIdoc?.idocType === item.idocType; return <button type="button" className={selected ? "selected" : ""} key={`${item.idocType}-${item.release}`} onClick={() => selectIdoc(item)}><span><b>{item.idocType}</b><small>{item.description || "SAP IDoc"}</small></span><code>{item.extensionType || "basic"} · {item.release || "current"}</code>{selected && <i>Schema fetched</i>}</button>; })}{!idocs.length && <p>Test the SAP connection, then retrieve the available IDoc types.</p>}</div>{draft.config.selectedIdoc && <footer><CheckCircle2/><span><b>{draft.config.selectedIdoc.idocType}</b><small>{draft.config.selectedIdoc.segments?.length || 0} metadata rows · SAP release {draft.config.selectedIdoc.release || draft.config.release} · schema stored with shared connection</small></span></footer>}</section>}
      {status && <div ref={testOutputRef} role="status" aria-live="polite" className={`connection-test-output ${statusOk === true ? "success" : statusOk === false ? "failure" : "pending"}`}><header><span><b>{statusOk === true ? "CONNECTION SUCCEEDED" : statusOk === false ? "CONNECTION FAILED" : "CONNECTION TEST"}</b><small>Selectable test response</small></span><button onClick={copyStatus}><ClipboardCopy/> {copied ? "Copied" : "Copy output"}</button></header><textarea aria-label="Connection test output" readOnly value={status} onFocus={(event) => event.currentTarget.select()}/></div>}
    </main>
    <footer><button onClick={test}>Test Connection</button><button onClick={onClose}>Cancel</button><button className="primary" onClick={() => onCreate(draft)}>Create</button></footer>
  </div></div>;
}
function ConnectionDialog({ type, onClose, onCreate }: any) {
  const [draft, setDraft] = useState<any>({
      id: `${type}-${Date.now()}`,
      type,
      name: `${type.toUpperCase()} Connection`,
      config: {
        mode: ["ems", "kafka", "pubsub"].includes(type)
          ? "memory"
          : type === "sap"
            ? "mock"
            : "external",
        driver: "sqlite",
        url: type === "jdbc" ? "${properties.connections.jdbc.url}" : "integration.db",
        baseUrl: type === "http" ? "${properties.connections.http.baseUrl}" : undefined,
        host:
          type === "ftp"
            ? "${properties.connections.ftp.host}"
            : type === "sftp"
              ? "${properties.connections.sftp.host}"
              : type === "ems"
                ? "${properties.connections.ems.host}"
                : undefined,
        port:
          type === "sftp"
            ? "${properties.connections.sftp.port}"
            : type === "ftp"
              ? "${properties.connections.ftp.port}"
              : type === "ems"
                ? "${properties.connections.ems.port}"
                : undefined,
        bootstrapServers:
          type === "kafka" ? "${properties.connections.kafka.bootstrapServers}" : undefined,
        projectId:
          type === "pubsub" ? "${properties.connections.pubsub.projectId}" : undefined,
        applicationServerHost:
          type === "sap" ? "${properties.connections.sap.applicationServerHost}" : undefined,
        systemNumber:
          type === "sap" ? "${properties.connections.sap.systemNumber}" : undefined,
        client: type === "sap" ? "${properties.connections.sap.client}" : undefined,
        language: "EN",
        connectionType: "dedicated",
        maxConnections: 8,
      },
    }),
    [status, setStatus] = useState(""),
    [statusOk, setStatusOk] = useState<boolean | null>(null),
    [copied, setCopied] = useState(false);
  const set = (k: string, v: any) =>
      setDraft((d: any) => ({ ...d, config: { ...d.config, [k]: v } })),
    test = async () => {
      setStatus("Testing…");
      setStatusOk(null);
      setCopied(false);
      try {
        const r = await fetch("/api/connections/test", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(draft),
        });
        const out = await r.json();
        setStatus(out.message || out.detail || JSON.stringify(out, null, 2));
        setStatusOk(r.ok && out.ok !== false);
      } catch (error: any) {
        setStatus(error?.message || "Connection test failed");
        setStatusOk(false);
      }
    },
    copyStatus = () => {
      const output = document.querySelector<HTMLTextAreaElement>(
        ".connection-test-output textarea",
      );
      const fallbackCopy = () => {
        output?.focus();
        output?.select();
        document.execCommand("copy");
      };
      setCopied(true);
      if (navigator.clipboard?.writeText) {
        void navigator.clipboard.writeText(status).catch(fallbackCopy);
      } else {
        fallbackCopy();
      }
    };
  return (
    <div className="modal-backdrop">
      <div className="runtime-modal connection-dialog">
        <header>
          <b>
            Create {type === "sap" ? "SAP ECC" : type.toUpperCase()} shared
            connection
          </b>
          <button onClick={onClose}>×</button>
        </header>
        <main>
          <label>
            Name
            <input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          {["ems", "kafka", "pubsub"].includes(type) && (
            <label>
              Runtime mode
              <select
                value={draft.config.mode}
                onChange={(e) => set("mode", e.target.value)}
              >
                <option value="memory">Local in-memory test broker</option>
                <option value="external">External system</option>
              </select>
            </label>
          )}
          {type === "jdbc" && (
            <>
              <label>
                Database
                <select
                  value={draft.config.driver}
                  onChange={(e) => set("driver", e.target.value)}
                >
                  {[
                    "sqlite",
                    "postgresql",
                    "mysql",
                    "mariadb",
                    "sqlserver",
                    "oracle",
                    "db2",
                    "snowflake",
                  ].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <label>
                Connection URL
                <input
                  value={draft.config.url}
                  onChange={(e) => set("url", e.target.value)}
                />
              </label>
            </>
          )}
          {type === "http" && (
            <label>
              Base URL
              <input
                value={draft.config.baseUrl || ""}
                onChange={(e) => set("baseUrl", e.target.value)}
                placeholder="https://api.example.com"
              />
            </label>
          )}
          {["ftp", "sftp"].includes(type) && (
            <>
              <label>
                Host
                <input
                  value={draft.config.host || ""}
                  onChange={(e) => set("host", e.target.value)}
                  placeholder="files.example.com"
                />
              </label>
              <label>
                Port
                <input
                  value={draft.config.port || ""}
                  onChange={(e) => set("port", e.target.value)}
                />
              </label>
              <label>
                Working directory
                <input
                  onChange={(e) => set("workingDirectory", e.target.value)}
                />
              </label>
              {type === "sftp" && (
                <label>
                  Private key file
                  <input
                    onChange={(e) => set("privateKeyFile", e.target.value)}
                  />
                </label>
              )}
            </>
          )}
          {type === "ems" && (
            <>
              <label>
                EMS host
                <input value={draft.config.host || ""} onChange={(e) => set("host", e.target.value)} />
              </label>
              <label>
                Port
                <input
                  value={draft.config.port || ""}
                  onChange={(e) => set("port", e.target.value)}
                />
              </label>
              <label>
                Factory
                <select
                  onChange={(e) => set("connectionFactoryType", e.target.value)}
                >
                  <option>QueueConnectionFactory</option>
                  <option>TopicConnectionFactory</option>
                  <option>ConnectionFactory</option>
                </select>
              </label>
            </>
          )}
          {type === "kafka" && (
            <>
              <label>
                Bootstrap servers
                <input
                  value={draft.config.bootstrapServers || ""}
                  onChange={(e) => set("bootstrapServers", e.target.value)}
                  placeholder="localhost:9092"
                />
              </label>
              <label>
                Security protocol
                <select
                  onChange={(e) => set("securityProtocol", e.target.value)}
                >
                  <option>PLAINTEXT</option>
                  <option>SASL_SSL</option>
                  <option>SSL</option>
                </select>
              </label>
            </>
          )}
          {type === "pubsub" && (
            <>
              <label>
                GCP project ID
                <input value={draft.config.projectId || ""} onChange={(e) => set("projectId", e.target.value)} />
              </label>
              <label>
                Credentials file
                <input
                  onChange={(e) => set("credentialsFile", e.target.value)}
                />
              </label>
              <label>
                Emulator host
                <input
                  onChange={(e) => set("emulatorHost", e.target.value)}
                  placeholder="localhost:8085"
                />
              </label>
            </>
          )}
          {type === "sap" && (
            <>
              <label>
                Runtime adapter
                <select
                  value={draft.config.mode}
                  onChange={(e) => set("mode", e.target.value)}
                >
                  <option value="mock">Local SAP design-time mock</option>
                  <option value="external">SAP NetWeaver RFC SDK</option>
                </select>
              </label>
              <label>
                Connection type
                <select
                  value={draft.config.connectionType}
                  onChange={(e) => set("connectionType", e.target.value)}
                >
                  <option value="dedicated">Application server</option>
                  <option value="logongroup">
                    Message server / logon group
                  </option>
                  <option value="snc">SNC secured</option>
                  <option value="sncwithlogongroup">SNC + logon group</option>
                  <option value="websocket">WebSocket</option>
                </select>
              </label>
              <label>
                Application server host
                <input
                  value={draft.config.applicationServerHost || ""}
                  onChange={(e) => set("applicationServerHost", e.target.value)}
                  placeholder="sap-ecc.example.com"
                />
              </label>
              <label>
                System number
                <input
                  value={draft.config.systemNumber || ""}
                  onChange={(e) => set("systemNumber", e.target.value)}
                  placeholder="00"
                />
              </label>
              <label>
                Client
                <input
                  value={draft.config.client || ""}
                  onChange={(e) => set("client", e.target.value)}
                  placeholder="100"
                />
              </label>
              <label>
                Language
                <input
                  value={draft.config.language}
                  onChange={(e) => set("language", e.target.value)}
                />
              </label>
              <label>
                Message server host
                <input
                  onChange={(e) => set("messageServerHost", e.target.value)}
                />
              </label>
              <label>
                System ID
                <input onChange={(e) => set("systemId", e.target.value)} />
              </label>
              <label>
                Logon group
                <input
                  onChange={(e) => set("logonGroup", e.target.value)}
                  placeholder="PUBLIC"
                />
              </label>
              <label>
                SAP Router
                <input onChange={(e) => set("sapRouter", e.target.value)} />
              </label>
              <label>
                Program ID (inbound)
                <input onChange={(e) => set("programId", e.target.value)} />
              </label>
              <label>
                Gateway host
                <input onChange={(e) => set("gatewayHost", e.target.value)} />
              </label>
              <label>
                Gateway service
                <input
                  onChange={(e) => set("gatewayService", e.target.value)}
                />
              </label>
              <label>
                Maximum connections
                <input
                  type="number"
                  value={draft.config.maxConnections}
                  onChange={(e) =>
                    set("maxConnections", Number(e.target.value))
                  }
                />
              </label>
              <label>
                <input
                  type="checkbox"
                  onChange={(e) => set("rfcTrace", e.target.checked)}
                />{" "}
                Enable RFC trace
              </label>
            </>
          )}
          <label>
            Username
            <input onChange={(e) => set("username", e.target.value)} />
          </label>
          <label>
            Password
            <input
              type="password"
              onChange={(e) => set("password", e.target.value)}
            />
          </label>
          {status && (
            <div
              className={`connection-test-output ${statusOk === true ? "success" : statusOk === false ? "failure" : "pending"}`}
            >
              <header>
                <b>
                  {statusOk === true
                    ? "CONNECTION SUCCEEDED"
                    : statusOk === false
                      ? "CONNECTION FAILED"
                      : "CONNECTION TEST"}
                </b>
                <button onClick={copyStatus} type="button">
                  <ClipboardCopy /> {copied ? "Copied" : "Copy output"}
                </button>
              </header>
              <textarea
                aria-label="Connection test output"
                readOnly
                value={status}
                onFocus={(event) => event.currentTarget.select()}
              />
            </div>
          )}
        </main>
        <footer>
          <button onClick={test}>Test Connection</button>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={() => onCreate(draft)}>
            Create
          </button>
        </footer>
      </div>
    </div>
  );
}
function ActivityConfig({ node, resources, tasks, update }: any) {
  const c = node.config,
    set = (k: string, v: any) => update({ config: { ...c, [k]: v } }),
    field = (label: string, key: string) => (
      <label>
        {label}
        <input
          value={c[key] ?? ""}
          onChange={(e) => set(key, e.target.value)}
        />
      </label>
    ),
    rt: any = {
      jdbc: "jdbc",
      ems: "ems",
      kafka: "kafka",
      pubsub: "pubsub",
      http: "http",
    };
  return (
    <div className="config-body">
      <label>
        Display name
        <input
          value={node.name}
          onChange={(e) => update({ name: e.target.value })}
        />
      </label>
      <label>
        Activity type
        <input disabled value={`${node.type} / ${c.operation || ""}`} />
      </label>
      {rt[node.type] && (
        <label>
          Shared connection
          <select
            value={c.resourceId || ""}
            onChange={(e) => set("resourceId", e.target.value)}
          >
            <option value="">Select…</option>
            {resources
              .filter((r: Resource) => r.type === rt[node.type])
              .map((r: Resource) => (
                <option value={r.id} key={r.id}>
                  {r.name}
                </option>
              ))}
          </select>
        </label>
      )}
      {node.type === "call_task" && (
        <>
          <label>
            Sub Task
            <select
              value={c.taskId || ""}
              onChange={(e) => set("taskId", e.target.value)}
            >
              <option value="">Select…</option>
              {tasks
                .filter((t: Task) => t.kind === "subtask")
                .map((t: Task) => (
                  <option value={t.id} key={t.id}>
                    {t.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={!!c.spawn}
              onChange={(e) => set("spawn", e.target.checked)}
            />{" "}
            Spawn without waiting
          </label>
          <Mappings
            value={c.inputMappings || {}}
            change={(v: any) => set("inputMappings", v)}
          />
        </>
      )}
      {node.type === "timer" && (
        <>
          {field("Start time", "startTime")}
          {field("Interval", "interval")}
          <label>
            Unit
            <select
              value={c.unit || "minutes"}
              onChange={(e) => set("unit", e.target.value)}
            >
              <option>seconds</option>
              <option>minutes</option>
              <option>hours</option>
              <option>days</option>
            </select>
          </label>
        </>
      )}
      {["ems", "kafka", "pubsub"].includes(node.type) && (
        <>
          {field(
            c.operation?.includes("queue")
              ? "Queue"
              : c.operation === "subscribe"
                ? "Subscription"
                : "Topic",
            c.operation?.includes("queue")
              ? "queue"
              : c.operation === "subscribe"
                ? "subscription"
                : "topic",
          )}
          {field("Message / expression", "message")}
          {[
            "receive",
            "get",
            "subscribe",
            "queue_receiver",
            "topic_subscriber",
          ].includes(c.operation) && field("Maximum messages", "maxMessages")}
        </>
      )}
      {node.type === "jdbc" && (
        <>
          <label className="wide">
            SQL
            <textarea
              value={c.sql || ""}
              onChange={(e) => set("sql", e.target.value)}
            />
          </label>
          <Mappings
            value={c.parameters || {}}
            change={(v: any) => set("parameters", v)}
          />
        </>
      )}
      {["file", "http", "http_listener", "rest", "soap"].includes(node.type) &&
        field(
          node.type === "file"
            ? "Path"
            : node.type.includes("listener")
              ? "Listener path"
              : "URL",
          node.type === "file"
            ? "path"
            : node.type.includes("listener")
              ? "path"
              : "url",
        )}
      <div className="resource-note wide">
        Every field accepts <code>{"${properties.key}"}</code>,{" "}
        <code>{"${input.id}"}</code>, and <code>{"${last.value}"}</code>.
      </div>
    </div>
  );
}
function Mappings({ value, change }: any) {
  return (
    <div className="mapping wide">
      <b>Dynamic field mappings</b>
      {Object.entries(value).map(([k, v]: any) => (
        <div className="mapping-row" key={k}>
          <input value={k} readOnly />
          <span>←</span>
          <input
            value={v}
            onChange={(e) => change({ ...value, [k]: e.target.value })}
          />
        </div>
      ))}
      <button
        onClick={() =>
          change({ ...value, [`field${Object.keys(value).length + 1}`]: "" })
        }
      >
        <Plus /> Add mapping
      </button>
    </div>
  );
}
function EdgeConfig({ edge, properties, update, onDelete }: any) {
  const [sample, setSample] = useState('{\n  "last": { "status": "OK", "amount": 100 },\n  "input": {},\n  "properties": {}\n}'), [result, setResult] = useState<any>(null), [testing, setTesting] = useState(false);
  const functions = ["exists()", "empty()", "contains(, )", "startsWith(, )", "endsWith(, )", "matches(, )", "not()", " and ", " or "];
  const paths = ["${last.status}", "${last.amount}", "${input}", ...properties.slice(0, 8).map((property: Property) => `\${properties.${property.key}}`)];
  const evaluate = async () => {
    setTesting(true);
    try {
      const context = JSON.parse(sample), response = await fetch("/api/conditions/evaluate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ expression: edge.condition || "", context }) });
      const output = await response.json(); setResult(response.ok ? output.result : output.detail || "Evaluation failed");
    } catch (error: any) { setResult(error.message); }
    setTesting(false);
  };
  return <div className="transition-editor">
    <header><label>Transition type<select value={edge.type || "success"} onChange={(event) => update({ type: event.target.value })}><option value="success">Success</option><option value="success_condition">Success with condition</option><option value="success_no_match">Success with no matching condition</option><option value="error">Error</option></select></label><button className="delete-transition" title="Delete selected transition (Delete or Backspace)" onClick={onDelete}><Trash2/> Delete Transition</button></header>
    {edge.type === "success_condition" && <div className="condition-workbench"><section><h4>CONDITION EXPRESSION</h4><textarea aria-label="Transition condition expression" value={edge.condition || ""} onChange={(event) => update({ condition: event.target.value })} placeholder='contains(${last.status}, "READY") and ${last.amount} > 0'/><div className="condition-functions"><b>Functions</b>{functions.map((name) => <button key={name} onClick={() => update({ condition: `${edge.condition || ""}${edge.condition ? " " : ""}${name}` })}>{name}</button>)}</div><div className="condition-paths"><b>Paths</b>{paths.map((path) => <button key={path} onClick={() => update({ condition: `${edge.condition || ""}${edge.condition ? " " : ""}${path}` })}>{path}</button>)}</div></section><section><h4>EVALUATE PATH / FUNCTION</h4><textarea aria-label="Condition sample context" value={sample} onChange={(event) => setSample(event.target.value)} spellCheck={false}/><button className="evaluate-condition" onClick={evaluate} disabled={testing}><CirclePlay/> {testing ? "Evaluating…" : "Evaluate condition"}</button>{result !== null && <output className={result === true ? "true" : result === false ? "false" : "error"}>{typeof result === "boolean" ? `Result: ${result}` : String(result)}</output>}</section></div>}
    {edge.type !== "success_condition" && <p className="transition-help">{edge.type === "success_no_match" ? "Runs when no conditional Success transition from the activity matches." : edge.type === "error" ? "Runs when the source activity raises an unhandled error." : "Runs whenever the source activity completes successfully."}</p>}
  </div>;
}
function ConnectionConfig({ resource, update }: any) {
  return (
    <div className="config-body">
      <label>
        Name
        <input
          value={resource.name}
          onChange={(e) => update({ name: e.target.value })}
        />
      </label>
      <label>
        Type
        <input disabled value={resource.type.toUpperCase()} />
      </label>
      <label className="wide">
        Configuration JSON
        <textarea
          value={JSON.stringify(resource.config, null, 2)}
          onChange={(e) => {
            try {
              update({ config: JSON.parse(e.target.value) });
            } catch {}
          }}
        />
      </label>
    </div>
  );
}
function DebugBar({ state, act }: any) {
  return (
    <div className="debug-bar">
      <Bug />
      <b>{state.status}</b>
      <button onClick={() => act("continue")}>
        <CirclePlay /> Continue
      </button>
      <button onClick={() => act("pause")}>
        <Pause /> Pause
      </button>
      <button onClick={() => act("step_in")}>
        <SkipForward /> Step In
      </button>
      <button onClick={() => act("step_over")}>
        <SkipForward /> Step Over
      </button>
      <button onClick={() => act("step_out")}>
        <SkipBack /> Step Out
      </button>
      <button onClick={() => act("jump_in")}>Jump In</button>
      <button onClick={() => act("jump_out")}>Jump Out</button>
      <button onClick={() => act("stop")}>
        <Square /> Stop
      </button>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
