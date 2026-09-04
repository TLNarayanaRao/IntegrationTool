import React, { Component, ErrorInfo, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlignHorizontalSpaceAround,
  AlignVerticalSpaceAround,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  BookOpen,
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
  LoaderCircle,
  Maximize2,
  Minimize2,
  Monitor,
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
  WandSparkles,
} from "lucide-react";
import SchemaStudio, { SchemaDoc } from "./SchemaStudio";
import ActivityEditor from "./ActivityEditor";
import ActivityPicker from "./ActivityPicker";
import DataNodeIcon from "./DataNodeIcon";
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
import "./home-screen.css";
const Braces = DataNodeIcon;
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
  | "snowflake"
  | "amqp"
  | "excel"
  | "xml"
  | "json"
  | "flat"
  | "mapper"
  | "dataweave"
  | "transform"
  | "ai_transform"
  | "log"
  | "confirm"
  | "catch"
  | "throw"
  | "rethrow"
  | "ems"
  | "jms"
  | "kafka"
  | "pubsub"
  | "sap"
  | "java"
  | "python"
  | "basic"
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
    | "snowflake"
    | "amqp"
    | "ftp"
    | "sftp"
    | "http"
    | "ems"
    | "jms"
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
  custom_functions: Array<{ id: string; name: string; parameters: string[]; expression: string; description?: string }>;
  properties: Record<string, Property[]>;
  active_environment: string;
  tasks: Task[];
  active_task_id: string;
  process?: any;
};

class StudioErrorBoundary extends Component<React.PropsWithChildren, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Integration Fabric Studio render failure", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 32, background: "#08131f", color: "#d9efff", fontFamily: "system-ui, sans-serif" }}>
        <section style={{ maxWidth: 680, width: "100%", padding: 28, border: "1px solid #d35c68", borderRadius: 14, background: "#102333", boxShadow: "0 18px 60px #0008" }}>
          <h1 style={{ marginTop: 0 }}>Studio recovered from a screen error</h1>
          <p>The editor stopped rendering, but the saved project remains in the local runtime. Reload the Studio and use Project → Refresh or Open to continue.</p>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", color: "#ffb7bd" }}>{this.state.error.message}</pre>
          <button type="button" onClick={() => window.location.reload()} style={{ padding: "10px 16px", borderRadius: 8, cursor: "pointer" }}>Reload Studio</button>
        </section>
      </main>
    );
  }
}
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
    (item.type === "jms" && operation === "receive_message") ||
    (item.type === "kafka" && ["receive", "get"].includes(operation)) ||
    (item.type === "pubsub" && operation === "subscribe") ||
    (item.type === "amqp" && operation === "receive") ||
    (item.type === "sap" && ["idoc_listener", "rfc_bapi_listener"].includes(operation));
};
const ai = (asset: string) => (
  <img src={`/activity-icons/${asset.includes(".") ? asset : `${asset}.png`}`} alt="" />
);
const resourceIconSources: Record<string, string> = { http: "/activity-icons/http.png", ftp: "/activity-icons/ftp.png", sftp: "/activity-icons/sftp.png", ems: "/activity-icons/ems.png", jms: "/activity-icons/jms-connection.svg", kafka: "/vendor-logos/apache-kafka.svg", pubsub: "/vendor-logos/gcp-pubsub.png", jdbc: "/activity-icons/JDBC-Query.png", snowflake: "/activity-icons/snowflake.svg", amqp: "/vendor-logos/rabbitmq.svg", sap: "/vendor-logos/sap.svg", sap_tid: "/vendor-logos/sap.svg" };
const ResourceVendorIcon = ({ type }: { type: string }) => resourceIconSources[type] ? <img className={`resource-vendor-icon resource-${type}`} src={resourceIconSources[type]} alt=""/> : <Database/>;
const packs: { name: string; icon: any; items: Def[] }[] = [
  {
    name: "Starters & Tasks",
    icon: Workflow,
    items: [
      {
        type: "start",
        operation: "start",
        label: "Start",
        asset: "start-play",
      },
      {
        type: "timer",
        operation: "schedule",
        label: "Scheduler",
        asset: "scheduler.svg",
      },
      {
        type: "call_task",
        operation: "call",
        label: "Call Sub Task",
        asset: "call-task",
      },
      {
        type: "end",
        operation: "end",
        label: "End",
        asset: "end-stop.svg",
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
    name: "JMS",
    icon: MessageSquare,
    items: [
      ["get_queue_message", "Get JMS Queue Message", "jms-get.svg"],
      ["receive_message", "JMS Receive Message", "jms-receive.svg"],
      ["request_reply", "JMS Request Reply", "jms-request-reply.svg"],
      ["send_message", "JMS Send Message", "jms-send.svg"],
      ["reply_message", "Reply to JMS Message", "jms-reply.svg"],
      ["wait_request", "Wait for JMS Request", "jms-wait.svg"],
    ].map(([operation, label, asset]) => ({ type: "jms", operation, label, asset }) as Def),
  },
  {
    name: "Kafka",
    icon: Radio,
    items: [
      ["receive", "Kafka Receive Message"],
      ["send", "Kafka Send Message"],
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
    name: "Snowflake",
    icon: Database,
    items: [
      ["insert", "Snowflake Insert", "snowflake.svg"],
      ["query", "Snowflake Query", "snowflake.svg"],
      ["update", "Snowflake Update", "snowflake.svg"],
      ["delete", "Snowflake Delete", "snowflake.svg"],
      ["bulk_load", "Snowflake Bulk Load", "snowflake.svg"],
    ].map(([operation, label, asset]) => ({ type: "snowflake", operation, label, asset }) as Def),
  },
  {
    name: "AMQP",
    icon: Radio,
    items: [
      ["receive", "AMQP Receive Message", "amqp-receive.svg"],
      ["get", "AMQP Get Message", "amqp-get.svg"],
      ["send", "AMQP Send Message", "amqp-send.svg"],
      ["dead_letter", "AMQP Dead Letter Message", "amqp-dead-letter.svg"],
    ].map(([operation, label, asset]) => ({ type: "amqp", operation, label, asset }) as Def),
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
      { type: "excel", operation: "read", label: "Read Excel Workbook", asset: "excel-read.svg" },
    ],
  },
  {
    name: "General",
    icon: Activity,
    items: [
      { type: "mapper", operation: "map", label: "Mapper", asset: "mapper.svg" },
      { type: "dataweave", operation: "transform", label: "Transform", asset: "dataweave-transform.svg" },
      { type: "log", operation: "write", label: "Log", asset: "log" },
      { type: "catch", operation: "catch", label: "Catch Exception", asset: "catch-exception.svg" },
      { type: "throw", operation: "throw", label: "Throw Exception", asset: "throw-exception.svg" },
      { type: "rethrow", operation: "rethrow", label: "Rethrow Exception", asset: "rethrow-exception.svg" },
      { type: "confirm", operation: "acknowledge", label: "Confirm Message", asset: "general-confirm.svg" },
      {
        type: "java",
        operation: "invoke",
        label: "Java Activity",
        asset: "runtime",
      },
      { type: "python", operation: "invoke", label: "Python Invoke", asset: "runtime" },
      { type: "basic", operation: "external_command", label: "External Command", asset: "external-command.svg" },
      { type: "basic", operation: "assign", label: "Assign", asset: "general-assign.svg" },
      { type: "basic", operation: "checkpoint", label: "Checkpoint", asset: "general-checkpoint.svg" },
      { type: "basic", operation: "sleep", label: "Sleep", asset: "general-sleep.svg" },
      { type: "basic", operation: "get_shared_variable", label: "Get Shared Variable", asset: "general-shared-get.svg" },
      { type: "basic", operation: "set_shared_variable", label: "Set Shared Variable", asset: "general-shared-set.svg" },
    ],
  },
];
const defaultProperties: Property[] = [
  { key: "runtime.logDirectory", value: "", data_type: "string" },
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
  { key: "connections.jdbc.connectionMode", value: "python", data_type: "string" },
  { key: "connections.jdbc.driverDirectory", value: "", data_type: "string" },
  { key: "connections.jdbc.driverClass", value: "", data_type: "string" },
  { key: "connections.jdbc.odbcDriver", value: "", data_type: "string" },
  { key: "connections.jdbc.authentication", value: "SQL Server Authentication", data_type: "string" },
  { key: "connections.jdbc.encrypt", value: true, data_type: "boolean" },
  { key: "connections.jdbc.trustServerCertificate", value: false, data_type: "boolean" },
  { key: "connections.jdbc.serverHostname", value: "", data_type: "string" },
  { key: "connections.jdbc.httpPath", value: "", data_type: "string" },
  { key: "connections.jdbc.accessToken", value: "", data_type: "password" },
  { key: "connections.jdbc.clientId", value: "", data_type: "string" },
  { key: "connections.jdbc.clientSecret", value: "", data_type: "password" },
  { key: "connections.jdbc.catalog", value: "", data_type: "string" },
  { key: "connections.jdbc.useCloudFetch", value: true, data_type: "boolean" },
  { key: "connections.jdbc.serviceName", value: "", data_type: "string" },
  { key: "connections.jdbc.sid", value: "", data_type: "string" },
  { key: "connections.jdbc.sslCaFile", value: "", data_type: "string" },
  { key: "connections.jdbc.timeoutSeconds", value: 30, data_type: "integer" },
  { key: "connections.jdbc.minimumPoolSize", value: 1, data_type: "integer" },
  { key: "connections.jdbc.maximumPoolSize", value: 10, data_type: "integer" },
  { key: "connections.snowflake.mode", value: "external", data_type: "string" },
  { key: "connections.snowflake.authenticationType", value: "Username/Password", data_type: "string" },
  { key: "connections.snowflake.provider", value: "Snowflake", data_type: "string" },
  { key: "connections.snowflake.account", value: "", data_type: "string" },
  { key: "connections.snowflake.username", value: "", data_type: "string" },
  { key: "connections.snowflake.password", value: "", data_type: "password" },
  { key: "connections.snowflake.warehouse", value: "", data_type: "string" },
  { key: "connections.snowflake.database", value: "", data_type: "string" },
  { key: "connections.snowflake.schema", value: "PUBLIC", data_type: "string" },
  { key: "connections.snowflake.role", value: "", data_type: "string" },
  { key: "connections.snowflake.loginTimeoutSeconds", value: 60, data_type: "integer" },
  { key: "connections.snowflake.minimumConnections", value: 2, data_type: "integer" },
  { key: "connections.snowflake.maximumConnections", value: 8, data_type: "integer" },
  { key: "connections.snowflake.maximumConnectionWaitSeconds", value: 300, data_type: "integer" },
  { key: "connections.snowflake.serviceThreads", value: 8, data_type: "integer" },
  { key: "connections.amqp.brokerType", value: "RabbitMQ", data_type: "string" },
  { key: "connections.amqp.amqpVersion", value: "AMQP-0-9-1", data_type: "string" },
  { key: "connections.amqp.hostPort", value: "localhost:5672", data_type: "string" },
  { key: "connections.amqp.virtualHost", value: "/", data_type: "string" },
  { key: "connections.amqp.username", value: "guest", data_type: "string" },
  { key: "connections.amqp.password", value: "guest", data_type: "password" },
  { key: "connections.amqp.clientId", value: "", data_type: "string" },
  { key: "connections.amqp.authenticationType", value: "SAS", data_type: "string" },
  { key: "connections.amqp.connectionString", value: "", data_type: "password" },
  { key: "connections.amqp.tenantId", value: "", data_type: "string" },
  { key: "connections.amqp.azureClientId", value: "", data_type: "string" },
  { key: "connections.amqp.clientSecret", value: "", data_type: "password" },
  { key: "connections.amqp.sharedAccessKeyName", value: "", data_type: "string" },
  { key: "connections.amqp.sharedAccessKey", value: "", data_type: "password" },
  { key: "connections.amqp.entityType", value: "Queue", data_type: "string" },
  { key: "connections.amqp.entityName", value: "", data_type: "string" },
  { key: "connections.amqp.entitySubscriberName", value: "", data_type: "string" },
  { key: "connections.amqp.connectionTimeoutMsec", value: 30000, data_type: "integer" },
  { key: "connections.amqp.sessionCount", value: 1, data_type: "integer" },
  { key: "connections.amqp.idleTimeoutMsec", value: 0, data_type: "integer" },
  { key: "connections.amqp.connectionRecovery", value: true, data_type: "boolean" },
  { key: "connections.amqp.retryIntervalMsec", value: 3000, data_type: "integer" },
  { key: "connections.amqp.retryAttempts", value: 20, data_type: "integer" },
  { key: "connections.amqp.networkRecoveryIntervalMsec", value: 5000, data_type: "integer" },
  { key: "connections.amqp.sslEnabled", value: false, data_type: "boolean" },
  { key: "connections.amqp.caFile", value: "", data_type: "string" },
  { key: "connections.amqp.clientCertificateFile", value: "", data_type: "string" },
  { key: "connections.amqp.clientKeyFile", value: "", data_type: "string" },
  { key: "connections.amqp.clientKeyPassword", value: "", data_type: "password" },
  { key: "connections.ems.host", value: "localhost", data_type: "string" },
  { key: "connections.ems.port", value: 7222, data_type: "integer" },
  { key: "connections.ems.serverUrl", value: "tcp://localhost:7222", data_type: "string" },
  { key: "connections.ems.driverDirectory", value: "", data_type: "string" },
  { key: "connections.ems.connectionFactoryClass", value: "com.tibco.tibjms.TibjmsConnectionFactory", data_type: "string" },
  { key: "connections.ems.connectionTimeoutSeconds", value: 30, data_type: "integer" },
  { key: "connections.ems.destination", value: "orders", data_type: "string" },
  { key: "connections.ems.sessionCount", value: 1, data_type: "integer" },
  { key: "connections.ems.flowLimit", value: 0, data_type: "integer" },
  { key: "connections.ems.receiveTimeoutMs", value: 30000, data_type: "integer" },
  { key: "connections.ems.username", value: "", data_type: "string" },
  { key: "connections.ems.password", value: "", data_type: "password" },
  { key: "connections.ems.clientId", value: "", data_type: "string" },
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
  { key: "connections.jms.provider", value: "Generic JMS 2.0", data_type: "string" },
  { key: "connections.jms.serverUrl", value: "tcp://localhost:61613", data_type: "string" },
  { key: "connections.jms.driverDirectory", value: "", data_type: "string" },
  { key: "connections.jms.connectionFactoryClass", value: "", data_type: "string" },
  { key: "connections.jms.connectionTimeoutSeconds", value: 30, data_type: "integer" },
  { key: "connections.jms.host", value: "localhost", data_type: "string" },
  { key: "connections.jms.port", value: 61613, data_type: "integer" },
  { key: "connections.jms.username", value: "", data_type: "string" },
  { key: "connections.jms.password", value: "", data_type: "password" },
  { key: "connections.jms.clientId", value: "", data_type: "string" },
  { key: "connections.jms.connectionFactoryType", value: "Direct", data_type: "string" },
  { key: "connections.jms.connectionFactory", value: "ConnectionFactory", data_type: "string" },
  { key: "connections.jms.jndiContextFactory", value: "", data_type: "string" },
  { key: "connections.jms.jndiProviderUrl", value: "", data_type: "string" },
  { key: "connections.jms.jndiUsername", value: "", data_type: "string" },
  { key: "connections.jms.jndiPassword", value: "", data_type: "password" },
  { key: "connections.jms.sslEnabled", value: false, data_type: "boolean" },
  { key: "connections.jms.sslTrustedCertificates", value: "", data_type: "string" },
  { key: "connections.jms.reconnectAttempts", value: 3, data_type: "integer" },
  { key: "connections.jms.reconnectDelayMs", value: 5000, data_type: "integer" },
  { key: "connections.kafka.bootstrapServers", value: "localhost:9092", data_type: "string" },
  { key: "connections.kafka.clientId", value: "", data_type: "string" },
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
  { key: "connections.kafka.reconnectBackoffMilliseconds", value: 50, data_type: "integer" },
  { key: "connections.kafka.retryBackoffMilliseconds", value: 100, data_type: "integer" },
  { key: "connections.kafka.authenticationType", value: "None", data_type: "string" },
  { key: "connections.kafka.useTicketCache", value: false, data_type: "boolean" },
  { key: "connections.kafka.keytabFile", value: "", data_type: "string" },
  { key: "connections.kafka.principalName", value: "", data_type: "string" },
  { key: "connections.kafka.jaasConfigFile", value: "", data_type: "string" },
  { key: "connections.kafka.loginCallbackHandler", value: "", data_type: "string" },
  { key: "connections.kafka.schemaRegistryVendor", value: "Confluent", data_type: "string" },
  { key: "connections.kafka.clientProperties", value: "{}", data_type: "json" },
  { key: "connections.pubsub.projectId", value: "my-gcp-project", data_type: "string" },
  { key: "connections.pubsub.authenticationType", value: "Service Account JSON", data_type: "string" },
  { key: "connections.pubsub.serviceAccountJson", value: "", data_type: "password" },
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
const supportsOutboundRetry = (type = "", operation = "") =>
  ["http", "jdbc", "snowflake", "amqp", "ftp", "sftp"].includes(type) ||
  (["ems", "jms"].includes(type) && ["send", "publish", "request_reply", "reply", "send_message", "reply_message"].includes(operation)) ||
  (type === "kafka" && ["send", "publish", "get"].includes(operation)) ||
  (type === "pubsub" && operation === "publish") ||
  (type === "rest" && operation === "invoke") ||
  (type === "soap" && operation === "request_reply") ||
  (type === "sap" && ["idoc_acknowledgment", "idoc_confirmation", "post_idoc", "invoke_rfc_bapi", "reply_rfc_bapi", "read_table"].includes(operation));
const advancedDefaults = (type = "", operation = "") => ({
  logPayload: "${properties.advanced.logPayload}",
  ...(supportsOutboundRetry(type, operation) ? {
    retryEnabled: "${properties.advanced.retryEnabled}",
    retryCount: "${properties.advanced.retryCount}",
    retryIntervalSeconds: "${properties.advanced.retryIntervalSeconds}",
  } : {}),
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
const ensureTaskEnd = (task: Task): Task => {
  if (task.activities.some((activity) => activity.type === "end")) return task;
  const rightmost = task.activities.reduce<Node | undefined>(
    (current, activity) => !current || activity.position.x > current.position.x ? activity : current,
    undefined,
  );
  const endId = `${task.id}-end`;
  const end: Node = {
    id: endId,
    type: "end",
    name: "End",
    position: { x: Math.max(350, (rightmost?.position.x || 70) + 220), y: rightmost?.position.y || 150 },
    config: { operation: "end", advanced: advancedDefaults() },
  };
  const sources = new Set(task.transitions.map((transition) => transition.source));
  const terminals = task.activities.filter((activity) => !sources.has(activity.id) && !["throw", "rethrow"].includes(activity.type));
  return {
    ...task,
    activities: [...task.activities, end],
    transitions: [
      ...task.transitions,
      ...terminals.map((activity, index) => ({
        id: `${task.id}-end-edge-${Date.now()}-${index}`,
        source: activity.id,
        target: endId,
        type: "success" as const,
      })),
    ],
  };
};
const xmlEscape = (value: unknown, attribute = false) => {
  const escaped = String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  return attribute ? escaped.replaceAll('"', "&quot;") : escaped;
};
const legacyXmlOutput = (output: any) => {
  if (!output || typeof output !== "object" || !output.root || !("value" in output)) return "";
  const localName = (name: string) => name.includes("}") ? name.slice(name.lastIndexOf("}") + 1) : name;
  const render = (name: string, value: any, depth = 0): string => {
    const indent = "  ".repeat(depth), tag = localName(name);
    if (Array.isArray(value)) return value.map((item) => render(tag, item, depth)).join("\n");
    if (value === null || value === undefined) return `${indent}<${tag}/>`;
    if (typeof value !== "object") return `${indent}<${tag}>${xmlEscape(value)}</${tag}>`;
    const attributes = Object.entries(value).filter(([key]) => key.startsWith("@")).map(([key, item]) => ` ${localName(key.slice(1))}="${xmlEscape(item, true)}"`).join("");
    const text = value["#text"] === undefined ? "" : xmlEscape(value["#text"]);
    const children = Object.entries(value).filter(([key]) => !key.startsWith("@") && key !== "#text").flatMap(([key, item]) => Array.isArray(item) ? item.map((entry) => render(key, entry, depth + 1)) : [render(key, item, depth + 1)]);
    if (!children.length) return text ? `${indent}<${tag}${attributes}>${text}</${tag}>` : `${indent}<${tag}${attributes}/>`;
    return `${indent}<${tag}${attributes}>${text}${text ? "" : "\n"}${children.join("\n")}\n${indent}</${tag}>`;
  };
  return render(String(output.root), output.value);
};
const formatRuntimeOutput = (record: any) => {
  const output = record?.displayOutput ?? record?.logEvent ?? record?.output;
  if (["xml", "flat"].includes(record?.type) && output?.xml) return String(output.xml);
  if (record?.type === "xml") {
    const xml = legacyXmlOutput(record?.output);
    if (xml) return xml;
  }
  if (typeof output === "string") return output;
  return JSON.stringify(output, null, 2);
};
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
  custom_functions: [],
  properties: envs,
  active_environment: "local",
  tasks: [starter()],
  active_task_id: "main",
};
// Projects can be loaded from older versions or interrupted autosaves. Keep
// malformed optional values out of the render path; one bad activity must not
// bring down the entire editor.
const normalizeProject = (value: any): Project => {
  const source = value && typeof value === "object" ? value : {};
  const tasks = Array.isArray(source.tasks) ? source.tasks : [];
  const normalizedTasks = tasks.map((rawTask: any, taskIndex: number) => {
    const task = rawTask && typeof rawTask === "object" ? rawTask : {};
    const activities = Array.isArray(task.activities) ? task.activities : [];
    return ensureTaskEnd({
      ...task,
      id: String(task.id || `task-${taskIndex + 1}`),
      name: String(task.name || `Task ${taskIndex + 1}`),
      kind: task.kind === "subtask" ? "subtask" : "starter",
      activities: activities.map((rawActivity: any, activityIndex: number) => {
        const activity = rawActivity && typeof rawActivity === "object" ? rawActivity : {};
        const position = activity.position && typeof activity.position === "object" ? activity.position : {};
        return {
          ...activity,
          id: String(activity.id || `activity-${taskIndex + 1}-${activityIndex + 1}`),
          type: String(activity.type || "log"),
          name: String(activity.name || "Activity"),
          position: {
            x: Number.isFinite(Number(position.x)) ? Number(position.x) : 80 + activityIndex * 190,
            y: Number.isFinite(Number(position.y)) ? Number(position.y) : 150,
          },
          config: activity.config && typeof activity.config === "object" ? activity.config : {},
        };
      }),
      transitions: Array.isArray(task.transitions) ? task.transitions : [],
    });
  });
  const fallback = structuredClone(initial);
  const next = { ...fallback, ...source, tasks: normalizedTasks.length ? normalizedTasks : fallback.tasks } as Project;
  next.active_task_id = next.tasks.some((task) => task.id === source.active_task_id) ? source.active_task_id : next.tasks[0].id;
  next.resources = Array.isArray(source.resources) ? source.resources : [];
  next.schemas = Array.isArray(source.schemas) ? source.schemas : [];
  next.custom_functions = Array.isArray(source.custom_functions) ? source.custom_functions : [];
  next.properties = source.properties && typeof source.properties === "object" ? source.properties : structuredClone(envs);
  return next;
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
  const connectionTypes = new Set(["jdbc", "snowflake", "amqp", "ftp", "sftp", "http", "ems", "jms", "kafka", "pubsub", "sap"]);
  task.activities.forEach((item) => {
    const operation = item.config.operation || "";
    if (item.type === "timer") {
      const mode = item.config.scheduleMode || "dateTime";
      if (mode === "dateTime" && !item.config.scheduledDateTime && item.config.runOnceOnLocalStart === false) add("error", "Scheduler", `${item.name} has no execution date and time.`, "Choose a date/time or enable local Run once for testing.", item.id);
      if (mode === "cron" && !String(item.config.cronExpression || "").trim()) add("error", "Scheduler", `${item.name} has no cron expression.`, "Enter a five-field cron expression.", item.id);
    }
    if (connectionTypes.has(item.type) && !item.config.resourceId && !["http_listener", "start", "end"].includes(item.type)) add("error", "Connection", `${item.name} has no shared connection.`, "Select a compatible shared connection in Configuration.", item.id);
    if (item.config.resourceId && !project.resources.some((resource) => resource.id === item.config.resourceId)) add("error", "Connection", `${item.name} references a missing shared connection.`, "Select an existing connection or create one under Resources.", item.id);
    if (item.type === "call_task") {
      const dynamic = String(item.config.dynamicTaskId || "").trim();
      const fallbackValid = project.tasks.some((candidate) => candidate.id === item.config.taskId && candidate.kind === "subtask");
      if (!dynamic && !fallbackValid) add("error", "Task", `${item.name} has no valid Sub Task or dynamic override.`, "Select a fallback Sub Task or enter a dynamic ID/name expression.", item.id);
      if (dynamic.startsWith("${") && !dynamic.endsWith("}")) add("error", "Task", `${item.name} has an incomplete dynamic Sub Task expression.`, "Close the expression with } or enter a literal Sub Task ID/name.", item.id);
    }
    if (["mapper", "transform", "ai_transform"].includes(item.type)) {
      if (!Object.keys(item.config.targetSchema || {}).length && !item.config.targetSchemaId) add("mapping", "Mapper", `${item.name} has no target schema.`, "Select an XSD from Project Schemas or define an inline target schema.", item.id);
      if (!(item.config.mappings || []).length) add("mapping", "Mapper", `${item.name} has no field mappings.`, "Map execution-path fields to the target schema.", item.id);
    }
    if (item.type === "dataweave") {
      const script = String(item.config.script || "");
      if (!script.trim()) add("error", "Transform", `${item.name} has no DataWeave script.`, "Enter or AI-generate an executable transform script.", item.id);
      else if (!script.includes("---")) add("error", "Transform", `${item.name} is missing the DataWeave header/body separator.`, "Add --- before the transform expression.", item.id);
      if (item.config.aiReviewRequired) add("mapping", "Transform", `${item.name} contains an unreviewed AI-generated draft.`, "Review the script and run Map & Test before packaging.", item.id);
    }
    if (item.type === "jdbc" && operation === "call" && !String(item.config.procedure || "").trim()) add("error", "JDBC", `${item.name} has no procedure or function.`, "Select or enter a stored procedure/function.", item.id);
    if (item.type === "jdbc" && operation !== "call" && !String(item.config.sql || "").trim() && !item.config.overrideSqlStatement) add("error", "JDBC", `${item.name} has no SQL statement.`, "Build SQL in the JDBC designer or enable a mapped SQL override.", item.id);
    if (item.type === "snowflake") {
      if (!item.config.resourceId) add("error", "Snowflake", `${item.name} has no Snowflake JDBC connection.`, "Select a Snowflake shared connection.", item.id);
      if (operation === "query" && !String(item.config.statement || item.config.sql || item.config.entity || "").trim()) add("error", "Snowflake", `${item.name} has no SELECT statement or entity.`, "Choose downloaded metadata or enter a Snowflake SELECT statement.", item.id);
      if (["insert", "update", "delete", "bulk_load"].includes(operation) && !String(item.config.entity || item.config.tableName || "").trim()) add("error", "Snowflake", `${item.name} has no target entity.`, "Choose a downloaded table or enter the target table name.", item.id);
      if (item.config.merge && !String(item.config.mergeOnColumns || "").trim()) add("error", "Snowflake", `${item.name} enables Merge without Merge On Columns.`, "Enter one or more comma-separated match columns.", item.id);
      if (operation === "insert" && item.config.merge && Number(item.config.batchSize || 100) !== 1) add("error", "Snowflake", `${item.name} Merge requires Batch Size 1.`, "Set Batch Size to 1 as required by the Snowflake plug-in.", item.id);
    }
    if (item.type === "amqp" && !item.config.resourceId) add("error", "AMQP", `${item.name} has no AMQP connection.`, "Select an AMQP shared connection.", item.id);
    if (item.type === "excel" && !String(item.config.filePath || item.config.inputMappings?.filePath || "").trim()) add("error", "Excel", `${item.name} has no workbook path.`, "Enter a workbook path or map filePath in Input.", item.id);
    if (item.type === "basic" && operation === "external_command" && !String(item.config.command || item.config.inputMappings?.command || "").trim()) add("error", "External Command", `${item.name} has no executable command.`, "Enter a command or map it in Input.", item.id);
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
  const [project, setProject] = useState<Project>(initial),
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
    [editingConnection, setEditingConnection] = useState<Resource | null>(null),
    [schemaEditor, setSchemaEditor] = useState<SchemaDoc | "new" | null>(null),
    [aiBuilderOpen, setAiBuilderOpen] = useState(false),
    [packageOpen, setPackageOpen] = useState(false),
    [debugState, setDebugState] = useState<any>(null),
    [executionOutputs, setExecutionOutputs] = useState<Record<string, any>>({}),
    [endpoints, setEndpoints] = useState<any[]>([]),
    [runtimeState, setRuntimeState] = useState<any>(null),
    [systemLogInfo, setSystemLogInfo] = useState<any>(null),
    [breakpoints, setBreakpoints] = useState<string[]>([]),
    [busy, setBusy] = useState(false),
    [workStatus, setWorkStatus] = useState("Loading project workspace…"),
    [zoom, setZoom] = useState(1),
    [validation, setValidation] = useState<{ title: string; issues: ValidationIssue[] } | null>(null),
    [connectionDraft, setConnectionDraft] = useState<{ source: string; x: number; y: number } | null>(null),
    [selectionBox, setSelectionBox] = useState<{ startX: number; startY: number; x: number; y: number; pointerId: number; baseIds: string[] } | null>(null),
    [quickAddDrag, setQuickAddDrag] = useState<{ source: string; startClientX: number; startClientY: number; x: number; y: number; pointerId: number } | null>(null),
    [edgeRewire, setEdgeRewire] = useState<{ edgeId: string; endpoint: "source" | "target"; fixedId: string; x: number; y: number } | null>(null),
    [openTaskIds, setOpenTaskIds] = useState<string[]>([initial.active_task_id]),
    [taskTabMenu, setTaskTabMenu] = useState<{ taskId: string; x: number; y: number } | null>(null);
  const [monitorMode, setMonitorMode] = useState<"normal" | "expanded" | "fullscreen">("normal");
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
  const autosaveTimer = useRef<number | null>(null);
  const canvas = useRef<HTMLDivElement>(null),
    fileInput = useRef<HTMLInputElement>(null),
    drag = useRef<any>(null),
    activityClipboard = useRef<{ activities: Node[]; transitions: Edge[] } | null>(null),
    explorerClipboard = useRef<{ type: string; value: any } | null>(null),
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
  useEffect(() => {
    const ready = window.setTimeout(() => setWorkStatus(""), 900);
    return () => window.clearTimeout(ready);
  }, []);
  const [closed, setClosed] = useState(true),
    [theme, setTheme] = useState(
      localStorage.getItem("integration-fabric-theme") || "midnight",
    );
  const [activeTab, setActiveTab] = useState<
      "configuration" | "input" | "map_test" | "output" | "advanced" | "errors" | "documentation"
    >("configuration"),
    [propertyEditor, setPropertyEditor] = useState<string | null>(null),
    [renameOpen, setRenameOpen] = useState(false),
    [sampleGalleryOpen, setSampleGalleryOpen] = useState(false),
    [helpDialog, setHelpDialog] = useState<"about" | "shortcuts" | null>(null),
    [treeHeight, setTreeHeight] = useState(305),
    [configHeight, setConfigHeight] = useState(285),
    [explorerWidth, setExplorerWidth] = useState(Number(localStorage.getItem("integration-fabric-explorer-width")) || 245),
    [paletteOpen, setPaletteOpen] = useState(true);
  useEffect(() => {
    if (closed) return;
    if (autosaveTimer.current !== null) window.clearTimeout(autosaveTimer.current);
    const snapshot = structuredClone(project);
    autosaveTimer.current = window.setTimeout(() => {
      autosaveTimer.current = null;
      void fetch(`/api/projects/${snapshot.id}`, {
        method: "PUT",
        headers: { "content-type": "application/json", "x-fabric-autosave": "true" },
        body: JSON.stringify(snapshot),
        keepalive: true,
      }).catch((error) => console.warn("Integration Fabric autosave failed", error));
    }, 700);
    return () => { if (autosaveTimer.current !== null) { window.clearTimeout(autosaveTimer.current); autosaveTimer.current = null; } };
  }, [project, closed]);
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
  useEffect(() => setSystemLogInfo(null), [project.id]);
  useEffect(() => {
    const missingEnd = project.tasks.some((item) => !item.activities.some((activity) => activity.type === "end"));
    if (missingEnd) setProject((current) => ({ ...current, tasks: current.tasks.map(ensureTaskEnd), process: undefined }));
  }, [project.id, project.tasks.map((item) => `${item.id}:${item.activities.some((activity) => activity.type === "end")}`).join("|")]);
  useEffect(() => {
    const available = new Set(project.tasks.map((item) => item.id));
    setOpenTaskIds((current) => {
      const next = current.filter((id) => available.has(id));
      if (project.active_task_id && available.has(project.active_task_id) && !next.includes(project.active_task_id)) next.push(project.active_task_id);
      return next.length ? next : project.tasks[0] ? [project.tasks[0].id] : [];
    });
  }, [project.id, project.active_task_id, project.tasks.map((item) => item.id).join("|")]);
  useEffect(() => {
    if (!taskTabMenu) return;
    const dismiss = () => setTaskTabMenu(null);
    window.addEventListener("pointerdown", dismiss);
    return () => window.removeEventListener("pointerdown", dismiss);
  }, [taskTabMenu]);
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
    if (!endpoints.length) return;
    let cancelled = false;
    const refreshRuntime = async () => {
      try {
        const response = await fetch(debugState?.sessionId ? `/api/debug/${debugState.sessionId}` : `/api/projects/${project.id}/runtime-state`);
        if (!response.ok) {
          // Uvicorn restarts clear in-memory debugger sessions. The browser
          // may still have the old session id and must not poll it forever.
          if (debugState?.sessionId && response.status === 404) {
            setDebugState(null);
            setEndpoints([]);
            setExecutionOutputs({});
            setRuntimeState(null);
            setLogs((current) => [...current, { level: "WARN", message: "The previous debug session expired when the runtime restarted. Start Debug again to create a new session." }]);
          }
          return;
        }
        const state = await response.json();
        if (cancelled) return;
        if (debugState?.sessionId) setDebugState(state);
        else setRuntimeState(state);
        setExecutionOutputs(state.activityOutputs || {});
        setLogs(state.logs || []);
        if (state.endpoints?.length) setEndpoints(state.endpoints);
      } catch { /* The sidecar can briefly restart during development. */ }
    };
    void refreshRuntime();
    const timer = window.setInterval(refreshRuntime, 750);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [project.id, endpoints.length, debugState?.sessionId]);
  useEffect(() => {
    const move = (e: PointerEvent) => {
        const activeDrag = drag.current;
        if (!activeDrag || !activeDrag.positions || !canvas.current || (activeDrag.pointerId != null && activeDrag.pointerId !== e.pointerId)) return;
        const deltaX = (e.clientX - activeDrag.startX) / zoom;
        const deltaY = (e.clientY - activeDrag.startY) / zoom;
        mutateTask((t) => ({
          ...t,
          activities: t.activities.map((n) =>
            activeDrag.positions[n.id]
              ? {
                  ...n,
                  position: {
                    x: Math.max(0, activeDrag.positions[n.id].x + deltaX),
                    y: Math.max(0, activeDrag.positions[n.id].y + deltaY),
                  },
                }
              : n,
          ),
        }));
      },
      stopDrag = (event?: PointerEvent) => {
        if (!drag.current || (event && drag.current.pointerId != null && drag.current.pointerId !== event.pointerId)) return;
        const target = drag.current.captureTarget as HTMLElement | undefined;
        const pointerId = drag.current.pointerId as number | undefined;
        if (target && pointerId != null && target.hasPointerCapture?.(pointerId)) target.releasePointerCapture(pointerId);
        drag.current = null;
      },
      blur = () => stopDrag();
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stopDrag);
    window.addEventListener("pointercancel", stopDrag);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stopDrag);
      window.removeEventListener("pointercancel", stopDrag);
      window.removeEventListener("blur", blur);
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
      if (target && target !== connectionDraft.source && byId[target]?.type !== "catch") {
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
    if (!edgeRewire) return;
    const move = (event: PointerEvent) => {
      if (!canvas.current) return;
      const box = canvas.current.getBoundingClientRect();
      setEdgeRewire((draft) => draft ? { ...draft, x: (event.clientX - box.left + canvas.current!.scrollLeft) / zoom, y: (event.clientY - box.top + canvas.current!.scrollTop) / zoom } : null);
    };
    const up = (event: PointerEvent) => {
      const targetElement = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>(".node[data-node-id]");
      const nodeId = targetElement?.dataset.nodeId;
      if (nodeId && nodeId !== edgeRewire.fixedId && (edgeRewire.endpoint !== "target" || byId[nodeId]?.type !== "catch")) mutateTask((current) => ({ ...current, transitions: current.transitions.map((transition) => transition.id === edgeRewire.edgeId ? { ...transition, [edgeRewire.endpoint]: nodeId } : transition) }));
      setEdgeRewire(null);
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [edgeRewire?.edgeId, edgeRewire?.endpoint, project.active_task_id, zoom]);
  useEffect(() => {
    if (!quickAddDrag) return;
    const move = (event: PointerEvent) => {
      if (event.pointerId !== quickAddDrag.pointerId || !canvas.current) return;
      const box = canvas.current.getBoundingClientRect();
      const clientX = Math.max(box.left + 8, Math.min(event.clientX, box.right - 8));
      const clientY = Math.max(box.top + 8, Math.min(event.clientY, box.bottom - 8));
      const dragX = (clientX - box.left + canvas.current.scrollLeft) / zoom;
      const dragY = (clientY - box.top + canvas.current.scrollTop) / zoom;
      const distance = Math.hypot(event.clientX - quickAddDrag.startClientX, event.clientY - quickAddDrag.startClientY);
      if (distance >= 18) {
        // Dragging the glossy + is the command itself. Open the picker as soon
        // as the pointer has clearly moved; do not depend on a later drop event.
        setMenu({ type: "canvas", x: clientX + 12, y: clientY - 80, cx: Math.max(8, dragX - 52), cy: Math.max(8, dragY - 38), connectFrom: quickAddDrag.source, quickAdd: true });
        setQuickAddDrag(null);
        return;
      }
      setQuickAddDrag((draft) => draft ? { ...draft, x: dragX, y: dragY } : null);
    };
    const finish = (event: PointerEvent) => {
      if (event.pointerId !== quickAddDrag.pointerId) return;
      const box = canvas.current?.getBoundingClientRect(), distance = Math.hypot(event.clientX - quickAddDrag.startClientX, event.clientY - quickAddDrag.startClientY);
      setQuickAddDrag(null);
      if (!box || distance < 12) return;
      // The visible canvas can be quite short when the activity editor is open.
      // Treat every completed drag as intentional and clamp its destination to
      // the canvas instead of silently rejecting releases a few pixels outside.
      const clientX = Math.max(box.left + 8, Math.min(event.clientX, box.right - 8));
      const clientY = Math.max(box.top + 8, Math.min(event.clientY, box.bottom - 8));
      const dropX = (clientX - box.left + canvas.current!.scrollLeft) / zoom;
      const dropY = (clientY - box.top + canvas.current!.scrollTop) / zoom;
      const picker = { type: "canvas", x: clientX + 12, y: clientY - 80, cx: Math.max(8, dropX - 52), cy: Math.max(8, dropY - 38), connectFrom: quickAddDrag.source, quickAdd: true };
      // A completed pointer drag may emit a synthetic click after pointerup.
      // Open on the next event-loop turn so that click cannot reach the Studio's
      // global menu-dismiss handler and immediately close this picker.
      window.setTimeout(() => setMenu(picker), 0);
    };
    const cancel = (event: PointerEvent) => { if (event.pointerId === quickAddDrag.pointerId) setQuickAddDrag(null); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", finish); window.addEventListener("pointercancel", cancel);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", finish); window.removeEventListener("pointercancel", cancel); };
  }, [quickAddDrag?.source, quickAddDrag?.pointerId, project.active_task_id, zoom]);
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
    setOpenTaskIds((current) => current.includes(id) ? current : [...current, id]);
    setProject((p) => ({ ...p, active_task_id: id }));
    const first = t?.activities[0]?.id || "";
    setSelected(first);
    setSelectedIds(first ? [first] : []);
    setSelectedEdge(null);
    setSelectedResource(null);
  };
  const closeTaskTabs = (taskId: string, mode: "one" | "left" | "right" | "others") => {
    const index = openTaskIds.indexOf(taskId);
    if (index < 0) return;
    let keep = mode === "others" ? [taskId]
      : mode === "left" ? openTaskIds.slice(index)
        : mode === "right" ? openTaskIds.slice(0, index + 1)
          : openTaskIds.filter((id) => id !== taskId);
    if (!keep.length) {
      const fallback = project.tasks.find((item) => item.id !== taskId) || project.tasks.find((item) => item.id === taskId);
      if (fallback) keep = [fallback.id];
    }
    setOpenTaskIds(keep);
    if (!keep.includes(project.active_task_id) && keep[0]) selectTask(keep[Math.min(index, keep.length - 1)] || keep[0]);
    setTaskTabMenu(null);
  };
  const addActivity = (d: Def, pos?: { x: number; y: number; connectFrom?: string }) => {
    const id = `${d.type}-${Date.now()}`,
      config: any = {
        operation: d.operation,
        advanced: advancedDefaults(d.type, d.operation || ""),
      };
    if (d.type === "timer")
      Object.assign(config, {
        scheduleMode: "dateTime",
        scheduledDateTime: "",
        cronExpression: "0 * * * *",
        timezone: "local",
        repeatEnabled: false,
        interval: 1,
        unit: "minutes",
        runOnceOnLocalStart: true,
      });
    if (d.type === "call_task")
      Object.assign(config, {
        taskId: project.tasks.find((t) => t.kind === "subtask")?.id || "",
        spawn: false,
        inputMappings: {},
      });
    if (["ems", "jms", "kafka", "pubsub"].includes(d.type))
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
    if (d.type === "ems") Object.assign(config, { messagingStyle: d.operation?.includes("topic") ? "Topic" : "Queue", messageType: "Text", acknowledgeMode: ["queue_receiver", "topic_subscriber"].includes(d.operation || "") ? "Auto" : undefined, deliveryMode: "Persistent", priority: 4, expiration: 0, queue: d.operation === "queue_receiver" ? "${properties.connections.ems.destination}" : undefined, topic: d.operation === "topic_subscriber" ? "${properties.connections.ems.destination}" : undefined, maxSessions: "${properties.connections.ems.sessionCount}", flowLimit: "${properties.connections.ems.flowLimit}", receiveTimeout: "${properties.connections.ems.receiveTimeoutMs}", dynamicProperties: "{}" });
    if (d.type === "jms") Object.assign(config, { messagingStyle: "Queue", messageType: "Text", acknowledgeMode: ["get_queue_message", "receive_message", "wait_request"].includes(d.operation || "") ? "Auto" : undefined, deliveryMode: "Persistent", priority: 4, expiration: 0, maxSessions: 1, receiveTimeout: 30000, requestTimeout: 30000, dynamicProperties: "{}" });
    if (d.type === "kafka") Object.assign(config, { acknowledgeMode: d.operation === "receive" || d.operation === "get" ? "Auto" : undefined, keySerializer: "String", valueSerializer: "String", keyDeserializer: "String", valueDeserializer: "String", acks: "all", compressionType: "none", retries: 3, bufferMemory: 33554432, batchSize: 16384, lingerMs: 0, maxRequestSize: 1048576, enableIdempotence: false, enableAutoCommit: true, autoOffsetReset: "earliest", fetchMinBytes: 1, maxPollRecords: 1, sessionTimeoutMs: 45000, heartbeatIntervalMs: 3000, additionalProperties: "{}" });
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
    if (d.type === "snowflake")
      Object.assign(config, {
        resourceId: project.resources.find((r) => r.type === "snowflake")?.id || "",
        entity: "", tableName: "", timeout: d.operation === "query" || d.operation === "delete" ? 100 : 0,
        maximumRows: 100, batchSize: 100, createTableFromXsd: false,
        valueColumns: "", parameterColumns: "", preparedParameters: "",
        overrideDatabaseName: "", overrideSchemaName: "", interpretEmptyStringAsNull: false,
        merge: false, mergeOnColumns: "", faultOnBatchFailure: false, createTableIfNoneExists: false,
        stageType: "UserStage", namedStage: "", fileFormat: "DelimitedFiles", validationMode: false,
        purgeStageFiles: false, compressData: true, onError: "ABORT_STATEMENT",
        skipFileErrorCount: 1, skipFileErrorPercentage: 1,
      });
    if (d.type === "amqp")
      Object.assign(config, {
        resourceId: project.resources.find((r) => r.type === "amqp")?.id || "",
        queueName: "", entityType: "Queue", entityName: "", subscriptionName: "",
        destinationType: "Queue", exchangeType: "direct", exchangeName: "", routingKey: "",
        messageType: "TextMessage", acknowledgeMode: d.operation === "receive" ? "Auto" : "Auto",
        deliveryMode: "Persistent", expiration: 0, priority: 4, getMessageID: true,
        maxMessages: 1, receiverMode: "PeekLock", durableSubscription: false, sharedSubscription: false,
        useRetry: false, totalTimeoutSeconds: 12, maxAttempts: 10, backoffTimeMsec: 1000,
      });
    if (d.type === "excel") Object.assign(config, { filePath: "", sheetName: "", headerRow: 1, startRow: 2, maximumRows: 0, dataOnly: true, nestedHeaders: true, skipBlankRows: true });
    if (d.type === "basic" && d.operation === "external_command") Object.assign(config, { command: "", provideCommandOutput: true, removeParameterQuotes: false, outputFile: "", outputLineSplitting: "None", splitToken: "", workingDirectory: "", environment: "", timeoutSeconds: 300, encoding: "utf-8" });
    if (["mapper", "transform", "ai_transform"].includes(d.type))
      Object.assign(config, {
        language: "JSONPath / functions",
        sourceSchema: {},
        targetSchema: {},
        mappings: [],
        threshold: 70,
      });
    if (d.type === "dataweave")
      Object.assign(config, {
        script: "%dw 2.0\noutput application/json\n---\npayload",
        inputMimeType: "application/json",
        outputMimeType: "application/json",
        outputTarget: "payload",
        outputVariable: "transformResult",
        variables: {},
        sampleInput: "{}",
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
    if (d.type === "flat") Object.assign(config, {
      inputSource: "String", filePath: "", fileEncoding: "UTF-8", format: "delimited",
      delimiter: ",", lineSeparator: "Auto", header: true, rootElement: "records",
      recordElement: "record", trimValues: true, skipBlankLines: true,
    });
    if (
      d.type === "http_listener" ||
      (d.type === "rest" && d.operation === "receiver")
    )
      Object.assign(config, { path: "/events", methods: "GET,POST,PUT,PATCH,DELETE,HEAD,OPTIONS,TRACE,CONNECT" });
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
      position: pos ? { x: pos.x, y: pos.y } : {
        x: 160 + (nodes.length % 4) * 180,
        y: 270 + Math.floor(nodes.length / 4) * 105,
      },
      config,
    };
    if (d.type === "end") {
      const existingEnd = nodes.find((activity) => activity.type === "end");
      if (existingEnd) {
        mutateTask((current) => ({
          ...current,
          activities: current.activities.map((activity) => activity.id === existingEnd.id && pos ? { ...activity, position: { x: pos.x, y: pos.y } } : activity),
          transitions: pos?.connectFrom && pos.connectFrom !== existingEnd.id && !current.transitions.some((transition) => transition.source === pos.connectFrom && transition.target === existingEnd.id)
            ? [...current.transitions, { id: `transition-${Date.now()}`, source: pos.connectFrom, target: existingEnd.id, type: "success" }]
            : current.transitions,
        }));
        setSelected(existingEnd.id); setSelectedIds([existingEnd.id]); setSelectedEdge(null); setSelectedResource(null); setMenu(null);
        setLogs([{ level: "INFO", message: "A Task has one End boundary. The existing End activity was selected and moved to the drop position." }]);
        return;
      }
    }
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
    mutateTask((t) => ({
      ...t,
      activities: [...t.activities, n],
      transitions: pos?.connectFrom && t.activities.some((activity) => activity.id === pos.connectFrom) && !t.transitions.some((edge) => edge.source === pos.connectFrom && edge.target === id)
        ? [...t.transitions, { id: `transition-${Date.now()}`, source: pos.connectFrom, target: id, type: "success" }]
        : t.transitions,
    }));
    setSelected(id);
    setSelectedIds([id]);
    setSelectedEdge(null);
    setSelectedResource(null);
    setMenu(null);
  };
  const createExceptionHandlers = (catchActivityId: string, exceptionTypes: string[]) => {
    const selectedTypes = [...new Set(exceptionTypes.filter(Boolean))];
    if (!selectedTypes.length) return;
    const stamp = Date.now();
    mutateTask((current) => {
      const origin = current.activities.find((activity) => activity.id === catchActivityId);
      if (!origin || origin.type !== "catch") return current;
      const activities = current.activities.filter((activity) => !String(activity.config?.generatedByCatchAI || "").startsWith(`${catchActivityId}:`));
      const removed = new Set(current.activities.filter((activity) => String(activity.config?.generatedByCatchAI || "").startsWith(`${catchActivityId}:`)).map((activity) => activity.id));
      const transitions = current.transitions.filter((transition) => !removed.has(transition.source) && !removed.has(transition.target) && transition.source !== catchActivityId);
      const generatedActivities: Node[] = [];
      const generatedTransitions: Edge[] = [];
      selectedTypes.forEach((exceptionType, index) => {
        const catchId = index === 0 ? catchActivityId : `${catchActivityId}-ai-${stamp}-${index}`;
        const throwId = `${catchActivityId}-throw-${stamp}-${index}`;
        const catchPosition = { x: origin.position.x, y: origin.position.y + index * 145 };
        if (index === 0) {
          const position = activities.findIndex((activity) => activity.id === catchActivityId);
          activities[position] = { ...origin, name: `Catch ${exceptionType}`, position: catchPosition, config: { ...origin.config, catchAll: false, errorType: exceptionType, errorCode: "" } };
        } else generatedActivities.push({ id: catchId, type: "catch", name: `Catch ${exceptionType}`, position: catchPosition, config: { operation: "catch", catchAll: false, errorType: exceptionType, errorCode: "", advanced: advancedDefaults(), generatedByCatchAI: `${catchActivityId}:${exceptionType}` } });
        generatedActivities.push({
          id: throwId,
          type: "throw",
          name: `Throw ${exceptionType}`,
          position: { x: catchPosition.x + 235, y: catchPosition.y },
          config: {
            operation: "throw",
            errorType: exceptionType,
            advanced: advancedDefaults(),
            generatedByCatchAI: `${catchActivityId}:${exceptionType}`,
            inputMappings: {
              type: `\${activities.${catchId}.output.type}`,
              code: `\${activities.${catchId}.output.code}`,
              message: `\${activities.${catchId}.output.message}`,
              details: `\${activities.${catchId}.output.details}`,
              stackTrace: `\${activities.${catchId}.output.stackTrace}`,
            },
          },
        });
        generatedTransitions.push({ id: `${catchId}-to-${throwId}`, source: catchId, target: throwId, type: "success" });
      });
      return { ...current, activities: [...activities, ...generatedActivities], transitions: [...transitions, ...generatedTransitions] };
    });
    setSelected(catchActivityId); setSelectedIds([catchActivityId]); setSelectedEdge(null);
    setLogs([{ level: "INFO", message: `Catch AI generated ${selectedTypes.length} exception handler block${selectedTypes.length === 1 ? "" : "s"} with code, message, details, and stack-trace mappings.` }]);
  };
  const openCatchAI = () => {
    const existing = node?.type === "catch" ? node : nodes.find((activity) => activity.type === "catch" && !activity.config?.generatedByCatchAI);
    const catchId = existing?.id || `catch-ai-${Date.now()}`;
    if (!existing) {
      const lowest = nodes.reduce((value, activity) => Math.max(value, activity.position.y), 120);
      const catchNode: Node = {
        id: catchId,
        type: "catch",
        name: "Catch Exception",
        position: { x: 80, y: lowest + 135 },
        config: { operation: "catch", catchAll: true, errorType: "", errorCode: "", advanced: advancedDefaults() },
      };
      mutateTask((current) => ({ ...current, activities: [...current.activities, catchNode] }));
      setLogs([{ level: "INFO", message: "Added a Catch block and opened Catch AI. Select task exceptions to generate mapped handlers." }]);
    }
    setSelected(catchId); setSelectedIds([catchId]); setSelectedEdge(null); setSelectedResource(null);
    setActiveTab("configuration"); setConfigHeight((height) => Math.max(height, 390)); setMenu(null);
  };
  const deleteSelectedActivity = () => {
    const targets = selectedIds.length ? nodes.filter((item) => selectedIds.includes(item.id)) : node ? [node] : [];
    if (!targets.length) return;
    if (targets.some(isEventActivity) && nodes.filter(isEventActivity).every((item) => targets.some((target) => target.id === item.id))) {
      setLogs([{ level: "WARN", message: "A Task must retain one event activity. Add a replacement event to replace this starter." }]);
      return;
    }
    if (targets.some((item) => item.type === "end") && nodes.filter((item) => item.type === "end").every((item) => targets.some((target) => target.id === item.id))) {
      setLogs([{ level: "WARN", message: "A Task must retain one End activity. Drag End to reposition it instead of deleting it." }]);
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
  const newProject = (requestedName?: string) => {
    const suppliedName = typeof requestedName === "string" ? requestedName : undefined;
    const name = (suppliedName ?? prompt("New application name", "New Integration Application"))?.trim();
    if (!name) return;
    const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || `project-${Date.now()}`;
    const next = structuredClone(initial);
    next.id = id; next.name = name; next.description = ""; next.resources = []; next.schemas = []; next.custom_functions = []; next.properties = structuredClone(envs); next.packaging = { ...next.packaging, artifact_name: id }; next.tasks = [starter("main", "Main Task")]; next.active_task_id = "main";
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
    setProject(normalizeProject(output));
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
    setWorkStatus(format === "package" ? "Saving project package…" : "Saving project JSON…");
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
    } finally { setWorkStatus(""); }
  };
  const saveProjectFolder = async () => {
    setWorkStatus("Saving project workspace…");
    try {
      const saved = await persistProject();
      const folderName = projectFilename("").replace(/\.$/, "");
      if (window.fabricDesktop) {
        const remembered = typeof projectFileHandle.current === "string" && !/\.(ifproject|zip|json)$/i.test(projectFileHandle.current) ? projectFileHandle.current : undefined;
        const folderPath = await window.fabricDesktop.saveProjectFolder({ path: remembered, folderName, project: saved });
        if (!folderPath) { setLogs([{ level: "INFO", message: "Project folder save cancelled." }]); return; }
        projectFileHandle.current = folderPath;
        localStorage.setItem(`integration-fabric-project-path:${project.id}`, folderPath);
        setLogs([{ level: "INFO", message: `Saved project folder: ${folderPath}` }]);
        return;
      }
      const picker = (window as any).showDirectoryPicker;
      if (!picker) {
        setLogs([{ level: "INFO", message: "Browser mode cannot write a project folder directly. Downloading a portable .ifproject package instead." }]);
        await saveProjectFile("package", true);
        return;
      }
      const root = await picker({ mode: "readwrite" });
      const folder = await root.getDirectoryHandle(folderName, { create: true });
      const write = async (parts: string[], value: string) => {
        let directory = folder;
        for (const part of parts.slice(0, -1)) directory = await directory.getDirectoryHandle(part, { create: true });
        const file = await directory.getFileHandle(parts[parts.length - 1], { create: true }), writable = await file.createWritable();
        await writable.write(value); await writable.close();
      };
      const taskPaths = saved.tasks.map((item: any) => `tasks/${item.id}.json`);
      const resourcePaths = saved.resources.map((item: any) => `resources/connections/${item.id}.json`);
      const schemaPaths = saved.schemas.map((item: any) => `schemas/${item.name}`);
      const propertyPaths = Object.keys(saved.properties).map((environment) => `properties/${environment}.json`);
      const metadata: any = { ...saved, tasks: undefined, resources: undefined, schemas: undefined, properties: undefined, packaging: undefined, process: undefined, layout: { version: 1, tasks: taskPaths, resources: resourcePaths, schemas: schemaPaths, properties: propertyPaths, packaging: "packaging/packaging.json" } };
      await write(["project.json"], JSON.stringify(metadata, null, 2));
      await Promise.all(saved.tasks.map((item: any) => write(["tasks", `${item.id}.json`], JSON.stringify(item, null, 2))));
      await Promise.all(saved.resources.map((item: any) => write(["resources", "connections", `${item.id}.json`], JSON.stringify(item, null, 2))));
      await Promise.all(saved.schemas.map((item: any) => write(["schemas", item.name], item.content || "")));
      await Promise.all(Object.entries(saved.properties).map(([environment, values]) => write(["properties", `${environment}.json`], JSON.stringify({ environment, values }, null, 2))));
      await write(["packaging", "packaging.json"], JSON.stringify(saved.packaging, null, 2));
      setLogs([{ level: "INFO", message: `Saved structured project folder ${folderName}.` }]);
    } catch (error: any) {
      if (error?.name !== "AbortError") setLogs([{ level: "ERROR", message: error?.message || "Project folder save failed" }]);
    } finally { setWorkStatus(""); }
  };
  const save = () => saveProjectFolder();
  const exportProject = () => saveProjectFile("package", true);
  const saveJsonFile = () => saveProjectFile("json", true);
  const buildDeploymentPackage = async (settings: Record<string, any>) => {
    setWorkStatus("Validating and building deployment package…");
    try {
      const issues = validateProjectDefinition(project);
      const blocking = issues.filter((item) => item.severity === "error");
      if (blocking.length) {
        setValidation({ title: `Validate Project · ${project.name}`, issues });
        throw new Error(`Package blocked by ${blocking.length} project validation error${blocking.length === 1 ? "" : "s"}.`);
      }
      const next = { ...project, packaging: { ...project.packaging, ...settings } };
      const saved = await fetch(`/api/projects/${project.id}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(next) });
      if (!saved.ok) throw new Error("Unable to save packaging configuration.");
      setProject(normalizeProject(await saved.json()));
      const selectedEnvironments = settings.environments?.length ? settings.environments : [settings.environment || project.active_environment];
      const query = new URLSearchParams({ target: settings.target, environments: selectedEnvironments.join(","), starters: (settings.starterTaskIds || []).join(","), archive: settings.format, artifacts: settings.artifacts.join(",") });
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
    } catch (error: any) {
      setLogs([{ level: "ERROR", message: error?.message || "Package generation failed" }]);
      throw error;
    } finally { setWorkStatus(""); }
  };
  const run = async (requestedTaskId?: unknown) => {
      setBusy(true);
      try {
        await persistProject();
        const r = await fetch(`/api/projects/${project.id}/run`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            input: { orderId: "10001" },
            environment: project.active_environment,
            task_id: typeof requestedTaskId === "string" ? requestedTaskId : task.id,
          }),
        }),
          out = await r.json();
        setLogs(out.logs || [{ level: "ERROR", message: out.detail }]);
        setExecutionOutputs(out.activity_outputs || {});
        setEndpoints(out.endpoints || []);
        setRuntimeState(out);
      } catch (error: any) {
        setLogs([{ level: "ERROR", message: error?.message || "Run failed" }]);
      } finally { setBusy(false); }
    },
    debug = async (requestedTaskId?: unknown) => {
      await persistProject();
      const r = await fetch(`/api/projects/${project.id}/debug`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            input: {},
            environment: project.active_environment,
            task_id: typeof requestedTaskId === "string" ? requestedTaskId : task.id,
            breakpoints,
          }),
        }),
        out = await r.json();
      if (out.status === "stopped") {
        setDebugState(null);
        setExecutionOutputs({});
        setEndpoints([]);
        setRuntimeState(null);
        setLogs(out.logs || []);
        return;
      }
      setDebugState(out);
      setExecutionOutputs(out.activityOutputs || {});
      setLogs(out.logs || [{ level: "ERROR", message: out.detail }]);
      setEndpoints(out.endpoints || []);
      setRuntimeState(out);
    },
    debugAction = async (action: string) => {
      if (!debugState) return;
      const r = await fetch(`/api/debug/${debugState.sessionId}/action`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ action }),
        }),
        out = await r.json();
      if (out.status === "stopped") {
        setDebugState(null); setExecutionOutputs({}); setEndpoints([]); setRuntimeState(null); setLogs(out.logs || []);
        return;
      }
      setDebugState(out);
      setExecutionOutputs(out.activityOutputs || {});
      setLogs(out.logs || []);
      setEndpoints(out.endpoints || endpoints);
      if (out.currentTaskId && out.currentTaskId !== project.active_task_id)
        selectTask(out.currentTaskId);
    };
  const loadSystemLogs = async () => {
    setWorkStatus("Loading saved project logs…");
    try {
      const response = await fetch(`/api/projects/${project.id}/logs?limit=2000&environment=${encodeURIComponent(project.active_environment)}`);
      const output = await response.json();
      if (!response.ok) throw new Error(output.detail || "Unable to load saved logs");
      setSystemLogInfo(output);
      setLogs(output.entries || []);
    } catch (error: any) {
      setLogs((current) => [...current, { level: "ERROR", message: error?.message || "Unable to load saved logs" }]);
    } finally { setWorkStatus(""); }
  };
  const downloadSystemLogs = async () => {
    try {
      const response = await fetch(`/api/projects/${project.id}/logs?limit=10000&environment=${encodeURIComponent(project.active_environment)}`);
      const output = await response.json();
      if (!response.ok) throw new Error(output.detail || "Unable to download saved logs");
      const blob = new Blob([(output.entries || []).map((entry: any) => JSON.stringify(entry)).join("\n") + "\n"], { type: "application/x-ndjson" });
      browserDownload(blob, `${project.id}-${project.active_environment}-application.log`);
      setLogs((current) => [...current, { level: "INFO", message: "Downloaded saved application logs to the browser Downloads folder." }]);
    } catch (error: any) {
      setLogs((current) => [...current, { level: "ERROR", message: error?.message || "Unable to download saved logs" }]);
    }
  };
  const executionActive = busy || (!!debugState && !["completed", "failed", "stopped"].includes(debugState.status)) || endpoints.length > 0 || ["running", "listening", "paused"].includes(runtimeState?.status);
  const visibleWorkStatus = workStatus || (busy ? "Starting and running task…" : debugState?.status === "paused" ? "Debugger paused" : debugState ? `Debugger ${debugState.status || "working"}…` : runtimeState?.status === "listening" ? "Application is listening" : "");
  const stopExecution = async () => {
    try {
      if (debugState?.sessionId) await fetch(`/api/debug/${debugState.sessionId}/action`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "stop" }) });
      const response = await fetch(`/api/projects/${project.id}/stop`, { method: "POST" });
      const stopped = response.ok ? await response.json() : { status: "stopped", logs: [...logs, { level: "INFO", message: `Application ${project.name} stopped by user` }] };
      setDebugState(null); setBusy(false); setEndpoints([]); setExecutionOutputs({}); setRuntimeState(null); setLogs(stopped.logs || []);
    } catch (error: any) {
      setBusy(false); setDebugState(null); setEndpoints([]); setExecutionOutputs({}); setRuntimeState(null);
      setLogs((current) => [...current, { level: "ERROR", message: error?.message || "Unable to stop execution" }]);
    }
  };
  const importProject = async (file: File) => {
    setWorkStatus(`Loading project ${file.name}…`);
    try {
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
        setProject(normalizeProject(out));
        setClosed(false);
        const first = out.tasks?.[0]?.activities?.[0]?.id || "";
        setSelected(first); setSelectedIds(first ? [first] : []);
        projectFileHandle.current = null;
        setLogs([
          { level: "INFO", message: `Imported complete project ${out.name}.` },
        ]);
        return out;
      } else setLogs([{ level: "ERROR", message: out.detail }]);
      return null;
    } catch (error: any) {
      setLogs([{ level: "ERROR", message: error?.message || "Project import failed" }]);
      return null;
    } finally { setWorkStatus(""); }
  };
  const importFromFileSystem = async () => {
    setWorkStatus("Opening project from filesystem…");
    try {
    if (window.fabricDesktop) {
      const selectedFile = await window.fabricDesktop.openProject();
      if (!selectedFile) return;
      if (selectedFile.kind === "folder" && selectedFile.project) {
        const response = await fetch(`/api/projects/${(selectedFile.project as any).id}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(selectedFile.project) });
        const imported = await response.json();
        if (!response.ok) { setLogs([{ level: "ERROR", message: imported.detail || "Unable to open project folder" }]); return; }
        const normalized = normalizeProject(imported); setProject(normalized); setClosed(false); const first = normalized.tasks?.[0]?.activities?.[0]?.id || ""; setSelected(first); setSelectedIds(first ? [first] : []);
        projectFileHandle.current = selectedFile.path; localStorage.setItem(`integration-fabric-project-path:${imported.id}`, selectedFile.path);
        setLogs([{ level: "INFO", message: `Opened project folder ${selectedFile.path}.` }]); return;
      }
      if (!selectedFile.bytes) return;
      const imported = await importProject(new File([new Uint8Array(selectedFile.bytes)], selectedFile.name));
      projectFileHandle.current = null;
      if (imported?.id) localStorage.removeItem(`integration-fabric-project-path:${imported.id}`);
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
    } finally { setWorkStatus(""); }
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
  const explorerCopy = (type: string, id?: string) => {
    const value = type === "task" ? project.tasks.find((item) => item.id === id)
      : type === "resource" ? project.resources.find((item) => item.id === id)
      : type === "schema" ? project.schemas.find((item) => item.id === id)
      : type === "property" ? { name: id, values: project.properties[id || ""] }
      : null;
    if (value) { explorerClipboard.current = { type, value: structuredClone(value) }; setLogs([{ level: "INFO", message: `Copied ${type} ${id || ""} to Project Explorer clipboard.` }]); }
  };
  const explorerPaste = (target: string) => {
    const copied = explorerClipboard.current;
    if (!copied) { setLogs([{ level: "WARN", message: "Project Explorer clipboard is empty." }]); return; }
    const stamp = Date.now();
    if (target === "tasks" && copied.type === "task") {
      const item = { ...structuredClone(copied.value), id: `task-${stamp}`, name: `${copied.value.name} Copy` };
      item.activities = item.activities.map((activity: Node, index: number) => ({ ...activity, id: `${activity.type}-${stamp}-${index}` }));
      const ids = Object.fromEntries(copied.value.activities.map((activity: Node, index: number) => [activity.id, item.activities[index].id]));
      item.transitions = item.transitions.map((edge: Edge, index: number) => ({ ...edge, id: `edge-${stamp}-${index}`, source: ids[edge.source], target: ids[edge.target] }));
      setProject((current) => ({ ...current, tasks: [...current.tasks, item] }));
    } else if (target === "resources" && copied.type === "resource") setProject((current) => ({ ...current, resources: [...current.resources, { ...structuredClone(copied.value), id: `resource-${stamp}`, name: `${copied.value.name} Copy` }] }));
    else if (target === "schemas" && copied.type === "schema") setProject((current) => ({ ...current, schemas: [...current.schemas, { ...structuredClone(copied.value), id: `schema-${stamp}`, name: copied.value.name.replace(/\.xsd$/i, "-copy.xsd") }] }));
    else if (target === "properties" && copied.type === "property") { const name = `${copied.value.name}-copy`; setProject((current) => ({ ...current, properties: { ...current.properties, [name]: structuredClone(copied.value.values) } })); }
    else { setLogs([{ level: "WARN", message: `A ${copied.type} cannot be pasted into ${target}.` }]); return; }
    setLogs([{ level: "INFO", message: `Pasted ${copied.type} into ${target}.` }]);
  };
  const explorerRename = (type: string, id?: string) => {
    if (type === "application") { setRenameOpen(true); return; }
    const currentName = type === "task" ? project.tasks.find((item) => item.id === id)?.name : type === "resource" ? project.resources.find((item) => item.id === id)?.name : type === "schema" ? project.schemas.find((item) => item.id === id)?.name : id;
    const name = prompt(`Rename ${type}`, currentName || "")?.trim(); if (!name || name === currentName) return;
    if (type === "task") setProject((current) => ({ ...current, tasks: current.tasks.map((item) => item.id === id ? { ...item, name } : item) }));
    if (type === "resource") setProject((current) => ({ ...current, resources: current.resources.map((item) => item.id === id ? { ...item, name } : item) }));
    if (type === "schema") setProject((current) => ({ ...current, schemas: current.schemas.map((item) => item.id === id ? { ...item, name: name.toLowerCase().endsWith(".xsd") ? name : `${name}.xsd` } : item) }));
    if (type === "property" && id) setProject((current) => { const properties = { ...current.properties, [name]: current.properties[id] }; delete properties[id]; return { ...current, properties, active_environment: current.active_environment === id ? name : current.active_environment }; });
  };
  const explorerRemove = (type: string, id?: string) => {
    if (type === "application") { void deleteCurrent(); return; }
    if (!confirm(`Remove this ${type} from ${project.name}?`)) return;
    if (type === "task" && id) { if (project.tasks.length === 1) { setLogs([{ level: "WARN", message: "A project must keep at least one Task." }]); return; } const remaining = project.tasks.filter((item) => item.id !== id); setProject((current) => ({ ...current, tasks: remaining, active_task_id: current.active_task_id === id ? remaining[0].id : current.active_task_id })); }
    if (type === "resource") setProject((current) => ({ ...current, resources: current.resources.filter((item) => item.id !== id) }));
    if (type === "schema") setProject((current) => ({ ...current, schemas: current.schemas.filter((item) => item.id !== id) }));
    if (type === "property" && id) setProject((current) => { const properties = { ...current.properties }; delete properties[id]; return { ...current, properties, active_environment: current.active_environment === id ? Object.keys(properties)[0] || "local" : current.active_environment }; });
  };
  const explorerRefresh = async () => { setWorkStatus("Refreshing project workspace…"); try { const response = await fetch(`/api/projects/${project.id}`); if (response.ok) { setProject(normalizeProject(await response.json())); setLogs([{ level: "INFO", message: "Project Explorer refreshed from saved project storage." }]); } } finally { setWorkStatus(""); } };
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
        createProject={newProject}
        importProject={importProject}
        importFromFileSystem={importFromFileSystem}
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
          {menu === "file" && <FileMenu stop={(e: React.MouseEvent) => e.stopPropagation()} save={save} saveJson={saveJsonFile} exportProject={exportProject} importProject={importFromFileSystem} openProjects={() => setClosed(true)} sampleProjects={() => setSampleGalleryOpen(true)} catchAI={openCatchAI} closeProject={closeProject} deleteProject={deleteCurrent}/>}</div>
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
          { label: "Stop Execution", detail: "Stop the active run, listener deployment, or debug session", icon: Square, action: stopExecution, disabled: !executionActive },
        ]}/>
        <TopMenu label="Window" open={menu === "window"} toggle={(e: React.MouseEvent) => { e.stopPropagation(); setMenu(menu === "window" ? null : "window"); }} commands={[
          { label: "Project Explorer", detail: "Move focus to the project tree", icon: FolderOpen, action: () => focusStudioPanel(".explorer") },
          { label: "Task Designer", detail: "Move focus to the orchestration canvas", icon: Workflow, action: () => focusStudioPanel(".canvas") },
          { label: "Configuration", detail: "Move focus to activity configuration", icon: Settings2, action: () => focusStudioPanel(".config") },
          { label: "Execution & Debug", detail: "Move focus to runtime output", icon: Bug, action: () => focusStudioPanel(".monitor") },
        ]}/>
        <TopMenu label="Help" open={menu === "help"} toggle={(e: React.MouseEvent) => { e.stopPropagation(); setMenu(menu === "help" ? null : "help"); }} commands={[
          { label: "Installed Activity Guide", detail: "Offline product activity and runtime documentation", icon: BookOpen, action: () => window.open("/help/activity-reference.html", "_blank", "noopener") },
          { label: "Keyboard Shortcuts", detail: "Designer and runtime commands", icon: Settings2, action: () => setHelpDialog("shortcuts") },
          { label: "About Integration Fabric", detail: "Product and project information", icon: Workflow, action: () => setHelpDialog("about") },
        ]}/>
        <span className="menu-spacer" />
        <ThemePicker theme={theme} setTheme={setTheme} />
        {executionActive ? <button className="global-stop" onClick={stopExecution}><Square/> Stop</button> : <><button onClick={run}><CirclePlay /> Run</button><button onClick={debug}><Bug /> Debug</button></>}
      </nav>
      <StudioRibbon
        selectedCount={selectedIds.length}
        newProject={newProject}
        openProject={() => setClosed(true)}
        importProject={importFromFileSystem}
        save={save}
        exportProject={exportProject}
        packageProject={() => setPackageOpen(true)}
        sampleProjects={() => setSampleGalleryOpen(true)}
        closeProject={closeProject}
        run={run}
        debug={debug}
        stop={stopExecution}
        executionActive={executionActive}
        aiBuild={() => setAiBuilderOpen(true)}
        catchAI={openCatchAI}
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
         <IntegrationBrandArtwork className="studio-brand-art" />
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
      </header>
      <aside className="explorer">
        <div className="explorer-width-splitter" title="Drag left or right to resize Project Explorer" onPointerDown={(event) => { event.preventDefault(); event.stopPropagation(); explorerSplit.current = { x: event.clientX, width: explorerWidth }; }}><span /></div>
         <div className="pane-title">PROJECT EXPLORER</div>
        <div className="tree project-tree" style={{ height: treeHeight }}>
          <button
            className="tree-row application-row"
            title="Double-click or use the edit button to rename the application"
            onDoubleClick={() => setRenameOpen(true)}
            onContextMenu={(e) => { e.preventDefault(); setMenu({ type: "application", x: e.clientX, y: e.clientY }); }}
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
                  setMenu({ type: "task", id: t.id, x: e.clientX, y: e.clientY });
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
            onContextMenu={(e) => { e.preventDefault(); setMenu({ type: "resources-root", x: e.clientX, y: e.clientY }); }}
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
                    onContextMenu={(e) => { e.preventDefault(); setMenu({ type: "resource", id: r.id, x: e.clientX, y: e.clientY }); }}
                     onClick={() => {
                        setSelectedResource(null);
                        setEditingConnection(r);
                        setSelected("");
                      setSelectedIds([]);
                      setSelectedEdge(null);
                      setActiveTab("configuration");
                    }}
                  >
                    <ResourceVendorIcon type={r.type}/>
                    {r.name}
                    <small>{r.type}</small>
                  </button>
                ))}
            </>
          )}
          <button
            className="tree-row indent"
            onClick={() => setOpen((o) => ({ ...o, Packaging: !o.Packaging }))}
            onContextMenu={(e) => { e.preventDefault(); setMenu({ type: "packaging", x: e.clientX, y: e.clientY }); }}
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
            onContextMenu={(e) => { e.preventDefault(); setMenu({ type: "schemas", x: e.clientX, y: e.clientY }); }}
          >
            {open.Schemas ? <ChevronDown /> : <ChevronRight />}
            <CodeXml /> Schemas{" "}
            <span className="count">{project.schemas.length}</span>
            <i
              onClick={(e) => {
                e.stopPropagation();
                setSchemaEditor("new");
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
                onClick={() => setSchemaEditor(s)}
                onContextMenu={(e) => { e.preventDefault(); setMenu({ type: "schema", id: s.id, x: e.clientX, y: e.clientY }); }}
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
            onContextMenu={(e) => { e.preventDefault(); setMenu({ type: "properties", x: e.clientX, y: e.clientY }); }}
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
                onContextMenu={(e) => { e.preventDefault(); setMenu({ type: "property", id: name, x: e.clientX, y: e.clientY }); }}
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
        <nav className="task-editor-tabs" aria-label="Open task editors">
          {openTaskIds.map((taskId) => {
            const openTask = project.tasks.find((item) => item.id === taskId);
            if (!openTask) return null;
            const active = taskId === project.active_task_id;
            return <div key={taskId} className={`task-editor-tab ${active ? "active" : ""}`} onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); setTaskTabMenu({ taskId, x: event.clientX, y: event.clientY }); }}>
              <button className="task-tab-title" title={openTask.name} onClick={() => selectTask(taskId)}><Workflow/><span>{openTask.name}</span><small>{openTask.kind === "starter" ? "Starter" : "Sub Task"}</small></button>
              <button className="task-tab-more" aria-label={`Task tab options for ${openTask.name}`} onClick={(event) => { event.stopPropagation(); const bounds = event.currentTarget.getBoundingClientRect(); setTaskTabMenu({ taskId, x: bounds.right - 8, y: bounds.bottom + 4 }); }}>•••</button>
              <button className="task-tab-close" aria-label={`Close ${openTask.name} tab`} onClick={(event) => { event.stopPropagation(); closeTaskTabs(taskId, "one"); }}>×</button>
            </div>;
          })}
        </nav>
        {taskTabMenu && <div className="task-tab-context" style={{ left: taskTabMenu.x, top: taskTabMenu.y }} onPointerDown={(event) => event.stopPropagation()}>
          <button onClick={() => closeTaskTabs(taskTabMenu.taskId, "one")}>Close Tab</button>
          <button onClick={() => closeTaskTabs(taskTabMenu.taskId, "others")}>Close Other Tabs</button>
          <button disabled={openTaskIds.indexOf(taskTabMenu.taskId) === 0} onClick={() => closeTaskTabs(taskTabMenu.taskId, "left")}>Close Tabs to the Left</button>
          <button disabled={openTaskIds.indexOf(taskTabMenu.taskId) === openTaskIds.length - 1} onClick={() => closeTaskTabs(taskTabMenu.taskId, "right")}>Close Tabs to the Right</button>
        </div>}
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
        {debugState && <DebugBar state={debugState} act={debugAction} stop={stopExecution} />}
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
            const target = event.target as Element;
            // The visual canvas is mostly the nested canvas-content/SVG rather
            // than this scrolling element itself. Any blank orchestrator click
            // should clear the active activity or transition selection.
            if (event.button !== 0 || target.closest(".node") || target.closest(".wires g")) return;
            if (!canvas.current) return;
            const bounds = canvas.current.getBoundingClientRect();
            const x = (event.clientX - bounds.left + canvas.current.scrollLeft) / zoom;
            const y = (event.clientY - bounds.top + canvas.current.scrollTop) / zoom;
            const additive = event.ctrlKey || event.metaKey || event.shiftKey;
            setSelectionBox({ startX: x, startY: y, x, y, pointerId: event.pointerId, baseIds: additive ? selectedIds : [] });
            if (!additive) { setSelectedIds([]); setSelected(""); }
            setSelectedEdge(null); setSelectedResource(null);
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (!selectionBox || selectionBox.pointerId !== event.pointerId || !canvas.current) return;
            const bounds = canvas.current.getBoundingClientRect();
            const x = (event.clientX - bounds.left + canvas.current.scrollLeft) / zoom;
            const y = (event.clientY - bounds.top + canvas.current.scrollTop) / zoom;
            const left = Math.min(selectionBox.startX, x), right = Math.max(selectionBox.startX, x);
            const top = Math.min(selectionBox.startY, y), bottom = Math.max(selectionBox.startY, y);
            const hits = nodes.filter((item) => item.position.x < right && item.position.x + 104 > left && item.position.y < bottom && item.position.y + 94 > top).map((item) => item.id);
            const nextIds = [...new Set([...selectionBox.baseIds, ...hits])];
            setSelectionBox((current) => current ? { ...current, x, y } : null);
            setSelectedIds(nextIds);
            setSelected((current) => current && nextIds.includes(current) ? current : nextIds[0] || "");
          }}
          onPointerUp={(event) => {
            if (!selectionBox || selectionBox.pointerId !== event.pointerId) return;
            if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
            setSelectionBox(null);
          }}
          onPointerCancel={(event) => {
            if (!selectionBox || selectionBox.pointerId !== event.pointerId) return;
            setSelectionBox(null);
          }}
        >
          <div
            className="canvas-content"
            style={{ transform: `scale(${zoom})` }}
          >
            <svg className="wires">
              <defs><marker id="transition-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
              {edges.map((e) => {
                const a = byId[e.source],
                  b = byId[e.target];
                if (!a || !b) return null;
                const d = `M${a.position.x + 104},${a.position.y + 38} C${a.position.x + 136},${a.position.y + 38} ${b.position.x - 32},${b.position.y + 38} ${b.position.x},${b.position.y + 38}`;
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
                    <path className="edge-line" d={d} markerEnd="url(#transition-arrow)" />
                    <text
                      x={(a.position.x + b.position.x + 104) / 2}
                      y={(a.position.y + b.position.y) / 2 + 31}
                    >
                      {e.type || "success"}
                    </text>
                    {selectedEdge === e.id && <><circle className="edge-rewire-handle source" cx={a.position.x + 104} cy={a.position.y + 38} r="7" onPointerDown={(event) => { event.preventDefault(); event.stopPropagation(); setEdgeRewire({ edgeId: e.id, endpoint: "source", fixedId: e.target, x: a.position.x + 104, y: a.position.y + 38 }); }}/><circle className="edge-rewire-handle target" cx={b.position.x} cy={b.position.y + 38} r="7" onPointerDown={(event) => { event.preventDefault(); event.stopPropagation(); setEdgeRewire({ edgeId: e.id, endpoint: "target", fixedId: e.source, x: b.position.x, y: b.position.y + 38 }); }}/></>}
                  </g>
                );
              })}
              {connectionDraft && byId[connectionDraft.source] && (
                <path
                  className="draft-connection"
                  d={`M${byId[connectionDraft.source].position.x + 104},${byId[connectionDraft.source].position.y + 38} C${byId[connectionDraft.source].position.x + 136},${byId[connectionDraft.source].position.y + 38} ${connectionDraft.x - 32},${connectionDraft.y} ${connectionDraft.x},${connectionDraft.y}`}
                />
              )}
              {quickAddDrag && byId[quickAddDrag.source] && <><path className="quick-add-draft" d={`M${byId[quickAddDrag.source].position.x + 104},${byId[quickAddDrag.source].position.y + 70} C${byId[quickAddDrag.source].position.x + 145},${byId[quickAddDrag.source].position.y + 70} ${quickAddDrag.x - 38},${quickAddDrag.y} ${quickAddDrag.x},${quickAddDrag.y}`}/><circle className="quick-add-drop" cx={quickAddDrag.x} cy={quickAddDrag.y} r="11"/><path className="quick-add-drop-plus" d={`M${quickAddDrag.x - 5},${quickAddDrag.y}H${quickAddDrag.x + 5}M${quickAddDrag.x},${quickAddDrag.y - 5}V${quickAddDrag.y + 5}`}/></>}
              {edgeRewire && byId[edgeRewire.fixedId] && <path className="draft-connection edge-rewire-draft" d={edgeRewire.endpoint === "target" ? `M${byId[edgeRewire.fixedId].position.x + 104},${byId[edgeRewire.fixedId].position.y + 38} C${byId[edgeRewire.fixedId].position.x + 136},${byId[edgeRewire.fixedId].position.y + 38} ${edgeRewire.x - 32},${edgeRewire.y} ${edgeRewire.x},${edgeRewire.y}` : `M${edgeRewire.x},${edgeRewire.y} C${edgeRewire.x + 32},${edgeRewire.y} ${byId[edgeRewire.fixedId].position.x - 32},${byId[edgeRewire.fixedId].position.y + 38} ${byId[edgeRewire.fixedId].position.x},${byId[edgeRewire.fixedId].position.y + 38}`} />}
            </svg>
            {selectionBox && <div className="canvas-selection-box" style={{ left: Math.min(selectionBox.startX, selectionBox.x), top: Math.min(selectionBox.startY, selectionBox.y), width: Math.abs(selectionBox.x - selectionBox.startX), height: Math.abs(selectionBox.y - selectionBox.startY) }} />}
            {nodes.map((n) => {
              const def = packs
                .flatMap((p) => p.items)
                .find(
                  (d) =>
                    d.type === n.type &&
                    (!d.operation || d.operation === n.config.operation),
                ) || packs.flatMap((p) => p.items).find((d) => d.type === n.type);
              return (
                <button
                  key={n.id}
                  data-node-id={n.id}
                  className={`node ${selectedIds.includes(n.id) ? "selected" : ""} ${selectedIds.length > 1 && selectedIds.includes(n.id) ? "multi-selected" : ""} ${debugState?.currentActivityId === n.id ? "debug-current" : ""} ${executionOutputs[n.id] ? "runtime-executed" : ""}`}
                  style={{ left: n.position.x, top: n.position.y }}
                  onPointerDown={(e) => {
                    if (e.button !== 0) return;
                    e.preventDefault();
                    e.stopPropagation();
                    const additive = e.ctrlKey || e.metaKey || e.shiftKey;
                    const nextIds = additive ? (selectedIds.includes(n.id) ? selectedIds : [...selectedIds, n.id]) : (selectedIds.includes(n.id) && selectedIds.length > 1 ? selectedIds : [n.id]);
                    const positions = Object.fromEntries(nodes.filter((item) => nextIds.includes(item.id)).map((item) => [item.id, { ...item.position }]));
                    drag.current = {
                      ids: nextIds,
                      positions,
                      startX: e.clientX,
                      startY: e.clientY,
                      pointerId: e.pointerId,
                      captureTarget: e.currentTarget,
                    };
                    e.currentTarget.setPointerCapture(e.pointerId);
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
                          ? "end-stop.svg"
                          : ["mapper", "transform", "ai_transform"].includes(n.type)
                            ? "mapper.svg"
                            : n.type === "dataweave"
                              ? "dataweave-transform.svg"
                              : def?.asset || "start-end",
                    )}
                  </span>
                  {breakpoints.includes(n.id) && <i className="breakpoint" />}
                  <strong>{n.name}</strong>
                  <span
                    className="connect-handle"
                    role="button"
                    aria-label={`Connect ${n.name} to another activity`}
                    title="Drag to another activity to create a transition"
                    onPointerDown={(event) => {
                      event.preventDefault(); event.stopPropagation();
                      setConnectionDraft({ source: n.id, x: n.position.x + 104, y: n.position.y + 38 });
                    }}
                  ><ChevronRight /></span>
                  <span
                    className={`quick-add-handle ${quickAddDrag?.source === n.id ? "dragging" : ""}`}
                    role="button"
                    aria-label={`Add and connect an activity after ${n.name}`}
                    title="Drag onto the canvas, then choose the next activity"
                    onPointerDown={(event) => {
                      event.preventDefault(); event.stopPropagation();
                      if (!canvas.current) return;
                      event.currentTarget.setPointerCapture(event.pointerId);
                      const box = canvas.current.getBoundingClientRect();
                      setMenu(null); setConnectionDraft(null);
                      setQuickAddDrag({ source: n.id, startClientX: event.clientX, startClientY: event.clientY, x: (event.clientX - box.left + canvas.current.scrollLeft) / zoom, y: (event.clientY - box.top + canvas.current.scrollTop) / zoom, pointerId: event.pointerId });
                    }}
                    onClick={(event) => {
                      event.preventDefault(); event.stopPropagation();
                    }}
                  ><Plus /></span>
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
        <section className="config" onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
          <div className="tabs">
            <b>
              <Settings2 /> {edge ? "Transition" : resource ? "Connection" : "Activity"}
            </b>
            {node ? (["configuration", "input", "map_test", "output", "advanced", "errors", "documentation"] as const).filter((tab) => tab !== "map_test" || ["mapper", "transform", "ai_transform", "dataweave"].includes(node.type)).map(
              (tab) => (
                <button
                  key={tab}
                  className={activeTab === tab ? "active" : ""}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === "configuration" ? "Configuration" : tab === "map_test" ? "Map & Test" : tab[0].toUpperCase() + tab.slice(1)}
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
              customFunctions={project.custom_functions || []}
              updateCustomFunctions={(customFunctions: any[]) => setProject((current) => ({ ...current, custom_functions: customFunctions }))}
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
              handleExceptions={(types: string[]) => createExceptionHandlers(node.id, types)}
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
      <aside className={`monitor monitor-${monitorMode}`}>
        <div className="pane-title"><span>EXECUTION / DEBUG</span><span className="monitor-actions">
          <button title="Load saved project logs" onClick={loadSystemLogs}><HardDrive/></button>
          <button title="Download saved project logs" onClick={downloadSystemLogs}><Download/></button>
          <button title={monitorMode === "expanded" ? "Restore execution panel" : "Expand execution panel"} onClick={() => setMonitorMode((mode) => mode === "expanded" ? "normal" : "expanded")}><Maximize2/></button>
          <button title={monitorMode === "fullscreen" ? "Exit full screen" : "Open execution panel full screen"} onClick={() => setMonitorMode((mode) => mode === "fullscreen" ? "normal" : "fullscreen")}>{monitorMode === "fullscreen" ? <Minimize2/> : <Square/>}</button>
        </span></div>
        <div className="run-state">
          <span />{" "}
          {debugState
            ? `${debugState.status} · stack ${debugState.callStack?.length || 0}`
            : `${runtimeState?.status || "Runtime"} · ${project.active_environment}`}
        </div>
        {systemLogInfo && <div className="system-log-info"><b>SYSTEM LOG · {String(systemLogInfo.environment || project.active_environment).toUpperCase()}</b><span title={systemLogInfo.path}>{systemLogInfo.path}</span><small>{systemLogInfo.configuredDirectory ? "Configured by runtime.logDirectory" : "Default Studio data directory"} · {(Number(systemLogInfo.maxBytes || 0) / 1024 / 1024).toFixed(0)} MB · {systemLogInfo.backupCount} rolling archives</small></div>}
        {runtimeState?.lastExecution && <section className="runtime-job-summary">
          <header><b>LAST EXECUTION</b><button title="Copy correlation ID" onClick={() => navigator.clipboard.writeText(runtimeState.lastExecution.correlationId)}><ClipboardCopy/></button></header>
          <dl><div><dt>Correlation ID</dt><dd>{runtimeState.lastExecution.correlationId}</dd></div><div><dt>Started</dt><dd>{runtimeState.lastExecution.startedAt || "—"}</dd></div><div><dt>Ended</dt><dd>{runtimeState.lastExecution.endedAt || "—"}</dd></div><div><dt>Duration</dt><dd>{Number(runtimeState.lastExecution.durationMs || 0).toFixed(1)} ms</dd></div></dl>
        </section>}
        {!!endpoints.length && <section className="runtime-endpoints">
          <strong>{endpoints.some((endpoint: any) => endpoint.kind === "subscription") ? "LIVE EVENT RECEIVERS" : "LIVE ENDPOINTS"}</strong>
          {endpoints.map((endpoint: any) => <article key={endpoint.activityId}>
            <span>{endpoint.kind === "subscription" ? `${String(endpoint.status || "ready").toUpperCase()} · ${endpoint.name}` : `${endpoint.methods?.join(", ")} · ${endpoint.name}`}</span>
            <code>{endpoint.url}</code>
            {endpoint.kind !== "subscription" && <button title="Copy endpoint URL" onClick={() => navigator.clipboard.writeText(endpoint.url)}><ClipboardCopy/> Copy</button>}
            {endpoint.kind === "subscription" && <small>Waiting continuously for events on {endpoint.destination}</small>}
            {endpoint.configuredUrl && endpoint.configuredUrl !== endpoint.url && <small>Packaged deployment: {endpoint.configuredUrl}</small>}
          </article>)}
        </section>}
        {(() => {
          const visible = Object.values(executionOutputs).filter((record: any) => !["start", "end", "log"].includes(record.type));
          return !!visible.length && <details className="runtime-outputs" open>
          <summary>EXECUTED PATH OUTPUTS <b>{visible.length}</b></summary>
          {visible.map((record: any) => <details key={record.activityId}>
            <summary><span>{record.name}</span><small>{record.type}</small></summary>
            <pre>{formatRuntimeOutput(record)}</pre>
          </details>)}
        </details>})()}
        {logs.map((l, i) => (
          <div className={`log ${(l.level || "info").toLowerCase()}`} key={i}>
            <small>{l.time ? new Date(l.time).toLocaleTimeString() : ""} {l.level}{l.correlationId ? ` · ${l.correlationId}` : ""}</small>
            <p>{l.message}</p>
            {l.payload !== undefined && l.payload !== "" && l.payload !== null && <pre>{JSON.stringify(l.payload, null, 2)}</pre>}
          </div>
        ))}
      </aside>
      <footer className="studio-status-bar">
        <span className="status-product"><Workflow/> Integration Fabric Studio</span>
        <span className="status-context">{project.name} · {task.name}</span>
        <span className="status-spacer"/>
        <span className="status-environment">{project.active_environment.toUpperCase()}</span>
        <span className={visibleWorkStatus ? "status-progress working" : "status-progress ready"}>{visibleWorkStatus ? <LoaderCircle/> : <CheckCircle2/>}<b>{visibleWorkStatus || "Ready"}</b></span>
      </footer>
      {visibleWorkStatus && <div className="studio-progress-toast" role="status" aria-live="polite"><LoaderCircle/><span><b>Studio is working</b><small>{visibleWorkStatus}</small></span></div>}
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
          actions={{
            newProject, importProject: importFromFileSystem, exportProject, save, refresh: explorerRefresh,
            rename: explorerRename, copy: explorerCopy, paste: explorerPaste, remove: explorerRemove,
            run: (id?: string) => run(id), debug: (id?: string) => debug(id), validate: (id?: string) => { const target = id ? project.tasks.find((item) => item.id === id) : null; if (!target) { runValidation("project"); return; } const issues = validateTaskDefinition(project, target); setValidation({ title: `Validate Task · ${target.name}`, issues }); selectTask(target.id); setLogs([{ level: issues.some((item) => item.severity === "error") ? "ERROR" : issues.length ? "WARN" : "INFO", message: issues.length ? `${target.name}: ${issues.length} validation finding${issues.length === 1 ? "" : "s"}.` : `${target.name}: validation successful.` }]); },
            properties: (type: string, id?: string) => { if (type === "application") setRenameOpen(true); else if (type === "task" && id) selectTask(id); else if (type === "resource" && id) setEditingConnection(project.resources.find((item) => item.id === id) || null); else if (type === "schema" && id) setSchemaEditor(project.schemas.find((item) => item.id === id) || null); else if (type === "property" && id) setPropertyEditor(id); else if (type === "packaging") setPackageOpen(true); },
            newSchema: () => setSchemaEditor("new"), newEnvironment: () => { const name = prompt("New environment name")?.trim().toLowerCase(); if (name && !project.properties[name]) setProject((current) => ({ ...current, properties: { ...current.properties, [name]: newEnvironmentProperties() } })); }, package: () => setPackageOpen(true),
          }}
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
                    ? "Scheduler"
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
                              : event === "amqp"
                                ? "receive"
                              : event === "sap"
                                ? "idoc_listener"
                                : event === "timer"
                                  ? "schedule"
                                  : "listen",
                  resourceId:
                    ["sap", "amqp"].includes(event)
                      ? project.resources.find((r) => r.type === event)?.id || ""
                      : undefined,
                  path: "/events",
                  ...(event === "timer" ? { scheduleMode: "dateTime", scheduledDateTime: "", cronExpression: "0 * * * *", timezone: "local", runOnceOnLocalStart: true } : {}),
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
      {editingConnection && (
        <SharedConnectionDialog
          type={editingConnection.type}
          initial={editingConnection}
          properties={project.properties[project.active_environment] || []}
          onClose={() => setEditingConnection(null)}
          onCreate={(updated: Resource) => {
            setProject((current) => ({ ...current, resources: current.resources.map((item) => item.id === editingConnection.id ? updated : item) }));
            setSelectedResource(null);
            setEditingConnection(null);
          }}
        />
      )}
      {schemaEditor && (
        <SchemaStudio
          schema={schemaEditor === "new" ? undefined : schemaEditor}
          initialTab={schemaEditor === "new" ? "design" : "source"}
          onClose={() => setSchemaEditor(null)}
          onSave={(s) => {
            setProject((p) => ({
              ...p,
              schemas: [...p.schemas.filter((x) => x.id !== s.id), s],
            }));
            setSchemaEditor(null);
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
      {packageOpen && <PackageDialog packaging={project.packaging} environments={Object.keys(project.properties)} tasks={project.tasks} onClose={() => setPackageOpen(false)} onPackage={buildDeploymentPackage}/>}
      {sampleGalleryOpen && <SampleGallery
        onClose={() => setSampleGalleryOpen(false)}
        onImport={async (file) => { const imported = await importProject(file); if (imported) setSampleGalleryOpen(false); }}
      />}
      {aiBuilderOpen && <AIBuilderDialog currentTask={task} onClose={() => setAiBuilderOpen(false)} onApply={(proposal: any) => {
        const generated = proposal.project, scope = proposal.scope;
        if (scope === "task") {
          const generatedTask = generated.tasks[0];
          setProject((current) => ({ ...current, tasks: current.tasks.map((item) => item.id === current.active_task_id ? { ...generatedTask, id: item.id, name: generatedTask.name || item.name, kind: item.kind } : item), resources: [...current.resources, ...(generated.resources || []).filter((resource: Resource) => !current.resources.some((existing) => existing.type === resource.type))] }));
        } else {
          const tasks = generated.tasks || [];
          setProject((current) => ({ ...current, name: generated.name || current.name, description: generated.description || current.description, tasks, active_task_id: tasks[0]?.id || current.active_task_id, resources: generated.resources || [], schemas: generated.schemas || [], packaging: { ...current.packaging, ...(generated.packaging || {}) } }));
        }
        setSelected(""); setSelectedIds([]); setSelectedEdge(null); setAiBuilderOpen(false); setLogs([{ level: "INFO", message: `Applied ${proposal.provider} AI design proposal. Validate the ${scope} before running.` }]);
      }}/>} 
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
function AIBuilderDialog({ currentTask, onClose, onApply }: any) {
  const [requirement, setRequirement] = useState(""), [scope, setScope] = useState<"task" | "project">("task"), [proposal, setProposal] = useState<any>(null), [status, setStatus] = useState<any>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { fetch("/api/ai/status").then((response) => response.json()).then(setStatus).catch(() => setStatus({ provider: "unavailable" })); }, []);
  const generate = async () => {
    setBusy(true); setError(""); setProposal(null);
    try { const response = await fetch("/api/ai/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ requirement, scope, current_task: currentTask }) }), output = await response.json(); if (!response.ok) throw new Error(output.detail || "AI design generation failed"); setProposal(output); }
    catch (failure: any) { setError(failure.message || "AI design generation failed"); }
    finally { setBusy(false); }
  };
  const taskCount = proposal?.project?.tasks?.length || 0, activityCount = proposal?.project?.tasks?.reduce((total: number, task: any) => total + task.activities.length, 0) || 0;
  return <div className="modal-backdrop"><div className="runtime-modal ai-builder-dialog"><header><span><WandSparkles/><span><b>AI Integration Builder</b><small>Natural language to editable middleware design</small></span></span><button aria-label="Close AI builder" onClick={onClose}>×</button></header><main><section className="ai-requirement"><div className="ai-scope"><button className={scope === "task" ? "active" : ""} onClick={() => setScope("task")}><Activity/> Current Task</button><button className={scope === "project" ? "active" : ""} onClick={() => setScope("project")}><Package/> Complete Project</button><small>{status?.provider === "openai" ? `OpenAI · ${status.model}` : "Local blueprint mode · set OPENAI_API_KEY for model-assisted generation"}</small></div><label>Describe the integration requirement<textarea autoFocus value={requirement} onChange={(event) => setRequirement(event.target.value)} placeholder="Receive a REST order, validate and transform JSON, insert it with JDBC, catch errors, log them, and return an HTTP response…"/></label><button className="generate-ai-design" disabled={busy || requirement.trim().length < 10} onClick={generate}><WandSparkles/> {busy ? "Designing…" : "Generate design preview"}</button>{error && <p className="ai-builder-error">{error}</p>}</section><section className="ai-preview">{proposal ? <><header><span><b>DESIGN PREVIEW</b><small>{proposal.summary}</small></span><span>{taskCount} tasks · {activityCount} activities · {proposal.project.resources?.length || 0} connections</span></header>{proposal.project.tasks.map((task: any) => <article key={task.id}><b>{task.name}</b><small>{task.kind}</small><div>{task.activities.map((activity: any) => <span key={activity.id}>{activity.name}</span>)}</div></article>)}<details><summary>Review generated JSON</summary><pre>{JSON.stringify(proposal.project, null, 2)}</pre></details></> : <div className="ai-preview-empty"><WandSparkles/><b>Your design preview appears here</b><p>Nothing is changed until you inspect the proposal and click Apply.</p></div>}</section></main><footer><span>Credentials are never stored in the generated project.</span><button onClick={onClose}>Cancel</button><button className="primary" disabled={!proposal} onClick={() => onApply(proposal)}>Apply generated {scope}</button></footer></div></div>;
}
const deploymentArtifactChoices: Record<string, { key: string; label: string; detail: string }[]> = {
  cloud: [
    { key: "dockerfile", label: "Dockerfile", detail: "OCI runtime image build" },
    { key: "configmap", label: "ConfigMap YAML", detail: "Selected environment values" },
    { key: "secret", label: "Secret YAML", detail: "Empty credential placeholders" },
    { key: "deployment", label: "Deployment YAML", detail: "Pods, probes, resources and replicas" },
    { key: "service", label: "Service YAML", detail: "Expose the configured listener port" },
    { key: "hpa", label: "Horizontal scaling YAML", detail: "CPU-based autoscaling" },
    { key: "package", label: "Kustomize package", detail: "Kustomization and package metadata" },
  ],
  "on-prem": [
    { key: "application", label: "Application descriptor", detail: "Administrator deployment configuration" },
    { key: "environment", label: "Environment properties", detail: "Non-secret selected environment values" },
    { key: "administrator", label: "Administrator deploy script", detail: "Deploy, scale and optional startup" },
    { key: "systemd", label: "systemd service", detail: "Linux service installation unit" },
    { key: "install", label: "Install script", detail: "Create directories and copy runtime files" },
    { key: "readme", label: "Deployment guide", detail: "Generated on-premises deployment steps" },
  ],
};
function PackageDialog({ packaging, environments, tasks, onClose, onPackage }: any) {
  const initialTarget = packaging?.target || "on-prem";
  const starterTasks = (tasks || []).filter((task: Task) => task.kind === "starter");
  const initialChoices = deploymentArtifactChoices[initialTarget] || deploymentArtifactChoices["on-prem"];
  const savedArtifacts = Array.isArray(packaging?.artifacts) ? packaging.artifacts.filter((key: string) => initialChoices.some((choice) => choice.key === key)) : [];
  const [draft, setDraft] = useState<any>({
    artifact_name: packaging?.artifact_name || "integration-application",
    version: packaging?.version || "1.0.0",
    target: initialTarget,
    starterTaskIds: Array.isArray(packaging?.starterTaskIds) && packaging.starterTaskIds.length ? packaging.starterTaskIds.filter((id: string) => starterTasks.some((task: Task) => task.id === id)) : starterTasks.map((task: Task) => task.id),
    environments: Array.isArray(packaging?.environments) && packaging.environments.length ? packaging.environments.filter((name: string) => environments.includes(name)) : [packaging?.environment || "production"].filter((name: string) => environments.includes(name)),
    format: packaging?.format || "ifpkg",
    artifacts: savedArtifacts.length ? savedArtifacts : initialChoices.map((choice) => choice.key),
    image: packaging?.image || "",
    replicas: packaging?.replicas || 1,
    minimumReplicas: packaging?.minimumReplicas || 1,
    maximumReplicas: packaging?.maximumReplicas || 3,
    cpuTargetPercent: packaging?.cpuTargetPercent || 70,
    serviceType: packaging?.serviceType || "ClusterIP",
    containerPort: packaging?.containerPort || 8787,
    instances: packaging?.instances || 1,
    startOnBoot: packaging?.startOnBoot || false,
    gracefulShutdownSeconds: packaging?.gracefulShutdownSeconds || 60,
    installRoot: packaging?.installRoot || "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const update = (key: string, value: any) => setDraft((current: any) => ({ ...current, [key]: value }));
  const chooseTarget = (target: string) => setDraft((current: any) => ({ ...current, target, artifacts: deploymentArtifactChoices[target].map((choice) => choice.key) }));
  const toggleArtifact = (key: string) => setDraft((current: any) => ({ ...current, artifacts: current.artifacts.includes(key) ? current.artifacts.filter((value: string) => value !== key) : [...current.artifacts, key] }));
  const toggleEnvironment = (name: string) => setDraft((current: any) => ({ ...current, environments: current.environments.includes(name) ? current.environments.filter((value: string) => value !== name) : [...current.environments, name] }));
  const toggleStarter = (id: string) => setDraft((current: any) => ({ ...current, starterTaskIds: current.starterTaskIds.includes(id) ? current.starterTaskIds.filter((value: string) => value !== id) : [...current.starterTaskIds, id] }));
  const extension = draft.format === "ifpkg" ? "ifpkg" : draft.format;
  const build = async () => {
    setError("");
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(draft.artifact_name.trim())) { setError("Artifact name may contain letters, numbers, dots, dashes, and underscores."); return; }
    if (!/^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$/.test(draft.version.trim())) { setError("Use a semantic version such as 1.0.0 or 1.0.0-beta.1."); return; }
    if (!draft.artifacts.length) { setError("Select at least one deployment artifact."); return; }
    if (!draft.environments.length) { setError("Select at least one environment profile."); return; }
    if (!draft.starterTaskIds.length) { setError("Select at least one Starter Task to package."); return; }
    setBusy(true);
    try { await onPackage(draft); }
    catch (failure: any) { setError(failure?.message || "Package generation failed."); }
    finally { setBusy(false); }
  };
  return <div className="modal-backdrop"><div className="package-modal">
    <header><div><Package/><b>Build deployment package</b><small>Choose how this integration will run</small></div><button onClick={onClose}>×</button></header>
    <main>
      <label>Artifact name<input value={draft.artifact_name} onChange={(event) => update("artifact_name", event.target.value)}/></label>
      <label>Version<input value={draft.version} onChange={(event) => update("version", event.target.value)}/></label>
      <div className="package-targets">
        <button className={draft.target === "on-prem" ? "selected" : ""} onClick={() => chooseTarget("on-prem")}><HardDrive/><span><b>On-premises Linux</b><small>Administrator and runtime-agent deployment without containers</small></span></button>
        <button className={draft.target === "cloud" ? "selected" : ""} onClick={() => chooseTarget("cloud")}><Cloud/><span><b>Cloud / Kubernetes</b><small>OCI image inputs and Kubernetes deployment descriptors</small></span></button>
      </div>
      <section className="package-starters"><header><span><b>TASK STARTERS</b><small>Select the deployable entry points. Called Sub Tasks are discovered recursively and included automatically; unrelated Sub Tasks are excluded.</small></span><button type="button" onClick={() => update("starterTaskIds", starterTasks.map((task: Task) => task.id))}>Select all</button></header><div>{starterTasks.map((task: Task) => <label key={task.id} className={draft.starterTaskIds.includes(task.id) ? "selected" : ""}><input type="checkbox" checked={draft.starterTaskIds.includes(task.id)} onChange={() => toggleStarter(task.id)}/><span><b>{task.name}</b><small>{task.description || "Starter Task"}</small></span></label>)}</div>{!starterTasks.length && <p>No Starter Tasks are available. Create a Starter Task before packaging.</p>}</section>
      <section className="package-environments"><header><span><b>ENVIRONMENT PROFILES</b><small>The application is common; configuration and secret files are generated separately for every selected profile.</small></span><button type="button" onClick={() => update("environments", environments)}>Select all</button></header><div>{environments.map((name: string) => <label key={name} className={draft.environments.includes(name) ? "selected" : ""}><input type="checkbox" checked={draft.environments.includes(name)} onChange={() => toggleEnvironment(name)}/><span><b>{name}</b><small>{draft.environments.includes(name) ? "Included" : "Not packaged"}</small></span></label>)}</div></section>
      <label>Archive format<select value={draft.format} onChange={(event) => update("format", event.target.value)}><option value="ifpkg">Integration package (.ifpkg)</option><option value="tar.gz">Compressed TAR (.tar.gz)</option><option value="ear">EAR-compatible ZIP (.ear)</option></select></label>
      <section className="package-artifacts">
        <header><span><b>SELECT DEPLOYMENT FILES</b><small>Core application, tasks, resources, schemas, and secret requirements are always included.</small></span><button type="button" onClick={() => update("artifacts", deploymentArtifactChoices[draft.target].map((choice) => choice.key))}>Select all</button></header>
        <div>{deploymentArtifactChoices[draft.target].map((choice) => <label key={choice.key} className={draft.artifacts.includes(choice.key) ? "selected" : ""}><input type="checkbox" checked={draft.artifacts.includes(choice.key)} onChange={() => toggleArtifact(choice.key)}/><span><b>{choice.label}</b><small>{choice.detail}</small></span></label>)}</div>
      </section>
      {draft.target === "cloud" ? <section className="package-runtime-options">
        <h3>Cloud runtime configuration</h3>
        <label>Container image<input value={draft.image} onChange={(event) => update("image", event.target.value)} placeholder={`integration-fabric/${draft.artifact_name}:${draft.version}`}/></label>
        <label>Container/listener port<input type="number" min="1" max="65535" value={draft.containerPort} onChange={(event) => update("containerPort", Number(event.target.value))}/></label>
        <label>Initial replicas<input type="number" min="1" value={draft.replicas} onChange={(event) => update("replicas", Number(event.target.value))}/></label>
        <label>Minimum replicas<input type="number" min="1" value={draft.minimumReplicas} onChange={(event) => update("minimumReplicas", Number(event.target.value))}/></label>
        <label>Maximum replicas<input type="number" min="1" value={draft.maximumReplicas} onChange={(event) => update("maximumReplicas", Number(event.target.value))}/></label>
        <label>CPU target %<input type="number" min="1" max="100" value={draft.cpuTargetPercent} onChange={(event) => update("cpuTargetPercent", Number(event.target.value))}/></label>
        <label>Service type<select value={draft.serviceType} onChange={(event) => update("serviceType", event.target.value)}><option>ClusterIP</option><option>NodePort</option><option>LoadBalancer</option></select></label>
      </section> : <section className="package-runtime-options">
        <h3>On-premises runtime configuration</h3>
        <label>Runtime instances<input type="number" min="1" value={draft.instances} onChange={(event) => update("instances", Number(event.target.value))}/></label>
        <label>Graceful shutdown (seconds)<input type="number" min="1" value={draft.gracefulShutdownSeconds} onChange={(event) => update("gracefulShutdownSeconds", Number(event.target.value))}/></label>
        <label>Install root<input value={draft.installRoot} onChange={(event) => update("installRoot", event.target.value)} placeholder={`/opt/integration-fabric/apps/${draft.artifact_name}`}/></label>
        <label className="package-toggle"><input type="checkbox" checked={!!draft.startOnBoot} onChange={(event) => update("startOnBoot", event.target.checked)}/> Start application after Administrator deployment</label>
      </section>}
      <div className="package-preview"><Package/><span><b>{draft.artifact_name}-{draft.version}-{draft.target}.{extension}</b><small>{draft.starterTaskIds.length} starter{draft.starterTaskIds.length === 1 ? "" : "s"} · {draft.environments.length} environment profile{draft.environments.length === 1 ? "" : "s"} · related Sub Tasks resolved automatically</small></span></div>
      <p className="package-security"><ShieldCheck/> Password values are removed. The target Administrator or Kubernetes secret provider supplies credentials during deployment.</p>
      {error && <p className="package-error"><AlertTriangle/>{error}</p>}
    </main>
    <footer><button disabled={busy} onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !draft.artifact_name.trim() || !draft.version.trim()} onClick={build}>{busy ? "Validating and building…" : "Validate and package"}</button></footer>
  </div></div>;
}
function StudioRibbon(props: any) {
  const command = (label: string, Icon: any, action: () => void, disabled = false, emphasis = false) =>
    <button type="button" className={emphasis ? "emphasis" : ""} disabled={disabled} onClick={(event) => { event.stopPropagation(); action(); }} title={label}><Icon/><span>{label}</span></button>;
  return <section className="studio-ribbon" aria-label="Studio ribbon">
    <div className="ribbon-group"><b>PROJECT</b><div>{command("New", FilePlus2, props.newProject)}{command("Open", FolderOpen, props.openProject)}{command("Import", Upload, props.importProject)}{command("Samples", BookOpen, props.sampleProjects)}{command("Save", Save, props.save)}{command("Export", Download, props.exportProject)}{command("Package", Package, props.packageProject)}{command("Close", Square, props.closeProject)}</div></div>
    <div className="ribbon-group"><b>EXECUTE & VALIDATE</b><div>{command("AI Build", WandSparkles, props.aiBuild)}{command("AI Catch", WandSparkles, props.catchAI)}{command("Run", CirclePlay, props.run, props.executionActive)}{command("Debug", Bug, props.debug, props.executionActive)}{command("Stop", Square, props.stop, !props.executionActive, props.executionActive)}{command("Validate Task", ShieldCheck, props.validateTask)}{command("Validate Project", CheckCircle2, props.validateProject)}</div></div>
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
  sampleProjects,
  catchAI,
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
      <button onClick={go(sampleProjects)}>
        <BookOpen />
        <span>
          Sample Projects<small>Open installed editable integration examples</small>
        </span>
      </button>
      <button onClick={go(catchAI)}>
        <WandSparkles />
        <span>
          AI Catch Blocks<small>Analyze task exceptions and generate mapped handlers</small>
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
type SampleProject = { id: string; name: string; category: string; description: string; activities: string[]; file: string; ready: boolean };
function SampleGallery({ onClose, onImport }: { onClose: () => void; onImport: (file: File) => Promise<any> }) {
  const [samples, setSamples] = useState<SampleProject[]>([]), [search, setSearch] = useState(""), [loading, setLoading] = useState(true), [opening, setOpening] = useState(""), [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    fetch(`/samples/catalog.json?v=${encodeURIComponent(String(import.meta.env.VITE_APP_VERSION || "current"))}`, { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error("The installed sample catalog is unavailable.");
      return response.json();
    }).then((items) => active && setSamples(items)).catch((reason) => active && setError(reason.message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);
  const visible = samples.filter((sample) => `${sample.name} ${sample.category} ${sample.description} ${sample.activities.join(" ")}`.toLowerCase().includes(search.trim().toLowerCase()));
  const open = async (sample: SampleProject) => {
    setOpening(sample.id); setError("");
    try {
      const response = await fetch(sample.file, { cache: "no-store" });
      if (!response.ok) throw new Error(`Unable to load installed sample ${sample.name}.`);
      await onImport(new File([await response.blob()], `${sample.id}.json`, { type: "application/json" }));
    } catch (reason: any) { setError(reason?.message || "Unable to open sample project."); }
    finally { setOpening(""); }
  };
  return <div className="modal-backdrop sample-gallery-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="sample-gallery">
    <div className="sample-gallery-header"><span><BookOpen/><span><b>Installed sample projects</b><small>Learn with editable projects bundled with Integration Fabric Studio</small></span></span><button aria-label="Close samples" onClick={onClose}>×</button></div>
    <div className="sample-gallery-search"><Search/><input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search samples, activities, or technologies…"/></div>
    <div className="sample-gallery-content">{loading ? <div className="sample-gallery-empty"><LoaderCircle/> Loading installed samples…</div> : visible.map((sample) => <article key={sample.id}><div className="sample-card-heading"><span><Package/></span><div><em>{sample.category}</em><h3>{sample.name}</h3></div><i className={sample.ready ? "ready" : "setup"}>{sample.ready ? "READY TO RUN" : "CONNECTION SETUP"}</i></div><p>{sample.description}</p><div className="sample-activities">{sample.activities.map((activity) => <code key={activity}>{activity}</code>)}</div><button disabled={!!opening} onClick={() => void open(sample)}>{opening === sample.id ? <><LoaderCircle/> Opening…</> : <><FolderOpen/> Open editable sample</>}</button></article>)}{!loading && !visible.length && <div className="sample-gallery-empty">No installed samples match your search.</div>}</div>
    <div className="sample-gallery-footer"><span>Samples are copied into project storage when opened. Connection samples contain placeholders and never include credentials.</span><button onClick={onClose}>Close</button></div>{error && <p className="sample-gallery-error"><AlertTriangle/>{error}</p>}
  </div></div>;
}
function IntegrationBrandArtwork({ className = "" }: { className?: string }) {
  return <div className={`integration-brand-art ${className}`.trim()} aria-label="Integration Studio">
    <img src="/branding/integration-studio-art.png" alt="Integration Studio" />
    <span className="integration-brand-particle" aria-hidden="true" />
  </div>;
}
function ProjectWelcome({ createProject, importProject, importFromFileSystem, theme, setTheme }: any) {
  const input = useRef<HTMLInputElement>(null), [createOpen, setCreateOpen] = useState(false), [samplesOpen, setSamplesOpen] = useState(false), [name, setName] = useState("New Integration Application"), [importing, setImporting] = useState(false);
  const beginImport = async () => {
    if (!window.fabricDesktop && !(window as any).showOpenFilePicker) { input.current?.click(); return; }
    setImporting(true);
    try { await importFromFileSystem(); } finally { setImporting(false); }
  };
  const importFile = async (file?: File) => {
    if (!file) return;
    setImporting(true);
    try { await importProject(file); } finally { setImporting(false); if (input.current) input.current.value = ""; }
  };
  const submitCreate = (event: React.FormEvent) => {
    event.preventDefault();
    const value = name.trim();
    if (value) createProject(value);
  };
  return <div className="project-home fabric-launch-home">
     <header><IntegrationBrandArtwork className="home-brand-art"/><ThemePicker theme={theme} setTheme={setTheme}/></header>
     <main>
      <section className="fabric-live-map" aria-label="Animated system integration fabric">
        <div className="home-grid"/><div className="home-aurora one"/><div className="home-aurora two"/>
        <svg className="fabric-routes" viewBox="0 0 1000 620" preserveAspectRatio="none" aria-hidden="true">
          <defs><linearGradient id="home-route" x1="0" x2="1"><stop offset="0" stopColor="#38d8ff"/><stop offset=".5" stopColor="#7b75ff"/><stop offset="1" stopColor="#43e6a8"/></linearGradient><filter id="home-glow-filter"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
          <path id="route-api" d="M300 101 C345 110 360 225 414 276"/>
          <path id="route-sap" d="M300 288.4 C340 288 370 300 410 304"/>
          <path id="route-manhattan" d="M300 505.1 C355 495 370 395 430 356"/>
          <path id="route-cloud" d="M700 101 C655 110 640 225 586 276"/>
          <path id="route-kafka" d="M700 288.4 C660 288 630 300 590 304"/>
          <path id="route-pubsub" d="M700 505.1 C645 495 630 395 570 356"/>
          <path id="route-website" d="M500 62.5 C500 130 490 190 500 222"/>
          <path id="route-rabbit" d="M500 554.5 C500 485 510 430 500 398"/>
          <path className="motion-only" id="route-api-out" d="M414 276 C360 225 345 110 300 101"/>
          <path className="motion-only" id="route-sap-out" d="M410 304 C370 300 340 288 300 288.4"/>
          <path className="motion-only" id="route-manhattan-out" d="M430 356 C370 395 355 495 300 505.1"/>
          <path className="motion-only" id="route-cloud-out" d="M586 276 C640 225 655 110 700 101"/>
          <path className="motion-only" id="route-kafka-out" d="M590 304 C630 300 660 288 700 288.4"/>
          <path className="motion-only" id="route-pubsub-out" d="M570 356 C630 395 645 495 700 505.1"/>
          <path className="motion-only" id="route-website-out" d="M500 222 C490 190 500 130 500 62.5"/>
          <path className="motion-only" id="route-rabbit-out" d="M500 398 C510 430 500 485 500 554.5"/>
          {[
            { route: "route-api", direction: "in", duration: 3.7, delay: -1.2 },
            { route: "route-sap", direction: "out", duration: 4.8, delay: -3.1 },
            { route: "route-manhattan", direction: "in", duration: 5.4, delay: -.6 },
            { route: "route-cloud", direction: "out", duration: 3.9, delay: -2.4 },
            { route: "route-kafka", direction: "in", duration: 3.2, delay: -1.7 },
            { route: "route-kafka", direction: "out", duration: 5.8, delay: -4.6 },
            { route: "route-pubsub", direction: "out", duration: 4.4, delay: -.9 },
            { route: "route-website", direction: "in", duration: 4.6, delay: -2.2 },
            { route: "route-rabbit", direction: "in", duration: 5.1, delay: -3.8 },
            { route: "route-api", direction: "out", duration: 6.2, delay: -4.9 },
            { route: "route-manhattan", direction: "out", duration: 6.7, delay: -2.8 },
            { route: "route-cloud", direction: "in", duration: 5.9, delay: -5.2 },
            { route: "route-pubsub", direction: "in", duration: 6.4, delay: -3.6 },
            { route: "route-website", direction: "out", duration: 5.3, delay: -4.1 },
          ].map((packet, index) => <circle key={`${packet.route}-${packet.direction}-${index}`} r={index % 3 === 0 ? "5.5" : "4.2"} className={`flow-packet ${packet.direction}`}><animate attributeName="opacity" values="0;.95;.95;0" keyTimes="0;.12;.86;1" dur={`${packet.duration}s`} begin={`${packet.delay}s`} repeatCount="indefinite"/><animateMotion dur={`${packet.duration}s`} repeatCount="indefinite" begin={`${packet.delay}s`} calcMode="linear"><mpath href={`#${packet.route}${packet.direction === "out" ? "-out" : ""}`}/></animateMotion></circle>)}
        </svg>
        <div className="system-node edge website"><Monitor/><span><b>Website</b><small>Web · Portal · Commerce</small></span></div>
        <div className="system-node source api"><Globe/><span><b>API</b><small>HTTP · REST · SOAP</small></span></div>
        <div className="system-node source sap-system"><img className="vendor-logo sap-logo" src="/vendor-logos/sap.svg" alt=""/><span><b>SAP</b><small>ECC · S/4HANA · IDoc</small></span></div>
        <div className="system-node source manhattan"><img className="vendor-logo manhattan-logo" src="/vendor-logos/manhattan-associates.svg" alt=""/><span><b>Manhattan</b><small>WMS · Order management</small></span></div>
        <div className="system-node target cloud"><Cloud/><span><b>Cloud</b><small>Services · Applications</small></span></div>
        <div className="system-node target kafka-system"><img className="vendor-logo kafka-logo" src="/vendor-logos/apache-kafka.svg" alt=""/><span><b>Kafka</b><small>Topics · Event streams</small></span></div>
        <div className="system-node target pubsub-system"><img className="vendor-logo pubsub-logo" src="/vendor-logos/gcp-pubsub.png" alt=""/><span><b>GCP Pub/Sub</b><small>Topics · Subscriptions</small></span></div>
        <div className="system-node edge rabbitmq"><img className="vendor-logo rabbitmq-logo" src="/vendor-logos/rabbitmq.svg" alt=""/><span><b>RabbitMQ</b><small>Queues · Exchanges</small></span></div>
        <div className="fabric-core"><i/><span><Workflow/><b>INTEGRATION</b><strong>FABRIC</strong><small>DESIGN · CONNECT · RUN</small></span></div>
        <div className="live-indicator"><i/> LIVE INTEGRATION FABRIC</div>
      </section>
      <section className="launch-actions">
        <span className="launch-eyebrow">BUILD THE CONNECTED ENTERPRISE</span>
        <h1>Mediation,<br /><span>Transformation &amp;</span><br />Deliver Integrations.</h1>
        <div className="launch-buttons">
          <button className="create-project" onClick={() => setCreateOpen(true)}><span><FilePlus2/></span><b>Create new project<small>Start with the standard project structure</small></b><ChevronRight/></button>
          <button className="import-project" onClick={beginImport} disabled={importing}><span><Upload/></span><b>{importing ? "Importing project…" : "Import existing project"}<small>.ifproject, project folder, ZIP or compatible JSON</small></b><ChevronRight/></button>
          <button className="sample-projects" onClick={() => setSamplesOpen(true)}><span><BookOpen/></span><b>Explore sample projects<small>Editable, installed examples for mapping, APIs, data, JDBC, and messaging</small></b><ChevronRight/></button>
          <button className="installed-guide" onClick={() => window.open("/help/activity-reference.html", "_blank", "noopener")}><span><BookOpen/></span><b>Open installed activity guide<small>Offline configuration, mapping, runtime, and error reference</small></b><ChevronRight/></button>
        </div>
      </section>
    </main>
    <footer><span><ShieldCheck/> Enterprise integration development</span><span>DESIGN TIME <i/> RUNTIME <i/> DEPLOYMENT</span></footer>
    <input ref={input} hidden type="file" accept=".ifproject,.zip,.json" onChange={(event) => void importFile(event.target.files?.[0])}/>
    {samplesOpen && <SampleGallery
      onClose={() => setSamplesOpen(false)}
      onImport={importProject}
    />}
    {createOpen && <div className="modal-backdrop home-create-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setCreateOpen(false)}><form className="home-create-dialog" onSubmit={submitCreate}><header><span><FilePlus2/><b>Create Integration Fabric project</b></span><button type="button" aria-label="Close create project" onClick={() => setCreateOpen(false)}>×</button></header><main><div className="create-project-mark"><Workflow/><span><b>New application</b><small>A clean integration workspace with enterprise defaults</small></span></div><label>Application name<input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="Customer Order Integration" required/></label><section><b>Project Explorer will include</b><div><span><Workflow/>Tasks</span><span><Cable/>Resources</span><span><Package/>Packaging</span><span><CodeXml/>Schemas</span><span><Braces/>Properties</span></div></section></main><footer><button type="button" onClick={() => setCreateOpen(false)}>Cancel</button><button className="primary" type="submit" disabled={!name.trim()}><FilePlus2/> Create project</button></footer></form></div>}
  </div>;
}
function Context({
  menu,
  addActivity,
  createTask,
  createConnection,
  actions,
  close,
}: any) {
  const connectionChoices: Record<string, { label: string; description: string }> = {
    http: { label: "HTTP Connection", description: "Listener, outbound HTTP and TLS" },
    ftp: { label: "FTP Connection", description: "File transfer over FTP" },
    sftp: { label: "SFTP Connection", description: "Secure SSH file transfer" },
    ems: { label: "EMS Connection", description: "TIBCO EMS queues and topics" },
    jms: { label: "JMS Connection", description: "Provider-neutral JMS queues and topics" },
    kafka: { label: "Kafka Connection", description: "Kafka brokers and security" },
    pubsub: { label: "Pub/Sub Connection", description: "Google Cloud messaging" },
    jdbc: { label: "Database Connection", description: "JDBC databases and pools" },
    snowflake: { label: "Snowflake JDBC Connection", description: "Snowflake authentication, pools and metadata" },
    amqp: { label: "AMQP Connection", description: "RabbitMQ, Qpid, ActiveMQ, AMQ and Azure Service Bus" },
    sap: { label: "SAP ECC Connection", description: "RFC, BAPI and IDoc metadata" },
    sap_tid: { label: "SAP TID Manager", description: "Transactional RFC state" },
  };
  const connectionIcons: Record<string, string> = {
    http: "/activity-icons/http.png", ftp: "/activity-icons/ftp.png", sftp: "/activity-icons/sftp.png",
    ems: "/activity-icons/ems.png", jms: "/activity-icons/jms-connection.svg", kafka: "/vendor-logos/apache-kafka.svg", pubsub: "/vendor-logos/gcp-pubsub.png",
    jdbc: "/activity-icons/JDBC-Query.png", snowflake: "/activity-icons/snowflake.svg", amqp: "/vendor-logos/rabbitmq.svg",
    sap: "/vendor-logos/sap.svg", sap_tid: "/vendor-logos/sap.svg",
  };
  if (menu.type === "canvas")
    return (
      <ActivityPicker
        menu={menu}
        packs={packs}
        addActivity={addActivity}
        close={close}
      />
    );
  const targetFolder = menu.type === "task" ? "tasks" : (menu.type === "resource" || menu.type === "resources-root") ? "resources" : menu.type === "schema" ? "schemas" : menu.type === "property" ? "properties" : menu.type;
  const explorerMenuTop = Math.max(8, Math.min(menu.y, Math.max(8, window.innerHeight - 240)));
  const explorerMenuMaxHeight = Math.max(180, window.innerHeight - explorerMenuTop - 8);
  const act = (callback: () => void) => () => { callback(); close(); };
  const item = (label: string, detail: string, Icon: any, callback: () => void, disabled = false) => <button disabled={disabled} onClick={act(callback)}><Icon/><span><b>{label}</b><small>{detail}</small></span></button>;
  const fileCommands = <div className="explorer-context-commands">
    {item("Copy", "Copy this explorer item", ClipboardCopy, () => actions.copy(menu.type, menu.id), !["task", "resource", "schema", "property"].includes(menu.type))}
    {item("Paste", `Paste into ${targetFolder}`, ClipboardPaste, () => actions.paste(targetFolder), !["tasks", "resources", "resources-root", "schemas", "properties"].includes(targetFolder))}
    {item("Rename", "Change the displayed name", Settings2, () => actions.rename(menu.type, menu.id), !["application", "task", "resource", "schema", "property"].includes(menu.type))}
    {item("Remove", "Remove from this project", Trash2, () => actions.remove(menu.type, menu.id), !["application", "task", "resource", "schema", "property"].includes(menu.type))}
    {item("Refresh", "Reload saved project state", Redo2, actions.refresh)}
    {item("Show Properties", "Open the selected item editor", Settings2, () => actions.properties(menu.type, menu.id))}
    {item("Import", "Import a project from the filesystem", Upload, actions.importProject)}
    {item("Export", "Export a portable project", Download, actions.exportProject)}
    {item("Save", "Save the current project folder", Save, actions.save)}
  </div>;
  return (
    <div
      className={`canvas-menu resource-menu ${menu.type === "resources" ? "connection-create-menu" : ""}`}
      style={{ left: Math.max(8, Math.min(menu.x, window.innerWidth - 340)), top: explorerMenuTop, maxHeight: explorerMenuMaxHeight }}
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
      {menu.type === "application" && <>{item("New Project", "Create another integration application", FilePlus2, actions.newProject)}{item("Run Active Task", "Execute the current task", CirclePlay, () => actions.run())}{item("Debug Active Task", "Start a debug session", Bug, () => actions.debug())}</>}
      {menu.type === "task" && <>{item("Run Task", "Execute this task", CirclePlay, () => actions.run(menu.id))}{item("Debug Task", "Debug this task", Bug, () => actions.debug(menu.id))}{item("Validate Task", "Validate configuration and mappings", ShieldCheck, () => actions.validate(menu.id))}</>}
      {menu.type === "schemas" && item("New XSD Schema", "Open the schema designer", CodeXml, actions.newSchema)}
      {menu.type === "properties" && item("New Environment", "Create another properties environment", Plus, actions.newEnvironment)}
      {menu.type === "packaging" && item("Configure Package", "Open deployment packaging", Package, actions.package)}
      {menu.type === "resources" && (
        <>
          <div className="connection-menu-heading"><Cable/><span><b>Create shared connection</b><small>Choose a reusable connector</small></span></div>
          {(
            [
              "http",
              "ftp",
              "sftp",
              "ems",
              "jms",
              "kafka",
              "pubsub",
              "jdbc",
              "snowflake",
              "amqp",
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
              <span className={`connection-menu-icon connector-${t}`}><img src={connectionIcons[t]} alt="" /></span><span><b>{connectionChoices[t].label}</b><small>{connectionChoices[t].description}</small></span><ChevronRight/>
            </button>
          ))}
        </>
      )}
      {menu.type !== "canvas" && <><div className="explorer-context-separator"/>{fileCommands}</>}
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
                <option value="timer">Scheduler</option>
                <option value="ems">EMS Queue Receiver</option>
                <option value="kafka">Kafka Receive Message</option>
                <option value="pubsub">GCP Pub/Sub Subscriber</option>
                <option value="amqp">AMQP Receive Message</option>
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
    { key: "driver", label: "Database", options: ["sqlite", "postgresql", "mysql", "mariadb", "sqlserver", "oracle", "db2", "snowflake", "databricks"] },
    { key: "connectionMode", label: "Connection runtime", options: ["jdbc", "python"], when: (config: any) => ["sqlserver", "mssql", "oracle"].includes(config.driver) },
    { key: "driverDirectory", label: "JDBC driver JAR directory", placeholder: "Blank uses the Integration Fabric driver directory", when: (config: any) => ["sqlserver", "mssql", "oracle"].includes(config.driver) && config.connectionMode !== "python" },
    { key: "driverClass", label: "JDBC driver class (blank = vendor default)", when: (config: any) => ["sqlserver", "mssql", "oracle"].includes(config.driver) && config.connectionMode !== "python" },
    { key: "url", label: "JDBC URL" }, { key: "host", label: "Host" }, { key: "port", label: "Port" },
    { key: "database", label: "Database name" }, { key: "schema", label: "Schema" },
    { key: "username", label: "Username" }, { key: "password", label: "Password", password: true },
    { key: "odbcDriver", label: "SQL Server ODBC driver (legacy Python mode)", when: (config: any) => ["sqlserver", "mssql"].includes(config.driver) && config.connectionMode === "python" },
    { key: "authentication", label: "SQL Server authentication", options: ["SQL Server Authentication", "Windows Integrated"], when: (config: any) => ["sqlserver", "mssql"].includes(config.driver) },
    { key: "encrypt", label: "Encrypt SQL Server connection", options: ["true", "false"], when: (config: any) => ["sqlserver", "mssql"].includes(config.driver) },
    { key: "trustServerCertificate", label: "Trust SQL Server certificate", options: ["false", "true"], when: (config: any) => ["sqlserver", "mssql"].includes(config.driver) },
    { key: "serviceName", label: "Oracle service name", when: (config: any) => config.driver === "oracle" },
    { key: "sid", label: "Oracle SID (when service name is not used)", when: (config: any) => config.driver === "oracle" },
    { key: "sslCaFile", label: "MySQL/MariaDB CA certificate file", when: (config: any) => ["mysql", "mariadb"].includes(config.driver) },
    { key: "serverHostname", label: "Databricks server hostname", when: (config: any) => config.driver === "databricks" },
    { key: "httpPath", label: "Databricks HTTP path", when: (config: any) => config.driver === "databricks" },
    { key: "authentication", label: "Databricks authentication", options: ["Personal Access Token", "OAuth M2M", "OAuth U2M"], when: (config: any) => config.driver === "databricks" },
    { key: "accessToken", label: "Databricks access token", password: true, when: (config: any) => config.driver === "databricks" && config.authentication === "Personal Access Token" },
    { key: "clientId", label: "Databricks OAuth client ID", when: (config: any) => config.driver === "databricks" && config.authentication === "OAuth M2M" },
    { key: "clientSecret", label: "Databricks OAuth client secret", password: true, when: (config: any) => config.driver === "databricks" && config.authentication === "OAuth M2M" },
    { key: "catalog", label: "Databricks catalog", when: (config: any) => config.driver === "databricks" },
    { key: "useCloudFetch", label: "Databricks CloudFetch", options: ["true", "false"], when: (config: any) => config.driver === "databricks" },
    { key: "timeoutSeconds", label: "Connection timeout (seconds)" },
    { key: "minimumPoolSize", label: "Minimum pool size" }, { key: "maximumPoolSize", label: "Maximum pool size" },
  ],
  snowflake: [
    { key: "mode", label: "Runtime mode", options: ["external", "mock"] },
    { key: "authenticationType", label: "Authentication type", options: ["Username/Password", "Federated Authentication and SSO", "OAuth", "Key Pair Authentication"] },
    { key: "provider", label: "Authentication provider", options: ["Snowflake", "Okta"] },
    { key: "account", label: "Account [account.region.platform]" },
    { key: "username", label: "Snowflake username" }, { key: "password", label: "Snowflake password", password: true, when: (config: any) => config.authenticationType === "Username/Password" },
    { key: "oktaTokenEndpoint", label: "Okta token endpoint", when: (config: any) => config.authenticationType === "OAuth" && config.provider === "Okta" },
    { key: "oktaUsername", label: "Okta username", when: (config: any) => config.authenticationType === "Federated Authentication and SSO" && config.provider === "Okta" },
    { key: "oktaPassword", label: "Okta password", password: true, when: (config: any) => config.authenticationType === "Federated Authentication and SSO" && config.provider === "Okta" },
    { key: "oktaEndpointUrl", label: "Okta endpoint URL", when: (config: any) => config.authenticationType === "Federated Authentication and SSO" && config.provider === "Okta" },
    { key: "clientId", label: "OAuth client ID", when: (config: any) => config.authenticationType === "OAuth" }, { key: "clientSecret", label: "OAuth client secret", password: true, when: (config: any) => config.authenticationType === "OAuth" },
    { key: "scope", label: "OAuth scope [session:role:<role>]", when: (config: any) => config.authenticationType === "OAuth" }, { key: "authorizationCode", label: "Authorization code", password: true, when: (config: any) => config.authenticationType === "OAuth" && config.provider === "Snowflake" },
    { key: "redirectUri", label: "OAuth redirect URI", when: (config: any) => config.authenticationType === "OAuth" && config.provider === "Snowflake" }, { key: "accessToken", label: "OAuth access token", password: true, when: (config: any) => config.authenticationType === "OAuth" },
    { key: "privateKeyFile", label: "Private key file", when: (config: any) => config.authenticationType === "Key Pair Authentication" }, { key: "privateKeyPassphrase", label: "Private key passphrase", password: true, when: (config: any) => config.authenticationType === "Key Pair Authentication" },
    { key: "loginTimeoutSeconds", label: "Login timeout (seconds)" },
    { key: "warehouse", label: "Warehouse" }, { key: "database", label: "Default database" }, { key: "schema", label: "Default schema" },
    { key: "role", label: "Default role" }, { key: "otherProperties", label: "Other properties [Name=Value;]" },
    { key: "minimumConnections", label: "Minimum connections" }, { key: "maximumConnections", label: "Maximum connections" },
    { key: "maximumConnectionWaitSeconds", label: "Maximum connection wait (seconds)" }, { key: "serviceThreads", label: "Service number of threads" },
  ],
  amqp: [
    { key: "brokerType", label: "Broker type", options: ["Qpid-1-0", "RabbitMQ", "ActiveMQ-1-0", "AzureSB-1-0", "AMQ-1-0", "ActiveMQ-Artemis-1-0"] },
    { key: "amqpVersion", label: "AMQP version", options: ["AMQP-0-9-1", "AMQP-1-0"], when: (config: any) => config.brokerType === "RabbitMQ" },
    { key: "hostPort", label: "Host:Port (comma-separated for failover)", required: true, when: (config: any) => config.brokerType !== "AzureSB-1-0" },
    { key: "virtualHost", label: "Virtual host", when: (config: any) => ["RabbitMQ", "Qpid-1-0"].includes(config.brokerType) },
    { key: "username", label: "Username", when: (config: any) => config.brokerType !== "AzureSB-1-0" },
    { key: "password", label: "Password", password: true, when: (config: any) => config.brokerType !== "AzureSB-1-0" },
    { key: "clientId", label: "Client ID", when: (config: any) => !["RabbitMQ", "AzureSB-1-0"].includes(config.brokerType) },
    { key: "authenticationType", label: "Azure authentication", options: ["SAS", "OAuth", "ManagedIdentity"], when: (config: any) => config.brokerType === "AzureSB-1-0" },
    { key: "connectionString", label: "Azure Service Bus endpoint / connection string", required: true, when: (config: any) => config.brokerType === "AzureSB-1-0" },
    { key: "tenantId", label: "Azure tenant ID", required: true, when: (config: any) => config.brokerType === "AzureSB-1-0" && config.authenticationType === "OAuth" },
    { key: "azureClientId", label: "Azure application/client ID", required: (config: any) => config.authenticationType === "OAuth", when: (config: any) => config.brokerType === "AzureSB-1-0" && ["OAuth", "ManagedIdentity"].includes(config.authenticationType) },
    { key: "clientSecret", label: "Azure client secret", required: true, password: true, when: (config: any) => config.brokerType === "AzureSB-1-0" && config.authenticationType === "OAuth" },
    { key: "sharedAccessKeyName", label: "Shared access key name", when: (config: any) => config.brokerType === "AzureSB-1-0" && config.authenticationType === "SAS" },
    { key: "sharedAccessKey", label: "Shared access key", password: true, when: (config: any) => config.brokerType === "AzureSB-1-0" && config.authenticationType === "SAS" },
    { key: "entityType", label: "Default entity type", options: ["Queue", "Topic"], when: (config: any) => config.brokerType === "AzureSB-1-0" },
    { key: "entityName", label: "Default entity name", when: (config: any) => config.brokerType === "AzureSB-1-0" },
    { key: "entitySubscriberName", label: "Default subscription", when: (config: any) => config.brokerType === "AzureSB-1-0" && config.entityType === "Topic" },
    { key: "connectionTimeoutMsec", label: "Connection timeout (msec)" },
    { key: "sessionCount", label: "RabbitMQ session count (1-20)", when: (config: any) => config.brokerType === "RabbitMQ" },
    { key: "idleTimeoutMsec", label: "Idle timeout (msec)", when: (config: any) => config.brokerType === "RabbitMQ" && config.amqpVersion === "AMQP-1-0" },
    { key: "connectionRecovery", label: "Connection recovery", options: ["true", "false"] },
    { key: "retryIntervalMsec", label: "Retry interval (msec)", when: (config: any) => config.brokerType !== "RabbitMQ" },
    { key: "retryAttempts", label: "Retry attempts", when: (config: any) => config.brokerType !== "RabbitMQ" },
    { key: "networkRecoveryIntervalMsec", label: "RabbitMQ recovery interval (msec)", when: (config: any) => config.brokerType === "RabbitMQ" },
    { key: "sslEnabled", label: "SSL confidentiality", options: ["false", "true"] },
    { key: "caFile", label: "Trusted CA file", when: (config: any) => String(config.sslEnabled) === "true" },
    { key: "clientCertificateFile", label: "Client certificate", when: (config: any) => String(config.sslEnabled) === "true" },
    { key: "clientKeyFile", label: "Client private key", when: (config: any) => String(config.sslEnabled) === "true" },
    { key: "clientKeyPassword", label: "Private key password", password: true, when: (config: any) => String(config.sslEnabled) === "true" },
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
    { key: "serverUrl", label: "JMS connection URL", required: true, placeholder: "tcp://ems-host:7222" },
    { key: "driverDirectory", label: "EMS/JMS driver JAR directory", placeholder: "Blank uses C:\\ProgramData\\Integration Fabric Studio\\drivers\\jms" },
    { key: "connectionFactoryClass", label: "Native connection factory class", placeholder: "com.tibco.tibjms.TibjmsConnectionFactory" },
    { key: "connectionFactoryType", label: "Connection factory type", options: ["Direct", "JNDI"] },
    { key: "messagingStyle", label: "Messaging style", options: ["Generic", "Queue/Topic"] },
    { key: "username", label: "Username", required: true }, { key: "password", label: "Password", required: true, password: true },
    { key: "clientId", label: "Client ID", placeholder: "Generated automatically when blank" },
    { key: "connectionFactory", label: "JNDI connection factory", required: true, when: (config: any) => config.connectionFactoryType === "JNDI", options: ["ConnectionFactory", "QueueConnectionFactory", "TopicConnectionFactory"] },
    { key: "queueConnectionFactory", label: "Queue connection factory", when: (config: any) => config.connectionFactoryType === "JNDI" && config.messagingStyle === "Queue/Topic" }, { key: "topicConnectionFactory", label: "Topic connection factory", when: (config: any) => config.connectionFactoryType === "JNDI" && config.messagingStyle === "Queue/Topic" },
    { key: "jndiContextFactory", label: "JNDI context factory", required: true, when: (config: any) => config.connectionFactoryType === "JNDI" }, { key: "jndiProviderUrl", label: "JNDI provider URL", required: true, when: (config: any) => config.connectionFactoryType === "JNDI" },
    { key: "jndiUsername", label: "JNDI username", required: true, when: (config: any) => config.connectionFactoryType === "JNDI" }, { key: "jndiPassword", label: "JNDI password", required: true, password: true, when: (config: any) => config.connectionFactoryType === "JNDI" },
    { key: "useXa", label: "Use XA connection factory", options: ["false", "true"] }, { key: "useUfo", label: "Use EMS unshared failover", options: ["false", "true"] },
    { key: "sslEnabled", label: "Enable SSL", options: ["false", "true"] }, { key: "sslTrustedCertificates", label: "SSL trusted certificates" },
    { key: "reconnectAttempts", label: "Reconnect attempts" }, { key: "reconnectDelayMs", label: "Reconnect delay (ms)" },
    { key: "heartbeatOutgoingMs", label: "Outgoing heartbeat (ms)" }, { key: "heartbeatIncomingMs", label: "Incoming heartbeat (ms)" },
    { key: "connectionTimeoutSeconds", label: "Connection timeout (seconds)" },
  ],
  jms: [
    { key: "provider", label: "JMS provider" }, { key: "serverUrl", label: "JMS connection URL", required: true, placeholder: "tcp://jms-host:61613" },
    { key: "driverDirectory", label: "JMS provider JAR directory", placeholder: "Blank uses C:\\ProgramData\\Integration Fabric Studio\\drivers\\jms" },
    { key: "connectionFactoryClass", label: "Connection factory class", required: (config: any) => config.connectionFactoryType !== "JNDI" },
    { key: "connectionFactoryType", label: "Connection factory type", options: ["Direct", "JNDI"] },
    { key: "username", label: "Username", required: true }, { key: "password", label: "Password", required: true, password: true }, { key: "clientId", label: "Client ID", placeholder: "Generated automatically when blank" },
    { key: "connectionFactory", label: "JNDI connection factory", required: true, when: (config: any) => config.connectionFactoryType === "JNDI" },
    { key: "jndiContextFactory", label: "JNDI initial context factory", required: true, when: (config: any) => config.connectionFactoryType === "JNDI" }, { key: "jndiProviderUrl", label: "JNDI provider URL", required: true, when: (config: any) => config.connectionFactoryType === "JNDI" },
    { key: "jndiUsername", label: "JNDI username", required: true, when: (config: any) => config.connectionFactoryType === "JNDI" }, { key: "jndiPassword", label: "JNDI password", required: true, password: true, when: (config: any) => config.connectionFactoryType === "JNDI" },
    { key: "sslEnabled", label: "Enable SSL", options: ["false", "true"] }, { key: "sslTrustedCertificates", label: "Trusted certificates" },
    { key: "reconnectAttempts", label: "Reconnect attempts" }, { key: "reconnectDelayMs", label: "Reconnect delay (ms)" },
    { key: "connectionTimeoutSeconds", label: "Connection timeout (seconds)" },
  ],
  kafka: [
    { key: "bootstrapServers", label: "Bootstrap servers", required: true },
    { key: "clientId", label: "Client ID" }, { key: "groupId", label: "Default consumer group" },
    { key: "securityProtocol", label: "Security protocol", options: ["PLAINTEXT", "SASL_PLAINTEXT", "SASL_SSL", "SSL"] },
    { key: "authenticationType", label: "Authentication type", options: ["None", "PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512", "GSSAPI", "OAUTHBEARER"] },
    { key: "saslMechanism", label: "SASL mechanism", options: ["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512", "GSSAPI", "OAUTHBEARER"] },
    { key: "username", label: "Username", required: (config: any) => ["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"].includes(config.saslMechanism) && config.securityProtocol?.includes("SASL") }, { key: "password", label: "Password", password: true, required: (config: any) => ["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"].includes(config.saslMechanism) && config.securityProtocol?.includes("SASL") },
    { key: "sslCaLocation", label: "SSL CA location" }, { key: "sslCertificateLocation", label: "SSL certificate location" },
    { key: "sslKeyLocation", label: "SSL key location" }, { key: "sslKeyPassword", label: "SSL key password", password: true },
    { key: "schemaRegistryUrl", label: "Schema Registry URL" }, { key: "schemaRegistryUsername", label: "Schema Registry username" },
    { key: "schemaRegistryPassword", label: "Schema Registry password", password: true },
    { key: "schemaRegistryVendor", label: "Schema Registry vendor", options: ["Confluent", "TIBCO", "Apicurio"] },
    { key: "useTicketCache", label: "Use Kerberos ticket cache", options: ["false", "true"] }, { key: "keytabFile", label: "Kerberos keytab file" }, { key: "principalName", label: "Kerberos principal" },
    { key: "jaasConfigFile", label: "OAuth JAAS config file" }, { key: "loginCallbackHandler", label: "OAuth login callback handler" },
    { key: "requestTimeoutMilliseconds", label: "Request timeout (ms)" }, { key: "connectionTimeoutMilliseconds", label: "Connection timeout (ms)" },
    { key: "reconnectBackoffMilliseconds", label: "Reconnect backoff (ms)" }, { key: "retryBackoffMilliseconds", label: "Retry backoff (ms)" },
    { key: "clientProperties", label: "Advanced client properties (JSON)" },
  ],
  pubsub: [
    { key: "authenticationType", label: "Authentication", required: true, options: ["Service Account JSON", "Application Default Credentials", "Emulator"] },
    { key: "serviceAccountJson", label: "Service account JSON", required: (config: any) => config.authenticationType === "Service Account JSON", multiline: true, jsonFile: true, when: (config: any) => config.authenticationType === "Service Account JSON" },
    { key: "projectId", label: "GCP project ID", required: (config: any) => config.authenticationType !== "Service Account JSON", placeholder: "Derived automatically from service-account JSON" },
    { key: "endpoint", label: "Service endpoint", when: (config: any) => config.authenticationType !== "Emulator" },
    { key: "emulatorHost", label: "Emulator host", required: (config: any) => config.authenticationType === "Emulator", when: (config: any) => config.authenticationType === "Emulator", placeholder: "localhost:8085" }, { key: "ackDeadlineSeconds", label: "Ack deadline (seconds)" },
    { key: "connectionTimeoutSeconds", label: "Connection timeout (seconds)" }, { key: "maxInboundMessageBytes", label: "Maximum inbound message bytes" },
    { key: "keepAliveSeconds", label: "Keep-alive time (seconds)" },
  ],
  sap: [
    { key: "mode", label: "Runtime adapter", options: ["mock", "external"] },
    { key: "driverDirectory", label: "SAP JCo driver directory", placeholder: "Blank uses C:\\ProgramData\\Integration Fabric Studio\\drivers\\sap" },
    { key: "destinationName", label: "JCo destination name", placeholder: "integration-fabric-sap" },
    { key: "release", label: "SAP release", options: ["current", "720", "730"] },
    { key: "connectionType", label: "Connection type", options: ["dedicated", "logongroup", "snc", "sncwithlogongroup", "websocket"] },
    { key: "applicationServerHost", label: "Application server host" }, { key: "systemNumber", label: "System number" },
    { key: "client", label: "Client number" }, { key: "language", label: "Language" }, { key: "username", label: "Username" },
    { key: "password", label: "Password", password: true }, { key: "messageServerHost", label: "Message server host" },
    { key: "systemId", label: "System ID" }, { key: "logonGroup", label: "Logon group" }, { key: "sapRouter", label: "SAP Router" },
    { key: "sncPartnerName", label: "SNC partner name", when: (config: any) => ["snc", "sncwithlogongroup"].includes(config.connectionType) },
    { key: "sncLibraryPath", label: "SNC library path", when: (config: any) => ["snc", "sncwithlogongroup"].includes(config.connectionType) },
    { key: "sncMyName", label: "SNC own name", when: (config: any) => ["snc", "sncwithlogongroup"].includes(config.connectionType) },
    { key: "sncQop", label: "SNC quality of protection", when: (config: any) => ["snc", "sncwithlogongroup"].includes(config.connectionType), options: ["", "1", "2", "3", "8", "9"] },
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
  if (type === "http") Object.assign(values, { connectorMode: "both", scheme: "http", authentication: "None", tlsEnabled: "false", clientAuthentication: "none", tlsVersion: "TLSv1.2", verifyTls: "true" });
  if (type === "sap") Object.assign(values, { mode: "external", release: "current", connectionType: "dedicated" });
  if (type === "jdbc") Object.assign(values, { driver: "postgresql", connectionMode: "python", authentication: "SQL Server Authentication", encrypt: "true", trustServerCertificate: "false" });
  if (type === "ems") Object.assign(values, { connectionFactoryType: "Direct", connectionFactoryClass: "com.tibco.tibjms.TibjmsConnectionFactory", connectionTimeoutSeconds: 30 });
  if (type === "jms") Object.assign(values, { connectionFactoryType: "Direct", connectionTimeoutSeconds: 30 });
  if (type === "snowflake") Object.assign(values, { mode: "external", authenticationType: "Username/Password", provider: "Snowflake" });
  if (type === "amqp") Object.assign(values, { brokerType: "RabbitMQ", amqpVersion: "AMQP-0-9-1", authenticationType: "SAS", connectionRecovery: "true", sslEnabled: "false" });
  if (type === "pubsub") Object.assign(values, { authenticationType: "Service Account JSON", projectId: "", serviceAccountJson: "" });
  return values;
}
function SharedConnectionDialog({ type, initial, properties, onClose, onCreate }: any) {
  const fields = connectionFieldSets[type] || [];
  const testOutputRef = useRef<HTMLDivElement>(null);
  const idocBrowserRef = useRef<HTMLElement>(null);
  const snowflakeBrowserRef = useRef<HTMLElement>(null);
  const [draft, setDraft] = useState<any>(() => {
    const value = initial ? structuredClone(initial) : { id: `${type}-${Date.now()}`, type, name: `${type === "sap" ? "SAP ECC" : type.toUpperCase()} Connection`, config: connectionDefaults(type) };
    // The old design-time memory/external selector is no longer part of real
    // shared connections. Editing an older resource upgrades it automatically.
    if (["ems", "jms", "kafka", "pubsub", "amqp"].includes(type)) delete value.config.mode;
    if (type === "pubsub" && !value.config.authenticationType) value.config.authenticationType = "Service Account JSON";
    return value;
  });
  const [status, setStatus] = useState(""), [statusOk, setStatusOk] = useState<boolean | null>(null), [copied, setCopied] = useState(false), [testing, setTesting] = useState(false);
  const [target, setTarget] = useState<string | null>(null), [propertySearch, setPropertySearch] = useState("");
  const [idocs, setIdocs] = useState<any[]>([]), [idocSearch, setIdocSearch] = useState(""), [idocLoading, setIdocLoading] = useState(false), [idocError, setIdocError] = useState(""), [idocPickerOpen, setIdocPickerOpen] = useState(false);
  const [snowflakeEntities, setSnowflakeEntities] = useState<any[]>([]), [snowflakeSearch, setSnowflakeSearch] = useState(""), [snowflakeLoading, setSnowflakeLoading] = useState(false), [snowflakeError, setSnowflakeError] = useState("");
  const set = (key: string, value: any) => setDraft((current: any) => ({ ...current, config: { ...current.config, [key]: value } }));
  const setConnectionField = (key: string, value: any) => setDraft((current: any) => {
    const config = { ...current.config, [key]: value };
    if (type === "jdbc" && key === "driver") {
      const defaults: Record<string, any> = {
        sqlite: { url: "integration.db", host: "", port: "", database: "", schema: "main" },
        postgresql: { url: "", port: 5432, schema: "public" }, mysql: { url: "", port: 3306, schema: "" },
        mariadb: { url: "", port: 3306, schema: "" },
        sqlserver: { url: "", port: 1433, schema: "dbo", connectionMode: "jdbc", driverClass: "com.microsoft.sqlserver.jdbc.SQLServerDriver", authentication: "SQL Server Authentication", encrypt: "true", trustServerCertificate: "false" },
        oracle: { url: "", port: 1521, schema: "", connectionMode: "jdbc", driverClass: "oracle.jdbc.OracleDriver" }, db2: { url: "", port: 50000, schema: "" },
        snowflake: { url: "", port: "", schema: "PUBLIC" },
        databricks: { url: "", port: 443, schema: "default", authentication: "Personal Access Token", useCloudFetch: "true" },
      };
      Object.assign(config, defaults[value] || {});
    }
    return { ...current, config };
  });
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
  const propertyBinding = (value: any) => typeof value === "string" ? value.match(/^\$\{properties\.([^}]+)\}$/)?.[1] : undefined;
  const displayedValue = (value: any) => {
    const key = propertyBinding(value);
    return key ? (properties as Property[]).find((item) => item.key === key)?.value ?? "" : value ?? "";
  };
  const fieldIsRequired = (field: any, config = draft.config) => typeof field.required === "function" ? !!field.required(config) : !!field.required;
  const missingRequiredFields = (resource: any) => fields.filter((field: any) => (!field.when || field.when(resource.config)) && fieldIsRequired(field, resource.config) && String(resource.config[field.key] ?? "").trim() === "").map((field: any) => field.label);
  const configurationError = (resource: any) => {
    if (type !== "pubsub" || resource.config.authenticationType !== "Service Account JSON") return "";
    try {
      const parsed = typeof resource.config.serviceAccountJson === "string" ? JSON.parse(resource.config.serviceAccountJson) : resource.config.serviceAccountJson;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") return "Service account JSON must contain one JSON object.";
      const requiredKeys = ["type", "project_id", "client_email", "private_key", "token_uri"];
      const missing = requiredKeys.filter((key) => !String(parsed[key] || "").trim());
      if (parsed.type !== "service_account") return "Credential JSON type must be service_account.";
      if (missing.length) return `Service account JSON is missing: ${missing.join(", ")}.`;
      return "";
    } catch (error: any) { return `Service account JSON is invalid: ${error.message}`; }
  };
  const fetchIdocs = async () => {
    setIdocPickerOpen(true);
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
      setIdocPickerOpen(false);
    } catch (error: any) { setIdocError(error?.message || "IDoc metadata download failed"); }
    finally { setIdocLoading(false); }
  };
  const fetchSnowflakeEntities = async () => {
    setSnowflakeLoading(true); setSnowflakeError("");
    requestAnimationFrame(() => snowflakeBrowserRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    try {
      const response = await fetch("/api/snowflake/entities", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ resource: runtimeResource(), database: draft.config.database, schema: draft.config.schema, pattern: snowflakeSearch || "%" }) });
      const output = await response.json();
      if (!response.ok) throw new Error(output.detail || "Snowflake entity discovery failed");
      setSnowflakeEntities(output.entities || []);
    } catch (error: any) { setSnowflakeError(error?.message || "Snowflake entity discovery failed"); }
    finally { setSnowflakeLoading(false); }
  };
  const selectSnowflakeEntity = async (item: any) => {
    setSnowflakeLoading(true); setSnowflakeError("");
    try {
      const response = await fetch("/api/snowflake/entities", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ resource: runtimeResource(), database: item.database, schema: item.schema, entity: item.name }) });
      const output = await response.json();
      if (!response.ok) throw new Error(output.detail || "Snowflake metadata download failed");
      const selected = output.entity;
      setDraft((current: any) => ({ ...current, config: { ...current.config, entityCatalog: [...(current.config.entityCatalog || []).filter((entry: any) => !(entry.database === selected.database && entry.schema === selected.schema && entry.name === selected.name)), selected] } }));
    } catch (error: any) { setSnowflakeError(error?.message || "Snowflake metadata download failed"); }
    finally { setSnowflakeLoading(false); }
  };
  const clearSnowflakeMetadata = () => setDraft((current: any) => ({ ...current, config: { ...current.config, entityCatalog: [] } }));
  const test = async () => {
    const resource = runtimeResource();
    const missing = missingRequiredFields(resource);
    if (missing.length) { setStatus(`Required connection values are missing: ${missing.join(", ")}`); setStatusOk(false); return; }
    const invalid = configurationError(resource);
    if (invalid) { setStatus(invalid); setStatusOk(false); return; }
    setStatus("Testing connection…"); setStatusOk(null); setCopied(false); setTesting(true);
    const controller = new AbortController();
    const configuredTimeout = Number(resource.config.connectionTimeoutMilliseconds || resource.config.connectionTimeoutMsec || Number(resource.config.connectionTimeoutSeconds || 30) * 1000);
    const timeout = window.setTimeout(() => controller.abort(), Math.min(65000, Math.max(5000, configuredTimeout + 3000)));
    try {
      const response = await fetch("/api/connections/test", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(resource), signal: controller.signal });
      const output = await response.json();
      setStatus(output.message || output.detail || JSON.stringify(output, null, 2)); setStatusOk(response.ok && output.ok !== false);
    } catch (error: any) { setStatus(error?.name === "AbortError" ? "Connection test timed out. Verify the URL, port, firewall, and broker listener protocol." : error?.message || "Connection test failed"); setStatusOk(false); }
    finally { window.clearTimeout(timeout); setTesting(false); }
  };
  const save = () => {
    const resource = runtimeResource(), missing = missingRequiredFields(resource);
    if (missing.length) { setStatus(`Required connection values are missing: ${missing.join(", ")}`); setStatusOk(false); return; }
    const invalid = configurationError(resource);
    if (invalid) { setStatus(invalid); setStatusOk(false); return; }
    onCreate(draft);
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
  const resolvedConfig = runtimeResource().config;
  return <div className="modal-backdrop"><div className="runtime-modal connection-dialog">
    <header><span className="connection-dialog-title"><Cable/><span><b>{initial ? "Edit" : "Create"} {type === "sap" ? "SAP ECC" : type === "snowflake" ? "Snowflake JDBC" : type.toUpperCase()} shared connection</b><small>{initial ? "Update the reusable project connection" : "Reusable across every task in this project"}</small></span></span><span className="connection-header-actions">{type === "sap" && <button type="button" className="browse-properties retrieve-idocs" onClick={fetchIdocs} disabled={idocLoading}><Download/> {idocLoading ? "Retrieving…" : "Retrieve IDoc types"}</button>}{type === "snowflake" && <button type="button" className="browse-properties retrieve-idocs" onClick={fetchSnowflakeEntities} disabled={snowflakeLoading}><Download/> {snowflakeLoading ? "Retrieving…" : "Retrieve entities"}</button>}<button aria-label="Close" onClick={onClose}>×</button></span></header>
    <main>
      <label>Name<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })}/></label>
      {target && <section className="connection-property-picker">
        <header><span><b>SELECT PROPERTY</b><small>Map to {fields.find((field: any) => field.key === target)?.label}</small></span><button aria-label="Close property picker" onClick={() => setTarget(null)}>×</button></header>
        <div className="property-picker-search"><Search/><input autoFocus aria-label="Find connection property" value={propertySearch} onChange={(event) => setPropertySearch(event.target.value)} placeholder="Search connector properties…"/></div>
        <div className="property-browser-list">{visibleProperties.map((item) => <button key={item.key} onClick={() => { set(target, propertyExpression(item.key)); setTarget(null); setPropertySearch(""); }}><span><b>{item.key}</b><small>{item.data_type}</small></span><code>{item.data_type === "password" ? "••••••" : String(item.value)}</code></button>)}{!visibleProperties.length && <p>No matching connector properties.</p>}</div>
      </section>}
      {fields.filter((field: any) => !field.when || field.when(resolvedConfig)).map((field: any) => {
        const required = fieldIsRequired(field, resolvedConfig), binding = propertyBinding(draft.config[field.key]), value = displayedValue(draft.config[field.key]);
        const title = <span className="connection-field-label"><span>{field.label}{required && <i>*</i>}</span><small>{required ? "Required" : "Optional"}</small></span>;
        const mapped = binding && <small className="resolved-property-value">Value resolved from <code>{binding}</code></small>;
        const textValue = typeof value === "string" ? value : JSON.stringify(value, null, 2);
        return <label className={required ? "connection-field-required" : "connection-field-optional"} key={`${field.key}-${field.label}`}>{title}{field.options ? <><select required={required} value={String(value)} onChange={(event) => setConnectionField(field.key, event.target.value)}>{field.options.map((option: string) => <option key={option} value={option}>{option}</option>)}</select>{mapped}</> : <span className={`property-field-wrap ${field.multiline ? "multiline" : ""}`}>{field.multiline ? <textarea required={required} rows={9} spellCheck={false} placeholder={field.placeholder || "Paste the complete service-account JSON object"} value={textValue} onChange={(event) => setConnectionField(field.key, event.target.value)}/> : <input required={required} placeholder={field.placeholder || (required ? "Required value" : "Optional")} type={field.password ? "password" : "text"} value={textValue} onChange={(event) => setConnectionField(field.key, event.target.value)}/>}<button type="button" title={`Browse properties for ${field.label}`} aria-label={`Browse properties for ${field.label}`} onClick={() => { setTarget(field.key); setPropertySearch(""); }}><Braces/></button>{field.jsonFile && <input className="service-account-file" aria-label="Upload service account JSON" type="file" accept="application/json,.json" onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; const content = await file.text(); setDraft((current: any) => { const config = { ...current.config, [field.key]: content }; try { const parsed = JSON.parse(content); if (parsed.project_id) config.projectId = parsed.project_id; } catch {} return { ...current, config }; }); event.currentTarget.value = ""; }}/>} {mapped}</span>}</label>;
      })}
      {type === "sap" && <section ref={idocBrowserRef} className="sap-idoc-browser"><header><span><b>SAP IDOC METADATA</b><small>Target release: {draft.config.release === "720" ? "SAP 7.20" : draft.config.release === "730" ? "SAP 7.30" : "Current / auto-detect"}. Retrieve and store the matching schema in this shared connection.</small></span><button type="button" onClick={fetchIdocs} disabled={idocLoading}><Download/> {idocLoading ? "Retrieving…" : "Retrieve IDoc types"}</button></header><div className="sap-idoc-search"><Search/><input value={idocSearch} onChange={(event) => setIdocSearch(event.target.value)} onKeyDown={(event) => event.key === "Enter" && fetchIdocs()} placeholder="Filter IDoc types, for example ORDERS…"/></div>{idocError && <p className="sap-idoc-error">{idocError}</p>}<div className="sap-idoc-list">{idocs.map((item) => { const selected = draft.config.selectedIdoc?.idocType === item.idocType; return <button type="button" className={selected ? "selected" : ""} key={`${item.idocType}-${item.release}`} onClick={() => selectIdoc(item)}><span><b>{item.idocType}</b><small>{item.description || "SAP IDoc"}</small></span><code>{item.extensionType || "basic"} · {item.release || "current"}</code>{selected && <i>Schema fetched</i>}</button>; })}{!idocs.length && <p>Test the SAP connection, then retrieve the available IDoc types.</p>}</div>{draft.config.selectedIdoc && <footer><CheckCircle2/><span><b>{draft.config.selectedIdoc.idocType}</b><small>{draft.config.selectedIdoc.segments?.length || 0} metadata rows · SAP release {draft.config.selectedIdoc.release || draft.config.release} · schema stored with shared connection</small></span></footer>}</section>}
      {type === "snowflake" && <section ref={snowflakeBrowserRef} className="sap-idoc-browser snowflake-entity-browser"><header><span><b>SNOWFLAKE SCHEMA METADATA</b><small>Retrieve TABLE and VIEW entities from the configured database and schema, then select each entity whose column metadata should be stored.</small></span><button type="button" onClick={fetchSnowflakeEntities} disabled={snowflakeLoading}><Download/> {snowflakeLoading ? "Retrieving…" : "Retrieve entities"}</button></header><div className="sap-idoc-search"><Search/><input value={snowflakeSearch} onChange={(event) => setSnowflakeSearch(event.target.value)} onKeyDown={(event) => event.key === "Enter" && fetchSnowflakeEntities()} placeholder="Entity name pattern, for example ORDER_%…"/></div>{snowflakeError && <p className="sap-idoc-error">{snowflakeError}</p>}<div className="sap-idoc-list">{snowflakeEntities.map((item) => { const stored = (draft.config.entityCatalog || []).some((entry: any) => entry.database === item.database && entry.schema === item.schema && entry.name === item.name); return <button type="button" className={stored ? "selected" : ""} key={`${item.database}.${item.schema}.${item.name}`} onClick={() => selectSnowflakeEntity(item)}><span><b>{item.name}</b><small>{item.database}.{item.schema}</small></span><code>{item.entityType || "TABLE"}</code>{stored && <i>Metadata fetched</i>}</button>; })}{!snowflakeEntities.length && <p>Test the Snowflake connection, then retrieve tables and views.</p>}</div>{!!draft.config.entityCatalog?.length && <footer><CheckCircle2/><span><b>{draft.config.entityCatalog.length} entities stored</b><small>{draft.config.entityCatalog.reduce((count: number, item: any) => count + (item.columns?.length || 0), 0)} columns available to Snowflake activity input/output editors</small></span><button type="button" onClick={clearSnowflakeMetadata}>Remove metadata</button></footer>}</section>}
      {status && <div ref={testOutputRef} role="status" aria-live="polite" className={`connection-test-output ${statusOk === true ? "success" : statusOk === false ? "failure" : "pending"}`}><header><span><b>{statusOk === true ? "CONNECTION SUCCEEDED" : statusOk === false ? "CONNECTION FAILED" : "CONNECTION TEST"}</b><small>Selectable test response</small></span><button onClick={copyStatus}><ClipboardCopy/> {copied ? "Copied" : "Copy output"}</button></header><textarea aria-label="Connection test output" readOnly value={status} onFocus={(event) => event.currentTarget.select()}/></div>}
      {type === "sap" && idocPickerOpen && <div className="sap-idoc-picker" role="dialog" aria-modal="true" aria-label="Select SAP IDoc type" onMouseDown={(event) => { if (event.target === event.currentTarget) setIdocPickerOpen(false); }}><div className="sap-idoc-picker-card"><header><span><b>SELECT SAP IDOC TYPE</b><small>Search SAP and select one type to retrieve its structure and schema.</small></span><button type="button" aria-label="Close IDoc picker" onClick={() => setIdocPickerOpen(false)}>×</button></header><div className="sap-idoc-picker-search"><Search/><input autoFocus value={idocSearch} onChange={(event) => setIdocSearch(event.target.value)} onKeyDown={(event) => event.key === "Enter" && fetchIdocs()} placeholder="Search IDoc types, for example ORDERS…"/><button type="button" onClick={fetchIdocs} disabled={idocLoading}>{idocLoading ? "Searching…" : "Search"}</button></div>{idocError && <p className="sap-idoc-error">{idocError}</p>}<div className="sap-idoc-picker-list">{idocs.map((item) => { const selected = draft.config.selectedIdoc?.idocType === item.idocType; return <button type="button" className={selected ? "selected" : ""} key={`${item.idocType}-${item.release}`} onClick={() => selectIdoc(item)} disabled={idocLoading}><span><b>{item.idocType}</b><small>{item.description || "SAP IDoc"}</small></span><code>{item.extensionType || "basic"} · {item.release || "current"}</code>{selected && <i>Schema fetched</i>}</button>; })}{!idocs.length && !idocLoading && <p>No IDoc types found. Adjust the search and try again.</p>}</div><footer><small>{idocs.length} IDoc type(s) found · Select one to retrieve metadata</small></footer></div></div>}
    </main>
    <footer><button onClick={test} disabled={testing}>{testing ? "Testing…" : "Test Connection"}</button><button onClick={onClose}>Cancel</button><button className="primary" onClick={save}>{initial ? "Save changes" : "Create connection"}</button></footer>
  </div></div>;
}
function ConnectionDialog({ type, onClose, onCreate }: any) {
  const [draft, setDraft] = useState<any>({
      id: `${type}-${Date.now()}`,
      type,
      name: `${type.toUpperCase()} Connection`,
      config: {
        mode: ["ems", "jms", "kafka", "pubsub"].includes(type)
          ? "memory"
          : type === "sap"
            ? "external"
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
                : type === "jms"
                  ? "${properties.connections.jms.host}"
                : undefined,
        port:
          type === "sftp"
            ? "${properties.connections.sftp.port}"
            : type === "ftp"
              ? "${properties.connections.ftp.port}"
              : type === "ems"
                ? "${properties.connections.ems.port}"
                : type === "jms"
                  ? "${properties.connections.jms.port}"
                : undefined,
        bootstrapServers:
          type === "kafka" ? "${properties.connections.kafka.bootstrapServers}" : undefined,
        projectId:
          type === "pubsub" ? "${properties.connections.pubsub.projectId}" : undefined,
        applicationServerHost:
          type === "sap" ? "${properties.connections.sap.applicationServerHost}" : undefined,
        driverDirectory:
          type === "sap" ? "${properties.connections.sap.driverDirectory}" : undefined,
        destinationName: type === "sap" ? "integration-fabric-sap" : undefined,
        systemNumber:
          type === "sap" ? "${properties.connections.sap.systemNumber}" : undefined,
        client: type === "sap" ? "${properties.connections.sap.client}" : undefined,
        language: "EN",
        connectionType: "dedicated",
        sncQop: "",
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
                    value={draft.config.maximumConnections ?? 8}
                    onChange={(e) =>
                    set("maximumConnections", Number(e.target.value))
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
      snowflake: "snowflake",
      amqp: "amqp",
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
      {["ems", "kafka", "pubsub", "amqp"].includes(node.type) && (
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
function DebugBar({ state, act, stop }: any) {
  const waitingForEvent = state.status === "listening";
  return (
    <div className="debug-bar">
      <Bug />
      <b>{waitingForEvent ? "ready · waiting for event" : state.status}</b>
      <button disabled={waitingForEvent} onClick={() => act("continue")}>
        <CirclePlay /> Continue
      </button>
      <button disabled={waitingForEvent} onClick={() => act("pause")}>
        <Pause /> Pause
      </button>
      <button disabled={waitingForEvent} onClick={() => act("step_in")}>
        <SkipForward /> Step In
      </button>
      <button disabled={waitingForEvent} onClick={() => act("step_over")}>
        <SkipForward /> Step Over
      </button>
      <button disabled={waitingForEvent} onClick={() => act("step_out")}>
        <SkipBack /> Step Out
      </button>
      <button disabled={waitingForEvent} onClick={() => act("jump_in")}>Jump In</button>
      <button disabled={waitingForEvent} onClick={() => act("jump_out")}>Jump Out</button>
      <button className="debug-stop" onClick={stop}>
        <Square /> Stop
      </button>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<StudioErrorBoundary><App /></StudioErrorBoundary>);
