import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Braces,
  CalendarClock,
  CheckCircle2,
  Database,
  ExternalLink,
  FlaskConical,
  Plus,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  WandSparkles,
  Workflow,
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
    | "methods"
    | "textarea"
    | "resource"
    | "artifact"
    | "idoc"
    | "snowflake_entity"
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
const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"];
const isMapperActivity = (type: string) => ["mapper", "transform", "ai_transform"].includes(type);
const mapperFunctions = [
  "concat", "substring", "substringBefore", "substringAfter", "stringLength", "normalizeSpace", "upperCase", "lowerCase", "translate", "trim", "replace", "matches", "tokenize", "startsWith", "endsWith", "contains", "compare", "codepointsToString", "stringToCodepoints", "format", "parseDate", "formatDate", "formatDateTime", "currentDate", "currentTime", "currentDateTime", "timezoneFromDateTime", "adjustDateTimeToTimezone", "addDays", "addMonths", "dateDifference", "yearsFromDuration", "monthsFromDuration", "daysFromDuration", "hoursFromDuration", "minutesFromDuration", "secondsFromDuration", "number", "integer", "decimal", "round", "roundHalfToEven", "floor", "ceiling", "abs", "min", "max", "sum", "average", "count", "boolean", "not", "true", "false", "ifThenElse", "coalesce", "exists", "empty", "default", "distinctValues", "deepEqual", "sort", "reverse", "subsequence", "insertBefore", "remove", "first", "last", "position", "indexOf", "join", "split", "filter", "map", "reduce", "forEach", "forEachGroup", "localName", "namespaceUri", "name", "nodeName", "root", "path", "data", "nil", "isNil", "jsonParse", "jsonRender", "xmlParse", "xmlRender", "base64Encode", "base64Decode", "hexEncode", "hexDecode", "urlEncode", "urlDecode", "uuid", "hash", "xpath", "jsonPath", "property", "processContext", "taskOutput", "lookup", "crossReference", "trace", "error"
];

type MappingWhen = { condition: string; source: any };
type StructuredMapping = { $rule: "for-each" | "for-each-group" | "if" | "when-otherwise" | "choose"; source?: any; select?: string; groupBy?: string; condition?: string; otherwise?: any; whens?: MappingWhen[]; duplicateOf?: string };
const mappingSource = (value: any) => value && typeof value === "object" && ("$rule" in value || "operator" in value) ? (value.select || value.source) : value;

function MappingContextMenu({ menu, value, close, change, remove, duplicate, canDuplicate = false, required = false }: any) {
  const panel = useRef<HTMLDivElement>(null), source = String(mappingSource(value) || ""), [mode, setMode] = useState<StructuredMapping["$rule"] | "">(""), [select, setSelect] = useState(source), [condition, setCondition] = useState(source ? `exists(${source})` : ""), [groupBy, setGroupBy] = useState(""), [otherwise, setOtherwise] = useState(""), [whens, setWhens] = useState<MappingWhen[]>([{ condition: source ? `exists(${source})` : "true()", source }]);
  useEffect(() => {
    if (!menu) return;
    const dismiss = (event: PointerEvent) => { if (!panel.current?.contains(event.target as globalThis.Node)) close(); };
    window.addEventListener("pointerdown", dismiss);
    return () => window.removeEventListener("pointerdown", dismiss);
  }, [menu, close]);
  useEffect(() => { if (menu) { const next = String(mappingSource(value) || ""); let storedWhens = value?.whens; if (!storedWhens?.length && (value?.operator || value?.$rule) === "choose") { try { storedWhens = JSON.parse(String(value?.source || "[]")); } catch { storedWhens = []; } } setMode((value?.operator || value?.$rule || "") as StructuredMapping["$rule"] | ""); setSelect(next); setCondition(value?.condition || (next ? `exists(${next})` : "")); setGroupBy(value?.groupBy || ""); setOtherwise(value?.otherwise || ""); setWhens(storedWhens?.length ? storedWhens : [{ condition: next ? `exists(${next})` : "true()", source: next }]); } }, [menu, value]);
  if (!menu) return null;
  const apply = (next: StructuredMapping) => { change(next); close(); };
  const commit = () => {
    if (!mode) return;
    if (mode === "choose") {
      const branches = whens.filter((branch) => branch.condition.trim() && String(branch.source ?? "").trim());
      if (branches.length) apply({ $rule: "choose", source: JSON.stringify(branches), whens: branches, otherwise });
      return;
    }
    if (select.trim()) apply({ $rule: mode, source: select.trim(), select: select.trim(), condition, groupBy, otherwise });
  };
  const content = <div ref={panel} className="mapping-context-menu" style={{ left: Math.max(8, Math.min(menu.x, window.innerWidth - 350)), top: Math.max(8, Math.min(menu.y, window.innerHeight - 455)) }} onPointerDown={(event) => event.stopPropagation()}>
    <header><Braces/><span><b>{menu.label}</b><small>Mapping statement</small></span></header>
    <button className={mode === "for-each" ? "selected" : ""} onClick={() => setMode("for-each")}>For Each…<small>Iterate a repeating source value</small></button>
    <button className={mode === "for-each-group" ? "selected" : ""} onClick={() => setMode("for-each-group")}>For Each Group…<small>Group repeated values before mapping</small></button>
    <button disabled={required} className={mode === "if" ? "selected" : ""} onClick={() => setMode("if")}>If…<small>{required ? "Required schema fields cannot be conditional" : "Emit this target only when true"}</small></button>
    <button className={mode === "when-otherwise" ? "selected" : ""} onClick={() => setMode("when-otherwise")}>When / Otherwise…<small>Choose between two mapping values</small></button>
    <button className={mode === "choose" ? "selected" : ""} onClick={() => setMode("choose")}>Choose…<small>Evaluate multiple When branches, then Otherwise</small></button>
    {mode && <section className="mapping-rule-editor">{mode !== "choose" && <label>Source expression<input value={select} placeholder="Drag a source first, or enter its expression" onChange={(event) => setSelect(event.target.value)}/></label>}{mode === "for-each-group" && <label>Group-by child path<input value={groupBy} placeholder="customerId" onChange={(event) => setGroupBy(event.target.value)}/></label>}{(mode === "if" || mode === "when-otherwise") && <label>Condition<input value={condition} onChange={(event) => setCondition(event.target.value)}/></label>}{mode === "when-otherwise" && <label>Otherwise value/expression<input value={otherwise} onChange={(event) => setOtherwise(event.target.value)}/></label>}{mode === "choose" && <div className="mapping-choose-editor">{whens.map((branch, index) => <div key={index}><b>WHEN {index + 1}</b><input aria-label={`When ${index + 1} condition`} value={branch.condition} placeholder="${input.status} = 'ACTIVE'" onChange={(event) => setWhens((items) => items.map((item, current) => current === index ? { ...item, condition: event.target.value } : item))}/><input aria-label={`When ${index + 1} value`} value={String(branch.source ?? "")} placeholder="Value or source expression" onChange={(event) => setWhens((items) => items.map((item, current) => current === index ? { ...item, source: event.target.value } : item))}/><button disabled={whens.length === 1} onClick={() => setWhens((items) => items.filter((_, current) => current !== index))}>Remove</button></div>)}<button onClick={() => setWhens((items) => [...items, { condition: "", source: "" }])}><Plus/> Add When</button><label>Otherwise value/expression<input value={otherwise} onChange={(event) => setOtherwise(event.target.value)}/></label></div>}<div><button onClick={() => setMode("")}>Cancel</button><button className="apply" disabled={mode === "choose" ? !whens.some((branch) => branch.condition.trim() && String(branch.source ?? "").trim()) : !select.trim()} onClick={commit}>Apply mapping</button></div>{mode !== "choose" && !select.trim() && <small>Select or drag an actual source sequence; the mapper no longer substitutes the ambiguous $&#123;last&#125; expression.</small>}</section>}
    <button disabled={!canDuplicate && !value} onClick={() => { if (duplicate) duplicate(); else change(typeof value === "object" ? { ...value, duplicateOf: `${menu.path}-${Date.now()}` } : { $rule: "if", source: value, condition: "true()", duplicateOf: `${menu.path}-${Date.now()}` }); close(); }}>Duplicate {canDuplicate ? "repeating occurrence" : "mapping"}<small>{canDuplicate ? "Create another target occurrence with its complete child mapping tree" : "Create an independently editable statement"}</small></button>
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

function parentTreePaths(path: string): string[] {
  const parts = path.split(".").filter(Boolean);
  return parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join("."));
}
function hasTreeChildren(rows: Array<{ path: string; depth: number }>, row: { path: string; depth: number }): boolean {
  return rows.some((candidate) => candidate.depth === row.depth + 1 && candidate.path.startsWith(`${row.path}.`));
}
function useTreeCollapse() {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const toggle = (path: string) => setCollapsed((current) => {
    const next = new Set(current);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });
  return {
    collapsed,
    toggle,
    visible: (path: string) => parentTreePaths(path).every((parent) => !collapsed.has(parent)),
  };
}
function TreeToggle({ path, label, collapsed, toggle }: { path: string; label: string; collapsed: boolean; toggle: (path: string) => void }) {
  return <span className={`tree-toggle ${collapsed ? "collapsed" : "expanded"}`} role="button" tabIndex={0} aria-label={`${collapsed ? "Expand" : "Collapse"} ${label}`} aria-expanded={!collapsed} title={`${collapsed ? "Expand" : "Collapse"} ${label}`} onClick={(event) => { event.preventDefault(); event.stopPropagation(); toggle(path); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); toggle(path); } }}><i aria-hidden="true">{collapsed ? "+" : "−"}</i></span>;
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
        { ...f("scheduleMode", "Schedule mode", "select"), options: ["dateTime", "cron"] },
        f("scheduledDateTime", "Scheduled date and time"),
        f("cronExpression", "Cron expression"),
        { ...f("timezone", "Time zone", "select"), options: ["local", "UTC"] },
        f("repeatEnabled", "Repeat after first run", "boolean"),
        f("interval", "Interval", "number"),
        {
          ...f("unit", "Unit", "select"),
          options: ["seconds", "minutes", "hours", "days"],
        },
        f("runOnceOnLocalStart", "Run once immediately when started locally", "boolean"),
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
        f("dynamicTaskId", "Dynamic Sub Task ID/name expression", "text", "Resolved for every invocation. Use a literal Sub Task ID/name or an expression such as ${properties.routing.targetTask}; the selected Sub Task remains the fallback."),
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
      output: [d("type", "Exception type"), d("code", "Error code"), d("message", "Error message"), d("stackTrace", "Stack trace"), d("activityId", "Failed activity ID"), d("details", "Fault details", "object"), d("cause", "Original cause", "object")],
      errors: [],
    };
  if (n.type === "throw")
    return {
      configuration: [f("errorType", "Exception type"), f("code", "Error code"), f("message", "Error message"), f("details", "Fault details (JSON)", "textarea")],
      input: [d("message", "Error message", "string", true), d("code", "Error code"), d("type", "Exception type"), d("stackTrace", "Stack trace"), d("details", "Fault details", "object")],
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
        f("methods", "Allowed HTTP methods", "methods", "Select every HTTP method accepted by this listener."),
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
        f("methods", "Allowed HTTP methods", "methods", "Select every HTTP method exposed by this REST resource."),
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
        { ...f("resourceId", "JDBC shared connection", "resource"), resourceType: "jdbc", required: true },
        ...(op === "call" ? [f("schema", "Procedure schema"), f("catalog", "Catalog or package"), f("procedure", "Procedure / function", "text", "Browse and refresh procedure metadata from the JDBC designer below.")] : []),
        f("timeout", "Timeout (seconds)", "number"),
        ...(["query", "dynamic", "call"].includes(op) ? [f("maxRows", "Maximum rows (0 retrieves all)", "number")] : []),
        f("overrideTransactionBehavior", "Override transaction behavior", "boolean"),
        f("overrideJdbcConnection", "Override JDBC connection", "boolean"),
        ...(["query", "dynamic"].includes(op) ? [f("useNil", "Use nil for SQL NULL", "boolean"), f("interpretEmptyStringAsNull", "Interpret empty string as NULL", "boolean"), f("interpretInvalidXmlChars", "Interpret invalid XML characters", "boolean"), f("processInSubsets", "Process result in subsets", "boolean"), f("subsetSize", "Subset size", "number"), f("overrideSqlStatement", "Allow mapped SQL override", "boolean")] : []),
        ...(["insert", "update", "delete"].includes(op) ? [f("insertIfRecordDoesNotExist", "Insert if record does not exist", "boolean"), f("interpretEmptyStringAsNull", "Interpret empty string as NULL", "boolean"), f("batchUpdate", "Batch update", "boolean"), f("overrideSqlStatement", "Allow mapped SQL override", "boolean")] : []),
      ],
      input: [d("ServerTimeZone", "Database server time zone", "string"), d("timeout", "Dynamic timeout", "number"), ...(["query", "dynamic"].includes(op) ? [d("maxRows", "Dynamic maximum rows", "number"), d("SqlStatement", "Dynamic SQL override", "string"), d("parameters", "Prepared statement parameters", "object")] : op === "call" ? [d("parameters", "IN and IN/OUT procedure parameters", "object")] : [d("parameters", "Prepared statement parameters", "object"), d("records", "Batch parameter records", "array"), d("SqlUpdateStatement", "Dynamic update SQL", "string"), d("InsertStatement", "Insert-if-missing SQL", "string")])],
      output: ["query", "dynamic"].includes(op) ? [d("resultSet", "JDBC result set", "object"), d("resultSet.Record", "Result records", "array"), d("rows", "Result records", "array"), d("rowCount", "Rows returned", "integer"), d("lastSubset", "Last result subset", "boolean")] : op === "call" ? [d("resultSets", "Procedure result sets", "array"), d("outParameters", "OUT and IN/OUT parameters", "object"), d("UnresolvedResultSets", "Unresolved result sets", "array")] : [d("noOfUpdates", "Number of updates", "integer"), d("rowCount", "Affected rows", "integer"), d("lastInsertId", "Generated key", "integer|string")],
      errors: [
        { type: "JDBCConnectionNotFoundException", description: "The selected JDBC shared connection is unavailable." },
        { type: "InvalidTimeZoneException", description: "The database server time zone is invalid." },
        { type: "JDBCSQLException", description: "The database rejected the SQL or procedure call." },
        { type: "LoginTimedOutException", description: "The database login timed out." },
        { type: "InvalidSQLTypeException", description: "A prepared parameter type does not match its database column." },
        { type: "DuplicatedFieldNameException", description: "The query result contains an unsupported duplicate field name." },
        { type: "ActivityTimedOutException", description: "The configured activity timeout was reached." },
      ],
    };
  if (n.type === "amqp") {
    const resource = { ...f("resourceId", "AMQP connection", "resource"), resourceType: "amqp", required: true };
    const destination = [f("queueName", "Queue name"), { ...f("entityType", "Entity type", "select"), options: ["Queue", "Topic"] }, f("entityName", "Entity name"), f("subscriptionName", "Subscription name"), f("durableSubscription", "Durable subscription", "boolean"), f("sharedSubscription", "Shared subscription", "boolean")];
    const message = [{ ...f("messageType", "Message type", "select"), options: op === "receive" ? ["TextMessage", "BytesMessage", "Simple", "Any"] : ["TextMessage", "BytesMessage", "Simple"] }];
    const errors = [{ type: "AMQPPluginException", description: "The AMQP operation failed or its message configuration is invalid." }, { type: "AMQPConnectionException", description: "The broker connection failed or could not be recovered." }];
    if (op === "send") return { configuration: [resource, { ...f("destinationType", "RabbitMQ destination type", "select"), options: ["Queue", "Exchange"] }, ...destination.slice(0, 3), { ...f("exchangeType", "Exchange type", "select"), options: ["direct", "topic", "fanout", "headers"] }, f("exchangeName", "Exchange name"), f("routingKey", "Routing key"), ...message, f("getMessageID", "Get message ID", "boolean"), { ...f("deliveryMode", "Delivery mode", "select"), options: ["Persistent", "Non-Persistent"] }, f("expiration", "Expiration (msec)", "number"), f("priority", "Priority (0-9)", "number"), f("type", "Message type/property")], input: [d("userProperties", "User properties", "object"), d("deliveryMode", "Dynamic delivery mode"), d("messageID", "Message ID"), d("expiration", "Dynamic expiration", "integer"), d("priority", "Dynamic priority", "integer"), d("type", "Dynamic type"), d("contentType", "Content type"), d("sessionID", "Azure session ID"), d("correlationID", "Correlation ID"), d("exchangeName", "Dynamic exchange"), d("routingKey", "Dynamic routing key"), d("topicName", "Dynamic topic"), d("queueName", "Dynamic queue"), d("body", "Message body", "string|binary", true)], output: [d("sendResult", "Send succeeded", "boolean"), d("MessageId", "Broker message ID")], errors };
    if (op === "dead_letter") return { configuration: [resource, f("useRetry", "Use retry", "boolean"), f("totalTimeoutSeconds", "Total timeout (seconds)", "number"), f("maxAttempts", "Maximum attempts", "number"), f("backoffTimeMsec", "Backoff time (msec)", "number")], input: [d("settlementToken", "Settlement token", "string", true), d("deadLetterReason", "Dead-letter reason"), d("deadLetterErrorDescription", "Dead-letter error description"), d("useRetry", "Dynamic retry", "boolean"), d("totalTimeoutSeconds", "Dynamic total timeout", "integer"), d("maxAttempts", "Dynamic attempts", "integer"), d("backoffTimeMsec", "Dynamic backoff", "integer")], output: [d("status", "Dead-letter status"), d("settlementToken", "Settlement token"), d("messageId", "Processed message ID")], errors };
    return { configuration: [resource, ...destination, ...message, f("maxMessages", "Maximum messages", "number"), { ...f("acknowledgeMode", "Acknowledge mode", "select"), options: op === "receive" ? ["Auto", "Client", "Client or Dead Letter Queue"] : ["Auto", "Client"] }, { ...f("receiverMode", "Azure receiver mode", "select"), options: ["PeekLock", "ReceiveAndDelete"] }, f("getCorrelationID", "Get correlation ID", "boolean"), f("sessionEnabled", "Azure session enabled", "boolean"), { ...f("receiveType", "Session receive type", "select"), options: ["FirstAvailableSession", "SpecificSession", "AllAvailableSessions"] }, f("maxConcurrentSessions", "Maximum concurrent sessions", "number"), f("sessionId", "Specific session ID"), f("prefetchCount", "Prefetch count / credits", "number")], input: [d("queueName", "Dynamic queue"), d("topicName", "Dynamic topic"), d("subscriptionName", "Dynamic subscription")], output: [d("received", "Message received", "boolean"), d("UserProperties", "User properties", "object"), d("MessageProperties", "AMQP message properties", "object"), d("body", "Message body", "string|binary"), d("settlementToken", "Client/dead-letter settlement token"), d("ackId", "Confirm Message handle")], errors };
  }
  if (n.type === "snowflake") {
    const commonConfiguration: Field[] = [
      { ...f("resourceId", "Snowflake JDBC connection", "resource"), resourceType: "snowflake", required: true },
      f("entity", "Entity", "snowflake_entity", "Tables and views retrieved in the Snowflake connection Schema section."),
      f("timeout", "Activity timeout (seconds)", "number"),
      f("overrideDatabaseName", "Override database name"), f("overrideSchemaName", "Override schema name"),
      f("interpretEmptyStringAsNull", "Interpret empty string as NULL", "boolean"),
    ];
    const documentedErrors = [
      { type: "SNOWFLAKE_CONNECTION", description: "The Snowflake shared resource or connection pool is unavailable." },
      { type: "SNOWFLAKE_DATABASE_JDBC-500005", description: "Snowflake failed to create a prepared statement." },
      { type: "SNOWFLAKE_DATABASE_JDBC-500007", description: "Snowflake failed to bind prepared-statement parameters." },
      { type: "SNOWFLAKE_DATABASE_JDBC-500009", description: "Snowflake failed to execute the generated query." },
      { type: "SNOWFLAKE_DATABASE_JDBC-500013", description: "The activity could not generate its structured output." },
    ];
    if (op === "query") return {
      configuration: [...commonConfiguration, f("statement", "Snowflake SELECT statement", "textarea"), f("preparedParameters", "Prepared parameters [name:type]"), f("maximumRows", "Maximum rows (0 retrieves all)", "number")],
      input: [d("parameters", "Prepared statement parameters", "object")],
      output: [d("rows", "Query result records", "array"), d("rowCount", "Rows returned", "integer")],
      errors: [...documentedErrors, { type: "SNOWFLAKE_DATABASE_JDBC-500014", description: "Maximum Rows is negative." }],
    };
    if (op === "insert") return {
      configuration: [...commonConfiguration, f("createTableFromXsd", "Create table from XSD", "boolean"), f("schemaId", "Table XSD/schema"), f("tableName", "Table name"), f("valueColumns", "Values columns"), f("batchSize", "Batch size", "number"), f("faultOnBatchFailure", "Fault on batch failure", "boolean"), f("merge", "Merge existing records", "boolean"), f("mergeOnColumns", "Merge on columns")],
      input: [d("records", "Rows to insert", "array", true)],
      output: [d("rowsAttempted", "Rows attempted", "integer"), d("rowsAffected", "Rows affected", "integer"), d("batchFailures", "Batch failure details", "array")],
      errors: [...documentedErrors, { type: "SNOWFLAKE_DATABASE_JDBC-500016", description: "One or more insert batches failed." }, { type: "SNOWFLAKE_DATABASE_JDBC-500022", description: "Schema or table creation failed." }],
    };
    if (op === "update") return {
      configuration: [...commonConfiguration, f("valueColumns", "SET / Values columns"), f("parameterColumns", "WHERE / Parameter columns"), f("merge", "Insert when record does not exist", "boolean"), f("mergeOnColumns", "Merge on columns"), f("createTableIfNoneExists", "Create table if none exists", "boolean")],
      input: [d("records", "Rows containing values and parameters", "array", true)], output: [d("rowsAffected", "Rows affected", "integer")], errors: documentedErrors,
    };
    if (op === "delete") return {
      configuration: [...commonConfiguration, f("parameterColumns", "WHERE / Parameter columns"), f("merge", "Merge when record does not exist", "boolean"), f("mergeOnColumns", "Merge on columns"), f("createTableIfNoneExists", "Create table if none exists", "boolean")],
      input: [d("records", "Rows containing delete parameters", "array")], output: [d("rowsAffected", "Rows affected", "integer")], errors: documentedErrors,
    };
    return {
      configuration: [...commonConfiguration, f("createTableFromXsd", "Create table from XSD", "boolean"), f("schemaId", "Table XSD/schema"), f("tableName", "Table name"), { ...f("stageType", "Stage type", "select"), options: ["UserStage", "TableStage", "NamedStage", "AmazonS3"] }, f("namedStage", "Named stage / storage integration stage"), { ...f("fileFormat", "Amazon S3 file format", "select"), options: ["DelimitedFiles", "JSON", "AVRO", "ORC", "PARQUET", "XML"] }, f("validationMode", "Validation mode", "boolean"), f("purgeStageFiles", "Purge stage files", "boolean"), f("compressData", "Compress internal-stage data", "boolean"), { ...f("onError", "On error", "select"), options: ["CONTINUE", "SKIP_FILE", "SKIP_FILE_<num>", "SKIP_FILE_<num>%", "ABORT_STATEMENT"] }, f("skipFileErrorCount", "Skip file at error count", "number"), f("skipFileErrorPercentage", "Skip file at error percentage", "number"), f("merge", "Merge loaded records", "boolean"), f("mergeOnColumns", "Merge on columns")],
      input: [d("records", "Rows for an internal stage", "array"), d("filePath", "Local file for an internal stage", "string"), d("loadOptions", "Stage load options", "object")],
      output: [d("loadResults", "Per-file load results", "array"), d("loadResults.FILE", "Source file", "string"), d("loadResults.STATUS", "Load status", "string"), d("loadResults.ROWS_PARSED", "Rows parsed", "integer"), d("loadResults.ROWS_LOADED", "Rows loaded", "integer"), d("loadResults.ERRORS_SEEN", "Errors seen", "integer"), d("loadResults.FIRST_ERROR", "First error", "string"), d("loadResults.FIRST_ERROR_LINE", "First error line", "integer"), d("loadResults.FIRST_ERROR_CHARACTER", "First error character", "integer"), d("loadResults.FIRST_ERROR_COLUMN_NAME", "First error column", "string")],
      errors: [...documentedErrors, { type: "SNOWFLAKE_DATABASE_JDBC-500018", description: "Uploading data to the Snowflake stage failed." }, { type: "SNOWFLAKE_DATABASE_JDBC-500020", description: "Bulk-load validation found invalid data." }],
    };
  }
  if (n.type === "excel") return {
    configuration: [f("filePath", "Workbook file path", "text", "Reads .xlsx, .xlsm, or legacy .xls workbooks at runtime."), f("sheetName", "Worksheet name", "text", "Leave blank to return every worksheet/tab."), f("headerRow", "Header row", "number"), f("startRow", "First data row", "number"), f("maximumRows", "Maximum rows per sheet (0 = all)", "number"), f("dataOnly", "Return calculated cell values", "boolean"), f("nestedHeaders", "Convert dotted headers into nested JSON fields", "boolean"), f("skipBlankRows", "Skip blank rows", "boolean")],
    input: [d("filePath", "Dynamic workbook path", "string"), d("sheetName", "Dynamic worksheet/tab name", "string"), d("headerRow", "Dynamic header row", "integer"), d("startRow", "Dynamic first row", "integer"), d("maximumRows", "Dynamic maximum rows", "integer")],
    output: [d("workbook", "Workbook result", "object"), d("workbook.fileName", "Workbook file name"), d("workbook.sheetCount", "Worksheet count", "integer"), d("workbook.sheets", "Worksheets/tabs", "array"), d("workbook.sheets.name", "Worksheet name"), d("workbook.sheets.headers", "Column headers", "array"), d("workbook.sheets.rows", "Nested JSON row data", "array")],
    errors: [{ type: "EXCEL_READ", description: "The workbook, requested worksheet, or cell data could not be read." }],
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
                ...(parsing ? [
                  { ...f("inputSource", "Input source", "select"), options: ["String", "File path"] },
                  f("filePath", "Input file path", "text", "Read the formatted data directly from this local runtime path when Input source is File path."),
                  f("fileEncoding", "File encoding", "text", "Defaults to UTF-8 with optional BOM detection."),
                  f("rootElement", "Output XML root element"),
                  f("recordElement", "Output XML record element"),
                ] : []),
                { ...f("format", "Format", "select"), options: ["delimited", "fixed"] },
                f("delimiter", "Column separator"),
                { ...f("separatorRule", "Multi-character separator rule", "select"), options: ["single", "any-character"] },
                { ...f("lineSeparator", "Line separator", "select"), options: ["Auto", "LF", "CRLF", "CR"] },
                f("header", "First row is header", "boolean"),
                f("fields", "Field names", "text", "Comma-separated names used when the input has no header. An attached schema supplies these automatically."),
                f("fieldTypes", "Field data types", "text", "Optional comma-separated XML schema types such as string, integer, decimal, and boolean."),
                f("widths", "Fixed field widths"),
                f("fillCharacter", "Fixed-width fill character"),
                f("strictColumns", "Require exact column count", "boolean"),
                f("trimValues", "Trim parsed values", "boolean"),
                f("skipBlankLines", "Skip blank lines", "boolean"),
                f("includeFinalLineSeparator", "Append final line separator", "boolean"),
              ]),
      ],
      input: n.type === "xml" && parsing ? [d("xmlString", "XML text", "string"), d("xmlBinary", "XML binary/base64", "binary"), d("forceEncoding", "Forced encoding")] : n.type === "xml" ? [d("value", "XML schema tree", "object", true)] : n.type === "json" && parsing ? [d("jsonString", "JSON text", "string", true)] : n.type === "json" ? [d("value", "JSON schema tree", "object", true)] : parsing ? [d("text", "Formatted data string", "string"), d("filePath", "Direct file path", "string")] : [d("records", "Data records", "array", true)],
      output: parsing
        ? n.type === "json"
          ? [d("value", "Parsed JSON value", "json")]
          : [d("xml", n.type === "flat" ? "Parsed data XML" : "Parsed XML", "xml")]
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
  if (n.type === "ems" || n.type === "jms") {
    const jms = n.type === "jms", destinationKey = op.includes("queue") || op === "send" ? "queue" : op.includes("topic") || op === "publish" ? "topic" : "destination", resource = { ...f("resourceId", jms ? "JMS connection" : "TIBCO EMS connection", "resource"), resourceType: n.type, required: true },
      messageType = { ...f("messageType", "Message type", "select"), options: ["Text", "Bytes", "Map", "Object", "Object Ref", "Simple", "Stream", "XML Text"] },
      style = { ...f("messagingStyle", "Messaging style", "select"), options: ["Queue", "Topic", "Generic"] },
      ack = { ...f("acknowledgeMode", "Acknowledge mode", "select"), options: ["Auto", "Client", "Dups OK", "Explicit Client", "Explicit Client Dups OK", "Transactional"] },
      receiver = [resource, style, f(destinationKey, "Destination", "text", "Queue or topic name; expressions are supported."), messageType, f("messageSelector", "JMS message selector"), ack, f("maxSessions", "Maximum sessions", "number"), f("flowLimit", "Flow limit", "number"), f("receiveTimeout", "Receive timeout (ms)", "number")],
      sender = [resource, style, f(destinationKey, "Destination"), messageType,
        { ...f("deliveryMode", "Delivery mode", "select"), options: ["Persistent", "Non-Persistent"] }, f("priority", "Priority (0-9)", "number"), f("expiration", "Expiration (ms)", "number"), f("correlationId", "JMS correlation ID"), f("replyTo", "Reply-to destination"), f("disableMessageId", "Disable JMS message ID", "boolean"), f("disableTimestamp", "Disable JMS timestamp", "boolean"), f("dynamicProperties", "JMS application / dynamic properties (JSON)", "textarea")];
    const configs: Record<string, Field[]> = {
      queue_receiver: receiver,
      topic_subscriber: [...receiver, f("durable", "Durable subscriber", "boolean"), f("subscriptionName", "Durable subscription name"), f("sharedSubscription", "Shared subscription", "boolean")],
      queue_sender: sender,
      topic_publisher: sender,
      request_reply: [...sender, f("requestTimeout", "Request timeout (ms)", "number"), f("temporaryReplyDestination", "Use temporary reply destination", "boolean")],
      reply: [resource, style, f("destination", "Reply destination"), messageType, f("correlationId", "Request correlation ID"), ...sender.slice(4)],
      get_queue_message: [resource, f("queue", "Queue name"), messageType, f("messageSelector", "JMS message selector"), ack, f("receiveTimeout", "Receive timeout (ms)", "number")],
      receive_message: [resource, style, f("destination", "Destination"), messageType, f("messageSelector", "JMS message selector"), ack, f("maxSessions", "Maximum sessions", "number"), f("flowLimit", "Flow limit", "number"), f("receiveTimeout", "Receive timeout (ms)", "number"), f("durable", "Durable subscription", "boolean"), f("subscriptionName", "Durable subscription name"), f("sharedSubscription", "Shared subscription", "boolean")],
      send_message: [resource, style, f("destination", "Destination"), messageType, ...sender.slice(4)],
      reply_message: [resource, style, f("destination", "Reply destination"), messageType, f("correlationId", "Request correlation ID"), ...sender.slice(4)],
      wait_request: [resource, style, f("destination", "Destination"), messageType, f("messageSelector", "JMS message selector"), ack, f("receiveTimeout", "Receive timeout (ms)", "number")],
    };
    const receiving = ["queue_receiver", "topic_subscriber", "get_queue_message", "receive_message", "wait_request"].includes(op);
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
      publish: [resource, f("topic", "Topic name"), f("assignCustomPartition", "Assign custom partition", "boolean"), f("partitionId", "Partition ID", "number"), ...serialization, { ...f("acks", "Acknowledgements", "select"), options: ["0", "1", "all"] }, { ...f("compressionType", "Compression type", "select"), options: ["none", "gzip", "snappy", "lz4", "zstd"] }, f("retries", "Producer retries", "number"), f("bufferMemory", "Buffer memory (bytes)", "number"), f("batchSize", "Batch size", "number"), f("lingerMs", "Linger (ms)", "number"), f("maxRequestSize", "Maximum request size", "number"), f("transactionalId", "Transactional ID"), f("enableIdempotence", "Enable idempotence", "boolean"), f("additionalProperties", "Additional producer properties (JSON)", "textarea")],
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
  if (isMapperActivity(n.type))
    return {
      configuration: [],
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
  if (n.type === "dataweave")
    return {
      configuration: [],
      input: [d("payload", "DataWeave payload", "object", true), d("attributes", "Input attributes", "object"), d("variables", "Transform variables", "object")],
      output: [d("result", "Transformed payload", "object")],
      errors: [
        { type: "DATAWEAVE_SYNTAX", description: "The transform script could not be parsed." },
        { type: "DATAWEAVE_EXECUTION", description: "A selector, function, coercion, or collection operation failed." },
        { type: "DATAWEAVE_OUTPUT", description: "The transformed value cannot be rendered in the requested MIME type." },
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
      checkpoint: { configuration: [f("checkpointName", "Checkpoint name", "text", "Optional logical name stored in runtime execution metadata."), f("includeProcessState", "Include process state", "boolean")], input: [], output: [d("checkpointId", "Checkpoint ID"), d("timestamp", "Checkpoint timestamp", "dateTime")], errors: [{ type: "CheckpointException", description: "The process state could not be persisted." }] },
      sleep: { configuration: [f("duration", "Duration", "number"), { ...f("unit", "Unit", "select"), options: ["milliseconds", "seconds", "minutes"] }], input: [d("duration", "Dynamic duration", "number")], output: [d("sleptMilliseconds", "Elapsed delay", "integer")], errors: [{ type: "INTERRUPTED", description: "The wait was interrupted or cancelled." }] },
      get_context: { configuration: [], input: [], output: [d("taskId", "Task ID"), d("activityId", "Activity ID"), d("environment", "Environment"), d("correlationId", "Correlation ID")], errors: [] },
      set_context: { configuration: [], input: [d("values", "Context values", "object", true)], output: [d("context", "Updated process context", "object")], errors: commonErrors.slice(2) },
      get_shared_variable: { configuration: [f("name", "Shared variable name")], input: [d("default", "Default value", "object")], output: [d("name", "Variable name"), d("value", "Shared value", "object")], errors: [] },
      set_shared_variable: { configuration: [f("name", "Shared variable name")], input: [d("value", "Shared value", "object", true)], output: [d("name", "Variable name"), d("value", "Shared value", "object")], errors: [] },
      external_command: { configuration: [f("command", "Command to execute", "textarea", "Executable and arguments. Shell pipes are intentionally not evaluated."), f("provideCommandOutput", "Provide command output", "boolean"), f("removeParameterQuotes", "Remove parameter quotes", "boolean"), f("outputFile", "Output filename"), { ...f("outputLineSplitting", "Output line splitting", "select"), options: ["None", "AtOperatingSystemLineEnd", "AtSpecifiedToken"] }, f("splitToken", "Specified split token"), f("workingDirectory", "Working directory"), f("environment", "Environment variables [NAME=value,...]"), f("replaceEnvironment", "Replace inherited environment", "boolean"), f("timeoutSeconds", "Timeout seconds", "number"), f("encoding", "Output encoding")], input: [d("command", "Dynamic command", "string"), d("input", "Standard input", "string"), d("outputFile", "Dynamic output file", "string"), d("environment", "Dynamic environment", "object|string"), d("workingDirectory", "Dynamic working directory", "string"), d("splitToken", "Dynamic split token", "string")], output: [d("returnCode", "Process return code", "integer"), d("output", "Standard output", "string|array"), d("error", "Standard error", "string|array"), d("outputFile", "Written output file")], errors: [{ type: "CommandExecutionError", description: "The operating system command could not start or timed out." }, { type: "FileIOError", description: "Command output could not be written to the configured file." }, { type: "InvalidInputException", description: "The command or line-splitting configuration is invalid." }] },
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
  if (node.type === "snowflake" && node.config?.entityMetadata?.columns?.length) {
    const columns = node.config.entityMetadata.columns.map((column: any) => d(column.name, column.name, column.xsdType || "string", !!column.notNull));
    if (node.config.operation === "query") return { ...contract, output: [d("rows", "Query result records", "array"), ...columns.map((field: DataField) => ({ ...field, key: `rows.${field.key}` })), d("rowCount", "Rows returned", "integer")] };
    if (["insert", "update", "delete"].includes(node.config.operation)) return { ...contract, input: [d("records", "Snowflake records", "array"), ...columns.map((field: DataField) => ({ ...field, key: `records.${field.key}` }))] };
  }
  if (node.type === "jdbc" && node.config?.outputColumns?.length && ["query", "dynamic"].includes(node.config?.operation)) {
    const columns = node.config.outputColumns.map((column: any) => d(`resultSet.Record.${column.name}`, column.name, column.xsdType || column.dataType || "string"));
    return { ...contract, output: [...contract.output.filter((field) => field.key !== "resultSet.Record"), ...columns] };
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
    const dynamic = String(node.config?.dynamicTaskId || "").trim();
    const designTimeId = dynamic && !dynamic.startsWith("${") ? dynamic : node.config?.taskId;
    const called = tasks.find((candidate: any) => (candidate.id === designTimeId || candidate.name === designTimeId) && candidate.kind === "subtask");
    const input = boundaryFields(called, "start", schemas), output = boundaryFields(called, "end", schemas);
    return {
      ...contract,
      input: input.length ? input : contract.input,
      output: output.length ? output : contract.output,
    };
  }
  return contract;
}

function possibleTaskExceptions(task: any, tasks: any[], schemas: any[]): string[] {
  const values = new Set<string>(["RUNTIME", "VALIDATION", "UserDefinedException", "RethrowException"]);
  (task?.activities || []).filter((activity: any) => activity.type !== "catch").forEach((activity: any) => {
    resolvedActivityContract(activity, task, tasks, schemas).errors.forEach((error) => values.add(error.type));
  });
  return [...values].sort((left, right) => left.localeCompare(right));
}

function runtimeMappableInputs(node: any, contract: Contract): DataField[] {
  if (["xml", "json", "flat"].includes(node.type)) return contract.input;
  if (["start", "timer", "http_listener"].includes(node.type) || (node.type === "file" && node.config?.operation === "poll")) return contract.input;
  const existing = new Set(contract.input.map((field) => field.key));
  const inferred = (field: Field) => field.type === "number" ? "number" : field.type === "boolean" ? "boolean" : "string";
  const dynamic = contract.configuration
    .filter((field) => !existing.has(field.key) && !["resource", "task", "idoc", "snowflake_entity"].includes(field.type || "text"))
    .map((field) => d(field.key, field.label, inferred(field), !!field.required, field.help));
  const configuredJdbcParameters = Array.isArray(node.config?.preparedParameters) ? node.config.preparedParameters : [];
  const jdbcParameters = node.type === "jdbc"
    ? (configuredJdbcParameters.length ? configuredJdbcParameters : (node.config?.preparedParameterNames || []).map((name: string) => ({ name, type: "string" })))
      .map((parameter: any) => d(`parameters.${parameter.name}`, parameter.name, parameter.type || "string", true, `Prepared SQL value for :${parameter.name}.`))
    : [];
  return [...contract.input, ...jdbcParameters, ...dynamic];
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
  jdbc: { summary: "Executes the documented JDBC Query, Update, Call Procedure, or SQL Direct contract.", behavior: "The JDBC designer runs and fetches SQL metadata, derives prepared parameters and result fields, supports dynamic SQL overrides, batching, subsets, NULL handling, maximum rows, transaction overrides, and database-specific drivers.", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.13.0/doc/pdf/TIB_BW_6.13.0_bindings_palletes_reference.pdf?id=4" },
  snowflake: { summary: "Runs Snowflake Insert, Query, Update, Delete, or staged Bulk Load operations.", behavior: "The Snowflake JDBC shared connection supplies authentication, warehouse, database, schema, pooling, and downloaded table/view metadata. Activity inputs and outputs follow the TIBCO BusinessWorks Snowflake 6.3.1 contracts.", url: "https://docs.tibco.com/pub/bwpluginsnowflake/6.3.1/doc/pdf/TIB_bwpluginsnowflake_6.3.1_user-guide.pdf?id=0" },
  amqp: { summary: "Sends, receives, gets, or dead-letters AMQP messages.", behavior: "The shared connection supports RabbitMQ AMQP 0.9.1/1.0 and AMQP 1.0 broker profiles. Destinations, subscriptions, typed messages, properties, settlement handles, recovery, SSL, sessions, and Azure dead-letter behavior follow the TIBCO AMQP 6.5.3 contracts.", url: "https://docs.tibco.com/pub/bwpluginamqp/6.5.3/doc/pdf/TIB_bwpluginamqp_6.5.3_user-guide.pdf?id=1" },
  excel: { summary: "Reads an Excel workbook and publishes every selected worksheet as nested JSON.", behavior: "Leave Worksheet blank to read every tab. The configured header row becomes field names; dotted headers such as customer.address.city create nested objects. Formula cells can return their cached calculated values." },
  basic: { summary: "Executes the selected BusinessWorks-style general activity.", behavior: "External Command runs an executable without a shell, accepts stdin/environment/working-directory overrides, can capture or persist stdout and stderr, applies documented line splitting, and publishes the process return code.", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.13.0/doc/pdf/TIB_BW_6.13.0_bindings_palletes_reference.pdf?id=4" },
  ems: { summary: "Sends, receives, browses, or acknowledges TIBCO EMS messages.", behavior: "Destination, delivery, selector, acknowledgement, and message properties follow the selected EMS operation. Client acknowledgement handles can be passed to Confirm Message." },
  kafka: { summary: "Produces, receives, or commits Apache Kafka records.", behavior: "Broker security comes from the shared Kafka connection. Topic, key, headers, value, partitions, offsets, and acknowledgement handles are available for hierarchical mapping." },
  pubsub: { summary: "Publishes, receives, or acknowledges Google Cloud Pub/Sub messages.", behavior: "Project and credential defaults come from the shared connection. Message data, attributes, ordering keys, and acknowledgement handles remain available on the execution path." },
  sap: { summary: "Executes the selected SAP ECC operation.", behavior: "The shared SAP connection supplies system and authentication settings. IDoc metadata selected from SAP defines listener, parser, renderer, and sender structures." },
  mapper: { summary: "Maps execution-path data into a selected target schema.", behavior: "The consolidated Mapper includes schema trees, XPath-style functions, repeating For-Each/For-Each-Group rules, AI-assisted recommendations, validation, and an executable test surface." },
  transform: { summary: "Legacy Mapper activity retained for project compatibility.", behavior: "Existing Transform nodes continue to execute with Mapper behavior. New projects should use Mapper for visual/XPath mappings or Transform for DataWeave scripts." },
  ai_transform: { summary: "Legacy AI Mapper activity retained for project compatibility.", behavior: "Existing AI Transform nodes continue to use the consolidated Mapper and its AI recommendation/review workflow." },
  dataweave: { summary: "Transforms payloads with an executable DataWeave 2.0-compatible integration subset.", behavior: "Scripts support payload/attributes/vars selectors, objects, arrays, defaults, conditionals, concatenation, common coercion/string/collection functions, map/filter/groupBy/orderBy/distinctBy, JSON, XML, and text output. The editor validates and runs the same engine used at runtime.", url: "https://docs.mulesoft.com/dataweave/latest/dataweave-language-introduction" },
  call_task: { summary: "Invokes a reusable Sub Task and waits for its result.", behavior: "Mapped values become the Sub Task Start input. Dynamic Sub Task ID/name is resolved per invocation; the selected Sub Task is its design-time schema and runtime fallback. The Sub Task End output returns to this activity." },
  confirm: { summary: "Acknowledges one or more client-managed messages.", behavior: "Map the acknowledgement handle emitted by an EMS, Kafka, Pub/Sub, or compatible future receiver. The runtime dispatches confirmation to the originating connector." },
  start: { summary: "Defines the task input boundary.", behavior: "For Sub Tasks, the Start schema is the callable input contract. Starter Tasks normally use one external event activity instead." },
  end: { summary: "Defines the task output boundary.", behavior: "Mapped values become the final task result. For a Sub Task, this result is returned to its Call Sub Task activity." },
  log: { summary: "Writes a structured application log event.", behavior: "Message, level, and payload accept constants or dynamic mappings. Advanced automatic payload logging can be used when a dedicated Log activity is unnecessary." },
  xml: { summary: "Parses XML text into an XSD-defined tree or renders an XSD-defined tree as XML.", behavior: "Parse XML accepts serialized XML in Input and defines its published tree in Output Editor. Render XML defines and maps its source tree in Input Editor, then emits xmlString (or binary output when selected).", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/render-xml.htm" },
  json: { summary: "Converts between serialized JSON and a schema-defined activity tree.", behavior: "Parse JSON accepts jsonString and publishes the structure selected in Output Editor. Render JSON maps the structure selected in Input Editor and emits jsonString.", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.8.0/doc/html/binding-palette/render-json.htm" },
  flat: { summary: "Parses delimited/fixed-width text into records or renders records as formatted text.", behavior: "The schema contract defines record fields; Configuration controls separators, widths, headers, trimming, and line endings. Parse Data publishes records while Render Data accepts mapped records and emits text.", url: "https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/render-data.htm" },
};

function DocumentationStructure({ title, fields }: { title: string; fields: DataField[] }) {
  const rows = dataTreeRows(fields), tree = useTreeCollapse();
  return <section><h3>{title}</h3>{fields.length ? <div className="documentation-tree">{rows.map((field) => { if (!tree.visible(field.path)) return null; const group = field.group || hasTreeChildren(rows, field); return <div key={field.path} style={{ "--doc-depth": field.depth } as React.CSSProperties} className={group ? "group" : ""}>{group ? <TreeToggle path={field.path} label={field.label} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <i className="tree-elbow"/>}<span>{field.name}</span><code>{group ? "object" : field.type}</code><b>{field.required ? "required" : ""}</b><small>{field.help}</small></div>; })}</div> : <p>No explicit {title.toLowerCase()} fields are required for this operation.</p>}</section>;
}

function ActivityDocumentation({ node, contract }: { node: any; contract: Contract }) {
  const doc = activityDocumentation[node.type] || {
    summary: `Executes the ${node.name} activity on the current task path.`,
    behavior: "Configuration supplies design-time defaults. Input mappings, constants, property expressions, outputs, advanced policies, and documented errors are evaluated by the runtime.",
  };
  return <div className="activity-tab activity-documentation">
    <header><BookOpen/><span><h2>{node.name}</h2><small>{node.type} / {node.config?.operation || "default"}</small></span>{doc.url && <a href={doc.url} target="_blank" rel="noreferrer"><ExternalLink/> Official reference</a>}</header>
    <section><h3>Purpose</h3><p>{doc.summary}</p><p>{doc.behavior}</p></section>
    {node.type === "jdbc" && <section className="jdbc-documentation"><h3>Prepared SQL examples</h3><p>Use named parameters in the SQL editor. Each <code>:name</code> is automatically created as a typed field under <b>Input → parameters</b>.</p><pre>{`SELECT id, customer_name, status\nFROM orders\nWHERE status = :status AND created_at >= :fromDate;\n\nUPDATE orders SET status = :status WHERE id = :orderId;`}</pre><p>Choose the JDBC datatype beside every derived parameter. Runtime mappings and constants are converted to that datatype before the prepared statement is executed.</p></section>}
    <section><h3>Configuration reference</h3>{contract.configuration.length ? <div className="documentation-fields">{contract.configuration.map((field) => <article key={field.key}><b>{field.label}{field.required && " *"}</b><code>{field.type || "text"}</code><p>{field.help || `Sets the ${field.label.toLowerCase()} used by this activity.`}</p></article>)}</div> : <p>This boundary activity has no additional operation configuration.</p>}</section>
    <DocumentationStructure title="Input contract" fields={runtimeMappableInputs(node, contract)}/>
    <DocumentationStructure title="Output contract" fields={contract.output}/>
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
  handleExceptions,
  tab,
  update,
}: any) {
  const contract = resolvedActivityContract(node, task, tasks, schemas || []),
    cfg = node.config || {},
    upstreamSources = upstreamActivitySources(node, task, tasks, schemas || []),
    [mapperOpen, setMapperOpen] = useState(false),
    set = (key: string, value: any) =>
      update({ config: { ...cfg, [key]: value } });
  const exceptionTypes = possibleTaskExceptions(task, tasks, schemas || []);
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
          {node.type !== "timer" && contract.configuration.filter((field) => !(node.type === "call_task" && field.key === "dynamicTaskId")).map((field) => (
            <FieldEditor
              key={field.key}
              field={node.type === "catch" && field.key === "errorType" ? { ...field, type: "select", options: ["", ...exceptionTypes] } : field}
              value={cfg[field.key]}
              set={set}
              resources={resources}
              tasks={tasks}
              selectedResourceId={cfg.resourceId}
            />
          ))}
        </div>
        {node.type === "jdbc" && <JdbcDesigner config={cfg} resource={resources.find((resource: any) => resource.id === cfg.resourceId)} properties={properties} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>}
        {node.type === "timer" && <SchedulerEditor config={cfg} set={set}/>}
        {node.type === "call_task" && <CallTaskRoutingEditor config={cfg} tasks={tasks} properties={properties} set={set}/>}
        {node.type === "catch" && <CatchAIEditor nodeId={node.id} exceptionTypes={exceptionTypes} handleExceptions={handleExceptions}/>}
        {isMapperActivity(node.type) && (
          <>
            <TransformSchemaEditor config={cfg} schemas={schemas || []} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>
            <TransformPoliciesEditor ai config={cfg} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>
            <button className="open-mapper" onClick={() => setMapperOpen(true)}>
              <WandSparkles /> Open visual AI Mapper{" "}
              <small>{Array.isArray(cfg.mappings) ? cfg.mappings.length : 0} mappings configured</small>
            </button>
          </>
        )}
        {node.type === "dataweave" && <DataWeaveScriptEditor config={cfg} schemas={schemas || []} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>}
        {(node.type === "start" || node.type === "end") && (
          <TaskBoundarySchemaEditor node={node} config={cfg} schemas={schemas || []} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>
        )}
        {!(["xml", "json", "flat", "timer"].includes(node.type)) && <ExpressionHelp properties={properties} />}
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
    return isMapperActivity(node.type) ? (
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
  if (tab === "map_test" && isMapperActivity(node.type))
    return <TransformMapTestEditor node={node} config={cfg} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>;
  if (tab === "map_test" && node.type === "dataweave")
    return <DataWeaveTestEditor config={cfg} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>;
  if (tab === "output")
    return isMapperActivity(node.type) ? <TransformOutputEditor config={cfg}/> : <OutputEditor fields={contract.output} config={cfg} set={set} before={(["xml", "json", "flat"].includes(node.type) && cfg.operation === "parse") ? <DataContractSchemaEditor node={node} config={cfg} schemas={schemas || []} direction="output" setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/> : null}/>;
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

function CallTaskRoutingEditor({ config, tasks, properties, set }: any) {
  const subtasks = (tasks || []).filter((task: any) => task.kind === "subtask"), expression = String(config.dynamicTaskId || ""), literal = expression && !expression.startsWith("${"), resolvedDesignTime = literal ? subtasks.find((task: any) => task.id === expression || task.name === expression) : subtasks.find((task: any) => task.id === config.taskId);
  return <section className="call-task-routing">
    <header><Workflow/><span><b>DYNAMIC SUB TASK ROUTING</b><small>Resolved at runtime for every call; the selected Sub Task supplies the fallback contract.</small></span><i>{expression ? "OVERRIDE ACTIVE" : "STATIC FALLBACK"}</i></header>
    <div><label>Dynamic ID/name expression<input value={expression} onChange={(event) => set("dynamicTaskId", event.target.value)} placeholder="${properties.routing.targetTask}"/><small>Accepts a literal Sub Task ID/name, an environment property, task input, process variable, or previous activity output.</small></label><label>Insert project property<select value="" onChange={(event) => event.target.value && set("dynamicTaskId", `\${properties.${event.target.value}}`)}><option value="">Browse properties…</option>{(properties || []).map((property: any) => <option key={property.key} value={property.key}>{property.key}</option>)}</select><small>The expression is resolved using the active design-time or runtime environment.</small></label></div>
    <footer><span><b>Design-time interface</b>{resolvedDesignTime ? `${resolvedDesignTime.name} (${resolvedDesignTime.id})` : "No valid fallback Sub Task selected"}</span><span><b>Runtime precedence</b>dynamic override → selected fallback → TASK_NOT_FOUND</span></footer>
  </section>;
}

function CatchAIEditor({ nodeId, exceptionTypes, handleExceptions }: any) {
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => setSelected([]), [nodeId]);
  const toggle = (type: string) => setSelected((current) => current.includes(type) ? current.filter((item) => item !== type) : [...current, type]);
  return <section className="catch-ai-editor">
    <header><WandSparkles/><span><b>Catch AI · Task exception analyzer</b><small>Declared exceptions from every activity in the current Task are available below.</small></span><i>{exceptionTypes.length} FOUND</i></header>
    <div className="catch-ai-actions"><button type="button" onClick={() => setSelected(exceptionTypes)}>Select all</button><button type="button" onClick={() => setSelected([])}>Clear</button></div>
    <div className="catch-ai-types">{exceptionTypes.map((type: string) => <label key={type} className={selected.includes(type) ? "selected" : ""}><input type="checkbox" checked={selected.includes(type)} onChange={() => toggle(type)}/><ShieldAlert/><span><b>{type}</b><small>Generate Catch → Throw handler block</small></span></label>)}</div>
    <footer><span>Generated Throw activities map the caught error type, code, message, details, and stack trace automatically.</span><button type="button" disabled={!selected.length} onClick={() => handleExceptions?.(selected)}><WandSparkles/> Handle {selected.length || "selected"} exception{selected.length === 1 ? "" : "s"}</button></footer>
  </section>;
}

function SchedulerEditor({ config, set }: any) {
  const mode = config.scheduleMode || "dateTime";
  return <section className="scheduler-editor">
    <header><CalendarClock/><span><b>Scheduler trigger</b><small>Choose one deterministic schedule mode for this Starter Task.</small></span></header>
    <div className="scheduler-mode-tabs" role="tablist">
      <button type="button" className={mode === "dateTime" ? "active" : ""} onClick={() => set("scheduleMode", "dateTime")}>Date &amp; time</button>
      <button type="button" className={mode === "cron" ? "active" : ""} onClick={() => set("scheduleMode", "cron")}>Cron</button>
    </div>
    {mode === "dateTime" ? <div className="scheduler-fields">
      <label>First execution date and time<input type="datetime-local" value={config.scheduledDateTime || ""} onChange={(event) => set("scheduledDateTime", event.target.value)}/><small>Uses the selected time zone.</small></label>
      <label>Time zone<select value={config.timezone || "local"} onChange={(event) => set("timezone", event.target.value)}><option value="local">Machine local time</option><option value="UTC">UTC</option></select></label>
      <label className="scheduler-check"><input type="checkbox" checked={!!config.repeatEnabled} onChange={(event) => set("repeatEnabled", event.target.checked)}/> Repeat after the first execution</label>
      {config.repeatEnabled && <><label>Every<input type="number" min="1" value={config.interval || 1} onChange={(event) => set("interval", Number(event.target.value))}/></label><label>Interval unit<select value={config.unit || "minutes"} onChange={(event) => set("unit", event.target.value)}><option>seconds</option><option>minutes</option><option>hours</option><option>days</option></select></label></>}
    </div> : <div className="scheduler-fields cron-fields">
      <label>Cron expression<input value={config.cronExpression || "0 * * * *"} onChange={(event) => set("cronExpression", event.target.value)} placeholder="minute hour day month weekday"/><small>Five fields: minute, hour, day-of-month, month, day-of-week. Supports *, values, ranges, lists, and */step.</small></label>
      <label>Time zone<select value={config.timezone || "local"} onChange={(event) => set("timezone", event.target.value)}><option value="local">Machine local time</option><option value="UTC">UTC</option></select></label>
    </div>}
    <label className="scheduler-run-once"><input type="checkbox" checked={config.runOnceOnLocalStart !== false} onChange={(event) => set("runOnceOnLocalStart", event.target.checked)}/><span><b>Run once now for local Run/Debug</b><small>Executes immediately during local testing without waiting for the scheduled instant. Production packaging still honors the configured schedule.</small></span></label>
  </section>;
}

function DataWeaveScriptEditor({ config, schemas, setConfig }: any) {
  const [status, setStatus] = useState("");
  const templates = [
    { name: "Map collection", script: `%dw 2.0\noutput application/json\nfun normalize(value) = upper(trim(value))\n---\npayload.items map (item) -> {\n  id: item.id as String,\n  name: normalize(item.name default "")\n}` },
    { name: "Group records", script: `%dw 2.0\noutput application/json\n---\npayload.items groupBy (item) -> item.category default "unclassified"` },
    { name: "Enrich message", script: `%dw 2.0\noutput application/json\n---\n{\n  data: payload,\n  requestId: attributes.requestId default "",\n  region: vars.region default "global"\n}` },
    { name: "CSV to JSON", script: `%dw 2.0\ninput payload text/csv\noutput application/json\n---\npayload` },
  ];
  const chooseSchema = (key: "sourceSchemaId" | "targetSchemaId", id: string) => {
    const schema = schemas.find((item: any) => item.id === id);
    setConfig({ [key]: id, [key === "sourceSchemaId" ? "sourceSchema" : "targetSchema"]: schema?.content || {} });
  };
  const generate = async () => {
    setStatus("Generating a reviewable transform draft…");
    try {
      const response = await fetch("/api/dataweave/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sourceSchema: config.sourceSchema || {}, targetSchema: config.targetSchema || {}, threshold: config.threshold || 70 }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "AI transform generation failed");
      setConfig({ script: result.script, aiRecommendations: result.recommendations, aiReviewRequired: true });
      setStatus(`${result.recommendations?.length || 0} schema recommendations generated. Review and test the script before saving the project.`);
    } catch (error: any) { setStatus(error.message || "AI generation failed"); }
  };
  return <section className="dataweave-editor">
    <header><Braces/><span><b>DATAWEAVE TRANSFORM</b><small>Executable DataWeave 2.0-compatible integration language</small></span><button type="button" onClick={generate}><Sparkles/> AI generate</button></header>
    <div className="dataweave-contracts">
      <label>Source schema<select value={config.sourceSchemaId || ""} onChange={(event) => chooseSchema("sourceSchemaId", event.target.value)}><option value="">Runtime payload / no schema</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></label>
      <label>Target schema<select value={config.targetSchemaId || ""} onChange={(event) => chooseSchema("targetSchemaId", event.target.value)}><option value="">Dynamic output / no schema</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></label>
      <label>Input MIME type<select value={config.inputMimeType || "application/json"} onChange={(event) => setConfig({ inputMimeType: event.target.value })}><option>application/json</option><option>application/xml</option><option>text/plain</option><option>text/csv</option></select></label>
      <label>Output MIME type<select value={config.outputMimeType || "application/json"} onChange={(event) => {
        const mime = event.target.value, script = String(config.script || "").replace(/output\s+[^\s]+/, `output ${mime}`);
        setConfig({ outputMimeType: mime, script });
      }}><option>application/json</option><option>application/xml</option><option>text/csv</option><option>text/plain</option></select></label>
      <label>Output target<select value={config.outputTarget || "payload"} onChange={(event) => setConfig({ outputTarget: event.target.value })}><option value="payload">Message payload</option><option value="attributes">Message attributes</option><option value="variable">Flow variable</option></select></label>
      {config.outputTarget === "variable" && <label>Variable name<input value={config.outputVariable || "transformResult"} onChange={(event) => setConfig({ outputVariable: event.target.value })} placeholder="transformResult"/></label>}
    </div>
    <div className="dataweave-templates"><b>STARTING POINTS</b>{templates.map((template) => <button type="button" key={template.name} onClick={() => { setConfig({ script: template.script, outputMimeType: "application/json", inputMimeType: template.name === "CSV to JSON" ? "text/csv" : config.inputMimeType || "application/json", aiReviewRequired: false }); setStatus(`${template.name} template loaded. Use Map & Test with representative data before Run.`); }}>{template.name}</button>)}</div>
    <label className="dataweave-script"><span>Transform script <i>runtime executable</i></span><textarea value={config.script || "%dw 2.0\noutput application/json\n---\npayload"} onChange={(event) => setConfig({ script: event.target.value, aiReviewRequired: false })} spellCheck={false}/></label>
    <div className="dataweave-capabilities"><b>Embedded engine</b><span>Nested &amp; wildcard selectors</span><span>Objects &amp; arrays</span><span>default / if-else</span><span>Custom functions</span><span>as type coercion</span><span>map / flatMap / filter</span><span>mapObject / pluck</span><span>groupBy / orderBy / distinctBy</span><span>read / write</span><span>JSON / XML / CSV / text</span><small>Common integration transformations execute locally in Run, Debug, and Test. Namespaces, type declarations, pattern matching, annotations, and Mule runtime-only modules are rejected explicitly.</small></div>
    {status && <p className="dataweave-status">{status}</p>}
  </section>;
}

function DataWeaveTestEditor({ config, setConfig }: any) {
  const initial = typeof config.sampleInput === "string" ? config.sampleInput : JSON.stringify(config.sampleInput || {}, null, 2);
  const [input, setInput] = useState(initial || "{}");
  const [attributes, setAttributes] = useState(JSON.stringify(config.sampleAttributes || {}, null, 2));
  const [variables, setVariables] = useState(JSON.stringify(config.sampleVariables || config.variables || {}, null, 2));
  const [output, setOutput] = useState(config.lastTestOutput == null ? "" : typeof config.lastTestOutput === "string" ? config.lastTestOutput : JSON.stringify(config.lastTestOutput, null, 2));
  const [state, setState] = useState<"idle" | "running" | "valid" | "error">("idle"), [message, setMessage] = useState("The test uses the same embedded engine as Run and Debug.");
  const run = async () => {
    setState("running"); setMessage("Executing transform script…");
    try {
      const parsed = config.inputMimeType === "application/json" ? JSON.parse(input) : input, parsedAttributes = JSON.parse(attributes || "{}"), parsedVariables = JSON.parse(variables || "{}"), response = await fetch("/api/dataweave/test", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ script: config.script, input: parsed, attributes: parsedAttributes, variables: parsedVariables, inputMimeType: config.inputMimeType || "application/json" }) }), result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Transform test failed");
      setOutput(typeof result.output === "string" ? result.output : JSON.stringify(result.output, null, 2));
      setState("valid"); setMessage(`Valid ${result.version} transform · ${result.mimeType}`); setConfig({ sampleInput: input, sampleAttributes: parsedAttributes, sampleVariables: parsedVariables, lastTestOutput: result.output, outputMimeType: result.mimeType });
    } catch (error: any) { setState("error"); setMessage(error.message || "Transform test failed"); setOutput(""); }
  };
  return <div className="activity-tab dataweave-test">
    <header><FlaskConical/><span><b>Transform · Test</b><small>Execute representative payload data before running the Task.</small></span></header>
    <main><section className="dataweave-test-inputs"><label><span>INPUT PAYLOAD · {config.inputMimeType || "application/json"}</span><textarea value={input} onChange={(event) => { setInput(event.target.value); setState("idle"); }} spellCheck={false}/></label><details><summary>Message attributes</summary><textarea aria-label="Sample message attributes" value={attributes} onChange={(event) => { setAttributes(event.target.value); setState("idle"); }} spellCheck={false}/></details><details><summary>Flow variables</summary><textarea aria-label="Sample flow variables" value={variables} onChange={(event) => { setVariables(event.target.value); setState("idle"); }} spellCheck={false}/></details></section><label><span>GENERATED OUTPUT · {config.outputTarget || "payload"}</span><pre>{output || "Run the transform to generate output."}</pre></label></main>
    <footer className={state}><span>{state === "valid" ? <CheckCircle2/> : state === "error" ? <AlertTriangle/> : <FlaskConical/>}{message}</span><button type="button" disabled={state === "running" || !String(config.script || "").trim()} onClick={run}>{state === "running" ? "Running…" : "Run transform"}</button></footer>
  </div>;
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

function TransformPoliciesEditor({ ai, config, setConfig }: any) {
  const change = (key: string, value: any) => setConfig({ [key]: value });
  return <section className="transform-policies">
    <header><WandSparkles/><span><b>INTEGRATION MAPPING POLICIES</b><small>Executable output, compatibility, validation, and failure behavior</small></span></header>
    <div className="transform-policy-grid">
      <label>Mapping dialect<select value={config.language || "XPath 2.0 / functions"} onChange={(event) => change("language", event.target.value)}><option>XPath 2.0 / functions</option><option>XPath 1.0 compatibility</option><option>JSONPath / functions</option><option>XSLT 2.0 compatibility</option></select></label>
      <label>Null and missing values<select value={config.nullPolicy || "omit"} onChange={(event) => change("nullPolicy", event.target.value)}><option value="omit">Omit target field</option><option value="preserve">Preserve null / xsi:nil</option><option value="empty-string">Emit empty string</option><option value="default">Use configured default</option></select></label>
      <label>Type coercion<select value={config.typeCoercion || "safe"} onChange={(event) => change("typeCoercion", event.target.value)}><option value="strict">Strict schema types</option><option value="safe">Safe automatic coercion</option><option value="off">No coercion</option></select></label>
      <label>Mapping error behavior<select value={config.onMappingError || "fail"} onChange={(event) => change("onMappingError", event.target.value)}><option value="fail">Fail activity</option><option value="skip-field">Skip failed field</option><option value="use-null">Map null and continue</option></select></label>
      <label>Maximum output size (KB)<input type="number" min="0" step="1" value={config.maxOutputSizeKb || 0} onChange={(event) => change("maxOutputSizeKb", Math.max(0, Number(event.target.value) || 0))}/><small>0 means unlimited; execution fails before publishing an oversized result.</small></label>
      {config.nullPolicy === "default" && <label>Default null value<input value={config.defaultValue ?? ""} onChange={(event) => change("defaultValue", event.target.value)} placeholder="Schema-compatible fallback"/></label>}
      <label className="policy-switch"><input type="checkbox" checked={config.validateOutput !== false} onChange={(event) => change("validateOutput", event.target.checked)}/><span><b>Validate target output</b><small>Reject output that violates the configured JSON schema.</small></span></label>
      <label className="policy-switch"><input type="checkbox" checked={config.trimStrings === true} onChange={(event) => change("trimStrings", event.target.checked)}/><span><b>Trim mapped strings</b><small>Remove surrounding whitespace after functions are applied.</small></span></label>
      <label className="policy-switch"><input type="checkbox" checked={config.removeEmptyStructures === true} onChange={(event) => change("removeEmptyStructures", event.target.checked)}/><span><b>Remove empty structures</b><small>Prune null, empty objects, arrays, and strings from the final result.</small></span></label>
      <label className="policy-switch"><input type="checkbox" checked={config.copyNil !== false} onChange={(event) => change("copyNil", event.target.checked)}/><span><b>Copy nil semantics</b><small>Preserve explicit source null values when the null policy allows them.</small></span></label>
    </div>
    {ai && <div className="ai-policy-panel"><header><Sparkles/><span><b>AI MAPPING ASSISTANCE</b><small>Suggestions never overwrite manually approved rules.</small></span></header><div><label>Minimum confidence<input type="range" min="40" max="100" value={config.threshold || 70} onChange={(event) => change("threshold", Number(event.target.value))}/><b>{config.threshold || 70}%</b></label><label>Matching strategy<select value={config.aiStrategy || "balanced"} onChange={(event) => change("aiStrategy", event.target.value)}><option value="balanced">Balanced name, type, and hierarchy</option><option value="strict">Strict schema and type match</option><option value="semantic">Semantic business-name match</option></select></label><label className="policy-switch"><input type="checkbox" checked={config.requireAiReview !== false} onChange={(event) => change("requireAiReview", event.target.checked)}/><span><b>Require approval</b><small>Keep recommended mappings pending until reviewed.</small></span></label><label className="policy-switch"><input type="checkbox" checked={config.autoMapRepeating !== false} onChange={(event) => change("autoMapRepeating", event.target.checked)}/><span><b>Infer repeating structures</b><small>Recommend For-Each for compatible source and target cardinality.</small></span></label></div></div>}
  </section>;
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
  const tree = useTreeCollapse();
  return <div className="schema-hierarchy-preview"><header><Braces/><span><b>Tree preview</b><small>{fields.length} schema elements</small></span></header>{fields.map((field) => { if (!tree.visible(field.path)) return null; const group = hasTreeChildren(fields, field); return <div className={group ? "tree-branch-row" : ""} key={field.path} style={{ "--schema-depth": field.depth } as React.CSSProperties}>{group ? <TreeToggle path={field.path} label={field.name} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <i className="tree-elbow"/>}<span><b>{field.name}</b><small>{field.type}</small></span></div>; })}{!fields.length && <p>No schema elements are available yet.</p>}</div>;
}

function JdbcDesigner({ config, resource, properties, setConfig }: any) {
  const [metadata, setMetadata] = useState<any>(null), [preview, setPreview] = useState<any>(null), [status, setStatus] = useState(""), [busy, setBusy] = useState(false);
  const propertyValues = Object.fromEntries((properties || []).map((item: any) => [item.key, item.value]));
  const runtimeResource = resource ? { ...resource, config: Object.fromEntries(Object.entries(resource.config || {}).map(([key, value]) => { const match = typeof value === "string" ? value.match(/^\$\{properties\.([^}]+)\}$/) : null; return [key, match ? propertyValues[match[1]] : value]; })) } : null;
  const parameterTypes = ["string", "integer", "number", "boolean", "date", "time", "timestamp", "binary", "json"];
  const samples: Record<string, string> = {
    query: "SELECT id, customer_name, status\nFROM orders\nWHERE status = :status AND created_at >= :fromDate",
    insert: "INSERT INTO orders (id, customer_name, status)\nVALUES (:orderId, :customerName, :status)",
    update: "UPDATE orders\nSET status = :status\nWHERE id = :orderId",
    delete: "DELETE FROM orders\nWHERE id = :orderId",
    dynamic: "SELECT * FROM orders WHERE customer_id = :customerId",
  };
  const configuredParameters = Array.isArray(config.preparedParameters) ? config.preparedParameters : [];
  const updateSql = (sql: string) => {
    const named = [...sql.matchAll(/(^|[^:]):([A-Za-z_][A-Za-z0-9_]*)/g)].map((match) => match[2]);
    const count = (sql.match(/\?/g) || []).length;
    const names = [...new Set(named.length ? named : Array.from({ length: count }, (_, index) => `Parameter${index + 1}`))];
    const existing = Object.fromEntries(configuredParameters.map((item: any) => [item.name, item.type]));
    setConfig({ sql, preparedParameterNames: names, preparedParameters: names.map((name) => ({ name, type: existing[name] || "string" })) });
  };
  const setParameterType = (name: string, type: string) => setConfig({ preparedParameters: configuredParameters.map((item: any) => item.name === name ? { ...item, type } : item) });
  const request = async (path: string, body: any) => {
    if (!runtimeResource) { setStatus("Select a JDBC shared connection first."); return null; }
    setBusy(true); setStatus("");
    try { const response = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }); const output = await response.json(); if (!response.ok) throw new Error(output.detail || "JDBC operation failed"); return output; }
    catch (error: any) { setStatus(error?.message || "JDBC operation failed"); return null; }
    finally { setBusy(false); }
  };
  const fetchMetadata = async () => { const output = await request("/api/jdbc/metadata", { resource: runtimeResource }); if (output) { setMetadata(output); setStatus(`${output.tables?.length || 0} tables and views fetched.`); } };
  const run = async () => { const output = await request("/api/jdbc/test-query", { resource: runtimeResource, operation: config.operation, config: { ...config, parameters: Object.fromEntries((config.preparedParameterNames || []).map((name: string) => [name, null])) } }); if (output) { setPreview(output); const columns = output.columns || Object.keys(output.rows?.[0] || {}).map((name) => ({ name, dataType: typeof output.rows[0][name] })); setConfig({ outputColumns: columns }); setStatus(`${output.rowCount ?? output.noOfUpdates ?? 0} rows returned/affected. Output schema refreshed.`); } };
  return <section className="jdbc-designer"><header><span><Database/><b>JDBC SQL DESIGNER</b><small>Prepared SQL editor · parameters become typed Input fields automatically.</small></span><span><button type="button" onClick={fetchMetadata} disabled={busy || !resource}><RefreshCw/> Fetch metadata</button><button type="button" onClick={run} disabled={busy || !resource || (!String(config.sql || "").trim() && config.operation !== "call")}><FlaskConical/> Run &amp; fetch</button></span></header>{config.operation !== "call" && <><div className="jdbc-editor-toolbar"><span><b>SQL statement</b><small>Use <code>:parameterName</code> for safe dynamic values.</small></span><button type="button" onClick={() => updateSql(samples[config.operation] || samples.query)}>Insert sample {config.operation || "query"}</button></div><div className="jdbc-code-editor"><span aria-hidden="true">SQL</span><textarea aria-label="JDBC SQL statement" value={config.sql || ""} onChange={(event) => updateSql(event.target.value)} placeholder={samples[config.operation] || samples.query} spellCheck={false}/></div></>} {!!configuredParameters.length && <div className="jdbc-parameters"><header><b>Derived input parameters</b><small>Map values in Input → parameters; choose the database datatype here.</small></header>{configuredParameters.map((parameter: any, index: number) => <label key={`${parameter.name}-${index}`}><code>{index + 1}</code><span><b>:{parameter.name}</b><small>parameters.{parameter.name}</small></span><select aria-label={`Datatype for ${parameter.name}`} value={parameter.type || "string"} onChange={(event) => setParameterType(parameter.name, event.target.value)}>{parameterTypes.map((type) => <option key={type}>{type}</option>)}</select></label>)}</div>} {metadata && <div className="jdbc-schema-browser">{metadata.tables?.map((table: any) => <button type="button" key={`${table.schema}.${table.name}`} onClick={() => updateSql(`SELECT * FROM ${table.schema ? `${table.schema}.` : ""}${table.name}`)}><span><b>{table.name}</b><small>{table.schema} · {table.type}</small></span><code>{table.columns?.length || 0} columns</code></button>)}</div>} {preview && <pre>{JSON.stringify(preview, null, 2)}</pre>} {status && <p>{status}</p>}</section>;
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
      ) : field.type === "methods" ? (
        <span className="http-method-picker" role="group" aria-label={field.label}>
          {HTTP_METHODS.map((method) => {
            const selected = String(value || "")
              .split(",")
              .map((item) => item.trim().toUpperCase())
              .includes(method);
            return (
              <button
                type="button"
                key={method}
                className={selected ? "selected" : ""}
                aria-pressed={selected}
                onClick={() => {
                  const current = String(value || "")
                    .split(",")
                    .map((item) => item.trim().toUpperCase())
                    .filter((item) => HTTP_METHODS.includes(item));
                  const next = selected
                    ? current.filter((item) => item !== method)
                    : HTTP_METHODS.filter((item) => [...current, method].includes(item));
                  change(next.join(","));
                }}
              >
                {method}
              </button>
            );
          })}
          <small>{String(value || "").split(",").filter(Boolean).length} methods enabled</small>
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
      ) : field.type === "snowflake_entity" ? (
        <select value={value || ""} onChange={(e) => {
          const selected = resources.find((resource: any) => resource.id === selectedResourceId)?.config?.entityCatalog?.find((item: any) => `${item.database}.${item.schema}.${item.name}` === e.target.value || item.name === e.target.value);
          change(e.target.value);
          if (selected) set("entityMetadata", selected);
        }}>
          <option value="">Select an entity retrieved by the Snowflake connection…</option>
          {(resources.find((resource: any) => resource.id === selectedResourceId)?.config?.entityCatalog || []).map((item: any) => {
            const qualified = [item.database, item.schema, item.name].filter(Boolean).join(".");
            return <option value={qualified || item.name} key={qualified || item.name}>{qualified || item.name} · {item.entityType || "TABLE"}</option>;
          })}
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
    const fields = isMapperActivity(activity.type)
      ? transformSchemaFields(activity.config || {}).map((field) => ({ key: field.path, label: field.name, type: field.type }))
      : resolvedActivityContract(activity, task, tasks, schemas).output;
    return { activity, distance: pathDistance, fields };
  }).filter(Boolean).sort((a: any, b: any) => a.distance - b.distance) as ActivitySource[];
}
function DataSourcePane({ properties, sources = [], customFunctions = [], updateCustomFunctions }: any) {
  customFunctions = customFunctions.length ? customFunctions : properties?.customFunctions || [];
  updateCustomFunctions = updateCustomFunctions || properties?.updateCustomFunctions;
  const [tab, setTab] = useState<"data" | "functions" | "constants">("data"), [search, setSearch] = useState(""), [selectedSource, setSelectedSource] = useState("");
  const tree = useTreeCollapse();
  const item = (label: string, expression: string, type = "object", showExpression = true, depth = 0, group = false, enabled = true, treePath = expression) => {
    const branch = group ? <TreeToggle path={treePath} label={label} collapsed={tree.collapsed.has(treePath)} toggle={tree.toggle}/> : <i className="tree-elbow"/>;
    return enabled ? <button className={`source-tree-node ${group ? "tree-group-node" : ""} ${selectedSource === expression ? "source-selected" : ""}`} aria-pressed={selectedSource === expression} style={{ "--tree-depth": depth } as React.CSSProperties} data-expression={expression} key={`${label}-${expression}`} draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData("expression", expression); event.dataTransfer.setData("sourceType", type); event.dataTransfer.setData("sourceRepeating", String(type.toLowerCase().includes("[]") || type.toLowerCase().includes("array"))); setSelectedSource(expression); }} onClick={() => setSelectedSource(expression)} title={`Drag ${label} onto the desired target field`}>{branch}<Braces/><span><b>{label}</b>{showExpression && <small>{expression}</small>}</span><code>{type}</code></button> : <div className="source-tree-node tree-group-node" style={{ "--tree-depth": depth } as React.CSSProperties} key={`${label}-${depth}`}>{branch}<Braces/><span><b>{label}</b></span><code>{type}</code></div>;
  };
  const functionItems = mapperFunctions.filter((name) => name.toLowerCase().includes(search.toLowerCase()));
  const constantItem = (label: string, value: any, type: string) => <button className="source-tree-node constant-source" key={label} draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData("expression", `__fabric_constant__:${JSON.stringify(value)}`); event.dataTransfer.setData("sourceType", type); }} title={`Drag ${label} onto a simple target field`}><Braces/><span><b>{label}</b><small>{JSON.stringify(value)}</small></span><code>{type}</code></button>;
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
  return <aside className="source-pane"><div className="source-tabs"><button className={tab === "data" ? "active" : ""} onClick={() => setTab("data")}>Data</button><button className={tab === "functions" ? "active" : ""} onClick={() => setTab("functions")}>Functions</button><button className={tab === "constants" ? "active" : ""} onClick={() => setTab("constants")}>Constants</button></div><input className="source-search" aria-label={`Search ${tab}`} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${tab}…`}/>{tab === "data" ? <div className="source-list"><h4>EXECUTION PATH OUTPUTS · {visibleSources.length}</h4>{!query && item("Initial task input", "${input}", "object", false)}{visibleSources.map((source: ActivitySource) => { const sourceRows = dataTreeRows(source.fields); return <details className="activity-source" key={source.activity.id} open={source.distance === 1 || !!query}><summary><span className="tree-disclosure"/><Braces/><span><b>{source.activity.name}</b><small>{source.distance === 1 ? "Immediate predecessor" : `${source.distance} steps upstream`} · {source.activity.type}</small></span><code>{source.fields.length}</code></summary>{item("Output", `\${activities.${source.activity.id}.output}`, "object", false)}{sourceRows.map((field) => { const path = `${source.activity.id}.${field.path}`; if (!query && !tree.visible(path)) return null; return item(field.label, `\${activities.${source.activity.id}.output.${field.path}}`, field.type, false, field.depth + 1, field.group, true, path); })}</details>; })}{!visibleSources.length && <p className="source-empty">No connected upstream activity matches this search.</p>}<h4>PROCESS CONTEXT</h4>{item("Task ID", "${context.taskId}", "string", false)}{item("Environment", "${context.environment}", "string", false)}{item("Current activity ID", "${context.activityId}", "string", false)}<h4>GLOBAL VARIABLES</h4>{dataTreeRows(propertyFields).map((property) => { const path = `properties.${property.path}`; if (!query && !tree.visible(path)) return null; return item(property.label, `\${properties.${property.path}}`, property.type, false, property.depth, property.group, property.explicit, path); })}</div> : tab === "functions" ? <div className="source-list function-list"><div className="custom-function-heading"><h4>PROJECT FUNCTIONS · {customFunctions.length}</h4><button onClick={createFunction}><Plus/> New</button></div>{customFunctions.filter((fn: any) => fn.name.toLowerCase().includes(query)).map((fn: any) => item(fn.name, `custom:${fn.name}(${fn.parameters.map((name: string) => `$${name}`).join(", ")})`, "custom", false))}<h4>BW-STYLE FUNCTIONS · {functionItems.length}</h4>{functionItems.map((name) => item(name, `${name}()`, "function", false))}</div> : <div className="source-list constants-list"><h4>TYPED CONSTANTS</h4>{constantItem("Empty string", "", "string")}{constantItem("True", true, "boolean")}{constantItem("False", false, "boolean")}{constantItem("Zero", 0, "integer")}{constantItem("Empty object", {}, "object")}{constantItem("Empty array", [], "array")}{constantItem("Null", null, "null")}</div>}</aside>;
}
function describeMapping(expression: any, sources: ActivitySource[]): string {
  if (expression === undefined || expression === null || expression === "") return "Drop a source field or enter a constant";
  if (typeof expression === "object" && expression?.$rule) return `${expression.$rule} › ${describeMapping(expression.source, sources)}`;
  if (typeof expression !== "string") return `Constant › ${JSON.stringify(expression)}`;
  if (expression.startsWith("__fabric_constant__:")) return `Constant › ${expression.slice(20)}`;
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
function isComplexSchemaType(fieldType: any): boolean {
  const type = String(fieldType || "").toLowerCase();
  return type === "object" || type === "complex" || type === "json" || type.includes("array") || type.endsWith("[]") || type.includes("complex[]") || type.includes("object[]");
}
function MappingBinding({ expression, sources, onChange, onConstantChange, fieldType = "string", structural = false }: any) {
  const hasValue = expression !== undefined && expression !== null && expression !== "";
  const editableExpression = mappingSource(expression);
  const type = String(fieldType).toLowerCase();
  const booleanType = type.includes("boolean");
  const integerType = ["integer", "long", "short", "byte"].some((name) => type.includes(name));
  const numericType = integerType || ["number", "decimal", "double", "float"].some((name) => type.includes(name));
  const sourceExpression = typeof editableExpression === "string" && (editableExpression.startsWith("${") || editableExpression.startsWith("$") || editableExpression.includes("("));
  const literalValue = sourceExpression || editableExpression === "" || editableExpression == null
    ? ""
    : (!booleanType && !numericType && typeof editableExpression === "string"
      ? (/^(['"]).*\1$/.test(editableExpression) ? editableExpression : JSON.stringify(editableExpression))
      : String(editableExpression));
  const constantPanel = useRef<HTMLDetailsElement>(null);
  const validationFailure = useRef(false);
  const [literalDraft, setLiteralDraft] = useState(() => literalValue);
  const [literalError, setLiteralError] = useState("");

  useEffect(() => { setLiteralDraft(literalValue); setLiteralError(""); }, [literalValue]);

  if (structural || isComplexSchemaType(fieldType)) {
    return <div className={`mapping-binding structural-binding ${hasValue ? "mapped" : ""}`}><Braces/><span>{hasValue ? describeMapping(expression, sources) : "Structure is populated through its child elements"}</span>{hasValue && <button type="button" title="Clear structural statement" onClick={(event) => { event.stopPropagation(); onChange(""); }}>×</button>}</div>;
  }

  const commitConstant = (raw: string): boolean => {
    const commit = onConstantChange || onChange;
    if (booleanType) {
      validationFailure.current = false; setLiteralError(""); commit(raw === "true"); return true;
    }
    if (numericType) {
      const valid = integerType ? /^-?\d+$/.test(raw) : /^-?(?:\d+\.?\d*|\.\d+)$/.test(raw);
      if (!valid) {
        validationFailure.current = true;
        setLiteralError(integerType ? "Enter an integer without quotes or special characters." : "Enter a numeric value without quotes or special characters.");
        return false;
      }
      validationFailure.current = false; setLiteralError(""); commit(Number(raw)); return true;
    }
    const quoted = raw.match(/^(['"])([\s\S]*)\1$/);
    if (!quoted) { validationFailure.current = true; setLiteralError("String constants must be enclosed in matching single or double quotes."); return false; }
    if (/[\u0000-\u001f]/.test(quoted[2])) { validationFailure.current = true; setLiteralError("Control characters are not allowed in string constants."); return false; }
    validationFailure.current = false; setLiteralError(""); commit(onConstantChange ? quoted[2] : raw); return true;
  };
  const finishConstant = (raw: string) => {
    if (raw !== "" && commitConstant(raw) && constantPanel.current) constantPanel.current.open = false;
  };

  return <div className={`mapping-binding ${hasValue ? "mapped" : ""} ${literalError ? "literal-invalid" : ""}`}>
    <span>{describeMapping(expression, sources)}</span>
    {hasValue && <button type="button" title="Clear value" onClick={(event) => { event.stopPropagation(); onChange(""); }}>×</button>}
    <details
      ref={constantPanel}
      className="mapping-constant-editor"
      onClick={(event) => event.stopPropagation()}
      onToggle={(event) => { if (event.currentTarget.open) window.setTimeout(() => event.currentTarget.querySelector<HTMLElement>("input,select")?.focus(), 0); }}
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as globalThis.Node) && !validationFailure.current && constantPanel.current) constantPanel.current.open = false; }}
    >
      <summary role="button" tabIndex={0} aria-label={`Enter ${fieldType} constant value`} title="Enter a schema-typed constant value" onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.currentTarget.parentElement?.toggleAttribute("open"); } }}>123</summary>
      <div className="mapping-constant-box">
        <b>{fieldType} constant</b>
        {booleanType ? (
          <select aria-label="Constant boolean value" value={editableExpression === true ? "true" : editableExpression === false ? "false" : ""} onChange={(event) => { if (commitConstant(event.target.value) && constantPanel.current) constantPanel.current.open = false; }}><option value="">Select…</option><option value="true">true</option><option value="false">false</option></select>
        ) : (
          <input type="text" inputMode={numericType ? "decimal" : "text"} aria-label={`${fieldType} constant value`} value={literalDraft} placeholder={numericType ? (integerType ? "123" : "123.45") : "\"text value\" or 'text value'"} onChange={(event) => { const raw = event.target.value; if (numericType && !/^-?(?:\d*\.?\d*)?$/.test(raw)) return; validationFailure.current = false; setLiteralDraft(raw); setLiteralError(""); }} onBlur={() => finishConstant(literalDraft)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); finishConstant(literalDraft); } if (event.key === "Escape" && constantPanel.current) constantPanel.current.open = false; }}/>
        )}
        <small>{numericType ? "Numbers are unquoted and accept digits, an optional leading minus, and a decimal point when supported." : booleanType ? "Select the schema-valid boolean value." : "Strings require matching single or double quotes."}</small>
        {literalError && <em role="alert">{literalError}</em>}
      </div>
    </details>
    <details className="mapping-function-editor" onClick={(event) => event.stopPropagation()}><summary role="button" tabIndex={0} aria-label={`Enter advanced expression for ${fieldType} field`} title="Open function and expression editor" onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.currentTarget.parentElement?.toggleAttribute("open"); } }}>fx</summary><div className="mapping-function-box"><b>Function or expression</b><input aria-label="Advanced mapping expression" value={typeof editableExpression === "string" ? editableExpression : ""} placeholder="Choose a function or enter an expression…" onChange={(event) => onChange(event.target.value)}/><small>Use the Functions tab, project properties, or an advanced runtime expression.</small></div></details>
  </div>;
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
  const resize = useSourcePaneWidth(), tree = useTreeCollapse(), root = useRef<HTMLDivElement>(null), [selected, setSelected] = useState(firstTarget), [contextMenu, setContextMenu] = useState<any>(null);
  useEffect(() => { if (!rows.some((row) => row.explicit && row.path === selected)) setSelected(firstTarget); }, [firstTarget, selected, rows]);
  const connectionMappings = Object.fromEntries(Object.entries(mappings).map(([path, value]) => [path, mappingSource(value)]));
  return <div ref={root} className="activity-tab mapping-editor resizable-mapper visual-field-mapper" style={{ "--source-width": `${resize.width}px` } as React.CSSProperties}><DataSourcePane properties={properties} sources={sources}/><div className="source-splitter" title="Drag left or right to resize data sources" onPointerDown={resize.begin}><span/></div><section><div className="contract-heading"><SettingsTitle title="Activity input" text="Map simple schema elements and attributes. Complex structures are controlled exclusively through their child fields."/></div>{before}{fields.length ? <div className="input-contract-tree"><header><Braces/><span><b>{node.name}</b><small>Schema-typed hierarchical input · constants are validated against each simple field type</small></span></header>{rows.map((field) => { if (!tree.visible(field.path)) return null; const group = field.group || hasTreeChildren(rows, field), structural = group || isComplexSchemaType(field.type), branch = group ? <TreeToggle path={field.path} label={field.label} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <i className="tree-elbow"/>; return field.explicit ? <div data-target={structural ? undefined : field.path} className={`input-tree-row ${structural ? "tree-parent-target structural-row" : ""} ${selected === field.path ? "selected" : ""}`} key={field.path} style={{ "--target-depth": field.depth + 1 } as React.CSSProperties} onClick={() => setSelected(field.path)} onContextMenu={(event) => { event.preventDefault(); if (structural) return; setSelected(field.path); setContextMenu({ x: event.clientX, y: event.clientY, path: field.path, label: field.label }); }} onDragOver={(event) => { if (structural) return; event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={(event) => { event.preventDefault(); if (structural) return; const expression = event.dataTransfer.getData("expression"); if (!expression) return; setSelected(field.path); set({ ...mappings, [field.path]: expression }); }}>{branch}<span className="target-tree-field"><b>{field.label}</b>{field.required && <em>required</em>}<small>{field.type}{structural ? " · structural node" : " · schema-typed value"}{field.help && ` · ${field.help}`}</small></span><MappingBinding structural={structural} expression={mappings[field.path] ?? ""} fieldType={field.type} sources={sources} onChange={(value: any) => set({ ...mappings, [field.path]: value })}/></div> : <div className="input-tree-group" key={field.path} style={{ "--target-depth": field.depth + 1 } as React.CSSProperties}>{branch}<Braces/><span><b>{field.label}</b><small>object · {rows.filter((candidate) => candidate.path.startsWith(`${field.path}.`) && candidate.explicit).length} fields · child mappings only</small></span></div>; })}</div> : <div className="contract-empty"><CheckCircle2/>This starter/activity has no configurable input.</div>}</section><MappingConnections root={root} mappings={connectionMappings}/><MappingContextMenu menu={contextMenu} value={contextMenu ? mappings[contextMenu.path] : null} close={() => setContextMenu(null)} change={(value: any) => contextMenu && set({ ...mappings, [contextMenu.path]: value })} remove={() => { if (!contextMenu) return; const next = { ...mappings }; delete next[contextMenu.path]; set(next); }}/></div>;
}

type SchemaTreeField = { path: string; name: string; type: string; depth: number; repeating: boolean; minOccurs?: string; maxOccurs?: string };
function transformSchemaFields(config: any): SchemaTreeField[] {
  const text = config.targetSchemaText || JSON.stringify(config.targetSchema || {});
  try {
    const schema = JSON.parse(text), fields: SchemaTreeField[] = [];
    const walk = (node: any, prefix = "", depth = 0) => Object.entries(node?.properties || node || {}).forEach(([name, child]: any) => { const path = prefix ? `${prefix}.${name}` : name, repeating = child?.type === "array" || Array.isArray(child); const item = repeating ? (child?.items || child?.[0] || {}) : child; fields.push({ path, name, type: repeating ? `${item?.type || (item?.properties ? "object" : "value")}[]` : child?.type || typeof child, depth, repeating, minOccurs: child?.minItems != null ? String(child.minItems) : undefined, maxOccurs: child?.maxItems != null ? String(child.maxItems) : repeating ? "unbounded" : undefined }); if (item?.properties) walk(item, path, depth + 1); });
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
        const name = element.getAttribute("name") || element.getAttribute("ref")?.split(":").pop() || "element", rawType = element.getAttribute("type") || "complex", baseType = rawType.split(":").pop() || rawType, maxOccurs = element.getAttribute("maxOccurs") || "1", repeating = maxOccurs === "unbounded" || Number(maxOccurs) > 1, type = repeating ? `${baseType}[]` : baseType, path = prefix ? `${prefix}.${name}` : name;
        fields.push({ path, name, type, depth, repeating, minOccurs: element.getAttribute("minOccurs") || "1", maxOccurs });
        const inline = Array.from(element.children).find((child) => local(child) === "complextype"), referenced = complexTypes.get(baseType);
        const container = inline || referenced || element;
        Array.from(container.getElementsByTagNameNS("*", "attribute")).filter((attribute) => { let parent: Element | null = attribute.parentElement; while (parent && local(parent) !== "element") parent = parent.parentElement; return parent === element; }).forEach((attribute) => { const attributeName = attribute.getAttribute("name") || attribute.getAttribute("ref")?.split(":").pop() || "attribute"; fields.push({ path: `${path}.@${attributeName}`, name: `@${attributeName}`, type: (attribute.getAttribute("type") || "string").split(":").pop() || "string", depth: depth + 1, repeating: false }); });
        directElements(container).forEach((child) => walkElement(child, path, depth + 1));
      };
      Array.from(document.documentElement.children).filter((element) => local(element) === "element").forEach((element) => walkElement(element));
      return fields;
    } catch { return []; }
  }
}
function TransformInputEditor({ config, properties, sources, setMappings, customFunctions, updateCustomFunctions }: any) {
  properties = Object.assign([...(properties || [])], { customFunctions, updateCustomFunctions });
  const fields = transformSchemaFields(config), resize = useSourcePaneWidth(280), tree = useTreeCollapse(), root = useRef<HTMLDivElement>(null), [selected, setSelected] = useState(fields[0]?.path || ""), [contextMenu, setContextMenu] = useState<any>(null), mappings = Array.isArray(config.mappings) ? config.mappings : [];
  const mapTo = (target: string, source: any, sourceRepeating = false) => {
    if (typeof source === "string" && source.startsWith("__fabric_constant__:")) {
      try { mapConstant(target, JSON.parse(source.slice(20))); } catch { /* Ignore malformed drag data. */ }
      return;
    }
    const targetField = fields.find((field) => field.path === target), explicitlyIndexed = typeof source === "string" && /\[\d+\]/.test(source);
    const targetIsComplex = !!targetField && (hasTreeChildren(fields, targetField) || isComplexSchemaType(targetField.type));
    if (targetIsComplex && !targetField?.repeating) return;
    const repeat = !!targetField?.repeating && sourceRepeating && !explicitlyIndexed;
    const next = mappings.filter((rule: any) => !(rule.target === target && !rule.occurrenceId));
    next.push({ target, source, targetType: targetField?.type || "any", ...(repeat ? { select: source, operator: "for-each" } : {}), functions: [], enabled: true });
    if (repeat && typeof source === "string") {
      const match = source.match(/^\$\{activities\.([^.}]+)\.output(?:\.([^}]+))?\}$/), sourceActivity = match && sources.find((entry: ActivitySource) => entry.activity.id === match[1]), sourceRoot = match?.[2] || "";
      if (sourceActivity && sourceRoot) {
        const existingTargets = new Set(next.filter((rule: any) => !rule.occurrenceId).map((rule: any) => rule.target));
        fields.filter((candidate) => candidate.path.startsWith(`${target}.`)).forEach((candidate) => {
          const relative = candidate.path.slice(target.length + 1), sourcePath = `${sourceRoot}.${relative}`;
          if (!existingTargets.has(candidate.path) && sourceActivity.fields.some((sourceField: DataField) => sourceField.key === sourcePath)) {
            next.push({ target: candidate.path, source: `\${activities.${sourceActivity.activity.id}.output.${sourcePath}}`, targetType: candidate.type, functions: [], enabled: true, autoGenerated: true });
          }
        });
      }
    }
    setMappings(next);
  };
  const mapConstant = (target: string, constant: any) => setMappings([...mappings.filter((rule: any) => !(rule.target === target && !rule.occurrenceId)), { target, constant, targetType: fields.find((field) => field.path === target)?.type || "any", functions: [], enabled: true }]);
  const duplicateOccurrence = (target: string) => {
    const sourceLoop = mappings.find((rule: any) => rule.target === target && ["for-each", "for-each-group"].includes(rule.operator) && !rule.occurrenceId) || mappings.find((rule: any) => rule.target === target && ["for-each", "for-each-group"].includes(rule.operator));
    if (!sourceLoop) return;
    const occurrenceId = `occurrence-${Date.now()}`, sourceOccurrence = sourceLoop.occurrenceId;
    const family = mappings.filter((rule: any) => (rule.target === target || rule.target.startsWith(`${target}.`)) && rule.occurrenceId === sourceOccurrence);
    setMappings([...mappings, ...family.map((rule: any) => ({ ...rule, occurrenceId, duplicateOf: sourceOccurrence || "primary", autoGenerated: rule.autoGenerated || true }))]);
  };
  const removeOccurrence = (occurrenceId: string) => setMappings(mappings.filter((rule: any) => rule.occurrenceId !== occurrenceId));
  const connectionMappings = Object.fromEntries(mappings.filter((rule: any) => rule.enabled !== false && typeof rule.source === "string" && rule.source.startsWith("${")).map((rule: any) => [rule.target, rule.source]));
  const contextValue = contextMenu ? mappings.find((item: any) => item.target === contextMenu.path && !item.occurrenceId) : null;
  const contextField = contextMenu ? fields.find((field) => field.path === contextMenu.path) : null;
  return <div ref={root} className="activity-tab mapping-editor transform-input-editor resizable-mapper visual-field-mapper" style={{ "--source-width": `${resize.width}px` } as React.CSSProperties}><DataSourcePane properties={properties} sources={sources}/><div className="source-splitter" title="Drag left or right to resize data sources" onPointerDown={resize.begin}><span/></div><section><div className="contract-heading"><SettingsTitle title="Target schema mapping" text="Drop a repeating complex source to create its For-Each statement and matching child mappings. Use Duplicate occurrence for additional target copies."/></div><div className="target-schema-tree">{fields.map((field) => {
    if (!tree.visible(field.path)) return null;
    const rule = mappings.find((item: any) => item.target === field.path && !item.occurrenceId), group = hasTreeChildren(fields, field), structural = group || isComplexSchemaType(field.type), canMapStructure = structural && field.repeating, duplicateLoops = mappings.filter((item: any) => item.target === field.path && item.occurrenceId && ["for-each", "for-each-group"].includes(item.operator));
    return <React.Fragment key={field.path}><div data-target={!structural || canMapStructure ? field.path : undefined} className={`schema-tree-row ${structural ? "tree-parent-target structural-row" : ""} ${rule?.operator ? "mapping-statement-row" : ""} ${selected === field.path ? "selected" : ""}`} style={{ paddingLeft: 12 + field.depth * 18 }} onClick={() => setSelected(field.path)} onContextMenu={(event) => { event.preventDefault(); if (structural && !canMapStructure) return; setSelected(field.path); setContextMenu({ x: event.clientX, y: event.clientY, path: field.path, label: field.name }); }} onDragOver={(event) => { if (structural && !canMapStructure) return; event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={(event) => { event.preventDefault(); if (structural && !canMapStructure) return; const expression = event.dataTransfer.getData("expression"); if (expression) mapTo(field.path, expression, event.dataTransfer.getData("sourceRepeating") === "true"); }}>{group ? <TreeToggle path={field.path} label={field.name} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <span className="tree-node-dot"/>}<span className="tree-field"><b>{field.name}{field.repeating && <em> repeating</em>}</b><small>{field.type} · {field.minOccurs || "1"}..{field.maxOccurs || "1"}{structural && !field.repeating ? " · child mappings only" : ""}{rule?.operator && ` · ${String(rule.operator).replaceAll("-", " ").toUpperCase()} #1`}</small>{field.repeating && rule?.operator && <button type="button" className="duplicate-occurrence" onClick={(event) => { event.stopPropagation(); duplicateOccurrence(field.path); }}><Plus/> Duplicate occurrence</button>}</span><span className={`mapping-connection ${rule ? "connected" : ""}`}><i/><ArrowRight/></span><MappingBinding structural={structural} expression={rule && "constant" in rule ? rule.constant : rule?.source ?? ""} fieldType={field.type} sources={sources} onChange={(value: any) => mapTo(field.path, value)} onConstantChange={(value: any) => mapConstant(field.path, value)}/></div>{duplicateLoops.map((duplicate: any, index: number) => <div className="mapper-duplicate-card" key={duplicate.occurrenceId} style={{ marginLeft: 30 + field.depth * 18 }}><Braces/><span><b>{field.name} · FOR EACH #{index + 2}</b><small>{describeMapping(duplicate.source, sources)} · complete child mapping copy</small></span><button type="button" onClick={() => removeOccurrence(duplicate.occurrenceId)}>Remove</button></div>)}</React.Fragment>;
  })}{!fields.length && <div className="contract-empty">Select a project XSD or enter a valid inline target schema on Configuration.</div>}</div></section><MappingConnections root={root} mappings={connectionMappings}/><MappingContextMenu menu={contextMenu} value={contextValue} canDuplicate={!!contextField?.repeating && !!contextValue?.operator} duplicate={() => contextMenu && duplicateOccurrence(contextMenu.path)} close={() => setContextMenu(null)} change={(value: any) => contextMenu && setMappings([...mappings.filter((item: any) => !(item.target === contextMenu.path && !item.occurrenceId)), { target: contextMenu.path, targetType: contextField?.type || "any", ...(value && typeof value === "object" && value.$rule ? { source: value.source, operator: value.$rule, select: value.select, groupBy: value.groupBy, condition: value.condition, otherwise: value.otherwise, whens: value.whens, duplicateOf: value.duplicateOf } : { source: value }), functions: [], enabled: true }])} remove={() => contextMenu && setMappings(mappings.filter((item: any) => item.target !== contextMenu.path))}/></div>;
}
function TransformOutputEditor({ config }: any) {
  const fields = transformSchemaFields(config);
  const tree = useTreeCollapse();
  return <div className="activity-tab output-editor"><div className="contract-heading"><SettingsTitle title="Transformer output structure" text="Published target schema available to downstream activities"/></div><div className="output-schema-tree">{fields.map((field) => { if (!tree.visible(field.path)) return null; const group = hasTreeChildren(fields, field); return <div className={group ? "tree-parent-target" : ""} key={field.path} style={{ paddingLeft: 14 + field.depth * 18 }}>{group ? <TreeToggle path={field.path} label={field.name} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <span className="tree-node-dot"/>}<code>{field.name}</code><small>{field.type}</small><span>{field.depth ? "Nested field" : "Root field"}</span></div>; })}{!fields.length && <div className="contract-empty">No target schema is configured.</div>}</div></div>;
}

function TransformMapTestEditor({ node: _node, config, setConfig }: any) {
  const initialInput = config.sampleInput && typeof config.sampleInput === "object" ? config.sampleInput : { customer: { id: "C-100", name: "Sample customer" }, amount: 100 };
  const [inputText, setInputText] = useState(() => JSON.stringify(initialInput, null, 2));
  const [outputText, setOutputText] = useState(() => config.lastTestOutput ? JSON.stringify(config.lastTestOutput, null, 2) : "");
  const [status, setStatus] = useState<"idle" | "running" | "valid" | "error">("idle");
  const [message, setMessage] = useState("Enter representative input data, then execute the mappings saved in the Input tab.");
  const mappings = Array.isArray(config.mappings) ? config.mappings : [];
  const run = async () => {
    setStatus("running"); setMessage("Executing mapping rules and formulas…");
    try {
      const input = JSON.parse(inputText);
      const response = await fetch("/api/mapper/test", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input, mappings, targetSchema: config.targetSchema || {}, targetSchemaText: config.targetSchemaText || "", options: config }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || result.message || "Mapping test failed");
      setOutputText(JSON.stringify(result.output ?? {}, null, 2));
      setStatus(result.valid === false ? "error" : "valid");
      setMessage(result.valid === false ? (result.validationErrors || []).join(" · ") || "Output validation failed." : `${result.mappingCount ?? mappings.length} mapping rule${(result.mappingCount ?? mappings.length) === 1 ? "" : "s"} executed successfully.`);
      setConfig({ sampleInput: input, lastTestOutput: result.output ?? {} });
    } catch (error: any) {
      setStatus("error"); setMessage(error.message || "Mapping test failed"); setOutputText("");
    }
  };
  return <div className="activity-tab transform-map-test">
    <header><FlaskConical/><span><b>Mapper · Map &amp; Test</b><small>Execute the exact mappings, constants, conditions, grouping rules, and formulas configured in the Input tab.</small></span><i>{mappings.length} RULE{mappings.length === 1 ? "" : "S"}</i></header>
    <main>
      <section className="map-test-input"><header><span><b>TEST INPUT</b><small>JSON matching the upstream/source structure</small></span><button type="button" onClick={() => { setInputText(JSON.stringify(initialInput, null, 2)); setStatus("idle"); }}>Reset</button></header><textarea aria-label="Transform test input" value={inputText} onChange={(event) => { setInputText(event.target.value); setStatus("idle"); }} spellCheck={false}/></section>
      <section className="map-test-rules"><header><span><b>APPLIED MAPPINGS &amp; FORMULAS</b><small>Saved design-time rules executed in order</small></span></header><div>{mappings.map((rule: any, index: number) => <article key={`${rule.target}-${index}`} className={rule.enabled === false ? "disabled" : ""}><em>{index + 1}</em><span><code>{rule.source ?? ("constant" in rule ? JSON.stringify(rule.constant) : "No source")}</code><ArrowRight/><b>{rule.target || "result"}</b><small>{[rule.operator, ...(rule.functions || []).map((fn: any) => typeof fn === "string" ? fn : fn.name)].filter(Boolean).join(" → ") || "Direct mapping"}</small></span></article>)}{!mappings.length && <p>No mappings are saved. Configure target mappings in the Input tab first.</p>}</div></section>
      <section className="map-test-output"><header><span><b>GENERATED OUTPUT</b><small>Target structure produced by the mapper</small></span>{outputText && <button type="button" onClick={() => navigator.clipboard?.writeText(outputText)}>Copy output</button>}</header><pre>{outputText || "Run the mapping test to generate output."}</pre></section>
    </main>
    <footer className={status}><span>{status === "valid" ? <CheckCircle2/> : status === "error" ? <AlertTriangle/> : <FlaskConical/>}<b>{message}</b></span><button type="button" className="run-map-test" disabled={status === "running" || !mappings.length} onClick={run}><FlaskConical/>{status === "running" ? "Running…" : "Run mapping test"}</button></footer>
  </div>;
}
function OutputEditor({ fields, config, set, before }: any) {
  const rows = dataTreeRows(fields);
  const tree = useTreeCollapse();
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
        {rows.map((field) => { if (!tree.visible(field.path)) return null; const group = field.group || hasTreeChildren(rows, field); return field.explicit ? (
          <div className={field.group ? "tree-parent-target" : ""} key={field.path} style={{ "--output-depth": field.depth } as React.CSSProperties}>
            <code>{group ? <TreeToggle path={field.path} label={field.label} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <i className="tree-elbow"/>}{field.label}</code>
            <span>{field.type}</span>
            <span>{field.required ? "1" : "0..1"}</span>
            <span>{field.help || (field.group ? "Structured element" : "Published field")}</span>
          </div>
        ) : <div className="schema-tree-group" key={field.path} style={{ "--output-depth": field.depth } as React.CSSProperties}><code><TreeToggle path={field.path} label={field.label} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/><Braces/>{field.label}</code><span>object</span><span>group</span><span>Parent structure</span></div>; })}
      </div>
      {!fields.length && (
        <div className="contract-empty">No output schema is published.</div>
      )}
    </div>
  );
}
function AdvancedEditor({ node, value, properties, set }: any) {
  const propertyRows = dataTreeRows(properties.filter((p: any) => p.key.startsWith("advanced.")).map((p: any) => d(p.key, p.key.split(".").pop() || p.key, p.data_type)));
  const propertyTree = useTreeCollapse();
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
      ["http", "jdbc", "snowflake", "amqp", "ftp", "sftp"].includes(
        node.type,
      ) ||
      (node.type === "ems" && ["send", "publish", "request_reply", "reply"].includes(operation)) ||
      (node.type === "kafka" && ["send", "publish", "get"].includes(operation)) ||
      (node.type === "pubsub" && operation === "publish") ||
      (node.type === "rest" && operation === "invoke") ||
      (node.type === "soap" && operation === "request_reply") ||
      (node.type === "sap" &&
        ["idoc_acknowledgment", "idoc_confirmation", "post_idoc", "invoke_rfc_bapi", "reply_rfc_bapi", "read_table"].includes(operation)),
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
  useEffect(() => {
    if (outbound || !value || !("retryEnabled" in value || "retryCount" in value || "retryIntervalSeconds" in value)) return;
    const applicable = { ...value };
    delete applicable.retryEnabled; delete applicable.retryCount; delete applicable.retryIntervalSeconds;
    set(applicable);
  }, [node.id, outbound, value.retryEnabled, value.retryCount, value.retryIntervalSeconds]);
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
        {outbound && <article className="advanced-tree-branch">
          <header>
            <RefreshCw />
            <span>
              <b>Outbound retry policy</b>
              <small>
                Applied when this activity calls its target system.
              </small>
            </span>
            <i>OUTBOUND</i>
          </header>
          <div className="advanced-grid">
            <label className="advanced-tree-field">
              Retry{" "}
              <input
                list="advanced-property-values"
                value={advanced.retryEnabled}
                onChange={(e) => change("retryEnabled", e.target.value)}
              />
              <small>Boolean or global property expression</small>
            </label>
            <label className="advanced-tree-field">
              Retry count{" "}
              <input
                disabled={retryDisabled}
                value={advanced.retryCount}
                onChange={(e) => change("retryCount", e.target.value)}
              />
              <small>Default: 3 retry attempts</small>
            </label>
            <label className="advanced-tree-field">
              Retry interval (seconds){" "}
              <input
                disabled={retryDisabled}
                value={advanced.retryIntervalSeconds}
                onChange={(e) => change("retryIntervalSeconds", e.target.value)}
              />
              <small>Default: 60 seconds</small>
            </label>
          </div>
        </article>}
      </section>
      <aside>
        <b>PROJECT-GLOBAL PROPERTY MAPPINGS</b>
        <p>
          The active environment is resolved once for the complete project,
          including every Task, Sub Task, activity, and shared connection.
        </p>
        <div>
          {propertyRows.map((row) => { if (!propertyTree.visible(row.path)) return null; return row.explicit ? (
            <button key={row.path} className="advanced-property-leaf" style={{ "--tree-depth": row.depth } as React.CSSProperties} onClick={() => navigator.clipboard?.writeText("${properties." + row.path + "}")}><i className="tree-elbow"/><Braces/><span>{row.label}<small>{row.type} · {String(properties.find((property: any) => property.key === row.path)?.value)}</small></span></button>
          ) : <div key={row.path} className="advanced-property-group" style={{ "--tree-depth": row.depth } as React.CSSProperties}><TreeToggle path={row.path} label={row.label} collapsed={propertyTree.collapsed.has(row.path)} toggle={propertyTree.toggle}/><Braces/><span><b>{row.label}</b><small>property group</small></span></div>; })}
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
