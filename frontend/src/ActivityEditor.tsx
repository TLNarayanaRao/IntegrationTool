import React, { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Braces,
  CheckCircle2,
  Database,
  Plus,
  RefreshCw,
  ShieldAlert,
  WandSparkles,
} from "lucide-react";
import MapperStudio from "./MapperStudio";

type Field = {
  key: string;
  label: string;
  type?:
    | "text"
    | "number"
    | "boolean"
    | "select"
    | "textarea"
    | "resource"
    | "task";
  options?: string[];
  resourceType?: string;
  required?: boolean;
  help?: string;
};
type DataField = {
  key: string;
  label: string;
  type: string;
  required?: boolean;
  help?: string;
};
type Contract = {
  configuration: Field[];
  input: DataField[];
  output: DataField[];
  errors: { type: string; description: string }[];
};
const f = (
  key: string,
  label: string,
  type: Field["type"] = "text",
  help = "",
): Field => ({ key, label, type, help });
const d = (
  key: string,
  label: string,
  type = "string",
  required = false,
  help = "",
): DataField => ({ key, label, type, required, help });
const commonErrors = [
  {
    type: "CONNECTIVITY",
    description: "The configured shared connection is unavailable.",
  },
  {
    type: "RETRY_EXHAUSTED",
    description: "The reconnection or retry policy was exhausted.",
  },
  {
    type: "VALIDATION",
    description: "Required input or mapped data is invalid.",
  },
];
const mapperFunctions = [
  "concat", "substring", "substringBefore", "substringAfter", "stringLength", "normalizeSpace", "upperCase", "lowerCase", "trim", "replace", "matches", "tokenize", "startsWith", "endsWith", "contains", "format", "parseDate", "formatDate", "currentDate", "currentDateTime", "addDays", "addMonths", "dateDifference", "number", "integer", "decimal", "round", "floor", "ceiling", "abs", "min", "max", "sum", "average", "count", "boolean", "not", "ifThenElse", "coalesce", "exists", "empty", "default", "distinctValues", "sort", "reverse", "first", "last", "indexOf", "join", "split", "filter", "map", "reduce", "jsonParse", "jsonRender", "xmlParse", "xmlRender", "base64Encode", "base64Decode", "urlEncode", "urlDecode", "uuid", "hash", "xpath", "jsonPath", "property", "processContext", "taskOutput", "lookup", "crossReference", "nil", "isNil"
];

export function activityContract(n: any): Contract {
  const op = n.config.operation || "",
    base: Contract = {
      configuration: [],
      input: [],
      output: [],
      errors: [
        { type: "RUNTIME", description: "The activity could not complete." },
      ],
    };
  if (n.type === "start")
    return {
      ...base,
      input: [d("payload", "Starter payload", "object")],
      output: [d("payload", "Initial task payload", "object")],
      errors: [],
    };
  if (n.type === "end")
    return {
      ...base,
      input: [d("result", "Task result", "object")],
      output: [d("result", "Task output", "object")],
      errors: [],
    };
  if (n.type === "timer")
    return {
      configuration: [
        f("startTime", "Start time"),
        f("interval", "Interval", "number"),
        {
          ...f("unit", "Unit", "select"),
          options: ["seconds", "minutes", "hours", "days"],
        },
        f("runOnce", "Run once", "boolean"),
      ],
      input: [],
      output: [
        d("scheduledTime", "Scheduled time", "dateTime"),
        d("actualTime", "Actual fire time", "dateTime"),
        d("sequence", "Sequence", "integer"),
      ],
      errors: [
        {
          type: "SCHEDULER",
          description: "The schedule expression or interval is invalid.",
        },
      ],
    };
  if (n.type === "call_task")
    return {
      configuration: [
        { ...f("taskId", "Sub Task", "task"), required: true },
        f("dynamicTaskId", "Dynamic task override"),
        f("spawn", "Spawn without waiting", "boolean"),
      ],
      input: [d("payload", "Sub Task input", "object", true)],
      output: [
        d("taskId", "Invoked task ID"),
        d("output", "Sub Task output", "object"),
        d("spawned", "Spawn status", "boolean"),
      ],
      errors: [
        {
          type: "TASK_NOT_FOUND",
          description: "The selected or dynamic Sub Task does not exist.",
        },
        {
          type: "SUBTASK_ERROR",
          description: "The invoked Sub Task returned an error.",
        },
        ...commonErrors.slice(2),
      ],
    };
  if (n.type === "file") {
    const cfg = [
      f(
        "path",
        "File or directory path",
        "text",
        "Accepts environment expressions.",
      ),
      ...(["list", "poll"].includes(op)
        ? [f("pattern", "File name pattern")]
        : []),
      ...(["rename", "copy"].includes(op)
        ? [f("destination", "Destination path")]
        : []),
      ...(op === "write"
        ? [f("encoding", "Encoding"), f("append", "Append", "boolean")]
        : []),
      ...(op === "poll"
        ? [
            f("pollInterval", "Poll interval (seconds)", "number"),
            f("includeExisting", "Include existing files", "boolean"),
          ]
        : []),
    ];
    const inputs =
      op === "write"
        ? [d("content", "File content", "string", true)]
        : ["rename", "copy"].includes(op)
          ? [
              d("source", "Source path", "string", true),
              d("destination", "Destination path", "string", true),
            ]
          : [d("path", "Path", "string", true)];
    const outputs =
      op === "read"
        ? [
            d("content", "File content"),
            d("path", "Resolved path"),
            d("size", "Size", "integer"),
          ]
        : op === "list" || op === "poll"
          ? [
              d("files", "Matched files", "array"),
              d("count", "File count", "integer"),
            ]
          : [
              d("path", "Affected path"),
              d("success", "Operation result", "boolean"),
            ];
    return {
      configuration: cfg,
      input: inputs,
      output: outputs,
      errors: [
        {
          type: "FILE_NOT_FOUND",
          description: "The configured source path does not exist.",
        },
        {
          type: "FILE_IO",
          description:
            "The runtime cannot read, write, move, or delete the file.",
        },
        {
          type: "PERMISSION",
          description: "The runtime lacks filesystem permission.",
        },
      ],
    };
  }
  if (n.type === "ftp" || n.type === "sftp")
    return {
      configuration: [
        {
          ...f("resourceId", "Shared connection", "resource"),
          resourceType: n.type,
        },
        f(
          "remotePath",
          op === "change_dir" ? "Target directory" : "Remote path",
        ),
        f("workingDirectory", "Working directory"),
        f("binary", "Binary transfer", "boolean"),
        f("timeout", "Timeout seconds", "number"),
        ...(n.type === "sftp"
          ? [f("verifyHostKey", "Verify host key", "boolean")]
          : []),
      ],
      input:
        op === "put"
          ? [
              d("content", "Content", "binary|string", true),
              d("remotePath", "Remote path", "string", true),
            ]
          : [d("remotePath", "Remote path", "string", op !== "dir")],
      output:
        op === "get"
          ? [
              d("contentBase64", "Downloaded content", "base64"),
              d("size", "Size", "integer"),
            ]
          : op === "dir"
            ? [
                d("entries", "Directory entries", "array"),
                d("directory", "Current directory"),
              ]
            : [
                d("remotePath", "Remote path"),
                d("success", "Operation result", "boolean"),
              ],
      errors: [
        {
          type: "AUTHENTICATION",
          description: "Remote authentication failed.",
        },
        {
          type: "REMOTE_NOT_FOUND",
          description: "The remote path does not exist.",
        },
        { type: "TRANSFER", description: "The remote transfer failed." },
        ...commonErrors.slice(0, 2),
      ],
    };
  if (n.type === "http_listener")
    return {
      configuration: [
        {
          ...f("resourceId", "HTTP shared connection", "resource"),
          resourceType: "http",
        },
        f("path", "Listener path"),
        f("methods", "Allowed methods"),
        f("contentType", "Expected content type"),
        f("authentication", "Authentication policy"),
      ],
      input: [],
      output: [
        d("body", "Request body", "object|string"),
        d("headers", "Request headers", "object"),
        d("query", "Query parameters", "object"),
        d("pathParameters", "Path parameters", "object"),
        d("method", "HTTP method"),
      ],
      errors: [
        {
          type: "HTTP_BAD_REQUEST",
          description: "The inbound HTTP request is invalid.",
        },
        {
          type: "HTTP_UNAUTHORIZED",
          description: "Listener authentication rejected the request.",
        },
        {
          type: "HTTP_NOT_FOUND",
          description: "No matching listener resource exists.",
        },
      ],
    };
  if (n.type === "http" || (n.type === "rest" && op === "invoke"))
    return {
      configuration: [
        {
          ...f("resourceId", "HTTP shared connection", "resource"),
          resourceType: "http",
        },
        {
          ...f("method", "Method", "select"),
          options: ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
        },
        f("url", "Endpoint URL"),
        f("timeout", "Timeout seconds", "number"),
        f("followRedirects", "Follow redirects", "boolean"),
      ],
      input: [
        d("headers", "Headers", "object"),
        d("query", "Query parameters", "object"),
        d("body", "Request body", "object|string"),
      ],
      output: [
        d("statusCode", "Status code", "integer"),
        d("headers", "Response headers", "object"),
        d("body", "Response body", "object|string"),
      ],
      errors: [
        {
          type: "HTTP_CONNECTIVITY",
          description: "The HTTP endpoint could not be reached.",
        },
        {
          type: "HTTP_TIMEOUT",
          description: "The request exceeded its timeout.",
        },
        {
          type: "HTTP_CLIENT_ERROR",
          description: "The endpoint returned a 4xx response.",
        },
        {
          type: "HTTP_SERVER_ERROR",
          description: "The endpoint returned a 5xx response.",
        },
      ],
    };
  if (n.type === "http_response")
    return {
      configuration: [
        f("statusCode", "Status code", "number"),
        f("contentType", "Content type"),
      ],
      input: [
        d("headers", "Response headers", "object"),
        d("body", "Response body", "object|string", true),
      ],
      output: [
        d("statusCode", "Sent status code", "integer"),
        d("sent", "Response sent", "boolean"),
      ],
      errors: [
        {
          type: "HTTP_RESPONSE",
          description: "The listener response could not be written.",
        },
      ],
    };
  if (n.type === "rest" && op === "receiver")
    return {
      configuration: [
        {
          ...f("resourceId", "HTTP shared connection", "resource"),
          resourceType: "http",
        },
        f("path", "Resource path"),
        f("methods", "Allowed methods"),
        f("contentType", "Request content type"),
        f("responseType", "Response content type"),
      ],
      input: [],
      output: [
        d("body", "Request entity", "object"),
        d("headers", "Headers", "object"),
        d("query", "Query parameters", "object"),
        d("pathParameters", "URI parameters", "object"),
      ],
      errors: [
        {
          type: "REST_VALIDATION",
          description:
            "The request does not conform to its API/schema contract.",
        },
        {
          type: "REST_UNSUPPORTED_MEDIA",
          description: "The request media type is unsupported.",
        },
      ],
    };
  if (n.type === "soap")
    return op === "service"
      ? {
          configuration: [
            {
              ...f("resourceId", "HTTP shared connection", "resource"),
              resourceType: "http",
            },
            f("path", "Service path"),
            f("serviceName", "Service name"),
            f("operationName", "Operation name"),
            f("wsdl", "WSDL resource"),
          ],
          input: [],
          output: [
            d("envelope", "SOAP envelope", "xml"),
            d("headers", "SOAP/HTTP headers", "object"),
            d("operation", "Resolved operation"),
          ],
          errors: [
            {
              type: "SOAP_FAULT",
              description: "The request generated a SOAP fault.",
            },
            {
              type: "WSDL_VALIDATION",
              description: "The message does not conform to the WSDL.",
            },
          ],
        }
      : {
          configuration: [
            {
              ...f("resourceId", "HTTP shared connection", "resource"),
              resourceType: "http",
            },
            f("url", "Service endpoint"),
            f("soapAction", "SOAP action"),
            f("wsdl", "WSDL resource"),
            f("timeout", "Timeout seconds", "number"),
          ],
          input: [
            d("envelope", "SOAP envelope", "xml", true),
            d("headers", "SOAP headers", "object"),
          ],
          output: [
            d("statusCode", "HTTP status", "integer"),
            d("body", "SOAP response envelope", "xml"),
            d("headers", "Response headers", "object"),
          ],
          errors: [
            {
              type: "SOAP_FAULT",
              description: "The remote service returned a SOAP fault.",
            },
            {
              type: "WSDL_VALIDATION",
              description: "The request or response violates the WSDL.",
            },
            ...commonErrors.slice(0, 2),
          ],
        };
  if (n.type === "jdbc")
    return {
      configuration: [
        {
          ...f("resourceId", "Database shared connection", "resource"),
          resourceType: "jdbc",
        },
        ...(op === "call"
          ? [f("procedure", "Stored procedure")]
          : [f("sql", "SQL statement", "textarea")]),
        f("timeout", "Query timeout seconds", "number"),
        f("transaction", "Transaction mode", "select"),
      ],
      input: [
        d("parameters", "Named SQL parameters", "object"),
        ...(op === "dynamic" ? [d("sql", "Dynamic SQL", "string", true)] : []),
      ],
      output:
        op === "query" || op === "dynamic"
          ? [
              d("rows", "Result rows", "array"),
              d("rowCount", "Row count", "integer"),
            ]
          : op === "call"
            ? [
                d("resultSets", "Result sets", "array"),
                d("outParameters", "OUT parameters", "object"),
              ]
            : [
                d("rowCount", "Affected rows", "integer"),
                d("lastInsertId", "Generated key", "integer|string"),
              ],
      errors: [
        {
          type: "DB_CONNECTIVITY",
          description: "The database connection failed.",
        },
        {
          type: "DB_BAD_SQL",
          description: "The SQL or stored procedure is invalid.",
        },
        {
          type: "DB_CONSTRAINT",
          description: "A database constraint was violated.",
        },
        {
          type: "DB_TRANSACTION",
          description: "The transaction could not commit or roll back.",
        },
      ],
    };
  if (n.type === "xml" || n.type === "json" || n.type === "flat") {
    const format = n.type.toUpperCase();
    return {
      configuration: [
        ...(n.type === "xml"
          ? [
              f("schemaId", "XSD schema"),
              f("rootElement", "Root element"),
              f("encoding", "Encoding"),
            ]
          : n.type === "json"
            ? [
                f("schemaId", "JSON/XSD schema"),
                f("indent", "Indent", "number"),
              ]
            : [
                f("format", "Format", "select"),
                f("delimiter", "Delimiter"),
                f("fields", "Field names"),
                f("header", "First row is header", "boolean"),
              ]),
      ],
      input: [d("source", `${format} source`, "object|string", true)],
      output: [
        d(
          op === "parse" ? "value" : "content",
          op === "parse" ? "Parsed value" : "Rendered content",
          op === "parse" ? "object" : "string",
        ),
      ],
      errors: [
        {
          type: `${format}_PARSE`,
          description: `The ${format} input cannot be parsed.`,
        },
        {
          type: `${format}_RENDER`,
          description: `The value cannot be rendered as ${format}.`,
        },
        {
          type: "SCHEMA_VALIDATION",
          description: "The data does not conform to the selected schema.",
        },
      ],
    };
  }
  if (n.type === "ems" || n.type === "kafka" || n.type === "pubsub") {
    const destination =
      n.type === "ems"
        ? op.includes("queue")
          ? "queue"
          : "topic"
        : n.type === "pubsub" && op === "subscribe"
          ? "subscription"
          : "topic";
    return {
      configuration: [
        {
          ...f("resourceId", "Shared connection", "resource"),
          resourceType: n.type,
        },
        f(destination, destination[0].toUpperCase() + destination.slice(1)),
        ...([
          "receive",
          "get",
          "subscribe",
          "queue_receiver",
          "topic_subscriber",
        ].includes(op)
          ? [
              f("maxMessages", "Maximum messages", "number"),
              f("timeout", "Receive timeout seconds", "number"),
              f("acknowledge", "Acknowledge", "boolean"),
            ]
          : []),
        ...(n.type === "kafka"
          ? [f("groupId", "Consumer group"), f("key", "Message key")]
          : []),
      ],
      input: ["publish", "send", "request_reply", "reply"].includes(op)
        ? [
            d("message", "Message payload", "object|string", true),
            d("attributes", "Headers / attributes", "object"),
          ]
        : [],
      output: [
        "receive",
        "get",
        "subscribe",
        "queue_receiver",
        "topic_subscriber",
      ].includes(op)
        ? [
            d("messages", "Received messages", "array"),
            d("count", "Message count", "integer"),
          ]
        : [
            d("messageId", "Message ID"),
            d("destination", "Destination"),
            d("published", "Published", "boolean"),
          ],
      errors: [
        {
          type: "MESSAGING_CONNECTIVITY",
          description: "The broker or service is unavailable.",
        },
        {
          type: "DESTINATION_NOT_FOUND",
          description: "The queue, topic, or subscription does not exist.",
        },
        {
          type: "SERIALIZATION",
          description: "The message could not be serialized or deserialized.",
        },
        {
          type: "ACKNOWLEDGEMENT",
          description: "Message acknowledgement or commit failed.",
        },
      ],
    };
  }
  if (n.type === "sap") {
    const resource = {
        ...f("resourceId", "SAP ECC shared connection", "resource"),
        resourceType: "sap",
      },
      idoc = [
        f("idocType", "IDoc type"),
        f("extensionType", "Extension / CIM type"),
        f("release", "SAP release"),
      ],
      protocol = {
        ...f("invocationProtocol", "Invocation protocol", "select"),
        options: ["Request/Reply", "tRFC", "qRFC", "bgRFC"],
      };
    const configs: Record<string, Field[]> = {
      dynamic_connection: [
        resource,
        {
          ...f("connectionType", "Connection type", "select"),
          options: [
            "dedicated",
            "logongroup",
            "snc",
            "sncwithlogongroup",
            "websocket",
          ],
        },
        f("transactional", "Transactional", "boolean"),
        f("terminateConnection", "Terminate connection", "boolean"),
        f("timeout", "Timeout (ms)", "number"),
      ],
      idoc_acknowledgment: [
        resource,
        f("status", "SAP IDoc status"),
        f("successMessage", "Success message"),
        f("errorMessage", "Error message"),
      ],
      idoc_confirmation: [
        resource,
        f("confirmationMode", "Confirmation mode", "select"),
        f("destination", "Confirmation destination"),
        f("functionName", "Confirmation RFC"),
      ],
      idoc_converter: [
        resource,
        ...idoc,
        {
          ...f("idocOutputMode", "IDoc output mode", "select"),
          options: ["XML", "Raw"],
        },
      ],
      idoc_listener: [
        resource,
        {
          ...f("messagingSource", "Messaging source", "select"),
          options: ["NoMessaging", "JMS", "Kafka"],
        },
        {
          ...f("tidManagerId", "SAP TIDManager resource", "resource"),
          resourceType: "sap_tid",
        },
        ...idoc,
        f("programId", "Program ID"),
        protocol,
      ],
      idoc_parser: [
        resource,
        f("sourceDestination", "IDoc source destination"),
        ...idoc,
      ],
      idoc_reader: [
        resource,
        f("sourceDestination", "IDoc source destination"),
        ...idoc,
        f("confirmationMode", "Confirmation mode"),
      ],
      post_idoc: [
        resource,
        ...idoc,
        {
          ...f("idocInputMode", "IDoc input mode", "select"),
          options: ["XML", "Raw", "qRFC"],
        },
        f("confirmationMode", "Confirmation mode"),
        f("queueName", "SAP queue name"),
      ],
      idoc_renderer: [
        resource,
        ...idoc,
        {
          ...f("idocInputMode", "IDoc input mode", "select"),
          options: ["XML", "Raw"],
        },
      ],
      rfc_bapi_listener: [
        resource,
        f("functionName", "RFC / BAPI name"),
        protocol,
        f("programId", "Program ID"),
        {
          ...f("tidManagerId", "SAP TIDManager resource", "resource"),
          resourceType: "sap_tid",
        },
      ],
      invoke_rfc_bapi: [
        resource,
        f("functionName", "RFC / BAPI name"),
        protocol,
        f("queueName", "SAP queue name"),
        f("transactional", "Transactional", "boolean"),
        f("autoCommit", "Auto commit", "boolean"),
        f("contextEnd", "Context end", "boolean"),
        f("timeout", "Timeout (ms)", "number"),
      ],
      reply_rfc_bapi: [
        resource,
        f("functionName", "RFC / BAPI name"),
        f("listenerActivity", "RFC BAPI Listener activity"),
      ],
      read_table: [
        resource,
        f("tableName", "SAP table / view"),
        f("fields", "Fields (comma separated)"),
        f("where", "ABAP WHERE clauses"),
        f("rowSkip", "Rows to skip", "number"),
        f("rowCount", "Maximum rows", "number"),
        f("delimiter", "Delimiter"),
      ],
    };
    const listener = ["idoc_listener", "rfc_bapi_listener"].includes(op),
      converter = ["idoc_converter", "idoc_parser"].includes(op),
      invoke = op === "invoke_rfc_bapi";
    return {
      configuration: configs[op] || [resource],
      input: listener
        ? []
        : converter
          ? [
              d("SAPIDoc", "SAP IDoc control record", "object", true),
              d("IDoc", "Raw IDoc", "string|object", true),
            ]
          : invoke
            ? [
                d("importParameters", "RFC import parameters", "object"),
                d("changingParameters", "RFC changing parameters", "object"),
                d("tableParameters", "RFC table parameters", "object"),
                d("sessionID", "Dynamic connection session ID"),
              ]
            : op === "read_table"
              ? [
                  d("where", "Dynamic filter clauses", "array"),
                  d("fields", "Dynamic field list", "array"),
                ]
              : [
                  d("payload", "SAP activity payload", "object", true),
                  d("sessionID", "Dynamic connection session ID"),
                ],
      output: listener
        ? [
            d("SAPIDoc", "IDoc/RFC metadata", "object"),
            d("payload", "Inbound SAP payload", "object"),
            d("TID", "Transaction ID"),
          ]
        : converter
          ? [
              d("SAPIDoc", "Converted IDoc XML", "object"),
              d("format", "Output format"),
            ]
          : op === "read_table"
            ? [
                d("rows", "SAP table rows", "array"),
                d("fields", "Field metadata", "array"),
              ]
            : op === "dynamic_connection"
              ? [
                  d("sessionID", "Dynamic SAP session ID"),
                  d("connected", "Connection status", "boolean"),
                  d("transactional", "Transaction mode", "boolean"),
                ]
              : [
                  d("result", "SAP response", "object"),
                  d("successful", "Completion status", "boolean"),
                ],
      errors: [
        {
          type: "SAP_CONNECTION",
          description: "The SAP JCo/RFC connection could not be established.",
        },
        {
          type: "SAP_RFC",
          description: "SAP returned an RFC or BAPI exception.",
        },
        {
          type: "SAP_IDOC",
          description:
            "The IDoc could not be parsed, posted, confirmed, or acknowledged.",
        },
        {
          type: "SAP_TRANSACTION",
          description:
            "The tRFC, qRFC, bgRFC, or transactional context failed.",
        },
        {
          type: "SAP_SCHEMA",
          description:
            "The downloaded RFC, table, or IDoc metadata is invalid.",
        },
      ],
    };
  }
  if (n.type === "transform")
    return {
      configuration: [
        {
          ...f("language", "Mapping language", "select"),
          options: ["JSONPath / functions", "XPath 2.0", "XSLT 2.0"],
        },
      ],
      input: [d("source", "Source document", "object", true)],
      output: [d("result", "Mapped document", "object")],
      errors: [
        { type: "MAPPING", description: "A mapping expression failed." },
        {
          type: "SCHEMA_VALIDATION",
          description: "The mapped output violates its target schema.",
        },
      ],
    };
  if (n.type === "log")
    return {
      configuration: [
        {
          ...f("level", "Log level", "select"),
          options: ["DEBUG", "INFO", "WARN", "ERROR"],
        },
        f("message", "Message template"),
        f("includePayload", "Include payload", "boolean"),
      ],
      input: [
        d("message", "Message expression"),
        d("payload", "Payload", "object"),
      ],
      output: [d("payload", "Unchanged payload", "object")],
      errors: [
        {
          type: "LOGGING",
          description: "The runtime logger rejected the event.",
        },
      ],
    };
  if (n.type === "java")
    return {
      configuration: [
        f("className", "Java class"),
        f("method", "Method"),
        f("classpath", "JAR / classpath"),
        f("timeout", "Timeout seconds", "number"),
      ],
      input: [d("payload", "JSON input", "object")],
      output: [d("result", "Java result", "object")],
      errors: [
        {
          type: "JAVA_CLASS_NOT_FOUND",
          description: "The configured class or JAR cannot be loaded.",
        },
        {
          type: "JAVA_INVOCATION",
          description: "The Java method threw an exception.",
        },
        {
          type: "JAVA_TIMEOUT",
          description: "The worker exceeded its timeout.",
        },
      ],
    };
  return base;
}

export default function ActivityEditor({
  node,
  resources,
  tasks,
  properties,
  schemas,
  tab,
  update,
}: any) {
  const contract = activityContract(node),
    cfg = node.config || {},
    [mapperOpen, setMapperOpen] = useState(false),
    set = (key: string, value: any) =>
      update({ config: { ...cfg, [key]: value } });
  if (tab === "configuration")
    return (
      <div className="activity-tab contract-config">
        <div className="contract-heading">
          <SettingsTitle
            title="Activity configuration"
            text="Operation settings and shared resources"
          />
        </div>
        <div className="contract-grid">
          <label>
            Display name<b>*</b>
            <input
              value={node.name}
              onChange={(e) => update({ name: e.target.value })}
            />
          </label>
          <label>
            Activity kind
            <input value={`${node.type} / ${cfg.operation || ""}`} disabled />
          </label>
          {contract.configuration.map((field) => (
            <FieldEditor
              key={field.key}
              field={field}
              value={cfg[field.key]}
              set={set}
              resources={resources}
              tasks={tasks}
            />
          ))}
        </div>
        {node.type === "transform" && (
          <>
            <TransformSchemaEditor config={cfg} schemas={schemas || []} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>
            <button className="open-mapper" onClick={() => setMapperOpen(true)}>
              <WandSparkles /> Open visual AI Mapper{" "}
              <small>{Array.isArray(cfg.mappings) ? cfg.mappings.length : 0} mappings configured</small>
            </button>
          </>
        )}
        <ExpressionHelp properties={properties} />
        {mapperOpen && (
          <MapperStudio
            config={cfg}
            schemas={schemas || []}
            onClose={() => setMapperOpen(false)}
            onSave={(next: any) => {
              update({ config: { ...cfg, ...next } });
              setMapperOpen(false);
            }}
          />
        )}
      </div>
    );
  if (tab === "input")
    return node.type === "transform" ? (
      <TransformInputEditor config={cfg} schemas={schemas || []} properties={properties} tasks={tasks} setMappings={(value: any) => set("mappings", value)}/>
    ) : (
      <InputEditor
        fields={contract.input}
        mappings={cfg.inputMappings || {}}
        set={(v: any) => set("inputMappings", v)}
        properties={properties}
        tasks={tasks}
      />
    );
  if (tab === "output")
    return node.type === "transform" ? <TransformOutputEditor config={cfg}/> : <OutputEditor fields={contract.output} config={cfg} set={set} />;
  if (tab === "advanced")
    return (
      <AdvancedEditor
        node={node}
        value={cfg.advanced || {}}
        properties={properties}
        set={(v: any) => set("advanced", v)}
      />
    );
  return (
    <ErrorEditor
      errors={contract.errors}
      policy={cfg.errorPolicy || {}}
      set={(v: any) => set("errorPolicy", v)}
    />
  );
}

function TransformSchemaEditor({ config, schemas, setConfig }: any) {
  const choose = (id: string) => {
    if (id === "inline") {
      setConfig({ targetSchemaId: "", targetSchemaText: config.targetSchemaText || "{\n  \"type\": \"object\",\n  \"properties\": {}\n}" });
      return;
    }
    const schema = schemas.find((item: any) => item.id === id);
    if (schema) setConfig({ targetSchemaId: schema.id, targetSchemaText: schema.content });
  };
  const id = config.targetSchemaId || "inline", text = config.targetSchemaText || JSON.stringify(config.targetSchema || {}, null, 2);
  return <div className="transform-schema-editor"><div className="transform-schema-heading"><Braces/><span><b>TARGET TRANSFORMATION CONTRACT</b><small>Select an XSD from Project Schemas or define the target structure inline.</small></span></div><div className="transform-schema-columns single"><section><header><span><b>Target schema</b><small>{id === "inline" ? "Inline JSON Schema, sample JSON, or XSD" : "Project XSD with an editable working copy"}</small></span><select aria-label="Target schema" value={id} onChange={(event) => choose(event.target.value)}><option value="inline">Inline schema…</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></header><textarea aria-label="Target inline schema" value={text} onChange={(event) => setConfig({ targetSchemaId: "", targetSchemaText: event.target.value })} placeholder="Paste target JSON Schema or XSD here…" spellCheck={false}/></section></div></div>;
}

function FieldEditor({ field, value, set, resources, tasks }: any) {
  const change = (v: any) => set(field.key, v);
  return (
    <label
      className={field.type === "textarea" ? "wide" : ""}
      title={field.help || ""}
    >
      {field.label}
      {field.required && <b>*</b>}
      {field.type === "textarea" ? (
        <textarea
          value={value || ""}
          onChange={(e) => change(e.target.value)}
        />
      ) : field.type === "boolean" ? (
        <span className="switch-row">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => change(e.target.checked)}
          />
          {value ? "Enabled" : "Disabled"}
        </span>
      ) : field.type === "select" ? (
        <select
          value={value || field.options?.[0] || ""}
          onChange={(e) => change(e.target.value)}
        >
          {(field.options || ["local", "xa"]).map((x: string) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
      ) : field.type === "resource" ? (
        <select value={value || ""} onChange={(e) => change(e.target.value)}>
          <option value="">Select shared connection…</option>
          {resources
            .filter((r: any) => r.type === field.resourceType)
            .map((r: any) => (
              <option value={r.id} key={r.id}>
                {r.name}
              </option>
            ))}
        </select>
      ) : field.type === "task" ? (
        <select value={value || ""} onChange={(e) => change(e.target.value)}>
          <option value="">Select Sub Task…</option>
          {tasks
            .filter((t: any) => t.kind === "subtask")
            .map((t: any) => (
              <option value={t.id} key={t.id}>
                {t.name}
              </option>
            ))}
        </select>
      ) : (
        <input
          type={field.type === "number" ? "number" : "text"}
          value={value ?? ""}
          onChange={(e) =>
            change(
              field.type === "number" ? Number(e.target.value) : e.target.value,
            )
          }
        />
      )}{" "}
      {field.help && <small>{field.help}</small>}
    </label>
  );
}
function useSourcePaneWidth(initial = 250) {
  const [width, setWidth] = useState(initial), drag = useRef<number | null>(null);
  useEffect(() => {
    const move = (event: PointerEvent) => drag.current != null && setWidth(Math.max(190, Math.min(480, event.clientX - drag.current)));
    const up = () => { drag.current = null; };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, []);
  return { width, begin: (event: React.PointerEvent) => { const box = event.currentTarget.parentElement!.getBoundingClientRect(); drag.current = box.left; event.preventDefault(); } };
}
function DataSourcePane({ properties, tasks = [], onChoose }: any) {
  const [tab, setTab] = useState<"data" | "functions">("data"), [search, setSearch] = useState("");
  const item = (label: string, expression: string, type = "object") => <button key={`${label}-${expression}`} draggable onDragStart={(event) => event.dataTransfer.setData("expression", expression)} onClick={() => onChoose(expression)}><Braces/><span>{label}<small>{expression}</small></span><code>{type}</code></button>;
  const functionItems = mapperFunctions.filter((name) => name.toLowerCase().includes(search.toLowerCase()));
  return <aside className="source-pane"><div className="source-tabs"><button className={tab === "data" ? "active" : ""} onClick={() => setTab("data")}>Data</button><button className={tab === "functions" ? "active" : ""} onClick={() => setTab("functions")}>Functions</button></div><input className="source-search" aria-label={`Search ${tab}`} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${tab}…`}/>{tab === "data" ? <div className="source-list"><h4>PREVIOUS OUTPUT</h4>{item("Initial task input", "${input}")}{item("Previous activity", "${last}")}{tasks.filter((task: any) => task.kind === "subtask").map((task: any) => item(`${task.name} output`, `\${tasks.${task.id}.output}`))}<h4>PROCESS CONTEXT</h4>{item("Task ID", "${context.taskId}", "string")}{item("Environment", "${context.environment}", "string")}{item("Activity ID", "${context.activityId}", "string")}<h4>GLOBAL VARIABLES</h4>{properties.filter((property: any) => property.key.toLowerCase().includes(search.toLowerCase())).map((property: any) => item(property.key, `\${properties.${property.key}}`, property.data_type))}</div> : <div className="source-list function-list"><h4>BW-STYLE FUNCTIONS · {functionItems.length}</h4>{functionItems.map((name) => item(name, `${name}()`, "function"))}</div>}</aside>;
}
function InputEditor({ fields, mappings, set, properties, tasks }: any) {
  const resize = useSourcePaneWidth(), [selected, setSelected] = useState(fields[0]?.key || "");
  const choose = (expression: string) => selected && set({ ...mappings, [selected]: expression });
  return <div className="activity-tab mapping-editor resizable-mapper" style={{ "--source-width": `${resize.width}px` } as React.CSSProperties}><DataSourcePane properties={properties} tasks={tasks} onChoose={choose}/><div className="source-splitter" title="Drag left or right to resize data sources" onPointerDown={resize.begin}><span/></div><section><div className="contract-heading"><SettingsTitle title="Activity input" text="Select a target field, then click or drag data and functions from the left"/></div>{fields.length ? fields.map((field: DataField) => <label className={selected === field.key ? "selected" : ""} key={field.key} onClick={() => setSelected(field.key)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { setSelected(field.key); set({ ...mappings, [field.key]: event.dataTransfer.getData("expression") }); }}><span><b>{field.label}</b>{field.required && <i>required</i>}<small>{field.type}{field.help && ` · ${field.help}`}</small></span><ArrowRight/><input value={mappings[field.key] ?? ""} placeholder={`\${last.${field.key}}`} onChange={(event) => set({ ...mappings, [field.key]: event.target.value })}/></label>) : <div className="contract-empty"><CheckCircle2/>This starter/activity has no configurable input.</div>}</section></div>;
}

type SchemaTreeField = { path: string; name: string; type: string; depth: number };
function transformSchemaFields(config: any): SchemaTreeField[] {
  const text = config.targetSchemaText || JSON.stringify(config.targetSchema || {});
  try {
    const schema = JSON.parse(text), fields: SchemaTreeField[] = [];
    const walk = (node: any, prefix = "", depth = 0) => Object.entries(node?.properties || node || {}).forEach(([name, child]: any) => { const path = prefix ? `${prefix}.${name}` : name; fields.push({ path, name, type: child?.type || typeof child, depth }); if (child?.properties) walk(child, path, depth + 1); });
    walk(schema); return fields;
  } catch {
    return Array.from(text.matchAll(/<(?:xs|xsd):element\b[^>]*\bname=["']([^"']+)["'][^>]*(?:type=["'](?:xs:|xsd:)?([^"']+)["'])?[^>]*>/gi), (match: RegExpMatchArray) => ({ path: match[1], name: match[1], type: match[2] || "complex", depth: 0 }));
  }
}
function TransformInputEditor({ config, properties, tasks, setMappings }: any) {
  const fields = transformSchemaFields(config), resize = useSourcePaneWidth(280), [selected, setSelected] = useState(fields[0]?.path || ""), mappings = Array.isArray(config.mappings) ? config.mappings : [];
  const mapTo = (target: string, source: string) => setMappings([...mappings.filter((rule: any) => rule.target !== target), { target, source, functions: [], enabled: true }]);
  return <div className="activity-tab mapping-editor transform-input-editor resizable-mapper" style={{ "--source-width": `${resize.width}px` } as React.CSSProperties}><DataSourcePane properties={properties} tasks={tasks} onChoose={(expression: string) => selected && mapTo(selected, expression)}/><div className="source-splitter" title="Drag left or right to resize data sources" onPointerDown={resize.begin}><span/></div><section><div className="contract-heading"><SettingsTitle title="Target schema mapping" text="Click a target node, then choose or drag a data source/function"/></div><div className="target-schema-tree">{fields.map((field) => { const rule = mappings.find((item: any) => item.target === field.path); return <div className={`schema-tree-row ${selected === field.path ? "selected" : ""}`} key={field.path} style={{ paddingLeft: 12 + field.depth * 18 }} onClick={() => setSelected(field.path)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => mapTo(field.path, event.dataTransfer.getData("expression"))}><span className="tree-node-dot"/><span className="tree-field"><b>{field.name}</b><small>{field.type} · {field.path}</small></span><span className={`mapping-connection ${rule ? "connected" : ""}`}><i/><ArrowRight/></span><input aria-label={`Mapping for ${field.path}`} value={rule?.source || ""} placeholder="Drop or select a source…" onChange={(event) => mapTo(field.path, event.target.value)}/></div>; })}{!fields.length && <div className="contract-empty">Select a project XSD or enter a valid inline target schema on Configuration.</div>}</div></section></div>;
}
function TransformOutputEditor({ config }: any) {
  const fields = transformSchemaFields(config);
  return <div className="activity-tab output-editor"><div className="contract-heading"><SettingsTitle title="Transformer output structure" text="Published target schema available to downstream activities"/></div><div className="output-schema-tree">{fields.map((field) => <div key={field.path} style={{ paddingLeft: 14 + field.depth * 18 }}><span className="tree-node-dot"/><code>{field.name}</code><small>{field.type}</small><span>{field.path}</span></div>)}{!fields.length && <div className="contract-empty">No target schema is configured.</div>}</div></div>;
}
function OutputEditor({ fields, config, set }: any) {
  return (
    <div className="activity-tab output-editor">
      <div className="contract-heading">
        <SettingsTitle
          title="Activity output schema"
          text="Published values available to downstream activity mappings"
        />
      </div>
      <div className="output-options">
        <label>
          Output name
          <input
            value={config.outputName || ""}
            placeholder="ActivityOutput"
            onChange={(e) => set("outputName", e.target.value)}
          />
        </label>
        <label className="switch-row">
          <input
            type="checkbox"
            checked={config.validateOutput !== false}
            onChange={(e) => set("validateOutput", e.target.checked)}
          />{" "}
          Validate output schema
        </label>
      </div>
      <div className="schema-table">
        <header>
          <b>Field</b>
          <b>Data type</b>
          <b>Cardinality</b>
          <b>Description</b>
        </header>
        {fields.map((field: DataField) => (
          <div key={field.key}>
            <code>{field.key}</code>
            <span>{field.type}</span>
            <span>{field.required ? "1" : "0..1"}</span>
            <span>{field.label}</span>
          </div>
        ))}
      </div>
      {!fields.length && (
        <div className="contract-empty">No output schema is published.</div>
      )}
    </div>
  );
}
function AdvancedEditor({ node, value, properties, set }: any) {
  const defaults = {
      logPayload: "${properties.advanced.logPayload}",
      retryEnabled: "${properties.advanced.retryEnabled}",
      retryCount: "${properties.advanced.retryCount}",
      retryIntervalSeconds: "${properties.advanced.retryIntervalSeconds}",
    },
    advanced = { ...defaults, ...value },
    change = (key: string, next: any) => set({ ...advanced, [key]: next }),
    operation = node.config?.operation || "",
    outbound =
      ["http", "jdbc", "ftp", "sftp", "ems", "kafka", "pubsub"].includes(
        node.type,
      ) ||
      (node.type === "rest" && operation === "invoke") ||
      (node.type === "soap" && operation === "request_reply") ||
      (node.type === "sap" &&
        ![
          "idoc_listener",
          "rfc_bapi_listener",
          "idoc_converter",
          "idoc_parser",
          "idoc_renderer",
        ].includes(operation)),
    resolvedRetry = (() => {
      const match = String(advanced.retryEnabled).match(/^\$\{properties\.([^}]+)\}$/);
      return match
        ? properties.find((item: any) => item.key === match[1])?.value
        : advanced.retryEnabled;
    })(),
    retryDisabled = !(
      resolvedRetry === true ||
      ["true", "1", "yes", "on"].includes(String(resolvedRetry).toLowerCase())
    );
  const suggestions = [
    "true",
    "false",
    ...properties.map((p: any) => "${properties." + p.key + "}"),
  ];
  return (
    <div className="activity-tab advanced-editor">
      <div className="contract-heading">
        <SettingsTitle
          title="Advanced activity settings"
          text="Inherited automatically by every activity type"
        />
      </div>
      <datalist id="advanced-property-values">
        {suggestions.map((item: string) => (
          <option value={item} key={item} />
        ))}
      </datalist>
      <section>
        <article>
          <header>
            <Braces />
            <span>
              <b>Automatic payload logging</b>
              <small>
                Logs activity input and output without placing a Log activity on
                the canvas.
              </small>
            </span>
          </header>
          <label>
            Log Payload{" "}
            <input
              list="advanced-property-values"
              value={advanced.logPayload}
              onChange={(e) => change("logPayload", e.target.value)}
            />
            <small>Boolean or global property expression</small>
          </label>
        </article>
        <article className={!outbound ? "disabled-card" : ""}>
          <header>
            <RefreshCw />
            <span>
              <b>Outbound retry policy</b>
              <small>
                {outbound
                  ? "Applied when this activity calls its target system."
                  : "This activity does not make an outbound target-system call; retry settings are retained but not executed."}
              </small>
            </span>
            <i>{outbound ? "OUTBOUND" : "NOT APPLICABLE"}</i>
          </header>
          <div className="advanced-grid">
            <label>
              Retry{" "}
              <input
                disabled={!outbound}
                list="advanced-property-values"
                value={advanced.retryEnabled}
                onChange={(e) => change("retryEnabled", e.target.value)}
              />
              <small>Boolean or global property expression</small>
            </label>
            <label>
              Retry count{" "}
              <input
                disabled={!outbound || retryDisabled}
                value={advanced.retryCount}
                onChange={(e) => change("retryCount", e.target.value)}
              />
              <small>Default: 3 retry attempts</small>
            </label>
            <label>
              Retry interval (seconds){" "}
              <input
                disabled={!outbound || retryDisabled}
                value={advanced.retryIntervalSeconds}
                onChange={(e) => change("retryIntervalSeconds", e.target.value)}
              />
              <small>Default: 60 seconds</small>
            </label>
          </div>
        </article>
      </section>
      <aside>
        <b>PROJECT-GLOBAL PROPERTY MAPPINGS</b>
        <p>
          The active environment is resolved once for the complete project,
          including every Task, Sub Task, activity, and shared connection.
        </p>
        <div>
          {properties
            .filter((p: any) => p.key.startsWith("advanced."))
            .map((p: any) => (
              <button
                key={p.key}
                onClick={() =>
                  navigator.clipboard?.writeText("${properties." + p.key + "}")
                }
              >
                <Braces />
                <span>
                  {p.key}
                  <small>
                    {p.data_type} · {String(p.value)}
                  </small>
                </span>
              </button>
            ))}
        </div>
      </aside>
    </div>
  );
}
function ErrorEditor({ errors, policy, set }: any) {
  const change = (k: string, v: any) => set({ ...policy, [k]: v });
  return (
    <div className="activity-tab error-editor">
      <div className="contract-heading">
        <SettingsTitle
          title="Errors and fault policy"
          text="Operation-declared faults plus runtime handling"
        />
      </div>
      <div className="error-layout">
        <section>
          <h4>DECLARED ERROR TYPES</h4>
          {errors.length ? (
            errors.map((error: any) => (
              <article key={error.type}>
                <ShieldAlert />
                <span>
                  <b>{error.type}</b>
                  <small>{error.description}</small>
                </span>
              </article>
            ))
          ) : (
            <div className="contract-empty">
              <CheckCircle2 />
              No activity-specific faults.
            </div>
          )}
        </section>
        <aside>
          <label>
            On error
            <select
              value={policy.action || "propagate"}
              onChange={(e) => change("action", e.target.value)}
            >
              <option value="propagate">Propagate to error transition</option>
              <option value="continue">Continue with error document</option>
              <option value="ignore">Ignore and continue</option>
            </select>
          </label>
          <p>
            Outbound retry is configured consistently for all connectors on the
            Advanced tab.
          </p>
          <label>
            Error output variable
            <input
              value={policy.outputVariable || ""}
              placeholder="activityError"
              onChange={(e) => change("outputVariable", e.target.value)}
            />
          </label>
          <label className="switch-row">
            <input
              type="checkbox"
              checked={policy.includeInput !== false}
              onChange={(e) => change("includeInput", e.target.checked)}
            />{" "}
            Include activity input in fault
          </label>
        </aside>
      </div>
    </div>
  );
}
function SettingsTitle({ title, text }: any) {
  return (
    <>
      <div>
        <Database />
        <span>
          <b>{title}</b>
          <small>{text}</small>
        </span>
      </div>
    </>
  );
}
function ExpressionHelp({ properties }: any) {
  return (
    <div className="expression-strip">
      <AlertTriangle />
      <span>
        Dynamic expressions are supported in every text field:{" "}
        <code>${"{input.id}"}</code> <code>${"{last.value}"}</code>
        {properties.slice(0, 2).map((p: any) => (
          <code key={p.key}>${"{properties." + p.key + "}"}</code>
        ))}
      </span>
    </div>
  );
}
