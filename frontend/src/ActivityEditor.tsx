import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Braces,
  CheckCircle2,
  Database,
  ExternalLink,
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
    | "artifact"
    | "idoc"
    | "task";
  options?: string[];
  resourceType?: string;
  artifactType?: "java" | "python";
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
type DataTreeRow = DataField & { path: string; name: string; depth: number; group: boolean; explicit: boolean };
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
  "concat", "substring", "substringBefore", "substringAfter", "stringLength", "normalizeSpace", "upperCase", "lowerCase", "translate", "trim", "replace", "matches", "tokenize", "startsWith", "endsWith", "contains", "compare", "codepointsToString", "stringToCodepoints", "format", "parseDate", "formatDate", "formatDateTime", "currentDate", "currentTime", "currentDateTime", "timezoneFromDateTime", "adjustDateTimeToTimezone", "addDays", "addMonths", "dateDifference", "yearsFromDuration", "monthsFromDuration", "daysFromDuration", "hoursFromDuration", "minutesFromDuration", "secondsFromDuration", "number", "integer", "decimal", "round", "roundHalfToEven", "floor", "ceiling", "abs", "min", "max", "sum", "average", "count", "boolean", "not", "true", "false", "ifThenElse", "coalesce", "exists", "empty", "default", "distinctValues", "deepEqual", "sort", "reverse", "subsequence", "insertBefore", "remove", "first", "last", "position", "indexOf", "join", "split", "filter", "map", "reduce", "forEach", "forEachGroup", "localName", "namespaceUri", "name", "nodeName", "root", "path", "data", "nil", "isNil", "jsonParse", "jsonRender", "xmlParse", "xmlRender", "base64Encode", "base64Decode", "hexEncode", "hexDecode", "urlEncode", "urlDecode", "uuid", "hash", "xpath", "jsonPath", "property", "processContext", "taskOutput", "lookup", "crossReference", "trace", "error"
];

type StructuredMapping = { $rule: "for-each" | "for-each-group" | "if" | "when-otherwise"; source: any; select?: string; groupBy?: string; condition?: string; otherwise?: any; duplicateOf?: string };
const mappingSource = (value: any) => value && typeof value === "object" && "$rule" in value ? value.source : value;

function MappingContextMenu({ menu, value, close, change, remove }: any) {
  const panel = useRef<HTMLDivElement>(null), source = String(mappingSource(value) || "${last}"), [mode, setMode] = useState<StructuredMapping["$rule"] | "">(""), [select, setSelect] = useState(source), [condition, setCondition] = useState(`exists(${source})`), [groupBy, setGroupBy] = useState("id"), [otherwise, setOtherwise] = useState("");
  useEffect(() => {
    if (!menu) return;
    const dismiss = (event: PointerEvent) => { if (!panel.current?.contains(event.target as globalThis.Node)) close(); };
    window.addEventListener("pointerdown", dismiss);
    return () => window.removeEventListener("pointerdown", dismiss);
  }, [menu, close]);
  useEffect(() => { if (menu) { const next = String(mappingSource(value) || "${last}"); setMode(""); setSelect(next); setCondition(`exists(${next})`); setGroupBy("id"); setOtherwise(""); } }, [menu, value]);
  if (!menu) return null;
  const apply = (next: StructuredMapping) => { change(next); close(); };
  const commit = () => mode && apply({ $rule: mode, source, select: select || source, condition, groupBy, otherwise });
  const content = <div ref={panel} className="mapping-context-menu" style={{ left: Math.max(8, Math.min(menu.x, window.innerWidth - 350)), top: Math.max(8, Math.min(menu.y, window.innerHeight - 455)) }} onPointerDown={(event) => event.stopPropagation()}>
    <header><Braces/><span><b>{menu.label}</b><small>Mapping statement</small></span></header>
    <button className={mode === "for-each" ? "selected" : ""} onClick={() => setMode("for-each")}>For Each…<small>Iterate a repeating source value</small></button>
    <button className={mode === "for-each-group" ? "selected" : ""} onClick={() => setMode("for-each-group")}>For Each Group…<small>Group repeated values before mapping</small></button>
    <button className={mode === "if" ? "selected" : ""} onClick={() => setMode("if")}>If…<small>Emit this target only when true</small></button>
    <button className={mode === "when-otherwise" ? "selected" : ""} onClick={() => setMode("when-otherwise")}>When / Otherwise…<small>Choose between two mapping values</small></button>
    {mode && <section className="mapping-rule-editor"><label>Source expression<input value={select} onChange={(event) => setSelect(event.target.value)}/></label>{mode === "for-each-group" && <label>Group-by child path<input value={groupBy} onChange={(event) => setGroupBy(event.target.value)}/></label>}{(mode === "if" || mode === "when-otherwise") && <label>Condition<input value={condition} onChange={(event) => setCondition(event.target.value)}/></label>}{mode === "when-otherwise" && <label>Otherwise value/expression<input value={otherwise} onChange={(event) => setOtherwise(event.target.value)}/></label>}<div><button onClick={() => setMode("")}>Cancel</button><button className="apply" onClick={commit}>Apply mapping</button></div></section>}
    <button disabled={!value} onClick={() => { change(typeof value === "object" ? { ...value, duplicateOf: `${menu.path}-${Date.now()}` } : { $rule: "if", source: value, condition: "true()", duplicateOf: `${menu.path}-${Date.now()}` }); close(); }}>Duplicate mapping<small>Create an independently editable statement</small></button>
    <button disabled={!value} className="danger" onClick={() => { remove(); close(); }}>Delete mapping<small>Remove the target expression</small></button>
  </div>;
  return createPortal(content, document.body);
}

function dataTreeRows(fields: DataField[]): DataTreeRow[] {
  type Node = { name: string; path: string; children: Map<string, Node>; field?: DataField };
  const root: Node = { name: "", path: "", children: new Map() };
  fields.forEach((field) => {
    let parent = root;
    field.key.split(".").filter(Boolean).forEach((name, index, parts) => {
      const path = parts.slice(0, index + 1).join(".");
      if (!parent.children.has(name)) parent.children.set(name, { name, path, children: new Map() });
      parent = parent.children.get(name)!;
      if (index === parts.length - 1) parent.field = field;
    });
  });
  const rows: DataTreeRow[] = [];
  const walk = (node: Node, depth: number) => {
    const group = node.children.size > 0, field = node.field;
    rows.push({
      key: node.path, path: node.path, name: node.name,
      label: field?.label || node.name.replace(/([a-z])([A-Z])/g, "$1 $2"),
      type: field?.type || "object", required: field?.required, help: field?.help,
      depth, group, explicit: !!field,
    });
    node.children.forEach((child) => walk(child, depth + 1));
  };
  root.children.forEach((child) => walk(child, 0));
  return rows;
}

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
  if (n.type === "confirm")
    return {
      configuration: [
        f("ackId", "Acknowledgement handle", "text", "Map the ackId emitted by a JMS, Kafka, Pub/Sub, or future client-acknowledge receiver."),
        f("failIfMissing", "Fail when handle is missing", "boolean"),
      ],
      input: [d("ackId", "Acknowledgement handle", "string|array", true), d("ackIds", "Multiple acknowledgement handles", "array")],
      output: [d("confirmed", "Confirmation status", "boolean"), d("count", "Confirmed message count", "integer"), d("technologies", "Confirmed transports", "array")],
      errors: [
        { type: "ACKNOWLEDGEMENT_NOT_FOUND", description: "The acknowledgement handle is missing, expired, or was already confirmed." },
        { type: "ACKNOWLEDGEMENT_FAILED", description: "The transport rejected the message confirmation." },
      ],
    };
  if (n.type === "catch")
    return {
      configuration: [{ ...f("catchAll", "Catch all unhandled exceptions", "boolean") }, f("errorType", "Exception type", "text", "Used when Catch All is false; for example XMLParseException."), f("errorCode", "Error code filter")],
      input: [],
      output: [d("type", "Exception type"), d("code", "Error code"), d("message", "Error message"), d("activityId", "Failed activity ID"), d("details", "Fault details", "object"), d("cause", "Original cause", "object")],
      errors: [],
    };
  if (n.type === "throw")
    return {
      configuration: [f("errorType", "Exception type"), f("code", "Error code"), f("message", "Error message"), f("details", "Fault details (JSON)", "textarea")],
      input: [d("message", "Error message", "string", true), d("code", "Error code"), d("type", "Exception type"), d("details", "Fault details", "object")],
      output: [],
      errors: [{ type: "UserDefinedException", description: "The configured business fault is raised to the nearest matching handler." }],
    };
  if (n.type === "rethrow")
    return {
      configuration: [], input: [d("error", "Current caught exception", "object")], output: [],
      errors: [{ type: "RethrowException", description: "The current caught fault is propagated to the next available handler or calling task." }],
    };
  if (n.type === "file") {
    const common = [f("path", "Filename / directory", "text", "Absolute paths and project-property expressions are supported."), f("includeTimestamp", "Include timestamp metadata", "boolean")];
    const configs: Record<string, Field[]> = {
      read: [...common, { ...f("readAs", "Read as", "select"), options: ["Text", "Binary"] }, f("excludeFileContent", "Exclude file content", "boolean"), f("encoding", "Text encoding")],
      write: [...common, { ...f("writeAs", "Write as", "select"), options: ["Text", "Binary"] }, f("encoding", "Text encoding"), f("append", "Append to existing file", "boolean"), f("overwrite", "Overwrite existing file", "boolean"), f("createDirectories", "Create non-existing directories", "boolean"), f("addLineSeparator", "Add line separator", "boolean"), { ...f("compression", "Compression", "select"), options: ["None", "GZip"] }],
      list: [...common, f("pattern", "File name pattern / wildcard"), f("recursive", "Recursive", "boolean"), { ...f("listType", "List", "select"), options: ["Files and Directories", "Only Files", "Only Directories"] }, { ...f("sortBy", "Sort by", "select"), options: ["Name", "Size", "Last Modified"] }, { ...f("sortOrder", "Sort order", "select"), options: ["Ascending", "Descending"] }],
      delete: [...common, f("recursive", "Remove non-empty directory recursively", "boolean"), f("ignoreMissing", "Ignore missing file", "boolean")],
      rename: [...common, f("destination", "To filename"), f("overwrite", "Overwrite existing file", "boolean"), f("createDirectories", "Create non-existing directories", "boolean")],
      copy: [...common, f("destination", "Destination filename / directory"), f("overwrite", "Overwrite existing file", "boolean"), f("createDirectories", "Create non-existing directories", "boolean"), f("preserveAttributes", "Preserve file attributes", "boolean"), f("recursive", "Copy directory recursively", "boolean")],
      poll: [...common, f("pattern", "File name pattern / wildcard"), { ...f("eventType", "Change type", "select"), options: ["Created", "Modified", "Deleted", "Any"] }, f("pollInterval", "Poll interval (seconds)", "number"), f("includeExisting", "Include existing files", "boolean"), f("recursive", "Recursive", "boolean"), { ...f("postAction", "After processing", "select"), options: ["None", "Delete", "Move"] }, f("moveTo", "Move processed file to")],
    };
    const cfg = configs[op] || common;
    const inputs: Record<string, DataField[]> = {
      read: [d("path", "Filename", "string", true), d("encoding", "Text encoding")],
      write: [d("path", "Filename", "string", true), d("textContent", "Text content", "string"), d("binaryContent", "Binary content", "base64"), d("encoding", "Text encoding"), d("addLineSeparator", "Add line separator", "boolean")],
      list: [d("path", "Directory / wildcard", "string", true), d("recursive", "Recursive", "boolean")],
      delete: [d("path", "Filename / directory", "string", true), d("recursive", "Recursive", "boolean")],
      rename: [d("path", "From filename", "string", true), d("destination", "To filename", "string", true)],
      copy: [d("path", "Source filename / directory", "string", true), d("destination", "Destination filename / directory", "string", true), d("recursive", "Recursive", "boolean")],
      poll: [],
    };
    const outputs =
      op === "read"
        ? [
            d("textContent", "Text file content", "string"), d("binaryContent", "Binary file content", "base64"),
            d("fileInfo.fullName", "Full filename"), d("fileInfo.fileName", "Filename"), d("fileInfo.location", "Location"), d("fileInfo.type", "File type"), d("fileInfo.readProtected", "Read protected", "boolean"), d("fileInfo.writeProtected", "Write protected", "boolean"), d("fileInfo.size", "Size", "integer"), d("fileInfo.lastModified", "Last modified", "dateTime"),
          ]
        : op === "list" || op === "poll"
          ? [
            d("files", "Matched file information", "array"),
            d("count", "File count", "integer"),
            d("eventType", "Detected change", "string"),
            ]
          : [
              d("path", "Affected path"),
              d("success", "Operation result", "boolean"),
            ];
    return {
      configuration: cfg,
      input: inputs[op] || [d("path", "Filename / directory", "string", true)],
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
    const parsing = op === "parse";
    return {
      configuration: [
        ...(n.type === "xml"
          ? [
              { ...f(parsing ? "inputStyle" : "outputStyle", parsing ? "Input style" : "Output style", "select"), options: parsing ? ["Text", "Binary", "Dynamic"] : ["Text", "Binary"] },
              f(parsing ? "validateOutput" : "validateInput", parsing ? "Validate parsed output" : "Validate input tree", "boolean"),
              f("encoding", "Encoding"),
              ...(parsing ? [] : [f("suppressXmlDeclaration", "Suppress XML declaration", "boolean"), f("prettyPrint", "Pretty print", "boolean")]),
            ]
          : n.type === "json"
            ? [
                f(parsing ? "validateOutput" : "validateInput", parsing ? "Validate parsed output" : "Validate input tree", "boolean"),
                ...(parsing ? [{ ...f("duplicateKeyPolicy", "Duplicate keys", "select"), options: ["Last wins", "First wins", "Error"] }] : [{ ...f("rootStyle", "JSON root", "select"), options: ["With root", "Anonymous"] }, f("prettyPrint", "Pretty print", "boolean"), f("indent", "Indent spaces", "number"), f("asciiOnly", "Escape non-ASCII characters", "boolean"), f("omitNulls", "Omit null fields", "boolean")]),
              ]
            : [
                { ...f("format", "Format", "select"), options: ["delimited", "fixed"] },
                f("delimiter", "Column separator"),
                { ...f("separatorRule", "Multi-character separator rule", "select"), options: ["single", "any-character"] },
                { ...f("lineSeparator", "Line separator", "select"), options: ["Auto", "LF", "CRLF", "CR"] },
                f("header", "First row is header", "boolean"),
                f("widths", "Fixed field widths"),
                f("fillCharacter", "Fixed-width fill character"),
                f("strictColumns", "Require exact column count", "boolean"),
                f("trimValues", "Trim parsed values", "boolean"),
                f("skipBlankLines", "Skip blank lines", "boolean"),
                f("includeFinalLineSeparator", "Append final line separator", "boolean"),
              ]),
      ],
      input: n.type === "xml" && parsing ? [d("xmlString", "XML text", "string"), d("xmlBinary", "XML binary/base64", "binary"), d("forceEncoding", "Forced encoding")] : n.type === "xml" ? [d("value", "XML schema tree", "object", true)] : n.type === "json" && parsing ? [d("jsonString", "JSON text", "string", true)] : n.type === "json" ? [d("value", "JSON schema tree", "object", true)] : [d(parsing ? "text" : "records", parsing ? "Formatted text" : "Data records", parsing ? "string" : "array", true)],
      output: parsing
        ? [d(n.type === "flat" ? "records" : "value", "Parsed schema tree", n.type === "flat" ? "array" : "object")]
        : [d(n.type === "xml" ? "xmlString" : n.type === "json" ? "jsonString" : "text", `Rendered ${format} text`, "string")],
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
  if (n.type === "ems") {
    const resource = { ...f("resourceId", "JMS / TIBCO EMS connection", "resource"), resourceType: "ems", required: true },
      messageType = { ...f("messageType", "Message type", "select"), options: ["Text", "Bytes", "Map", "Object", "Object Ref", "Simple", "Stream", "XML Text"] },
      style = { ...f("messagingStyle", "Messaging style", "select"), options: ["Queue", "Topic", "Generic"] },
      ack = { ...f("acknowledgeMode", "Acknowledge mode", "select"), options: ["Auto", "Client", "Dups OK", "Explicit Client", "Explicit Client Dups OK", "Transactional"] },
      receiver = [resource, style, f(op.includes("queue") ? "queue" : "topic", "Destination", "text", "Queue or topic name; expressions are supported."), messageType, f("messageSelector", "JMS message selector"), ack, f("maxSessions", "Maximum sessions", "number"), f("flowLimit", "Flow limit", "number"), f("receiveTimeout", "Receive timeout (ms)", "number")],
      sender = [resource, style, f(op.includes("queue") ? "queue" : "topic", "Destination"), messageType,
        { ...f("deliveryMode", "Delivery mode", "select"), options: ["Persistent", "Non-Persistent"] }, f("priority", "Priority (0-9)", "number"), f("expiration", "Expiration (ms)", "number"), f("correlationId", "JMS correlation ID"), f("replyTo", "Reply-to destination"), f("disableMessageId", "Disable JMS message ID", "boolean"), f("disableTimestamp", "Disable JMS timestamp", "boolean"), f("dynamicProperties", "JMS application / dynamic properties (JSON)", "textarea")];
    const configs: Record<string, Field[]> = {
      queue_receiver: receiver,
      topic_subscriber: [...receiver, f("durable", "Durable subscriber", "boolean"), f("subscriptionName", "Durable subscription name"), f("sharedSubscription", "Shared subscription", "boolean")],
      queue_sender: sender,
      topic_publisher: sender,
      request_reply: [...sender, f("requestTimeout", "Request timeout (ms)", "number"), f("temporaryReplyDestination", "Use temporary reply destination", "boolean")],
      reply: [resource, style, f("destination", "Reply destination"), messageType, f("correlationId", "Request correlation ID"), ...sender.slice(4)],
    };
    const receiving = ["queue_receiver", "topic_subscriber"].includes(op);
    return {
      configuration: configs[op] || [resource],
      input: receiving ? [] : [d("message", "JMS message body", "object|string|binary", true), d("destination", "Dynamic destination override"), d("dynamicProperties", "Dynamic JMS properties", "object"), d("headers", "JMS headers", "object")],
      output: receiving ? [d("body", "JMS message body", "object|string|binary"), d("headers", "JMS standard headers", "object"), d("properties", "JMS application properties", "object"), d("ackId", "Client acknowledgement handle")] : op === "request_reply" ? [d("body", "Reply message body", "object|string|binary"), d("headers", "Reply JMS headers", "object"), d("properties", "Reply properties", "object")] : [d("messageId", "JMS message ID"), d("destination", "Resolved destination"), d("timestamp", "JMS timestamp", "dateTime")],
      errors: [
        { type: "JMSInvalidInputException", description: "The JMS activity input is invalid." },
        { type: "JMSMessageCreateException", description: "The configured JMS message could not be created." },
        { type: "JMSSessionCreateException", description: "A JMS session could not be created." },
        { type: receiving ? "JMSReceiveException" : "JMSSendException", description: `The JMS message could not be ${receiving ? "received" : "sent"}.` },
        { type: "ActivityTimedOutException", description: "The JMS operation reached its configured timeout." },
      ],
    };
  }
  if (n.type === "kafka") {
    const resource = { ...f("resourceId", "Kafka connection", "resource"), resourceType: "kafka", required: true },
      registry = [f("useRegistry", "Use Schema Registry", "boolean"), f("schemaRegistryUrl", "Schema Registry URL"), f("keySchemaSubject", "Key schema subject : version"), f("valueSchemaSubject", "Value schema subject : version")],
      serialization = [{ ...f("keySerializer", "Key serializer", "select"), options: ["String", "Byte Array", "Avro Schema", "JSON"] }, { ...f("valueSerializer", "Value serializer", "select"), options: ["String", "Byte Array", "Avro Schema", "JSON"] }, ...registry],
      consumerSerialization = [{ ...f("keyDeserializer", "Key deserializer", "select"), options: ["String", "Byte Array", "Avro Schema", "JSON"] }, { ...f("valueDeserializer", "Value deserializer", "select"), options: ["String", "Byte Array", "Avro Schema", "JSON"] }, ...registry],
      consumer = [resource, f("groupId", "Consumer group ID"), f("topic", "Topic names", "text", "Separate multiple topic names with semicolons."), f("assignCustomPartition", "Assign custom partitions", "boolean"), f("partitionIds", "Partition IDs / ranges"), f("consumerCount", "Consumer count", "number"), ...consumerSerialization, { ...f("acknowledgeMode", "Acknowledgement mode", "select"), options: ["Auto", "Manual"] }, f("enableAutoCommit", "Enable auto commit", "boolean"), f("autoOffsetReset", "Auto offset reset", "select"), f("fetchMinBytes", "Fetch minimum bytes", "number"), f("maxPollRecords", "Maximum poll records", "number"), f("sessionTimeoutMs", "Session timeout (ms)", "number"), f("heartbeatIntervalMs", "Heartbeat interval (ms)", "number"), f("additionalProperties", "Additional consumer properties (JSON)", "textarea")];
    const configs: Record<string, Field[]> = {
      send: [resource, f("topic", "Topic name"), f("assignCustomPartition", "Assign custom partition", "boolean"), f("partitionId", "Partition ID", "number"), ...serialization, { ...f("acks", "Acknowledgements", "select"), options: ["0", "1", "all"] }, { ...f("compressionType", "Compression type", "select"), options: ["none", "gzip", "snappy", "lz4", "zstd"] }, f("retries", "Producer retries", "number"), f("bufferMemory", "Buffer memory (bytes)", "number"), f("batchSize", "Batch size", "number"), f("lingerMs", "Linger (ms)", "number"), f("maxRequestSize", "Maximum request size", "number"), f("transactionalId", "Transactional ID"), f("enableIdempotence", "Enable idempotence", "boolean"), f("additionalProperties", "Additional producer properties (JSON)", "textarea")],
      receive: consumer,
      get: [...consumer, { ...f("seekPosition", "Seek position", "select"), options: ["current", "beginning", "end", "custom"] }, f("customOffset", "Custom offset", "number"), f("maxMessages", "Maximum messages", "number"), f("timeout", "Poll timeout (seconds)", "number")],
    };
    const receiving = ["receive", "get"].includes(op);
    return {
      configuration: configs[op] || [resource],
      input: receiving ? (op === "get" ? [d("topic", "Dynamic topic override"), d("partition", "Dynamic partition", "integer"), d("offset", "Dynamic offset", "long")] : []) : [d("message", "Kafka record value", "object|string|binary", true), d("key", "Kafka record key", "string|binary"), d("headers", "Kafka headers", "object"), d("topic", "Dynamic topic override"), d("partitionId", "Dynamic partition", "integer")],
      output: receiving ? [d("messages", "Kafka records", "array"), d("count", "Record count", "integer"), d("topic", "Topic"), d("partition", "Partition", "integer"), d("offset", "Offset", "long"), d("timestamp", "Record timestamp", "dateTime"), d("headers", "Record headers", "object"), d("ackId", "Manual acknowledgement handle")] : [d("messageId", "Generated record ID"), d("topic", "Topic"), d("partition", "Partition", "integer"), d("offset", "Offset", "long"), d("timestamp", "Record timestamp", "dateTime")],
      errors: [
        { type: "KafkaConnectionException", description: "The Kafka connection or broker is unavailable." },
        { type: "KafkaSerializationException", description: "The record key or value could not be serialized/deserialized." },
        { type: "KafkaProducerException", description: "The producer could not publish the record." },
        { type: "KafkaConsumerException", description: "The consumer could not fetch or acknowledge records." },
        { type: "KafkaSchemaRegistryException", description: "The Avro schema or registry subject could not be resolved." },
      ],
    };
  }
  if (n.type === "pubsub") {
    const resource = { ...f("resourceId", "Google Pub/Sub connection", "resource"), resourceType: "pubsub", required: true };
    const receiving = op === "subscribe";
    return {
      configuration: receiving ? [resource, f("projectId", "Project ID override"), f("subscription", "Subscription ID"), f("maxMessages", "Maximum message fetch count", "number"), { ...f("acknowledgeMode", "Acknowledge mode", "select"), options: ["Auto", "Client"] }, f("receiveTimeout", "Receive timeout (seconds)", "number"), f("sequenceKey", "Sequence key expression"), f("customJobId", "Custom job ID expression")] : [resource, f("projectId", "Project ID override"), f("topic", "Topic ID"), f("orderingKey", "Ordering key"), f("publishTimeout", "Publish timeout (seconds)", "number")],
      input: receiving ? [] : [d("data", "Message data", "string|binary", true, "Data or at least one attribute is required."), d("attributes", "Message attributes", "object"), d("topic", "Dynamic Topic ID")],
      output: receiving ? [d("MessageID", "Google message ID"), d("PublishTime", "Publish time", "dateTime"), d("Data", "Message data"), d("Attributes", "Message attributes", "object"), d("AckID", "Client acknowledgement handle")] : [d("TopicName", "Published topic name"), d("MessageID", "Google message ID")],
      errors: receiving ? [{ type: "GooglePubSubPluginException", description: "The subscriber could not receive or acknowledge the message." }, { type: "GooglePubSubConnectionException", description: "The Google Pub/Sub connection is unavailable." }] : [{ type: "GooglePublisherException", description: "The message could not be published." }, { type: "GooglePubSubConnectionException", description: "The Google Pub/Sub connection is unavailable." }, { type: "PublisherInvalidInputException", description: "Publisher requires message data or at least one attribute." }],
    };
  }
  if (n.type === "sap") {
    const resource = {
        ...f("resourceId", "SAP ECC shared connection", "resource"),
        resourceType: "sap",
      },
      idoc = [
        f("idocType", "IDoc type fetched from SAP", "idoc", "IDoc metadata is provided by the selected SAP ECC shared connection."),
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
  if (n.type === "transform" || n.type === "ai_transform")
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
        { ...f("mode", "Source mode", "select"), options: ["JAR / class", "Inline source"] },
        { ...f("artifactPath", "JAR, .class, or .java", "artifact"), artifactType: "java" },
        f("className", "Fully qualified Java class"),
        f("method", "Method"),
        f("instantiate", "Instantiate class", "boolean"),
        f("sourceCode", "Inline Java source", "textarea"),
        f("timeout", "Timeout seconds", "number"),
      ],
      input: [d("parameters", "Method parameters", "array"), d("payload", "JSON input", "object")],
      output: [d("methodReturnValue", "Method return value", "object"), d("className", "Invoked class"), d("method", "Invoked method")],
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
  if (n.type === "python")
    return {
      configuration: [
        { ...f("mode", "Source mode", "select"), options: ["Python file / package", "Inline source"] },
        { ...f("artifactPath", ".py, .zip, or .whl", "artifact"), artifactType: "python" },
        f("moduleName", "Module name"), f("function", "Function"), f("sourceCode", "Inline Python source", "textarea"), f("timeout", "Timeout seconds", "number"),
      ],
      input: [d("parameters", "Function parameters", "array"), d("payload", "JSON input", "object")],
      output: [d("result", "Python result", "object"), d("module", "Loaded module"), d("function", "Invoked function")],
      errors: [{ type: "PYTHON_IMPORT", description: "The module or package could not be imported." }, { type: "PYTHON_INVOCATION", description: "The selected Python function raised an exception." }],
    };
  if (n.type === "basic") {
    const basic: Record<string, Contract> = {
      empty: { configuration: [], input: [], output: [d("payload", "Unchanged payload", "object")], errors: [] },
      assign: { configuration: [f("variable", "Process variable", "text", "Name stored in process variables.")], input: [d("value", "Assigned value", "object", true)], output: [d("name", "Variable name"), d("value", "Assigned value", "object")], errors: commonErrors.slice(2) },
      sleep: { configuration: [f("duration", "Duration", "number"), { ...f("unit", "Unit", "select"), options: ["milliseconds", "seconds", "minutes"] }], input: [d("duration", "Dynamic duration", "number")], output: [d("sleptMilliseconds", "Elapsed delay", "integer")], errors: [{ type: "INTERRUPTED", description: "The wait was interrupted or cancelled." }] },
      get_context: { configuration: [], input: [], output: [d("taskId", "Task ID"), d("activityId", "Activity ID"), d("environment", "Environment"), d("correlationId", "Correlation ID")], errors: [] },
      set_context: { configuration: [], input: [d("values", "Context values", "object", true)], output: [d("context", "Updated process context", "object")], errors: commonErrors.slice(2) },
      get_shared_variable: { configuration: [f("name", "Shared variable name")], input: [d("default", "Default value", "object")], output: [d("name", "Variable name"), d("value", "Shared value", "object")], errors: [] },
      set_shared_variable: { configuration: [f("name", "Shared variable name")], input: [d("value", "Shared value", "object", true)], output: [d("name", "Variable name"), d("value", "Shared value", "object")], errors: [] },
      inspector: { configuration: [f("label", "Inspection label"), f("includePayload", "Include payload", "boolean")], input: [d("payload", "Inspected payload", "object")], output: [d("payload", "Unchanged payload", "object")], errors: [] },
    };
    return basic[op] || base;
  }
  return base;
}

function schemaDataFields(value: any): DataField[] {
  if (!value) return [];
  const config = typeof value === "string" ? { targetSchemaText: value } : { targetSchema: value };
  return transformSchemaFields(config).map((field) => d(field.path, field.name, field.type));
}

function activitySchemaText(node: any, schemas: any[]): string {
  const configured = node.config?.schemaText;
  if (configured) return configured;
  const selected = schemas.find((schema: any) => schema.id === node.config?.schemaId || schema.name === node.config?.schemaId);
  return selected?.content || "";
}

function boundaryFields(task: any, boundaryType: "start" | "end", schemas: any[]): DataField[] {
  if (!task) return [];
  const boundary = (task.activities || []).find((activity: any) => activity.type === boundaryType);
  const config = boundary?.config || {};
  const schemaId = config.interfaceSchemaId;
  const selected = schemaId ? schemas.find((schema: any) => schema.id === schemaId) : null;
  const configured = config.interfaceSchemaText || selected?.content;
  const modelSchema = boundaryType === "start" ? task.input_schema : task.output_schema;
  return schemaDataFields(configured || modelSchema);
}

function resolvedActivityContract(node: any, task: any, tasks: any[], schemas: any[]): Contract {
  const contract = activityContract(node);
  if (["xml", "json", "flat"].includes(node.type)) {
    const schemaFields = schemaDataFields(activitySchemaText(node, schemas));
    if (!schemaFields.length) return contract;
    const parsing = node.config?.operation === "parse";
    const flatLeaves = schemaFields.filter((field) => !schemaFields.some((candidate) => candidate.key.startsWith(`${field.key}.`)));
    const fields = node.type === "flat"
      ? [d("records", "Records", "array"), ...flatLeaves.map((field) => ({ ...field, key: `records.${field.label}` }))]
      : schemaFields;
    return parsing ? { ...contract, output: fields } : { ...contract, input: fields };
  }
  if (node.type === "start") {
    const fields = boundaryFields(task, "start", schemas);
    return fields.length ? { ...contract, input: [], output: fields } : contract;
  }
  if (node.type === "end") {
    const fields = boundaryFields(task, "end", schemas);
    return fields.length ? { ...contract, input: fields, output: fields } : contract;
  }
  if (node.type === "call_task") {
    const called = tasks.find((candidate: any) => candidate.id === (node.config?.dynamicTaskId || node.config?.taskId) && candidate.kind === "subtask");
    const input = boundaryFields(called, "start", schemas), output = boundaryFields(called, "end", schemas);
    return {
      ...contract,
      input: input.length ? input : contract.input,
      output: output.length ? output : contract.output,
    };
  }
  return contract;
}

function runtimeMappableInputs(node: any, contract: Contract): DataField[] {
  if (["xml", "json", "flat"].includes(node.type)) return contract.input;
  if (["start", "timer", "http_listener"].includes(node.type) || (node.type === "file" && node.config?.operation === "poll")) return contract.input;
  const existing = new Set(contract.input.map((field) => field.key));
  const inferred = (field: Field) => field.type === "number" ? "number" : field.type === "boolean" ? "boolean" : "string";
  const dynamic = contract.configuration
    .filter((field) => !existing.has(field.key) && !["resource", "task", "idoc"].includes(field.type || "text"))
    .map((field) => d(field.key, field.label, inferred(field), !!field.required, field.help));
  return [...contract.input, ...dynamic];
}

const activityDocumentation: Record<string, { summary: string; behavior: string; url?: string }> = {
  http_listener: {
    summary: "Starts a Starter Task when an inbound HTTP request matches its configured method and path.",
    behavior: "Run or Debug deploys the task and publishes its live Studio endpoint. The request body, headers, query parameters, method, path, and path parameters become the activity output. Host, port, authentication, and TLS are inherited from the selected HTTP shared connection.",
    url: "https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/http-receiver2.htm",
  },
  http: { summary: "Sends an outbound HTTP request and exposes the response to downstream activities.", behavior: "The shared HTTP connection supplies base address, security, TLS, proxy, and timeout defaults. Activity values and mapped inputs override defaults at execution time.", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/http-connector.htm" },
  http_response: { summary: "Completes the active inbound HTTP exchange.", behavior: "Status, headers, and body are returned to the caller that triggered the listener. Place it on the same execution path as the inbound HTTP, REST, or SOAP event." },
  rest: { summary: "Hosts or invokes a REST operation, depending on the selected operation.", behavior: "A Receiver starts the task from an inbound request. Invoke performs an outbound call. Request and response structures remain available as hierarchical mapping trees.", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/rest-binding2.htm" },
  soap: { summary: "Hosts a SOAP service or invokes a request/reply web service.", behavior: "Service mode publishes the configured contract and begins the task for a matching SOAP request. Request/reply mode uses the selected HTTP connection and WSDL metadata for outbound invocation.", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/soap-service-binding2.htm" },
  file: { summary: "Performs the selected filesystem operation.", behavior: "File paths and operation-specific values accept constants, property expressions, or mappings from earlier execution-path outputs. Runtime output contains operation-specific metadata and content." },
  ftp: { summary: "Performs the selected FTP operation through a shared FTP connection.", behavior: "Connection defaults come from the resource; paths, names, content, and transfer settings may be mapped dynamically for each invocation." },
  sftp: { summary: "Performs the selected secure file-transfer operation.", behavior: "Authentication and host-key policy come from the SFTP shared connection. Operation inputs remain dynamically mappable at runtime." },
  jdbc: { summary: "Executes the selected database operation through a pooled shared connection.", behavior: "SQL parameters and dynamic fields are mapped as a hierarchy. Query activities return rows; update and DDL activities return operation counts and status." },
  ems: { summary: "Sends, receives, browses, or acknowledges TIBCO EMS messages.", behavior: "Destination, delivery, selector, acknowledgement, and message properties follow the selected EMS operation. Client acknowledgement handles can be passed to Confirm Message." },
  kafka: { summary: "Produces, receives, or commits Apache Kafka records.", behavior: "Broker security comes from the shared Kafka connection. Topic, key, headers, value, partitions, offsets, and acknowledgement handles are available for hierarchical mapping." },
  pubsub: { summary: "Publishes, receives, or acknowledges Google Cloud Pub/Sub messages.", behavior: "Project and credential defaults come from the shared connection. Message data, attributes, ordering keys, and acknowledgement handles remain available on the execution path." },
  sap: { summary: "Executes the selected SAP ECC operation.", behavior: "The shared SAP connection supplies system and authentication settings. IDoc metadata selected from SAP defines listener, parser, renderer, and sender structures." },
  transform: { summary: "Maps execution-path data into a selected target schema.", behavior: "Choose a project schema or define an inline target schema, then map source tree fields, constants, properties, and functions to target nodes. Saved rules are executed by the runtime." },
  call_task: { summary: "Invokes a reusable Sub Task and waits for its result.", behavior: "Mapped values become the Sub Task Start input. The Sub Task End output returns to this activity and remains available to the calling task's downstream path." },
  confirm: { summary: "Acknowledges one or more client-managed messages.", behavior: "Map the acknowledgement handle emitted by an EMS, Kafka, Pub/Sub, or compatible future receiver. The runtime dispatches confirmation to the originating connector." },
  start: { summary: "Defines the task input boundary.", behavior: "For Sub Tasks, the Start schema is the callable input contract. Starter Tasks normally use one external event activity instead." },
  end: { summary: "Defines the task output boundary.", behavior: "Mapped values become the final task result. For a Sub Task, this result is returned to its Call Sub Task activity." },
  log: { summary: "Writes a structured application log event.", behavior: "Message, level, and payload accept constants or dynamic mappings. Advanced automatic payload logging can be used when a dedicated Log activity is unnecessary." },
  xml: { summary: "Parses XML text into an XSD-defined tree or renders an XSD-defined tree as XML.", behavior: "Parse XML accepts serialized XML in Input and defines its published tree in Output Editor. Render XML defines and maps its source tree in Input Editor, then emits xmlString (or binary output when selected).", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/render-xml.htm" },
  json: { summary: "Converts between serialized JSON and a schema-defined activity tree.", behavior: "Parse JSON accepts jsonString and publishes the structure selected in Output Editor. Render JSON maps the structure selected in Input Editor and emits jsonString.", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.8.0/doc/html/binding-palette/render-json.htm" },
  flat: { summary: "Parses delimited/fixed-width text into records or renders records as formatted text.", behavior: "The schema contract defines record fields; Configuration controls separators, widths, headers, trimming, and line endings. Parse Data publishes records while Render Data accepts mapped records and emits text.", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/render-data.htm" },
};

function ActivityDocumentation({ node, contract }: { node: any; contract: Contract }) {
  const doc = activityDocumentation[node.type] || {
    summary: `Executes the ${node.name} activity on the current task path.`,
    behavior: "Configuration supplies design-time defaults. Input mappings, constants, property expressions, outputs, advanced policies, and documented errors are evaluated by the runtime.",
  };
  const structure = (title: string, fields: DataField[]) => <section>
    <h3>{title}</h3>
    {fields.length ? <div className="documentation-tree">{dataTreeRows(fields).map((field) => <div key={field.path} style={{ "--doc-depth": field.depth } as React.CSSProperties} className={field.group ? "group" : ""}>
      <span>{field.name}</span><code>{field.group ? "object" : field.type}</code>{field.required && <b>required</b>}<small>{field.help}</small>
    </div>)}</div> : <p>No explicit {title.toLowerCase()} fields are required for this operation.</p>}
  </section>;
  return <div className="activity-tab activity-documentation">
    <header><BookOpen/><span><h2>{node.name}</h2><small>{node.type} / {node.config?.operation || "default"}</small></span>{doc.url && <a href={doc.url} target="_blank" rel="noreferrer"><ExternalLink/> Official reference</a>}</header>
    <section><h3>Purpose</h3><p>{doc.summary}</p><p>{doc.behavior}</p></section>
    <section><h3>Configuration reference</h3>{contract.configuration.length ? <div className="documentation-fields">{contract.configuration.map((field) => <article key={field.key}><b>{field.label}{field.required && " *"}</b><code>{field.type || "text"}</code><p>{field.help || `Sets the ${field.label.toLowerCase()} used by this activity.`}</p></article>)}</div> : <p>This boundary activity has no additional operation configuration.</p>}</section>
    {structure("Input contract", runtimeMappableInputs(node, contract))}
    {structure("Output contract", contract.output)}
    <section><h3>Errors and runtime policy</h3><div className="documentation-errors">{contract.errors.map((error) => <article key={error.type}><code>{error.type}</code><span>{error.description}</span></article>)}</div><p>Use the Errors tab to choose propagate, continue, or transition handling. The Advanced tab controls automatic payload logging and retry behavior for outbound calls.</p></section>
    <section><h3>Mapping rules</h3><p>Every mappable field accepts a typed constant, an environment property such as <code>{'${properties.connections.http.host}'}</code>, a function expression, or a field selected from the hierarchical execution-path data tree.</p></section>
  </div>;
}

export default function ActivityEditor({
  node,
  task,
  resources,
  tasks,
  properties,
  schemas,
  customFunctions = [],
  updateCustomFunctions,
  tab,
  update,
}: any) {
  const contract = resolvedActivityContract(node, task, tasks, schemas || []),
    cfg = node.config || {},
    upstreamSources = upstreamActivitySources(node, task, tasks, schemas || []),
    [mapperOpen, setMapperOpen] = useState(false),
    set = (key: string, value: any) =>
      update({ config: { ...cfg, [key]: value } });
  if (tab === "documentation") return <ActivityDocumentation node={node} contract={contract} />;
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
              selectedResourceId={cfg.resourceId}
            />
          ))}
        </div>
        {(node.type === "transform" || node.type === "ai_transform") && (
          <>
            <TransformSchemaEditor config={cfg} schemas={schemas || []} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>
            <button className="open-mapper" onClick={() => setMapperOpen(true)}>
              <WandSparkles /> Open visual AI Mapper{" "}
              <small>{Array.isArray(cfg.mappings) ? cfg.mappings.length : 0} mappings configured</small>
            </button>
          </>
        )}
        {(node.type === "start" || node.type === "end") && (
          <TaskBoundarySchemaEditor node={node} config={cfg} schemas={schemas || []} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>
        )}
        {!(["xml", "json", "flat"].includes(node.type)) && <ExpressionHelp properties={properties} />}
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
    return (node.type === "transform" || node.type === "ai_transform") ? (
      <TransformInputEditor config={cfg} schemas={schemas || []} properties={properties} sources={upstreamSources} customFunctions={customFunctions} updateCustomFunctions={updateCustomFunctions} setMappings={(value: any) => set("mappings", value)}/>
    ) : (
      <InputEditor
        node={node}
        fields={runtimeMappableInputs(node, contract)}
        mappings={cfg.inputMappings || {}}
        set={(v: any) => set("inputMappings", v)}
        properties={properties}
        sources={upstreamSources}
        customFunctions={customFunctions}
        updateCustomFunctions={updateCustomFunctions}
        before={(["xml", "json", "flat"].includes(node.type) && cfg.operation !== "parse") ? <DataContractSchemaEditor node={node} config={cfg} schemas={schemas || []} direction="input" setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/> : null}
      />
    );
  if (tab === "output")
    return (node.type === "transform" || node.type === "ai_transform") ? <TransformOutputEditor config={cfg}/> : <OutputEditor fields={contract.output} config={cfg} set={set} before={(["xml", "json", "flat"].includes(node.type) && cfg.operation === "parse") ? <DataContractSchemaEditor node={node} config={cfg} schemas={schemas || []} direction="output" setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/> : null}/>;
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
  return <div className="transform-schema-editor"><div className="transform-schema-heading"><Braces/><span><b>TARGET TRANSFORMATION CONTRACT</b><small>Select an XSD from Project Schemas or define the target structure inline.</small></span></div><div className="transform-schema-columns single"><section><header><span><b>Target schema</b><small>{id === "inline" ? "Inline JSON Schema, sample JSON, or XSD" : "Project XSD with an editable working copy"}</small></span><select aria-label="Target schema" value={id} onChange={(event) => choose(event.target.value)}><option value="inline">Inline schema…</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></header><textarea aria-label="Target inline schema" value={text} onChange={(event) => setConfig({ targetSchemaId: "", targetSchemaText: event.target.value })} placeholder="Paste target JSON Schema or XSD here…" spellCheck={false}/><SchemaHierarchyPreview text={text}/></section></div></div>;
}

function TaskBoundarySchemaEditor({ node, config, schemas, setConfig }: any) {
  const choose = (id: string) => {
    if (!id) { setConfig({ interfaceSchemaId: "", interfaceSchemaText: "" }); return; }
    if (id === "inline") {
      setConfig({ interfaceSchemaId: "", interfaceSchemaText: config.interfaceSchemaText || "{\n  \"type\": \"object\",\n  \"properties\": {}\n}" });
      return;
    }
    const schema = schemas.find((item: any) => item.id === id);
    if (schema) setConfig({ interfaceSchemaId: schema.id, interfaceSchemaText: schema.content });
  };
  const selected = config.interfaceSchemaId || (config.interfaceSchemaText ? "inline" : ""), start = node.type === "start";
  return <div className="transform-schema-editor task-interface-editor"><div className="transform-schema-heading"><Braces/><span><b>{start ? "TASK INPUT INTERFACE" : "TASK RETURN INTERFACE"}</b><small>{start ? "Defines the data accepted by this task and published by Start." : "Defines the response mapped into End and returned to Call Sub Task."}</small></span></div><div className="transform-schema-columns single"><section><header><span><b>{start ? "Input schema" : "Output schema"}</b><small>Select a project schema or define an inline JSON Schema/XSD contract.</small></span><select aria-label={start ? "Task input schema" : "Task output schema"} value={selected} onChange={(event) => choose(event.target.value)}><option value="">Generic object</option><option value="inline">Inline schema…</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></header>{selected && <><textarea aria-label={start ? "Task input inline schema" : "Task output inline schema"} value={config.interfaceSchemaText || ""} onChange={(event) => setConfig({ interfaceSchemaId: "", interfaceSchemaText: event.target.value })} placeholder="Paste JSON Schema or XSD here…" spellCheck={false}/><SchemaHierarchyPreview text={config.interfaceSchemaText || ""}/></>}</section></div></div>;
}

function DataContractSchemaEditor({ node, config, schemas, direction, setConfig }: any) {
  const selected = config.schemaId || (config.schemaText ? "inline" : "");
  const projectSchema = schemas.find((schema: any) => schema.id === config.schemaId || schema.name === config.schemaId);
  const text = config.schemaText || projectSchema?.content || "";
  const format = node.type === "flat" ? "data record" : node.type.toUpperCase();
  const choose = (id: string) => {
    if (!id) { setConfig({ schemaId: "", schemaText: "" }); return; }
    if (id === "inline") {
      setConfig({ schemaId: "", schemaText: config.schemaText || "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<xs:schema xmlns:xs=\"http://www.w3.org/2001/XMLSchema\">\n  <xs:element name=\"root\" type=\"xs:string\"/>\n</xs:schema>" });
      return;
    }
    setConfig({ schemaId: id, schemaText: "" });
  };
  return <div className="transform-schema-editor data-contract-editor"><div className="transform-schema-heading"><Braces/><span><b>{direction === "input" ? "INPUT EDITOR" : "OUTPUT EDITOR"} · {format} CONTRACT</b><small>{direction === "input" ? "Define the tree to map before serialization." : "Define the tree published after parsing."}</small></span></div><div className="transform-schema-columns single"><section><header><span><b>Structure schema</b><small>Choose a project XSD/JSON schema or provide an inline definition.</small></span><select aria-label={`${direction} structure schema`} value={selected} onChange={(event) => choose(event.target.value)}><option value="">Select schema…</option><option value="inline">Inline schema…</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></header>{selected === "inline" && <textarea aria-label={`Inline ${direction} schema`} value={config.schemaText || ""} onChange={(event) => setConfig({ schemaId: "", schemaText: event.target.value })} placeholder="Paste an inline XSD or JSON Schema here…" spellCheck={false}/>}<SchemaHierarchyPreview text={text}/></section></div></div>;
}

function SchemaHierarchyPreview({ text }: { text: string }) {
  const fields = transformSchemaFields({ targetSchemaText: text });
  return <div className="schema-hierarchy-preview"><header><Braces/><span><b>Tree preview</b><small>{fields.length} schema elements</small></span></header>{fields.map((field) => <div key={field.path} style={{ "--schema-depth": field.depth } as React.CSSProperties}><i className="tree-elbow"/><span><b>{field.name}</b><small>{field.type}</small></span></div>)}{!fields.length && <p>No schema elements are available yet.</p>}</div>;
}

function FieldEditor({ field, value, set, resources, tasks, selectedResourceId }: any) {
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
      ) : field.type === "artifact" ? (
        <span className="artifact-picker"><input value={value || ""} placeholder={`Select a ${field.artifactType} artifact…`} onChange={(e) => change(e.target.value)}/><button type="button" onClick={async () => { const selected = await window.fabricDesktop?.selectCodeArtifact(field.artifactType || "java"); if (selected?.path) change(selected.path); }}>Browse…</button></span>
      ) : field.type === "idoc" ? (
        <select value={value || resources.find((resource: any) => resource.id === selectedResourceId)?.config?.selectedIdoc?.idocType || ""} onChange={(e) => change(e.target.value)}>
          <option value="">Select an IDoc fetched by the SAP connection…</option>
          {(resources.find((resource: any) => resource.id === selectedResourceId)?.config?.idocCatalog || []).map((item: any) => (
            <option value={item.idocType} key={`${item.idocType}-${item.extensionType || ""}-${item.release || ""}`}>
              {item.idocType}{item.extensionType ? ` / ${item.extensionType}` : ""}{item.release ? ` · ${item.release}` : ""}
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
type ActivitySource = { activity: any; distance: number; fields: DataField[] };
function upstreamActivitySources(node: any, task: any, tasks: any[] = [], schemas: any[] = []): ActivitySource[] {
  if (!node || !task) return [];
  const reverse = new Map<string, string[]>();
  (task.transitions || []).forEach((edge: any) => reverse.set(edge.target, [...(reverse.get(edge.target) || []), edge.source]));
  const distance = new Map<string, number>(), queue: Array<{ id: string; distance: number }> = [{ id: node.id, distance: 0 }];
  while (queue.length) {
    const current = queue.shift()!;
    for (const source of reverse.get(current.id) || []) {
      const nextDistance = current.distance + 1;
      if (source === node.id || (distance.has(source) && distance.get(source)! <= nextDistance)) continue;
      distance.set(source, nextDistance); queue.push({ id: source, distance: nextDistance });
    }
  }
  return [...distance.entries()].map(([id, pathDistance]) => {
    const activity = (task.activities || []).find((item: any) => item.id === id);
    if (!activity) return null;
    const fields = (activity.type === "transform" || activity.type === "ai_transform")
      ? transformSchemaFields(activity.config || {}).map((field) => ({ key: field.path, label: field.name, type: field.type }))
      : resolvedActivityContract(activity, task, tasks, schemas).output;
    return { activity, distance: pathDistance, fields };
  }).filter(Boolean).sort((a: any, b: any) => a.distance - b.distance) as ActivitySource[];
}
function DataSourcePane({ properties, sources = [], onChoose, customFunctions = [], updateCustomFunctions }: any) {
  customFunctions = customFunctions.length ? customFunctions : properties?.customFunctions || [];
  updateCustomFunctions = updateCustomFunctions || properties?.updateCustomFunctions;
  const [tab, setTab] = useState<"data" | "functions">("data"), [search, setSearch] = useState("");
  const item = (label: string, expression: string, type = "object", showExpression = true, depth = 0, group = false, enabled = true) => enabled ? <button className={`source-tree-node ${group ? "tree-group-node" : ""}`} style={{ "--tree-depth": depth } as React.CSSProperties} data-expression={expression} key={`${label}-${expression}`} draggable onDragStart={(event) => event.dataTransfer.setData("expression", expression)} onClick={() => onChoose(expression)} title={`Map ${label}`}><i className="tree-elbow"/><Braces/><span><b>{label}</b>{showExpression && <small>{expression}</small>}</span><code>{type}</code></button> : <div className="source-tree-node tree-group-node" style={{ "--tree-depth": depth } as React.CSSProperties} key={`${label}-${depth}`}><i className="tree-elbow"/><Braces/><span><b>{label}</b></span><code>{type}</code></div>;
  const functionItems = mapperFunctions.filter((name) => name.toLowerCase().includes(search.toLowerCase()));
  const createFunction = () => {
    const name = window.prompt("Custom XPath function name", "normalizeCustomerId")?.trim();
    if (!name) return;
    const parameters = (window.prompt("Comma-separated parameters", "value") || "").split(",").map((entry) => entry.trim()).filter(Boolean);
    const expression = window.prompt("XPath-style body; reference parameters with $name", "upperCase(trim($value))")?.trim();
    if (!expression) return;
    updateCustomFunctions?.([...customFunctions.filter((entry: any) => entry.name !== name), { id: `function-${Date.now()}`, name, parameters, expression, description: "Project custom XPath function" }]);
  };
  const query = search.toLowerCase(), visibleSources = sources.map((source: ActivitySource) => ({ ...source, fields: source.fields.filter((field) => !query || field.label.toLowerCase().includes(query) || field.key.toLowerCase().includes(query) || source.activity.name.toLowerCase().includes(query)) })).filter((source: ActivitySource) => !query || source.activity.name.toLowerCase().includes(query) || source.fields.length);
  const propertyFields = properties.filter((property: any) => property.key.toLowerCase().includes(query)).map((property: any) => d(property.key, property.key.split(".").pop() || property.key, property.data_type));
  return <aside className="source-pane"><div className="source-tabs"><button className={tab === "data" ? "active" : ""} onClick={() => setTab("data")}>Data</button><button className={tab === "functions" ? "active" : ""} onClick={() => setTab("functions")}>Functions</button></div><input className="source-search" aria-label={`Search ${tab}`} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${tab}…`}/>{tab === "data" ? <div className="source-list"><h4>EXECUTION PATH OUTPUTS · {visibleSources.length}</h4>{!query && item("Initial task input", "${input}", "object", false)}{visibleSources.map((source: ActivitySource) => <details className="activity-source" key={source.activity.id} open={source.distance === 1 || !!query}><summary><Braces/><span><b>{source.activity.name}</b><small>{source.distance === 1 ? "Immediate predecessor" : `${source.distance} steps upstream`} · {source.activity.type}</small></span><code>{source.fields.length}</code></summary>{item("Output", `\${activities.${source.activity.id}.output}`, "object", false)}{dataTreeRows(source.fields).map((field) => item(field.label, `\${activities.${source.activity.id}.output.${field.path}}`, field.type, false, field.depth + 1, field.group))}</details>)}{!visibleSources.length && <p className="source-empty">No connected upstream activity matches this search.</p>}<h4>PROCESS CONTEXT</h4>{item("Task ID", "${context.taskId}", "string", false)}{item("Environment", "${context.environment}", "string", false)}{item("Current activity ID", "${context.activityId}", "string", false)}<h4>GLOBAL VARIABLES</h4>{dataTreeRows(propertyFields).map((property) => item(property.label, `\${properties.${property.path}}`, property.type, false, property.depth, property.group, property.explicit))}</div> : <div className="source-list function-list"><div className="custom-function-heading"><h4>PROJECT FUNCTIONS · {customFunctions.length}</h4><button onClick={createFunction}><Plus/> New</button></div>{customFunctions.filter((fn: any) => fn.name.toLowerCase().includes(query)).map((fn: any) => item(fn.name, `custom:${fn.name}(${fn.parameters.map((name: string) => `$${name}`).join(", ")})`, "custom", false))}<h4>BW-STYLE FUNCTIONS · {functionItems.length}</h4>{functionItems.map((name) => item(name, `${name}()`, "function", false))}</div>}</aside>;
}
function describeMapping(expression: any, sources: ActivitySource[]): string {
  if (expression === undefined || expression === null || expression === "") return "Drop a source field or enter a constant";
  if (typeof expression === "object" && expression?.$rule) return `${expression.$rule} › ${describeMapping(expression.source, sources)}`;
  if (typeof expression !== "string") return `Constant › ${JSON.stringify(expression)}`;
  if (expression === "${input}") return "Initial task input";
  const activityPath = expression.match(/^\$\{activities\.([^.}]+)\.output(?:\.([^}]+))?\}$/);
  if (activityPath) {
    const source = sources.find((item) => item.activity.id === activityPath[1]);
    if (source) {
      if (!activityPath[2]) return `${source.activity.name} › Output`;
      const field = source.fields.find((item) => item.key === activityPath[2]);
      const parts = activityPath[2].split(".");
      return `${source.activity.name} › ${field?.label || parts[parts.length - 1]}`;
    }
  }
  const property = expression.match(/^\$\{properties\.([^}]+)\}$/);
  if (property) return `Project property › ${property[1]}`;
  const context = expression.match(/^\$\{context\.([^}]+)\}$/);
  if (context) return `Process context › ${context[1]}`;
  if (expression.endsWith("()")) return `Function › ${expression.slice(0, -2)}`;
  if (!expression.includes("${") && !expression.startsWith("$") && !expression.includes("(")) return `Constant › ${expression}`;
  return "Advanced expression";
}
function MappingBinding({ expression, sources, onChange, onConstantChange, fieldType = "string" }: any) {
  const hasValue = expression !== undefined && expression !== null && expression !== "";
  const editableExpression = mappingSource(expression), textValue = typeof editableExpression === "string" ? editableExpression : JSON.stringify(editableExpression);
  const setConstant = (raw: string) => {
    const type = String(fieldType).toLowerCase();
    const commit = onConstantChange || onChange;
    if (type.includes("boolean")) return commit(raw === "true");
    if (["integer", "long", "number", "decimal"].some((name) => type.includes(name))) return commit(raw === "" ? "" : Number(raw));
    if (type.includes("object") || type.includes("array") || type.includes("json")) {
      try { return commit(JSON.parse(raw)); } catch { return commit(raw); }
    }
    commit(raw);
  };
  return <div className={`mapping-binding ${hasValue ? "mapped" : ""}`}><span>{describeMapping(expression, sources)}</span>{hasValue && <button title="Clear value" onClick={(event) => { event.stopPropagation(); onChange(""); }}>×</button>}<details className="mapping-constant-editor" onClick={(event) => event.stopPropagation()}><summary title="Enter a constant value">123</summary><div className="mapping-constant-box"><b>Constant value</b>{String(fieldType).toLowerCase().includes("boolean") ? <select aria-label="Constant boolean value" value={editableExpression === true ? "true" : editableExpression === false ? "false" : ""} onChange={(event) => setConstant(event.target.value)}><option value="">Select…</option><option value="true">true</option><option value="false">false</option></select> : (String(fieldType).toLowerCase().includes("object") || String(fieldType).toLowerCase().includes("array") || String(fieldType).toLowerCase().includes("json")) ? <textarea aria-label="Constant JSON value" value={textValue || ""} placeholder={String(fieldType).toLowerCase().includes("array") ? "[]" : "{}"} onChange={(event) => setConstant(event.target.value)}/> : <input type={["integer", "long", "number", "decimal"].some((name) => String(fieldType).toLowerCase().includes(name)) ? "number" : "text"} aria-label="Constant value" value={textValue || ""} placeholder="Enter a literal value…" onChange={(event) => setConstant(event.target.value)}/>}<small>The literal is stored with this target field and used without a source mapping.</small></div></details><details className="mapping-function-editor" onClick={(event) => event.stopPropagation()}><summary title="Open function and expression editor">fx</summary><div className="mapping-function-box"><b>Function or expression</b><input aria-label="Advanced mapping expression" value={typeof editableExpression === "string" ? editableExpression : ""} placeholder="Choose a function or enter an expression…" onChange={(event) => onChange(event.target.value)}/><small>Use the Functions tab, project properties, or an advanced runtime expression.</small></div></details></div>;
}
function MappingConnections({ root, mappings }: any) {
  const [paths, setPaths] = useState<Array<{ key: string; d: string }>>([]);
  useEffect(() => {
    const container = root.current as HTMLElement | null;
    if (!container) return;
    let frame = 0;
    const draw = () => {
      cancelAnimationFrame(frame); frame = requestAnimationFrame(() => {
        const box = container.getBoundingClientRect(), sourceNodes = Array.from(container.querySelectorAll<HTMLElement>("[data-expression]")), targetNodes = Array.from(container.querySelectorAll<HTMLElement>("[data-target]"));
        const next: Array<{ key: string; d: string }> = [];
        Object.entries(mappings || {}).forEach(([target, expression]: any) => {
          if (!expression) return;
          const source = sourceNodes.find((item) => item.dataset.expression === expression), destination = targetNodes.find((item) => item.dataset.target === target);
          if (!source || !destination || source.offsetParent === null || destination.offsetParent === null) return;
          const a = source.getBoundingClientRect(), b = destination.getBoundingClientRect(), x1 = a.right - box.left, y1 = a.top + a.height / 2 - box.top, x2 = b.left - box.left + 8, y2 = b.top + b.height / 2 - box.top, bend = Math.max(35, (x2 - x1) * .42);
          next.push({ key: target, d: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}` });
        });
        setPaths(next);
      });
    };
    draw(); const observer = new ResizeObserver(draw); observer.observe(container); container.addEventListener("scroll", draw, true); container.addEventListener("toggle", draw, true); window.addEventListener("resize", draw);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); container.removeEventListener("scroll", draw, true); container.removeEventListener("toggle", draw, true); window.removeEventListener("resize", draw); };
  }, [root, mappings]);
  return <svg className="field-mapping-lines" aria-hidden="true">{paths.map((path) => <g key={path.key}><path className="mapping-line-glow" d={path.d}/><path d={path.d}/></g>)}</svg>;
}
function InputEditor({ node, fields, mappings, set, properties, sources, customFunctions, updateCustomFunctions, before }: any) {
  properties = Object.assign([...(properties || [])], { customFunctions, updateCustomFunctions });
  const rows = dataTreeRows(fields), firstTarget = rows.find((row) => row.explicit)?.path || "";
  const resize = useSourcePaneWidth(), root = useRef<HTMLDivElement>(null), [selected, setSelected] = useState(firstTarget), [contextMenu, setContextMenu] = useState<any>(null);
  useEffect(() => { if (!rows.some((row) => row.explicit && row.path === selected)) setSelected(firstTarget); }, [firstTarget, selected, rows]);
  const choose = (expression: string) => selected && set({ ...mappings, [selected]: expression });
  const connectionMappings = Object.fromEntries(Object.entries(mappings).map(([path, value]) => [path, mappingSource(value)]));
  return <div ref={root} className="activity-tab mapping-editor resizable-mapper visual-field-mapper" style={{ "--source-width": `${resize.width}px` } as React.CSSProperties}><DataSourcePane properties={properties} sources={sources} onChoose={choose}/><div className="source-splitter" title="Drag left or right to resize data sources" onPointerDown={resize.begin}><span/></div><section><div className="contract-heading"><SettingsTitle title="Activity input" text="Map a source, function, or typed constant to this hierarchical input tree"/></div>{before}{fields.length ? <div className="input-contract-tree"><header><Braces/><span><b>{node.name}</b><small>Hierarchical input structure · {fields.length} mappable fields · right-click a field for BW mapping statements</small></span></header>{rows.map((field) => field.explicit ? <div data-target={field.path} className={`input-tree-row ${field.group ? "tree-parent-target" : ""} ${selected === field.path ? "selected" : ""}`} key={field.path} style={{ "--target-depth": field.depth + 1 } as React.CSSProperties} onClick={() => setSelected(field.path)} onContextMenu={(event) => { event.preventDefault(); setSelected(field.path); setContextMenu({ x: event.clientX, y: event.clientY, path: field.path, label: field.label }); }} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { setSelected(field.path); set({ ...mappings, [field.path]: event.dataTransfer.getData("expression") }); }}><i className="tree-elbow"/><span className="target-tree-field"><b>{field.label}</b>{field.required && <em>required</em>}<small>{field.type}{field.help && ` · ${field.help}`}</small></span><MappingBinding expression={mappings[field.path] ?? ""} fieldType={field.type} sources={sources} onChange={(value: any) => set({ ...mappings, [field.path]: value })}/></div> : <div className="input-tree-group" key={field.path} style={{ "--target-depth": field.depth + 1 } as React.CSSProperties}><i className="tree-elbow"/><Braces/><span><b>{field.label}</b><small>object · {rows.filter((candidate) => candidate.path.startsWith(`${field.path}.`) && candidate.explicit).length} fields</small></span></div>)}</div> : <div className="contract-empty"><CheckCircle2/>This starter/activity has no configurable input.</div>}</section><MappingConnections root={root} mappings={connectionMappings}/><MappingContextMenu menu={contextMenu} value={contextMenu ? mappings[contextMenu.path] : null} close={() => setContextMenu(null)} change={(value: any) => contextMenu && set({ ...mappings, [contextMenu.path]: value })} remove={() => { if (!contextMenu) return; const next = { ...mappings }; delete next[contextMenu.path]; set(next); }}/></div>;
}

type SchemaTreeField = { path: string; name: string; type: string; depth: number };
function transformSchemaFields(config: any): SchemaTreeField[] {
  const text = config.targetSchemaText || JSON.stringify(config.targetSchema || {});
  try {
    const schema = JSON.parse(text), fields: SchemaTreeField[] = [];
    const walk = (node: any, prefix = "", depth = 0) => Object.entries(node?.properties || node || {}).forEach(([name, child]: any) => { const path = prefix ? `${prefix}.${name}` : name; fields.push({ path, name, type: child?.type || typeof child, depth }); if (child?.properties) walk(child, path, depth + 1); });
    walk(schema); return fields;
  } catch {
    try {
      const document = new DOMParser().parseFromString(text, "application/xml");
      if (document.querySelector("parsererror")) return [];
      const local = (element: Element) => element.localName.toLowerCase();
      const complexTypes = new Map(Array.from(document.getElementsByTagNameNS("*", "complexType")).map((element) => [element.getAttribute("name") || "", element]));
      const directElements = (container: Element): Element[] => Array.from(container.children).flatMap((child) => local(child) === "element" ? [child] : ["complextype", "sequence", "all", "choice", "group", "extension"].includes(local(child)) ? directElements(child) : []);
      const fields: SchemaTreeField[] = [];
      const walkElement = (element: Element, prefix = "", depth = 0) => {
        const name = element.getAttribute("name") || element.getAttribute("ref")?.split(":").pop() || "element", rawType = element.getAttribute("type") || "complex", baseType = rawType.split(":").pop() || rawType, type = element.getAttribute("maxOccurs") === "unbounded" || Number(element.getAttribute("maxOccurs") || 1) > 1 ? `${baseType}[]` : baseType, path = prefix ? `${prefix}.${name}` : name;
        fields.push({ path, name, type, depth });
        const inline = Array.from(element.children).find((child) => local(child) === "complextype"), referenced = complexTypes.get(baseType);
        const container = inline || referenced || element;
        Array.from(container.getElementsByTagNameNS("*", "attribute")).filter((attribute) => { let parent: Element | null = attribute.parentElement; while (parent && local(parent) !== "element") parent = parent.parentElement; return parent === element; }).forEach((attribute) => { const attributeName = attribute.getAttribute("name") || attribute.getAttribute("ref")?.split(":").pop() || "attribute"; fields.push({ path: `${path}.@${attributeName}`, name: `@${attributeName}`, type: (attribute.getAttribute("type") || "string").split(":").pop() || "string", depth: depth + 1 }); });
        directElements(container).forEach((child) => walkElement(child, path, depth + 1));
      };
      Array.from(document.documentElement.children).filter((element) => local(element) === "element").forEach((element) => walkElement(element));
      return fields;
    } catch { return []; }
  }
}
function TransformInputEditor({ config, properties, sources, setMappings, customFunctions, updateCustomFunctions }: any) {
  properties = Object.assign([...(properties || [])], { customFunctions, updateCustomFunctions });
  const fields = transformSchemaFields(config), resize = useSourcePaneWidth(280), root = useRef<HTMLDivElement>(null), [selected, setSelected] = useState(fields[0]?.path || ""), [contextMenu, setContextMenu] = useState<any>(null), mappings = Array.isArray(config.mappings) ? config.mappings : [];
  const mapTo = (target: string, source: any) => setMappings([...mappings.filter((rule: any) => rule.target !== target), { target, source, functions: [], enabled: true }]);
  const mapConstant = (target: string, constant: any) => setMappings([...mappings.filter((rule: any) => rule.target !== target), { target, constant, functions: [], enabled: true }]);
  const connectionMappings = Object.fromEntries(mappings.filter((rule: any) => rule.enabled !== false && typeof rule.source === "string" && rule.source.startsWith("${")).map((rule: any) => [rule.target, rule.source]));
  const contextValue = contextMenu ? mappings.find((item: any) => item.target === contextMenu.path) : null;
  return <div ref={root} className="activity-tab mapping-editor transform-input-editor resizable-mapper visual-field-mapper" style={{ "--source-width": `${resize.width}px` } as React.CSSProperties}><DataSourcePane properties={properties} sources={sources} onChoose={(expression: string) => selected && mapTo(selected, expression)}/><div className="source-splitter" title="Drag left or right to resize data sources" onPointerDown={resize.begin}><span/></div><section><div className="contract-heading"><SettingsTitle title="Target schema mapping" text="Map a source, function, or typed constant into the target tree"/></div><div className="target-schema-tree">{fields.map((field) => { const rule = mappings.find((item: any) => item.target === field.path); return <div data-target={field.path} className={`schema-tree-row ${selected === field.path ? "selected" : ""}`} key={field.path} style={{ paddingLeft: 12 + field.depth * 18 }} onClick={() => setSelected(field.path)} onContextMenu={(event) => { event.preventDefault(); setSelected(field.path); setContextMenu({ x: event.clientX, y: event.clientY, path: field.path, label: field.name }); }} onDragOver={(event) => event.preventDefault()} onDrop={(event) => mapTo(field.path, event.dataTransfer.getData("expression"))}><span className="tree-node-dot"/><span className="tree-field"><b>{field.name}</b><small>{field.type} · level {field.depth + 1}</small></span><span className={`mapping-connection ${rule ? "connected" : ""}`}><i/><ArrowRight/></span><MappingBinding expression={rule && "constant" in rule ? rule.constant : rule?.source ?? ""} fieldType={field.type} sources={sources} onChange={(value: any) => mapTo(field.path, value)} onConstantChange={(value: any) => mapConstant(field.path, value)}/></div>; })}{!fields.length && <div className="contract-empty">Select a project XSD or enter a valid inline target schema on Configuration.</div>}</div></section><MappingConnections root={root} mappings={connectionMappings}/><MappingContextMenu menu={contextMenu} value={contextValue?.source ?? contextValue?.constant} close={() => setContextMenu(null)} change={(value: any) => contextMenu && setMappings([...mappings.filter((item: any) => item.target !== contextMenu.path), { target: contextMenu.path, ...(value && typeof value === "object" && value.$rule ? { source: value.source, operator: value.$rule, select: value.select, groupBy: value.groupBy, condition: value.condition, otherwise: value.otherwise, duplicateOf: value.duplicateOf } : { source: value }), functions: [], enabled: true }])} remove={() => contextMenu && setMappings(mappings.filter((item: any) => item.target !== contextMenu.path))}/></div>;
}
function TransformOutputEditor({ config }: any) {
  const fields = transformSchemaFields(config);
  return <div className="activity-tab output-editor"><div className="contract-heading"><SettingsTitle title="Transformer output structure" text="Published target schema available to downstream activities"/></div><div className="output-schema-tree">{fields.map((field) => <div key={field.path} style={{ paddingLeft: 14 + field.depth * 18 }}><span className="tree-node-dot"/><code>{field.name}</code><small>{field.type}</small><span>{field.depth ? "Nested field" : "Root field"}</span></div>)}{!fields.length && <div className="contract-empty">No target schema is configured.</div>}</div></div>;
}
function OutputEditor({ fields, config, set, before }: any) {
  const rows = dataTreeRows(fields);
  return (
    <div className="activity-tab output-editor">
      <div className="contract-heading">
        <SettingsTitle
          title="Activity output schema"
          text="Published values available to downstream activity mappings"
        />
      </div>
      {before}
      <div className="output-options">
        <label>
          Output name
          <input
            value={config.outputName || ""}
            placeholder="ActivityOutput"
            onChange={(e) => set("outputName", e.target.value)}
          />
        </label>
        {!before && <label className="switch-row">
          <input
            type="checkbox"
            checked={config.validateOutput !== false}
            onChange={(e) => set("validateOutput", e.target.checked)}
          />{" "}
          Validate output schema
        </label>}
      </div>
      <div className="schema-table">
        <header>
          <b>Field</b>
          <b>Data type</b>
          <b>Cardinality</b>
          <b>Description</b>
        </header>
        {rows.map((field) => field.explicit ? (
          <div className={field.group ? "tree-parent-target" : ""} key={field.path} style={{ "--output-depth": field.depth } as React.CSSProperties}>
            <code><i className="tree-elbow"/>{field.label}</code>
            <span>{field.type}</span>
            <span>{field.required ? "1" : "0..1"}</span>
            <span>{field.help || (field.group ? "Structured element" : "Published field")}</span>
          </div>
        ) : <div className="schema-tree-group" key={field.path} style={{ "--output-depth": field.depth } as React.CSSProperties}><code><i className="tree-elbow"/><Braces/>{field.label}</code><span>object</span><span>group</span><span>Parent structure</span></div>)}
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
      <section className="advanced-settings-tree">
        <div className="advanced-tree-root"><Braces/><span><b>Advanced</b><small>Activity policy tree</small></span></div>
        <article className="advanced-tree-branch">
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
          <label className="advanced-tree-field">
            Log Payload{" "}
            <input
              list="advanced-property-values"
              value={advanced.logPayload}
              onChange={(e) => change("logPayload", e.target.value)}
            />
            <small>Boolean or global property expression</small>
          </label>
        </article>
        <article className={`advanced-tree-branch ${!outbound ? "disabled-card" : ""}`}>
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
            <label className="advanced-tree-field">
              Retry{" "}
              <input
                disabled={!outbound}
                list="advanced-property-values"
                value={advanced.retryEnabled}
                onChange={(e) => change("retryEnabled", e.target.value)}
              />
              <small>Boolean or global property expression</small>
            </label>
            <label className="advanced-tree-field">
              Retry count{" "}
              <input
                disabled={!outbound || retryDisabled}
                value={advanced.retryCount}
                onChange={(e) => change("retryCount", e.target.value)}
              />
              <small>Default: 3 retry attempts</small>
            </label>
            <label className="advanced-tree-field">
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
          {dataTreeRows(properties.filter((p: any) => p.key.startsWith("advanced.")).map((p: any) => d(p.key, p.key.split(".").pop() || p.key, p.data_type))).map((row) => row.explicit ? (
            <button key={row.path} className="advanced-property-leaf" style={{ "--tree-depth": row.depth } as React.CSSProperties} onClick={() => navigator.clipboard?.writeText("${properties." + row.path + "}")}><i className="tree-elbow"/><Braces/><span>{row.label}<small>{row.type} · {String(properties.find((property: any) => property.key === row.path)?.value)}</small></span></button>
          ) : <div key={row.path} className="advanced-property-group" style={{ "--tree-depth": row.depth } as React.CSSProperties}><i className="tree-elbow"/><Braces/><span><b>{row.label}</b><small>property group</small></span></div>)}
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
