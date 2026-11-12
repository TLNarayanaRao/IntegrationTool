import XsdStructurePicker from "./XsdStructurePicker";
import {selectXsdStructure, selectedSchemaText} from "./xsdSelection";
import ModalLayer from "./ModalLayer";
import { editMapperXsd } from "./mapperXsd";
import EndpointSchemaPicker, { savedSchemaChoice, schemaChoiceName } from "./EndpointSchemaPicker";
import HttpContentTypePicker, { HttpContentTypeCheckboxes, savedContentTypes } from "./HttpContentTypePicker";
import HttpRequestParameters, { type RequestParameter } from "./HttpRequestParameters";
import SharedConnectionSelect, { type SharedConnection } from "./SharedConnectionSelect";
import TransformationTools from "./TransformationTools";
import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  ArrowRight,
  ExternalLink,
  BookOpen,
  CalendarClock,
  CheckCircle2,
  Database,
  FlaskConical,
  Plus,
  Pencil,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  WandSparkles,
  Workflow,
  X,
} from "lucide-react";
import MapperStudio from "./MapperStudio";
import MappingExpressionInput from "./MappingExpressionInput";
import {activityMappingRules, activityMappingsFromRules, autoMapLoopChildren, emptyRepeatOccurrence, mapActivityRepeatingDrop, mapRepeatingDrop, relativeLoopExpression, expandLoopExpression, removeRepeatOccurrence, removeMappingSubtree, type RepeatingDropMode} from "./mapperLoopMappings";
import { activityGuidance } from "./activityGuidance";
import { mappingTreeRows, MappingTreeRow } from "./mappingTree";
import { validateMapping } from "./mappingValidation";
import DataNodeIcon from "./DataNodeIcon";
import { resolveWorkspaceSubtask } from "./studioObjectName";
import { functionExpression, mapperFunctionCatalog, mapperFunctionCategories } from "./mapper-functions";
const Braces = DataNodeIcon;

// The normalized display name is the graph ID and mapping reference.
export const activityReferenceName = (value: unknown) => String(value || "Activity")
  .trim()
  .replace(/[^A-Za-z0-9_-]+/g, "-")
  .replace(/-+/g, "-")
  .replace(/^-|-$/g, "") || "Activity";

type Field = {
  key: string;
  label: string;
  type?:
    | "text"
    | "number"
    | "boolean"
    | "select"
    | "methods"
    | "requestParameters"
    | "textarea"
    | "schema"
    | "dataFormat"
    | "mediaType"
    | "mediaTypes"
    | "resource"
    | "artifact"
    | "idoc"
    | "snowflake_entity"
    | "task";
  options?: string[];
  resourceType?: string;
  resourceTypes?: string[];
  artifactType?: "java" | "python";
  required?: boolean;
  help?: string;
  propertyBrowse?: boolean;
  readOnly?: boolean;
  when?: (config: any) => boolean;
};
type DataField = {
  minOccurs?: string;
  maxOccurs?: string;
  repeating?: boolean;
  validationType?: string;
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

function httpRequestFields(output = false): DataField[] {
  const root = output ? "RestOutputResponse" : "RestInputRequest";
  const field = (path: string, type = "string", repeating = false) => ({...d(`${root}.${path}`, path.split(".").slice(-1)[0], type), minOccurs:"0", maxOccurs:repeating ? "unbounded" : "1", repeating});
  const mime = [field("mimeEnvelopeElement", "object"),field("mimeEnvelopeElement.mimePart", "object[]", true),
    field("mimeEnvelopeElement.mimePart.mimeHeaders", "object"),
    ...["content-type","content-transfer-encoding","content-id","content-disposition"].map(name => field(`mimeEnvelopeElement.mimePart.mimeHeaders.${name}`)),
    field("mimeEnvelopeElement.mimePart.binaryContent"),field("mimeEnvelopeElement.mimePart.textContent"),field("mimeEnvelopeElement.mimePart.fileName")];
  const customHeaders = output ? "Headers.DynamicHeaders" : "CustomHeaders";
  const headers = [field("Headers", "object"),...(output ? ["Allow","Content-Type","Content-Length","Content-Encoding","Date","Location","Set-Cookie","Pragma"] : ["accept","content-type","Accept-Charset","Accept-Encoding","Cookie","pragma"]).map(name => field(`Headers.${name}`, output && ["Allow","Set-Cookie"].includes(name) ? "string[]" : "string", output && ["Allow","Set-Cookie"].includes(name))),
    field(customHeaders, "object[]", true),field(`${customHeaders}.name`),field(`${customHeaders}.value`)];
  return [{...d(root,root,"object",true),minOccurs:"1",maxOccurs:"1"},...(output ? [field("statusLine","object"),field("statusLine.httpVersion"),field("statusLine.statusCode","integer"),field("statusLine.reasonPhrase"),field("body","any"),field("asciiContent"),field("binaryContent")] : [field("Config","object"),
    field("Config.host"),field("Config.port","integer"),field("Config.scheme"),field("Config.requestURI"),field("Config.Method"),field("Config.RequestBody","any"),field("Config.bodyFormat"),
    field("Config.QueryParameters","object"),field("Config.URIParameters","object"),field("Config.QueryString"),field("Config.FilePath"),
    field("Config.timeout","integer"),field("Config.activityTimeoutSeconds","number"),field("Config.followRedirects","boolean"),field("Config.raiseForStatus","boolean"),
    field("Config.streamRequest","boolean"),field("Config.responseFile"),field("Config.overwriteResponseFile","boolean"),field("Config.responseBodyMode"),
    field("Config.multipartPartHeaders","object"),
    field("Config.callbackUrl"),
    ...["openApiDocument","openApiReferenceDocuments","requestSchema","responseSchema"].map(name => field(`Config.${name}`,"any")),
    ...["openApiBaseUrl","openApiAllowedRefOrigins","operationId"].map(name => field(`Config.${name}`)),
    field("Config.validateRequest","boolean"),field("Config.validateResponse","boolean"),
    ...["requestEntityProcessing","sendBodyMode","successStatusCodes"].map(name => field(`Config.${name}`))]),...headers,...mime];
}

function httpInputMappings(config: any): any {
  const customRoot = "RestInputRequest.CustomHeaders";
  const legacyRoot = "RestInputRequest.Headers.DynamicHeaders";
  const saved = Object.entries(config.inputMappings || {});
  const isUnder = (key: string, root: string) => key === root || key.startsWith(`${root}.`);
  const hasCustomHeaders = saved.some(([key]) => isUnder(key, customRoot));
  const mappings = saved.flatMap(([key, value]): [string, unknown][] => {
    if (!isUnder(key, legacyRoot)) return [[key, value]];
    return hasCustomHeaders ? [] : [[customRoot + key.slice(legacyRoot.length), value]];
  });
  const aliases: Record<string,string> = {host:"host",port:"port",scheme:"scheme",url:"requestURI",method:"Method",body:"RequestBody",bodyType:"bodyFormat",query:"QueryParameters",pathParameters:"URIParameters",activityTimeoutSeconds:"activityTimeoutSeconds",followRedirects:"followRedirects",requestEntityProcessing:"requestEntityProcessing",sendBodyMode:"sendBodyMode",successStatusCodes:"successStatusCodes",raiseForStatus:"raiseForStatus",socketTimeoutMs:"timeout"};
  for (const key of ["openApiDocument","openApiBaseUrl","openApiReferenceDocuments","openApiAllowedRefOrigins","operationId","validateRequest","requestSchema","validateResponse","responseSchema"]) aliases[key]=key;
  const convert = (key:string) => key === "headers" || key.startsWith("headers.") ? `RestInputRequest.Headers${key.slice(7)}` : key === "accept" ? "RestInputRequest.Headers.accept" : key === "contentType" ? "RestInputRequest.Headers.content-type" : aliases[key] ? `RestInputRequest.Config.${aliases[key]}` : key;
  const literal = (value:any) => typeof value === "string" && value.startsWith("${") ? value : JSON.stringify(value);
  const result:any = {};
  const standard:Record<string,string>={accept:"accept","content-type":"content-type","accept-charset":"Accept-Charset","accept-encoding":"Accept-Encoding",cookie:"Cookie",pragma:"pragma"};
  const custom = new Map<string,number>();
  let nextIndex=Math.max(-1,...mappings.map(([key])=>Number(key.match(/^RestInputRequest\.CustomHeaders\.(\d+)(?:\.|$)/)?.[1] ?? -1)))+1;
  const header=(name:string,value:any,mapped=false) => {
    const known=standard[name.toLowerCase()];
    if(known) {result[`RestInputRequest.Headers.${known}`]=mapped ? value : literal(value);return;}
    const index=custom.get(name.toLowerCase()) ?? nextIndex++;
    custom.set(name.toLowerCase(),index);
    const prefix=`${customRoot}.${index}`;
    result[prefix]='{}';result[`${prefix}.name`]=JSON.stringify(name);result[`${prefix}.value`]=mapped ? value : literal(value);
  };
  for (const key of [...Object.keys(aliases),"accept","contentType"]) if (config[key] !== undefined) result[convert(key)] = literal(config[key]);
  if(config.headers && typeof config.headers==='object') for(const [name,value] of Object.entries(config.headers)) header(name,value);
  else if(config.headers) result['RestInputRequest.Headers']=literal(config.headers);
  if (config.timeout !== undefined) result["RestInputRequest.Config.timeout"] = typeof config.timeout === 'number' ? String(config.timeout*1000) : `multiply(${literal(config.timeout)}, 1000)`;
  for (const [key,value] of mappings) {
    if(key.startsWith('headers.')) header(key.slice(8),value,true);
    else result[convert(key)] = value;
  }
  return result;
}

function httpRequestOccurrences(fields: DataField[], mappings: any): DataField[] {
  let result=fields;
  for (const root of ["RestInputRequest.CustomHeaders","RestInputRequest.mimeEnvelopeElement.mimePart","DynamicHTTPHeaders.Headers"]) {
    const indices=[...new Set(Object.keys(mappings || {}).filter(key => key.startsWith(`${root}.`)).map(key => key.slice(root.length+1).split('.')[0]).filter(key => /^\d+$/.test(key)))].sort((a,b)=>Number(a)-Number(b));
    if (!indices.length) continue;
    const children=(root === "DynamicHTTPHeaders.Headers" ? activityContract({type:"http_response",config:{}}).input : httpRequestFields()).filter(field => field.key.startsWith(`${root}.`));
    result=result.filter(field => !field.key.startsWith(`${root}.`));
    const index=result.findIndex(field => field.key===root)+1;
    result=[...result.slice(0,index),...indices.flatMap(number => [{...d(`${root}.${number}`,`${root.split('.').slice(-1)[0]} [${Number(number)+1}]`,"object"),minOccurs:"1",maxOccurs:"1"},...children.map(field => ({...field,key:`${root}.${number}${field.key.slice(root.length)}`}))]),...result.slice(index)];
  }
  return result;
}
export const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"];
const isMapperActivity = (type: string) => ["mapper", "transform", "ai_transform"].includes(type);
type MappingWhen = { condition: string; source: any };
type StructuredMapping = { $rule: "for-each" | "for-each-group" | "if" | "when-otherwise" | "choose"; source?: any; select?: string; groupBy?: string; condition?: string; otherwise?: any; whens?: MappingWhen[]; duplicateOf?: string };
const mappingSource = (value: any): any => {
  if (value && typeof value === "object" && ("$rule" in value || "operator" in value || ("target" in value && ("source" in value || "constant" in value)))) {
    return value.constant !== undefined ? JSON.stringify(value.constant) : mappingSource(value.select || value.source || "");
  }
  return value;
};

function cardinalitySymbol(field: { type?: string; validationType?: string; repeating?: boolean; required?: boolean; minOccurs?: string; maxOccurs?: string }): string {
  const repeating = field.repeating || field.maxOccurs === 'unbounded' || Number(field.maxOccurs) > 1 || /array|\[\]/i.test(field.validationType || field.type || '');
  const minimum = field.minOccurs != null ? Number(field.minOccurs) : field.required ? 1 : 0;
  return repeating ? minimum > 0 ? '+' : '*' : minimum === 0 ? '?' : '';
}

function defaultGroupedLoopSource(row: MappingTreeRow, rows: MappingTreeRow[]) {
  const insideGroup = rows.some(parent => (parent.kind === 'loop' || parent.duplicateRoot) && parent.key !== row.loopKey
    && (parent.rule?.operator || parent.rule?.$rule) === 'for-each-group' && row.ancestors.includes(parent.key));
  return insideGroup ? 'current-group()' : undefined;
}

function MappingContextMenu({ menu, value, close, change, remove, duplicate, canDuplicate = false, canDelete = !!value }: any) {
  const [whenCount, setWhenCount] = useState<string | null>(null);
  useEffect(() => { setWhenCount(null); }, [menu]);
  const panel = useRef<HTMLDivElement>(null), source = String(mappingSource(value) || "");
  useEffect(() => {
    if (!menu) return;
    const dismiss = (event: PointerEvent) => { if (!panel.current?.contains(event.target as globalThis.Node)) close(); };
    window.addEventListener("pointerdown", dismiss, true);
    return () => window.removeEventListener("pointerdown", dismiss, true);
  }, [menu, close]);
  if (!menu) return null;
  const apply = (next: StructuredMapping) => { change(next); close(); };
  const content = <div ref={panel} className="mapping-context-menu" style={{ left: Math.max(8, Math.min(menu.x, window.innerWidth - 350)), top: Math.max(8, Math.min(menu.y, window.innerHeight - 455)) }} onPointerDown={(event) => event.stopPropagation()}>
    <header><DataNodeIcon/><span><b>{menu.label}</b></span></header>
    <button onClick={() => apply({...(value && typeof value === 'object' ? value : {}), $rule:'for-each', operator:'for-each', source:mappingSource(value) || menu.defaultLoopSource || '', select:undefined, constant:undefined})}>For Each…</button>
    <button onClick={() => apply({...(value && typeof value === 'object' ? value : {}), $rule:'for-each-group', operator:'for-each-group', source:mappingSource(value) ?? '', select:undefined, constant:undefined, groupBy:value?.groupBy || ''})}>For Each Group…</button>
    <button disabled={menu.required || menu.duplicateRoot} title={menu.duplicateRoot ? "Apply conditions to child mappings within a duplicate" : menu.required ? "Required target fields cannot be wrapped in If" : undefined} onClick={() => {
      const previous = value && typeof value === 'object' ? value : {};
      const mappedValue = previous.constant !== undefined ? JSON.stringify(previous.constant) : mappingSource(value) ?? '';
      apply({...previous, $rule:'if', operator:'if', source:mappedValue, select:undefined, constant:undefined,
        condition:(previous.$rule || previous.operator) === 'if' ? previous.condition || '' : ''});
    }}>If…</button>
    <button disabled={menu.duplicateRoot} onClick={() => setWhenCount(String(value?.whens?.length || 1))}>When / Otherwise…</button>
    {whenCount !== null && <section className="mapping-rule-editor">
      <label>How many When conditions?<input autoFocus type="number" min="1" max="100" step="1" value={whenCount} onChange={event => setWhenCount(event.target.value)}/></label>

      <div><button onClick={() => setWhenCount(null)}>Cancel</button><button className="apply" disabled={!Number.isInteger(Number(whenCount)) || Number(whenCount) < 1 || Number(whenCount) > 100} onClick={() => {
        const previous = value?.whens || ((value?.$rule || value?.operator) === 'when-otherwise' ? [{condition: value.condition, source: value.source}] : []);
        const branches = Array.from({length: Number(whenCount)}, (_, index) => previous[index] || {condition: '', source: index === 0 && !previous.length ? source : ''});
        apply({$rule: 'choose', source: JSON.stringify(branches), whens: branches, otherwise: value?.otherwise ?? ''});
      }}>Create branches</button></div>
    </section>}
    <button disabled={duplicate ? !canDuplicate : !value} onClick={() => { if (duplicate) duplicate(); else change(typeof value === "object" ? { ...value, duplicateOf: `${menu.path}-${Date.now()}` } : { $rule: "if", source: value, condition: "true()", duplicateOf: `${menu.path}-${Date.now()}` }); close(); }}>Duplicate mapping</button>
    <button disabled={!canDelete} className="danger" onClick={() => { remove(); close(); }}>Delete mapping</button>
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
      validationType: field?.validationType,
      minOccurs: field?.minOccurs, maxOccurs: field?.maxOccurs, repeating: field?.repeating,
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
    collapseAll: (paths:string[]) => setCollapsed(new Set(paths)),
    expandAll: () => setCollapsed(new Set()),
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
        f("ackId", "Acknowledgement handle", "text", "Map a broker acknowledgement handle, or place this activity after an SAP IDoc Parser to confirm the SAP tRFC early."),
        f("failIfMissing", "Fail when handle is missing", "boolean"),
      ],
      input: [d("ackId", "Acknowledgement handle", "string", false, "Optional for SAP IDoc early confirmation; otherwise map the client acknowledgement handle."), d("ackIds", "Multiple acknowledgement handles", "array")],
      output: [d("confirmed", "Confirmation status", "boolean"), d("count", "Confirmed message count", "integer"), d("technologies", "Confirmed transports", "array")],
      errors: [
        { type: "ACKNOWLEDGEMENT_NOT_FOUND", description: "The acknowledgement handle is missing, expired, or was already confirmed." },
        { type: "SAP_EARLY_CONFIRM_FAILED", description: "SAP rejected the early IDoc confirmation." },
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
        f("requestParameters", "Request parameters", "requestParameters", "Declare typed URI parameters, query parameters, and custom headers."),
        f("requestContentTypes", "Request content types", "mediaTypes", "Select the accepted request media types. A selected XSD applies to XML and a JSON Schema applies to JSON when several formats are selected."),
        f("responseContentTypes", "Response content types", "mediaTypes", "Select the offered response media types. With multiple selections, the Accept header selects the format; the first selected type is the default."),
        f("validateRequest", "Validate request schema", "boolean"),
        f("requestSchema", "Request schema", "schema", "Optional contract for the incoming request body. Select a project schema or browse for an XSD or JSON Schema file."),
        f("validateResponse", "Validate response schema", "boolean"),
        f("responseSchema", "Response schema", "schema", "Optional contract for the response body. Select or browse for a schema to make its fields available in HTTP Send Response."),
        f("activityTimeoutSeconds", "Request execution timeout (seconds)", "number"),
      ],
      input: [],
      output: [
        d("body", "Request body", "any"),
        d("binaryContent", "Base64 request bytes", "base64"),
        d("fileName", "Temporary uploaded file"),
        d("size", "Uploaded byte count", "integer"),
        d("headerPairs", "All received header pairs", "array"),
        d("clientIp", "Client IP", "string"),
        d("traceId", "HTTP trace ID", "string"),
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
      configuration: op === "write_precondition" ? [] : [
        {
          ...f("resourceId", "HTTP shared connection", "resource"),
          resourceType: "http",
        },
      ],
      input: ["sse_read","websocket_exchange","write_precondition"].includes(op) ? [
        ...httpRequestFields().filter(field => {
          if (op === "write_precondition") return ["RestInputRequest","RestInputRequest.Config","RestInputRequest.Headers"].includes(field.key);
          return !field.key.startsWith("RestInputRequest.Config.") || ["requestURI","QueryParameters","URIParameters","activityTimeoutSeconds","timeout",...(op === "websocket_exchange" ? ["RequestBody"] : [])].some(name => field.key === `RestInputRequest.Config.${name}`);
        }).filter(field => !field.key.startsWith("RestInputRequest.mimeEnvelopeElement")),
        ...(op === "write_precondition"
          ? [d("RestInputRequest.Config.currentETag","Current ETag","string"),d("RestInputRequest.Config.currentLastModified","Current Last-Modified","string"),d("RestInputRequest.Config.representationExists","Representation exists","boolean"),d("RestInputRequest.Config.requireWritePrecondition","Require a precondition","boolean")]
          : [d("RestInputRequest.Config.maxEvents","Maximum events","integer"),...(op === "sse_read" ? [d("RestInputRequest.Config.lastEventId","Last event ID","string")] : [])]),
      ] : httpRequestFields(),
      output: op === "write_precondition" ? [d("allowed","Write allowed","boolean"),d("statusCode","Suggested HTTP status","integer")]
        : ["sse_read","websocket_exchange"].includes(op) ? [d("events","Received events or messages","object[]"),d("eventCount","Number received","integer")]
        : httpRequestFields(true),
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
        f("contentType", "Response content type", "mediaType", "Choose a common media type, enter a custom value, or use Automatic to use the listener default."),
      ],
      input: [
        d("HTTPHeaders", "HTTPHeaders", "object", false, "Optional standard response headers and status. Unmapped fields keep the existing response defaults."),
        d("HTTPHeaders.Content-Type", "Content-Type", "string", false, "Response media type. Overrides the legacy contentType mapping when supplied."),
        {...d("HTTPHeaders.StatusLine", "StatusLine", "object", false, "Optional response status structure. Map httpVersion, statusCode and reasonPhrase independently, or map an entire object. Existing status-line string mappings remain supported."), validationType:"object|string"},
        d("HTTPHeaders.StatusLine.httpVersion", "httpVersion", "string", false, "Native HTTP/1 listeners send the selected HTTP/1.0 or HTTP/1.1 version. HTTP/1.0 closes the connection. On HTTP/2 or HTTP/3, the value must match the negotiated protocol; incompatible overrides fail."),
        d("HTTPHeaders.StatusLine.statusCode", "statusCode", "integer", false, "Numeric response status from 100 to 599, for example 201 without quotes. Overrides the legacy statusCode when mapped. Hosted final responses require 200–599."),
        d("HTTPHeaders.StatusLine.reasonPhrase", "reasonPhrase", "string", false, "Custom wire reason phrase on native HTTP/1 listeners, including an empty string. Omit for the standard phrase. HTTP/2 and HTTP/3 have no reason phrase; use an empty value or omit it. Unsupported transports and control characters fail validation."),
        {...d("HTTPHeaders.Cookies", "Cookies", "string[]", false, "One or more complete Set-Cookie values, such as session=abc; Path=/; HttpOnly. Each value is sent as its own Set-Cookie header."), minOccurs:"0", maxOccurs:"unbounded", repeating:true},
        d("DynamicHTTPHeaders", "DynamicHTTPHeaders", "object", false, "Optional custom response headers. Repeat Headers for each headerName/headerValue pair."),
        {...d("DynamicHTTPHeaders.Headers", "Headers", "object[]", false, "Add or duplicate a header entry, map a collection, or use For Each. Dynamic values override standard/legacy headers; repeated names emit separate header lines. Set-Cookie appends to Cookies."), minOccurs:"0", maxOccurs:"unbounded", repeating:true},
        d("DynamicHTTPHeaders.Headers.headerName", "headerName", "string", false, "HTTP header name, for example X-Correlation-ID. Required when the entry has a value."),
        d("DynamicHTTPHeaders.Headers.headerValue", "headerValue", "string", false, "HTTP header value. Empty strings are allowed; line breaks and control characters are rejected."),
        d("headers", "Response headers", "object"),
        d("body", "Response body", "any"),
        d("binaryContent", "Base64 response bytes", "base64"),
        d("fileName", "Response file to stream", "string"),
      ],
      output: [
        d("statusCode", "Sent status code", "integer"),
        d("statusLine", "Mapped status line", "object", false, "Mapped status settings retained for debugging. Supported version/reason overrides affect the native HTTP/1 wire response; transport compatibility is checked before sending."),
        d("statusLine.httpVersion", "httpVersion", "string", false, "Mapped protocol metadata, normalized to an HTTP/ version token."),
        d("statusLine.statusCode", "statusCode", "integer", false, "Effective numeric response status after applying optional StatusLine overrides."),
        d("statusLine.reasonPhrase", "reasonPhrase", "string", false, "Mapped reason phrase, sent on native HTTP/1 listeners. Nonempty reason phrases are unsupported on HTTP/2 and HTTP/3."),
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
        f("openApiDocument", "OpenAPI 3 / Swagger 2 JSON or YAML contract", "textarea"),
        f("openApiBaseUrl", "Contract base URL for relative references"),
        f("openApiReferenceDocuments", "Supplied external reference documents (URI/document JSON)", "textarea"),
        f("openApiAllowedRefOrigins", "Allowed external reference HTTPS origins"),
        f("operationId", "Contract operation ID"),

        {
          ...f("resourceId", "HTTP shared connection", "resource"),
          resourceType: "http",
        },
        f("path", "Resource path"),
        f("methods", "Allowed HTTP methods", "methods", "Select every HTTP method exposed by this REST resource."),
        f("requestParameters", "Request parameters", "requestParameters", "Declare typed URI parameters, query parameters, and custom headers."),
        f("requestContentTypes", "Request content types", "mediaTypes", "Select one or more accepted media types. With an OpenAPI contract, select media types declared by the operation or leave all unchecked to use the contract."),
        f("responseContentTypes", "Response content types", "mediaTypes", "Select the offered response media types. With multiple selections, the Accept header selects the format; the first selected type is the default."),
        f("activityTimeoutSeconds", "Request execution timeout (seconds)", "number"),
        f("validateRequest", "Validate request schema", "boolean"),
        f("requestSchema", "Request schema", "schema", "Optional contract for the incoming request body. Select a project schema or browse for an XSD or JSON Schema file."),
        f("validateResponse", "Validate response schema", "boolean"),
        f("responseSchema", "Response schema", "schema", "Optional contract for the response body. Select or browse for a schema to make its fields available in HTTP Send Response."),
      ],
      input: [],
      output: [
        d("body", "Request entity", "any"),
        d("binaryContent", "Base64 request bytes", "base64"),
        d("fileName", "Temporary uploaded file"),
        d("size", "Uploaded byte count", "integer"),
        d("headerPairs", "All received header pairs", "array"),
        d("clientIp", "Client IP", "string"),
        d("traceId", "HTTP trace ID", "string"),
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
        ...(op === "update" ? [f("insertIfRecordDoesNotExist", "Insert if record does not exist", "boolean")] : []),
        ...(["insert", "update", "delete"].includes(op) ? [f("interpretEmptyStringAsNull", "Interpret empty string as NULL", "boolean"), f("batchUpdate", "Batch update", "boolean"), f("overrideSqlStatement", "Allow mapped SQL override", "boolean")] : []),
      ],
      input: [d("ServerTimeZone", "Database server time zone", "string"), d("timeout", "Dynamic timeout", "number"), ...(["query", "dynamic"].includes(op) ? [d("maxRows", "Dynamic maximum rows", "number"), d("SqlStatement", "Dynamic SQL override", "string"), d("parameters", "Prepared statement parameters", "object"), d("rowOffset", "Row offset when processing subsets", "integer")] : op === "call" ? [d("parameters", "IN and IN/OUT procedure parameters", "object")] : [d("parameters", "Prepared statement parameters", "object"), d("records", "Batch parameter records", "array"), d("SqlUpdateStatement", "Dynamic update SQL", "string"), ...(op === "update" ? [d("InsertStatement", "Insert-if-missing SQL", "string")] : [])])],
      output: ["query", "dynamic"].includes(op) ? [d("resultSet", "JDBC result set", "object"), d("resultSet.Record", "Result records", "array"), d("rows", "Result records", "array"), d("rowCount", "Rows returned", "integer"), d("lastSubset", "Last result subset", "boolean"), d("nextRowOffset", "Offset for the next subset, when available", "integer")] : op === "call" ? [d("resultSets", "Procedure result sets", "array"), d("outParameters", "OUT and IN/OUT parameters", "object"), d("UnresolvedResultSets", "Unresolved result sets", "array")] : [d("noOfUpdates", "Number of updates", "integer"), d("rowCount", "Affected rows", "integer"), d("lastInsertId", "Generated key", "integer|string")],
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
    const cfg = n.config || {};
    const bwJson = cfg.schemaType === "XSD" || cfg.schemaType === "Generic";
    const xsdJson = cfg.schemaType === "XSD";
    const textInput = cfg.inputStyle !== "Binary";
    const binaryInput = ["Binary", "Dynamic"].includes(cfg.inputStyle);
    const fileInput = ["File", "File path"].includes(cfg.inputSource);
    const inlineFormat = (field: Field) => ({ ...field, when: (c: any) => !c.dataFormatId });
    const fields: Field[] = [
        ...(n.type === "xml"
          ? [
              { ...f(parsing ? "inputStyle" : "outputStyle", parsing ? "Input style" : "Output style", "select"), options: parsing ? ["Text", "Binary", "Dynamic"] : ["Text", "Binary"] },
              f(parsing ? "validateOutput" : "validateInput", parsing ? "Validate parsed output" : "Validate input tree", "boolean"),
              ...(parsing ? [] : [f("encoding", "Encoding"), f("suppressXmlDeclaration", "Suppress XML declaration", "boolean"), f("prettyPrint", "Pretty print", "boolean"),
                f("formatUsingDefaultNamespacePrefix", "Use default namespace", "boolean"), f("rootElement", "XSD root override", "text", "Optional global element name. The first declared root is used by default.")]),
            ]
          : n.type === "json"
            ? [
                { ...f("schemaType", "Schema type", "select"), options: ["Native JSON", "Generic", "XSD"] },
                ...(cfg.schemaType === "Generic" ? [] : [f(parsing ? "validateOutput" : "validateInput", parsing ? "Validate parsed output" : "Validate input tree", "boolean")]),
                ...(bwJson ? [
                  { ...f("jsonStyle", "JSON root style", "select"), options: ["None", "JSON with Root", "Anonymous Array"] },
                  f("badgerfish", "Badgerfish conversion", "boolean", "Preserve XML namespace declarations, attributes and text in JSON."),
                  ...(parsing || xsdJson ? [f("rootElement", "XML root element", "text", xsdJson ? "Optional global XSD element name." : "Root name for JSON without a root property. Defaults to root.")] : []),
                  ...(parsing ? [f("useNullForEmptyValues", "Use null for empty values", "boolean", "Treat empty objects and arrays as null where there is an XML container; scalar strings, numbers and booleans are unchanged.")] : []),
                  ...(!parsing ? [f("useEmptyValuesForNull", "Use empty values for null", "boolean"),
                    f("emptyToNull", "Convert empty elements to null", "boolean"),
                    ...(xsdJson ? [] : [f("inferPrimitiveTypes", "Infer numeric and boolean values", "boolean")])] : []),
                  ...(xsdJson && parsing && cfg.validateOutput !== false ? [f("ignoreAdditionalJsonFields", "Ignore additional JSON fields", "boolean")] : []),
                ] : []),
                ...(parsing ? [{ ...f("duplicateKeyPolicy", "Duplicate keys", "select"), options: ["Last wins", "First wins", "Error"] }] : [
                  ...(!bwJson ? [{ ...f("rootStyle", "JSON root", "select"), options: ["With root", "Anonymous"] }, f("omitNulls", "Omit null fields", "boolean")] : []),
                  f("prettyPrint", "Pretty print", "boolean"), f("indent", "Indent spaces", "number"), f("asciiOnly", "Escape non-ASCII characters", "boolean")]),
              ]
            : [
                ...(parsing ? [
                  { ...f("inputSource", "Input source", "select"), options: ["String", "File path"] },
                  ...(fileInput ? [inlineFormat(f("fileEncoding", "File encoding", "text", "Defaults to UTF-8 with optional BOM detection."))] : []),
                  f("manualStartRecord", "Manually specify start record", "boolean", "Expose the zero-based start offset in Input. Otherwise a batch size advances the offset within the task."),
                  f("continueOnError", "Continue on record errors", "boolean", "Report rejected records in ErrorRows and continue with the remaining records."),
                ] : []),
                f("dataFormatId", "Shared Data Format", "dataFormat", "Choose a project JSON schema asset containing a dataFormat object, or configure the format inline."),
                ...[
                ...(parsing ? [f("rootElement", "Output XML root element"), f("recordElement", "Output XML record element")] : []),
                { ...f("format", "Format", "select"), options: ["delimited", "fixed"] },
                f("delimiter", "Column separator"),
                { ...f("separatorRule", "Multi-character separator rule", "select"), options: ["single", "any-character"] },
                { ...f("lineSeparator", "Line separator", "select"), options: ["Auto", "LF", "CRLF", "CR"] },
                f("header", "First row is header", "boolean"),
                f("fields", "Field names", "text", "Comma-separated names used when the input has no header. An attached schema supplies these automatically."),
                f("fieldTypes", "Field data types", "text", "Optional comma-separated XML schema types such as string, integer, decimal, and boolean."),
                f("widths", "Fixed field widths"),
                f("fieldOffsets", "Fixed field offsets", "text", "Optional zero-based start:end offsets (end excluded), one per field. Overrides widths."),
                f("lineLength", "Fixed line length including separator", "number"),
                f("fillCharacter", "Fixed-width fill character"),
                f("strictColumns", "Require exact column count", "boolean"),
                f("trimValues", "Trim parsed values", "boolean"),
                ...(parsing ? [{ ...f("blankLinePolicy", "Blank lines", "select"), options: ["Skip", "Stop", "Keep"] }] : []),
                f("includeFinalLineSeparator", "Append final line separator", "boolean"),
                ].map(inlineFormat),
              ]),
      ];
    const input = n.type === "xml" && parsing ? [
        ...(textInput ? [d("xmlString", "XML text", "string")] : []),
        ...(binaryInput ? [d("xmlBinary", "XML binary", "object"), d("xmlBinary.bytes", "Base64 XML bytes", "base64"), d("xmlBinary.forceEncoding", "Forced encoding"), d("xmlBinary.byteCount", "Byte count", "integer")] : []),
      ] : n.type === "xml" ? [d("value", "XML schema tree", "object"), d("xmlString", "Existing XML document", "string", false, "Map an XML document to validate and serialize it directly."), ...(cfg.outputStyle === "Binary" ? [d("byteEncoding", "Binary XML encoding", "string")] : [])] : n.type === "json" && parsing ? [d("jsonString", "JSON text", "string", true)] : n.type === "json" ? [
        ...(bwJson ? [d("xmlString", "XML text", "string")] : []), ...(cfg.schemaType === "Generic" ? [] : [d("value", bwJson ? "XML schema tree" : "JSON value", "any")]),
      ] : parsing ? [
        fileInput ? d("fileName", "Input file path", "string") : d("text", "Formatted data string", "string"),
        d("skipHeaderCharacters", "Header characters to skip", "integer"),
        ...(cfg.manualStartRecord ? [d("startRecord", "Zero-based record offset", "integer")] : []),
        d("noOfRecords", "Records to parse (-1 for all)", "integer"),
      ] : [d("records", "Data records", "array", true)];
    const design = new Set(["inputStyle", "outputStyle", "inputSource", "schemaType", "dataFormatId"]);
    const extra = n.type === "xml" ? (parsing
      ? [f("forceEncoding", "Fallback binary encoding"), f("encoding", "Legacy binary encoding")]
      : [f("cdataElements", "CDATA element paths", "text", "Map a comma-separated list of schema paths, such as order.notes.")])
      : n.type === "flat" ? [f("lineEnding", "Custom line ending", "text", "Map a custom line ending when no line separator is selected."), f("skipBlankLines", "Skip blank records", "boolean")] : [];
    const runtime = [...fields.filter(field => !design.has(field.key)), ...extra];
    return {
      configuration: fields.filter(field => design.has(field.key) || field.type === "boolean"),
      input: [...input, ...runtime.map(field => d(`formatOptions.${field.key}`, field.label,
        field.type === "number" ? "integer" : field.type === "boolean" ? "boolean" : "string", false,
        field.options ? `Allowed values: ${field.options.join(", ")}.` : field.help))],
      output: parsing
        ? n.type === "json" && !bwJson
          ? [d("value", "Parsed JSON value", "json")]
          : [d("xml", n.type === "flat" ? "Parsed data XML" : "Parsed XML", "xml"),d("xmlString","XML text"),d("root","Root element"),d("value","Parsed tree","object"),...(n.type === "flat" ? [
            d("records","Typed records","array"),d("recordCount","Record count","integer"),d("fields","Field names","array"),
            d("Rows.schema","Parsed row structure","object"),d("ErrorRows.error","Rejected records","array"),d("ErrorRows.error.recordNumber","Record number","integer"),
            d("ErrorRows.error.message","Error message"),d("ErrorRows.error.raw","Raw record"),d("done","End of input","boolean"),d("nextRecord","Next record offset","integer"),
          ] : [])]
        : n.type === "xml" && cfg.outputStyle === "Binary" ? [d("xmlBytes","Base64 XML bytes","base64"),d("xmlBinary","XML binary","object"),d("xmlBinary.bytes","Base64 XML bytes","base64"),d("xmlBinary.byteCount","Byte count","integer"),d("binaryContent","Base64 XML bytes","base64"),d("bytes","Base64 XML bytes","base64"),d("byteCount","Byte count","integer"),d("encoding","Encoding")] : [d(n.type === "xml" ? "xmlString" : n.type === "json" ? "jsonString" : "text", `Rendered ${format} text`, "string"),d("content","Rendered content"),...(n.type === "flat" ? [d("Text","Formatted data text"),d("recordCount","Record count","integer")] : [])],
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
    const jms = n.type === "jms", destinationKey = op.includes("queue") || op === "send" ? "queue" : op.includes("topic") || op === "publish" ? "topic" : "destination", resource = { ...f("resourceId", jms ? "JMS connection" : "EMS connection", "resource"), resourceType: n.type, required: true },
      messageType = { ...f("messageType", "Message type", "select"), options: ["Text", "Bytes", "Map", "Object", "Object Ref", "Simple", "Stream", "XML Text"] },
      style = { ...f("messagingStyle", "Messaging style", "select"), options: ["Queue", "Topic", "Generic"] },
      ack = { ...f("acknowledgeMode", "Acknowledge mode", "select"), options: ["Auto", "Client", "Dups OK", "Explicit Client", "Explicit Client Dups OK", "Transactional"] },
      receiver = [resource, style, { ...f(destinationKey, "Destination", "text", "Queue or topic name; choose an environment property or enter an expression."), propertyBrowse: true }, messageType, f("messageSelector", "JMS message selector"), ack, { ...f("maxSessions", "Session count", "number", "Resolved from the selected environment at runtime."), propertyBrowse: true }, { ...f("flowLimit", "Flow limit", "number", "Resolved from the selected environment at runtime."), propertyBrowse: true }, { ...f("receiveTimeout", "Receive timeout (ms)", "number", "Resolved from the selected environment at runtime."), propertyBrowse: true }],
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
      consumer = [resource, { ...f("groupId", "Consumer group ID"), propertyBrowse: true }, { ...f("topic", "Topic names", "text", "Separate multiple topic names with semicolons."), propertyBrowse: true }, f("assignCustomPartition", "Assign custom partitions", "boolean"), f("partitionIds", "Partition IDs / ranges"), f("consumerCount", "Consumer count", "number"), ...consumerSerialization, { ...f("acknowledgeMode", "Acknowledgement mode", "select"), options: ["Auto", "Manual"] }, f("enableAutoCommit", "Enable auto commit", "boolean"), f("autoOffsetReset", "Auto offset reset", "select"), f("fetchMinBytes", "Fetch minimum bytes", "number"), f("maxPollRecords", "Maximum poll records", "number"), f("sessionTimeoutMs", "Session timeout (ms)", "number"), f("heartbeatIntervalMs", "Heartbeat interval (ms)", "number"), f("additionalProperties", "Additional consumer properties (JSON)", "textarea")],
      producer = [resource, { ...f("topic", "Topic name"), propertyBrowse: true }, f("assignCustomPartition", "Assign custom partition", "boolean"), f("partitionId", "Partition ID", "number"), ...serialization, f("waitForDelivery", "Wait for broker confirmation", "boolean", "Off uses Kafka's persistent buffered producer for maximum throughput. Enable only when this activity must return the broker partition and offset."), { ...f("acks", "Acknowledgements", "select"), options: ["0", "1", "all"] }, { ...f("compressionType", "Compression type", "select"), options: ["none", "gzip", "snappy", "lz4", "zstd"] }, f("retries", "Producer retries", "number"), f("bufferMemory", "Buffer memory (bytes)", "number"), f("batchSize", "Batch size", "number"), f("lingerMs", "Linger (ms)", "number"), f("maxRequestSize", "Maximum request size", "number"), f("transactionalId", "Transactional ID"), f("enableIdempotence", "Enable idempotence", "boolean"), f("additionalProperties", "Additional producer properties (JSON)", "textarea")];
    const configs: Record<string, Field[]> = {
      send: producer,
      publish: producer,
      receive: consumer,
      get: [...consumer, { ...f("seekPosition", "Seek position", "select"), options: ["current", "beginning", "end", "custom"] }, f("customOffset", "Custom offset", "number"), f("maxMessages", "Maximum messages", "number"), f("timeout", "Poll timeout (seconds)", "number")],
    };
    const receiving = ["receive", "get"].includes(op);
    return {
      configuration: configs[op] || [resource],
      input: receiving ? (op === "get" ? [d("topic", "Dynamic topic override"), d("partition", "Dynamic partition", "integer"), d("offset", "Dynamic offset", "long")] : []) : [d("message", "Kafka record value", "object|string|binary", true), d("key", "Kafka record key", "string|binary"), d("headers", "Kafka headers", "object"), d("topic", "Dynamic topic override"), d("partitionId", "Dynamic partition", "integer")],
      output: receiving ? [d("messages", "Kafka records", "array"), d("count", "Record count", "integer"), d("topic", "Topic"), d("partition", "Partition", "integer"), d("offset", "Offset", "long"), d("timestamp", "Record timestamp", "dateTime"), d("headers", "Record headers", "object"), d("ackId", "Manual acknowledgement handle")] : [d("messageId", "Generated record ID"), d("topic", "Topic"), d("queued", "Accepted by the local Kafka producer", "boolean"), d("deliveryConfirmed", "Broker delivery confirmed before completion", "boolean"), d("publishLatencyMs", "Publisher activity latency in milliseconds", "number"), d("partition", "Broker partition (confirmation mode)", "integer"), d("offset", "Broker offset (confirmation mode)", "long"), d("timestamp", "Record timestamp", "dateTime")],
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
      configuration: receiving ? [resource, f("projectId", "Project ID override"), f("subscription", "Subscription ID"), f("maxMessages", "Maximum message fetch count", "number"), { ...f("acknowledgeMode", "Acknowledge mode", "select"), options: ["Auto", "Client"] }, f("receiveTimeout", "Receive timeout (seconds)", "number"), f("sequenceKey", "Sequence key expression"), f("customJobId", "Custom job ID expression")] : [resource, f("projectId", "Project ID override"), f("topic", "Topic ID"), f("orderingKey", "Ordering key"), f("waitForDelivery", "Wait for Google confirmation", "boolean", "Off queues through the persistent batched gRPC publisher for maximum throughput. Enable only when the flow requires Google's message ID."), f("publishTimeout", "Publish timeout (seconds)", "number"), f("batchMaxMessages", "Batch maximum messages", "number"), f("batchMaxBytes", "Batch maximum bytes", "number"), f("batchDelayThresholdMilliseconds", "Batch delay threshold (ms)", "number")],
      input: receiving ? [] : [d("data", "Message data", "string|binary", true, "Data or at least one attribute is required."), d("attributes", "Message attributes", "object"), d("topic", "Dynamic Topic ID")],
      output: receiving ? [d("MessageID", "Google message ID"), d("PublishTime", "Publish time", "dateTime"), d("Data", "Message data"), d("Attributes", "Message attributes", "object"), d("AckID", "Client acknowledgement handle")] : [d("TopicName", "Published topic name"), d("MessageID", "Google or local queued message ID"), d("providerMessageId", "Google message ID when confirmation is enabled"), d("queued", "Accepted by local publisher", "boolean"), d("deliveryConfirmed", "Confirmed by Google", "boolean"), d("publishLatencyMs", "Activity enqueue latency (ms)", "number")],
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
        { ...f("commitOnTerminate", "Commit before termination", "boolean", "Otherwise a transactional session is rolled back when terminated."), when: (config: any) => !!config.terminateConnection },
        f("contextTimeout", "Session idle timeout (ms)", "number"),
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
        { ...f("messagingSource", "Messaging source", "select", "Receive directly from SAP JCo or through an EMS/JMS/Kafka bridge."), options: ["NoMessaging", "EMS", "JMS", "Kafka"] },
        { ...f("messagingResourceId", "Messaging shared connection", "resource"), resourceTypes: [String(n.config?.messagingSource || "").toLowerCase()].filter((value) => ["ems", "jms", "kafka"].includes(value)), when: (config: any) => !["", "NoMessaging"].includes(config.messagingSource || "NoMessaging") },
        { ...f("messagingDestination", "Queue or topic", "text"), when: (config: any) => !["", "NoMessaging"].includes(config.messagingSource || "NoMessaging") },
        { ...f("tidManagerId", "SAP TID Manager resource", "text", "Managed by the SAP JCo durable TID store."), readOnly: true },
        { ...f("idocType", "IDoc type fetched from SAP", "idoc", "Inherited from the SAP shared connection metadata.") },
        { ...f("extensionType", "Extension / CIM type", "text", "Read from the selected SAP IDoc metadata."), readOnly: true },
        { ...f("release", "SAP release", "text", "Read from the selected SAP shared connection."), readOnly: true },
        { ...f("programId", "Program ID", "text", "Read from the selected SAP shared connection."), readOnly: true },
        { ...f("invocationProtocol", "Invocation protocol", "text", "IDoc inbound delivery uses transactional RFC (tRFC)."), readOnly: true },
      ],
      idoc_parser: [
        resource,
        f("sourceDestination", "IDoc source destination"),
        ...idoc,
        { ...f("idocEncoding", "Flat IDoc encoding", "text", "Java/Python charset name, for example UTF-8, windows-1252, or ISO-8859-1.") },
        { ...f("idocRecordDelimiter", "Flat record delimiter", "text", "Use an escaped delimiter such as \\r\\n or a custom token when SDATA can contain line breaks.") },
        { ...f("invalidCharacterPolicy", "Invalid byte policy", "select"), options: ["strict", "replace"] },
        { ...f("parserEngine", "Parser engine", "select", "Built-in is always available; SAP JIDocLib requires the licensed sapidoc3.jar."), options: ["Built-in", "SAP JIDocLib (when installed)"] },
        f("validateIdocType", "Reject mismatched IDoc type or extension", "boolean"),
        { ...f("idocOutputMode", "IDoc output format", "select"), options: ["JSON", "XML"] },
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
          ...f("idocInputMode", "IDoc delivery protocol", "select"),
          options: ["tRFC", "qRFC"],
        },
        { ...f("inputFormat", "IDoc payload format", "select"), options: ["XML", "Raw"] },
        f("confirmationMode", "Confirmation mode"),
        f("queueName", "SAP queue name"),
      ],
      idoc_renderer: [
        resource,
        ...idoc,
        {
          ...f("idocInputMode", "IDoc delivery protocol", "select"),
          options: ["tRFC", "qRFC"],
        },
      ],
      rfc_bapi_listener: [
        resource,
        f("functionName", "RFC / BAPI name"),
        protocol,
        f("programId", "Program ID"),
        f("gatewayHost", "Gateway host override"),
        f("gatewayService", "Gateway service override"),
        f("maximumConnections", "Maximum concurrent requests", "number"),
        f("maxPendingEvents", "Maximum buffered requests", "number"),
        f("ackTimeoutSeconds", "Reply / acknowledgement timeout (seconds)", "number"),
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
        : op === "dynamic_connection"
          ? [
              d("sessionID", "Session ID (required only when terminating)"),
              d("contextTimeout", "Transaction context timeout in milliseconds", "integer"),
              d("connectionType", "dedicated, logongroup, snc, sncwithlogongroup, or websocket"),
              d("applicationServerHost", "Application server host"),
              d("systemNumber", "System number"),
              d("messageServerHost", "Message server host"),
              d("systemId", "SAP system ID"),
              d("logonGroup", "SAP logon group"),
              d("client", "SAP client"),
              d("username", "SAP user"),
              d("password", "SAP password"),
              d("language", "Logon language"),
              d("sapRouter", "SAProuter string"),
              d("sncPartnerName", "SNC partner name"),
              d("sncLibraryPath", "SNC library path"),
              d("sncMyName", "SNC own name"),
              d("sncQop", "SNC quality of protection"),
            ]
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
        ? op === "rfc_bapi_listener" ? [
            d("RfcRequest", "RFC/BAPI request", "object"),
            d("imports", "RFC import parameters", "object"),
            d("tables", "RFC table parameters", "object"),
            d("functionName", "Invoked RFC/BAPI"),
            d("invocationProtocol", "Invocation protocol"),
            d("TID", "Transaction ID"),
            d("CPIC_ID", "SAP connection ID"),
          ] : [
            d("SAPIDoc", "IDoc/RFC metadata", "object"),
            d("controlRecord", "SAP IDoc control record", "object"),
            d("payload", "Inbound SAP payload (XML)", "string"),
            d("TID", "Transaction ID"),
          ]
        : converter
          ? [
              ...(n.config?.idocOutputMode === "XML" ? [d("IDocXML", "Parsed IDoc XML", "string")] : [d("SAPIDoc", "Parsed IDoc JSON", "object")]),
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
        d("payload", "Payload text", "string", false, "Map a value or enter a text/expression; objects are rendered into the log as structured JSON."),
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
      split_records: {configuration:[f("batchSize", "Records per batch", "number")], input:[d("payload", "Records", "array")], output:[d("batches", "Record batches", "array"),d("count", "Record count", "integer")], errors:[{type:"InvalidInputException",description:"Records or batch size are invalid."}]},
      deduplicate: {configuration:[f("stateFile", "Durable state file", "text"), {...f("namespace", "Message namespace", "text", "Use the same namespace for claims, receipts and replay."), required:true}, f("maxStateSizeMb", "State capacity (MB)", "number"), f("leaseSeconds", "Claim lease (seconds)", "number")], input:[d("messageKey", "Stable message key", "string"),d("payload", "Message payload", "any")], output:[d("accepted", "Claim accepted", "boolean"),d("duplicate", "Duplicate delivery", "boolean"),d("messageKey", "Message key", "string"),d("claimToken", "Claim token", "string"),d("status", "Claim status", "string"),d("payload", "Message payload", "any")], errors:[{type:"MessageStateException",description:"Durable state could not be read or written."}]},
      message_receipt: {configuration:[f("stateFile", "Durable state file", "text"), {...f("namespace", "Message namespace", "text", "Use the same namespace for claims, receipts and replay."), required:true}, f("maxStateSizeMb", "State capacity (MB)", "number"), {...f("action", "Receipt action", "select", "Complete after downstream work; fail retains the message for explicit replay."), options:["complete","fail"]},f("retentionSeconds", "Completed-key retention (seconds)", "number")], input:[d("messageKey", "Message key", "string"),d("claimToken", "Claim token", "string"),d("error", "Failure reason", "string")], output:[d("messageKey", "Message key", "string"),d("status", "Receipt status", "string")], errors:[{type:"MessageStateException",description:"Claim token is missing, stale or expired."}]},
      replay_messages: {configuration:[f("stateFile", "Durable state file", "text"), {...f("namespace", "Message namespace", "text", "Use the same namespace for claims, receipts and replay."), required:true}, f("maxStateSizeMb", "State capacity (MB)", "number"), {...f("action", "Replay action", "select", "List failed/expired messages or explicitly requeue one key. No downstream work runs automatically."), options:["list","requeue","purge"]},f("limit", "Maximum replay records", "number")], input:[d("messageKey", "Key to requeue", "string")], output:[d("messages", "Replay candidates", "array"),d("count", "Candidate count", "integer")], errors:[{type:"MessageStateException",description:"Message is not eligible for replay or state is unavailable."}]},
      aggregate_messages: {configuration:[f("stateFile", "Durable state file", "text"), {...f("namespace", "Message namespace", "text", "Use the same namespace for claims, receipts and replay."), required:true}, f("maxStateSizeMb", "State capacity (MB)", "number"),{...f("action", "Aggregation action", "select", "Append a message; flush emits a partial group only after its timeout."), options:["append","flush"]},f("expectedCount", "Completion count", "number"),f("maxGroupItems", "Maximum group records", "number"),f("timeoutSeconds", "Group timeout (seconds)", "number")], input:[d("correlationKey", "Correlation key", "string"),d("messageId", "Stable message ID", "string"),d("payload", "Message payload", "any")], output:[d("ready", "Group ready for delivery", "boolean"),d("records", "Completed group records", "array"),d("count", "Group count", "integer"),d("timedOut", "Group timed out", "boolean"),d("status", "Group status", "string")], errors:[{type:"MessageStateException",description:"Correlation, completion settings or capacity are invalid."}]},
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

function schemaDataFields(value: any, schemaPath?: string, schemaDocuments?: any[]): DataField[] {
  if (!value) return [];
  const config = typeof value === "string" ? { targetSchemaText: value } : { targetSchema: value };
  return transformSchemaFields({...config, schemaPath, schemaDocuments}).map((field) => ({...d(field.path, field.name, field.type), minOccurs: field.minOccurs, maxOccurs: field.maxOccurs, repeating: field.repeating, required: Number(field.minOccurs) > 0}));
}

function activitySchemaAsset(node: any, schemas: any[]) {
  if (node.config?.schemaText && !node.config?.schemaId) return undefined;
  const id = node.config?.schemaId || (node.type === "flat" ? sharedDataFormat(node.config?.dataFormatId, schemas)?.schemaId : "");
  return schemas.find((schema: any) => schema.id === id || schema.name === id);
}

function activitySchemaText(node: any, schemas: any[]): string {
  const configured = node.config?.schemaText;
  const asset=activitySchemaAsset(node,schemas);
  return asset ? selectedSchemaText(asset.content,configured) : configured || "";
}

function sharedDataFormat(id: string, schemas: any[]) {
  const selected = schemas.find((schema: any) => schema.id === id || schema.name === id);
  try {
    const format = JSON.parse(selected?.content || "null")?.dataFormat;
    return format && typeof format === "object" && !Array.isArray(format) ? format : undefined;
  } catch { return undefined; }
}

function sharedDataFormatMappings(id: string, schemas: any[]): Record<string, string> {
  const asset = schemas.find((item: any) => item.id === id || item.name === id);
  try {
    const mapping = JSON.parse(asset?.content || "{}").inputMappings?.["formatOptions.delimiter"];
    return typeof mapping === "string" && /^\$\{properties\.bw\.dataFormat\.[A-Za-z0-9_.-]+\}$/.test(mapping)
      ? { "formatOptions.delimiter": mapping } : {};
  } catch { return {}; }
}

function boundaryFields(task: any, boundaryType: "start" | "end", schemas: any[]): DataField[] {
  if (!task) return [];
  const boundary = (task.activities || []).find((activity: any) => activity.type === boundaryType);
  const config = boundary?.config || {};
  const schemaId = config.interfaceSchemaId;
  const selected = schemaId ? schemas.find((schema: any) => schema.id === schemaId) : null;
  const configured = selected ? selectedSchemaText(selected.content,config.interfaceSchemaText) : config.interfaceSchemaText;
  const modelSchema = boundaryType === "start" ? task.input_schema : task.output_schema;
  return schemaDataFields(configured || modelSchema);
}

function resolvedActivityContract(node: any, task: any, tasks: any[], schemas: any[], resources: any[] = []): Contract {
  const contract = activityContract(node);
  if (node.type === "http_listener" || (node.type === "rest" && node.config?.operation === "receiver")) {
    const declarations: RequestParameter[] = Array.isArray(node.config?.requestParameters) ? node.config.requestParameters : [];
    const groups = {pathParameters: "path", query: "query", headers: "header"};
    contract.output = contract.output.flatMap(field => {
      const location = groups[field.key as keyof typeof groups];
      if (!location) return [field];
      return [field, ...declarations.filter(parameter => parameter.in === location && parameter.name?.trim()).map(parameter => {
        const name = parameter.name.trim();
        return {...d(`${field.key}.${location === "header" ? name.toLowerCase() : name}`, name, parameter.type),
          required: location === "path" || parameter.required};
      })];
    });
    const schema = node.config?.requestSchema;
    const fields = schemaDataFields(schema);
    if (fields.length) {
      const xml = typeof schema === "string" && schema.trimStart().startsWith("<");
      const root = xml ? "xmlBody" : "body";
      const bodyFields = fields.map(child => ({ ...child, key: `${root}.${child.key}` }));
      const output = contract.output.flatMap(field => {
        if (field.key !== "body") return [field];
        if (!xml) return [field, ...bodyFields];
        return [d(root, "Request body (XML fields)", "object"), ...bodyFields, d("body", "Raw request body", "any")];
      });
      return { ...contract, output };
    }
  }
  if (node.type === "http_response") {
    const endpoint = task?.activities?.find((activity: any) =>
      activity.type === "http_listener" || (activity.type === "rest" && activity.config?.operation === "receiver"),
    );
    const fields = schemaDataFields(endpoint?.config?.responseSchema);
    if (fields.length) return {
      ...contract,
      input: contract.input.flatMap(field => field.key === "body"
        ? [field, ...fields.map(child => ({ ...child, key: `body.${child.key}` }))]
        : [field]),
    };
  }
  if (node.type === "sap" && node.config?.operation === "idoc_parser") {
    const resource = resources.find((item: any) => item.id === node.config?.resourceId);
    const selected = resource?.config?.idocCatalog?.find((item: any) => item.idocType === node.config?.idocType) || resource?.config?.selectedIdoc;
    const mode = String(node.config?.idocOutputMode || "JSON").toUpperCase();
    if (mode === "JSON" && selected?.schema) {
      const fields = schemaDataFields(selected.schema);
      if (fields.length) return { ...contract, output: [...fields.map((field: any) => ({ ...field, key: `SAPIDoc.${field.key}` })), d("format", "Output format")] };
    }
    if (mode === "XML") {
      // XML mode is parsed XML data, not just a serialized payload. Publish
      // the reusable object tree as the primary output; IDocXML/payload remain
      // available when a downstream connector explicitly needs XML text.
      const fields = selected?.schema ? schemaDataFields(selected.schema) : [];
      return {
        ...contract,
        output: [
          ...fields.map((field: any) => ({ ...field, key: `xmlObject.${field.key}` })),
          d("xmlObject", "Parsed IDoc XML object", "object"),
          d("IDocXML", "Serialized IDoc XML", "string"),
          d("payload", "XML payload", "string"),
          d("format", "Output format"),
        ],
      };
    }
  }
  if (["xml", "json", "flat"].includes(node.type)) {
    if (node.type === "json" && node.config?.schemaType === "Generic") return contract;
    const asset = activitySchemaAsset(node, schemas);
    const schemaFields = schemaDataFields(activitySchemaText(node, schemas), asset?.source_path || asset?.name, schemas);
    if (!schemaFields.length) return contract;
    const parsing = node.config?.operation === "parse";
    const flatLeaves = schemaFields.filter((field) => !schemaFields.some((candidate) => candidate.key.startsWith(`${field.key}.`)));
    const fields = node.type === "flat"
      ? [d("records", "Records", "array"), ...flatLeaves.map((field) => ({ ...field, key: `records.${field.label}` }))]
      : schemaFields;
    return parsing ? { ...contract, output: [...contract.output.filter(field => !fields.some(candidate => candidate.key === field.key)), ...fields] } : { ...contract, input: [...contract.input.filter(field => !fields.some(candidate => candidate.key === field.key)), ...fields] };
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
    const called = resolveWorkspaceSubtask(tasks, designTimeId || "") ?? resolveWorkspaceSubtask(tasks, node.config?.taskId || "");
    const input = boundaryFields(called, "start", schemas), output = boundaryFields(called, "end", schemas);
    return {
      ...contract,
      input: input.length ? input : contract.input,
      output: output.length ? output : contract.output,
    };
  }
  return contract;
}

export function possibleTaskExceptions(task: any, tasks: any[] = [], schemas: any[] = []): string[] {
  const values = new Set<string>(["RUNTIME"]), visited = new Set<any>();
  const visit = (current: any) => {
    if (!current || visited.has(current)) return;
    visited.add(current);
    for (const activity of current.activities || []) {
      if (activity.type === "catch" || activity.config?.generatedByCatchAI) continue;
      if (activity.type === "throw") values.add(String(activity.config?.errorType || "UserDefinedException"));
      else resolvedActivityContract(activity, current, tasks, schemas).errors.forEach((error) => values.add(error.type));
      if (activity.type === "call_task") {
        const dynamic = String(activity.config?.dynamicTaskId || "").trim();
        const target = dynamic && !dynamic.includes("${") ? dynamic : activity.config?.taskId;
        const called = target ? tasks.find(candidate => [candidate.id,candidate.name].some(value => String(value).toLowerCase() === String(target).toLowerCase())) : null;
        visit(called);
      }
    }
  };
  visit(task);
  return [...values].filter(Boolean).sort((left,right) => left.localeCompare(right));
}

function runtimeMappableInputs(node: any, contract: Contract): DataField[] {
  if (node.type === "http" || (node.type === "rest" && node.config?.operation === "invoke")) return httpRequestOccurrences(contract.input,httpInputMappings(node.config || {}));
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

const isParseRender = (node: any) => ["xml", "json", "flat"].includes(node.type);

function formatInputMappings(config: any, contract: Contract) {
  const values = { ...(config.inputMappings || {}) };
  const legacy = new Map<string,string>();
  for (const field of contract.input.filter(field => field.key.startsWith("formatOptions."))) {
    const key = field.key.split(".")[1];
    if (key in values) {
      values[field.key] ??= values[key];
      delete values[key];
    }
    if (!contract.configuration.some(option => option.key === key)) legacy.set(key,field.key);
  }
  if (config.filePath && contract.input.some(field => field.key === "fileName")) legacy.set("filePath", "fileName");
  for (const [key, target] of legacy) {
    if (key in values) {
      values[target] ??= values[key];
      delete values[key];
    }
    if (target in values || config.formatOptions && key in config.formatOptions) continue;
    const value = config[key];
    if (value === "" || value == null) continue;
    values[target] = typeof value === "string" && /\$\{[^}]+\}/.test(value)
      ? value : `__mina_constant__:${JSON.stringify(value)}`;
  }
  return { values, legacy };
}

const activityDocumentation: Record<string, { summary: string; behavior: string }> = {
  http_listener: {
    summary: "Starts a Starter Task when an inbound HTTP request matches its configured method and path.",
    behavior: "Choose the server connection, methods, route, content types, and schema references when creating the task. Setup adds HTTP Send Response for the reply. Run or Debug shows the live endpoint, Swagger link, and Postman download when API documentation is enabled. JSON request fields appear under body. Parsed XSD fields appear under xmlBody, with the original XML under body.",
  },
  http: { summary: "Sends an outbound HTTP request and exposes the response to downstream activities.", behavior: "Select a shared HTTP client connection. In Input → RestInputRequest, map the URI, method, body, and query parameters under Config. Choose CustomHeaders → Add header to map each name/value pair independently, or use For Each for a collection. Set Content-Type and Accept under Headers." },
  sse_read: { summary: "Reads a bounded batch from a Server-Sent Events endpoint.", behavior: "Map an HTTP or HTTPS URL, maximum events and optional Last-Event-ID. The activity sends Accept: text/event-stream and closes after the requested event count, end of stream or timeout." },
  websocket_exchange: { summary: "Exchanges messages with a WebSocket server.", behavior: "Map a ws or wss URL, an optional outbound message and the maximum replies. Received binary messages are base64. The activity closes its connection when it finishes." },
  write_precondition: { summary: "Evaluates request validators before a write.", behavior: "Map inbound request headers and the current ETag, Last-Modified and existence. Branch on allowed, send 412 or 428 on rejection, and guard the actual write atomically in the datastore." },
  http_response: { summary: "Completes the active inbound HTTP exchange.", behavior: "Place HTTP Send Response on the same execution path as the listener or receiver. In Input, optional HTTPHeaders contains Content-Type, complex StatusLine and repeating Cookies. Map StatusLine.httpVersion, StatusLine.statusCode and StatusLine.reasonPhrase independently. Native HTTP/1 listeners send the mapped version (1.0 or 1.1) and custom reason phrase, including an empty phrase. HTTP/1.0 responses use Content-Length and close the connection. HTTP/2 and HTTP/3 require a matching negotiated version and no nonempty reason phrase; unsupported overrides fail before sending headers. HTTP/1 fallback on an HTTP/2 or HTTP/3 listener does not support custom reason phrases. Unmapped fields use existing defaults, and existing full status-line strings still work. Mapped settings remain visible in statusLine execution output. DynamicHTTPHeaders contains repeating Headers with headerName and headerValue. Dynamic headers override standard/legacy headers; duplicate names remain separate header lines, including Set-Cookie. Legacy statusCode, contentType and headers mappings still work. If the endpoint declares a response schema, its fields are available for body mapping. An explicit Content-Type must be offered by the endpoint and acceptable to the caller." },
  rest_receiver: { summary: "Starts a task for a matching REST method and route.", behavior: "In Request parameters, declare URI path placeholders, query values, and custom headers. Select a type and mark required entries. Invalid or missing required values return HTTP 400. Output provides pathParameters, query, headers with lowercase names, and body or xmlBody. Use HTTP Send Response to reply. Run or Debug exposes the live endpoint and, when enabled, Swagger and Postman." },
  rest_invoke: { summary: "Calls a remote REST API through a shared HTTP client connection.", behavior: "In Input → RestInputRequest.Config, map the URI and query parameters, request body, and optional OpenAPI contract and operation ID. Use CustomHeaders → Add header for repeating name/value pairs, or use For Each for a collection. RestOutputResponse exposes the status, headers, and body." },
  soap: { summary: "Hosts a SOAP service or invokes a request/reply web service.", behavior: "Service mode publishes the configured contract and begins the task for a matching SOAP request. Request/reply mode uses the selected HTTP connection and WSDL metadata for outbound invocation." },
  file: { summary: "Performs the selected filesystem operation.", behavior: "File paths and operation-specific values accept constants, property expressions, or mappings from earlier execution-path outputs. Runtime output contains operation-specific metadata and content." },
  ftp: { summary: "Performs the selected FTP operation through a shared FTP connection.", behavior: "Connection defaults come from the resource; paths, names, content, and transfer settings may be mapped dynamically for each invocation." },
  sftp: { summary: "Performs the selected secure file-transfer operation.", behavior: "Authentication and host-key policy come from the SFTP shared connection. Operation inputs remain dynamically mappable at runtime." },
  jdbc: { summary: "Executes a JDBC Query, Update, Call Procedure, or SQL Direct contract.", behavior: "The JDBC designer runs and fetches SQL metadata, derives prepared parameters and result fields, supports dynamic SQL overrides, batching, subsets, NULL handling, maximum rows, transaction overrides, and database-specific drivers." },
  snowflake: { summary: "Runs Snowflake Insert, Query, Update, Delete, or staged Bulk Load operations.", behavior: "The Snowflake JDBC shared connection supplies authentication, warehouse, database, schema, pooling, and downloaded table/view metadata. Activity inputs and outputs use MINA's schema-aware Snowflake contracts." },
  amqp: { summary: "Sends, receives, gets, or dead-letters AMQP messages.", behavior: "The shared connection supports RabbitMQ AMQP 0.9.1/1.0 and AMQP 1.0 broker profiles. Destinations, subscriptions, typed messages, properties, settlement handles, recovery, SSL, sessions, and Azure dead-letter behavior are configured in MINA." },
  excel: { summary: "Reads an Excel workbook and publishes every selected worksheet as nested JSON.", behavior: "Leave Worksheet blank to read every tab. The configured header row becomes field names; dotted headers such as customer.address.city create nested objects. Formula cells can return their cached calculated values." },
  basic: { summary: "Executes the selected general-purpose activity.", behavior: "External Command runs an executable without a shell, accepts stdin/environment/working-directory overrides, can capture or persist stdout and stderr, applies configured line splitting, and publishes the process return code." },
  ems: { summary: "Sends, receives, browses, or acknowledges EMS messages.", behavior: "Destination, delivery, selector, acknowledgement, and message properties follow the selected EMS operation. Client acknowledgement handles can be passed to Confirm Message." },
  kafka: { summary: "Produces, receives, or commits Apache Kafka records.", behavior: "Broker security comes from the shared Kafka connection. Topic, key, headers, value, partitions, offsets, and acknowledgement handles are available for hierarchical mapping." },
  pubsub: { summary: "Publishes, receives, or acknowledges Google Cloud Pub/Sub messages.", behavior: "Project and credential defaults come from the shared connection. Message data, attributes, ordering keys, and acknowledgement handles remain available on the execution path." },
  sap: { summary: "Executes the selected SAP ECC operation.", behavior: "The shared SAP connection supplies system and authentication settings. IDoc metadata selected from SAP defines listener, parser, renderer, and sender structures." },
  mapper: { summary: "Maps execution-path data into a selected target schema.", behavior: "In Input, drop a repeating complex source onto a repeating complex target. Copy-Of copies the whole collection and hides child bindings. For-Each creates editable child bindings for matching names; SmartMap also matches names that differ by underscores or hyphens. The loop shows the collection expression once and child expressions relative to the current item. Run Map & Test to check the output." },
  transform: { summary: "Legacy Mapper activity retained for project compatibility.", behavior: "Existing Transform nodes continue to execute with Mapper behavior. New projects should use Mapper for visual/XPath mappings or Transform for DataWeave scripts." },
  ai_transform: { summary: "Legacy AI Mapper activity retained for project compatibility.", behavior: "Existing AI Transform nodes continue to use the consolidated Mapper and its AI recommendation/review workflow." },
  dataweave: { summary: "Transforms payloads with MINA's executable DataWeave-compatible language subset.", behavior: "Scripts support payload/attributes/vars selectors, objects, arrays, defaults, conditionals, concatenation, common coercion/string/collection functions, map/filter/groupBy/orderBy/distinctBy, JSON, XML, and text output. The editor validates and runs the same engine used at runtime." },
  call_task: { summary: "Invokes a reusable Sub Task and waits for its result.", behavior: "Mapped values become the Sub Task Start input. Dynamic Sub Task ID/name is resolved per invocation; the selected Sub Task is its design-time schema and runtime fallback. The Sub Task End output returns to this activity." },
  confirm: { summary: "Acknowledges one or more client-managed messages.", behavior: "Map the acknowledgement handle emitted by an EMS, Kafka, Pub/Sub, or compatible future receiver. The runtime dispatches confirmation to the originating connector." },
  start: { summary: "Defines the task input boundary.", behavior: "For Sub Tasks, the Start schema is the callable input contract. Starter Tasks normally use one external event activity instead." },
  end: { summary: "Defines the task output boundary.", behavior: "Mapped values become the final task result. For a Sub Task, this result is returned to its Call Sub Task activity." },
  log: { summary: "Writes a structured application log event.", behavior: "Message, level, and payload accept constants or dynamic mappings. Advanced automatic payload logging can be used when a dedicated Log activity is unnecessary." },
  xml: { summary: "Parses XML text into an XSD-defined tree or renders an XSD-defined tree as XML.", behavior: "Parse XML accepts serialized XML in Input and defines its published tree in Output Editor. Render XML defines and maps its source tree in Input Editor, then emits xmlString (or binary output when selected)." },
  json: { summary: "Converts between serialized JSON and a schema-defined activity tree.", behavior: "Parse JSON accepts jsonString and publishes the structure selected in Output Editor. Render JSON maps the structure selected in Input Editor and emits jsonString." },
  flat: { summary: "Parses delimited/fixed-width text into records or renders records as formatted text.", behavior: "The schema contract defines record fields; Configuration controls separators, widths, headers, trimming, and line endings. Parse Data publishes records while Render Data accepts mapped records and emits text." },
};

function DocumentationStructure({ title, fields }: { title: string; fields: DataField[] }) {
  const rows = dataTreeRows(fields), tree = useTreeCollapse();
  return <section><h3>{title}</h3>{fields.length ? <div className="documentation-tree">{rows.map((field) => { if (!tree.visible(field.path)) return null; const group = field.group || hasTreeChildren(rows, field); return <div key={field.path} style={{ "--doc-depth": field.depth } as React.CSSProperties} className={group ? "group" : ""}>{group ? <TreeToggle path={field.path} label={field.label} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <i className="tree-elbow"/>}<span>{field.name}</span><code>{group ? "object" : field.type}</code><b>{field.required ? "required" : ""}</b><small>{field.help}</small></div>; })}</div> : <p>No explicit {title.toLowerCase()} fields are required for this operation.</p>}</section>;
}

function ActivityDocumentation({ node, contract }: { node: any; contract: Contract }) {
  const doc = activityDocumentation[node.type === "rest" ? (node.config?.operation === "invoke" ? "rest_invoke" : "rest_receiver") : node.type === "http" && activityDocumentation[node.config?.operation] ? node.config.operation : node.type] || {
    summary: `Executes the ${node.name} activity on the current task path.`,
    behavior: "Configuration supplies design-time defaults. Input mappings, constants, property expressions, outputs, advanced policies, and documented errors are evaluated by the runtime.",
  };
  return <div className="activity-tab activity-documentation">
    <header><BookOpen/><span><h2>{node.name}</h2><small>{node.type} / {node.config?.operation || "default"}</small></span><a href={`/help/index.html#activity-${String(node.type).toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${String(node.config?.operation || "default").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`} target="_blank" rel="noreferrer"><BookOpen/> Full activity reference and PDF</a></header>
    <section><h3>Purpose</h3><p>{doc.summary}</p><p>{doc.behavior}</p></section>
    {node.type === "jdbc" && <section className="jdbc-documentation"><h3>Prepared SQL examples</h3><p>Use named parameters in the SQL editor. Each <code>:name</code> is automatically created as a typed field under <b>Input → parameters</b>.</p><pre>{`SELECT id, customer_name, status\nFROM orders\nWHERE status = :status AND created_at >= :fromDate;\n\nUPDATE orders SET status = :status WHERE id = :orderId;`}</pre><p>Choose the JDBC datatype beside every derived parameter. Runtime mappings and constants are converted to that datatype before the prepared statement is executed.</p></section>}
    <section><h3>Configuration reference</h3>{contract.configuration.length ? <div className="documentation-fields">{contract.configuration.map((field) => <article key={field.key}><b>{field.label}{field.required && " *"}</b><code>{field.type || "text"}</code><p>{field.help || `Sets the ${field.label.toLowerCase()} used by this activity.`}</p></article>)}</div> : <p>This boundary activity has no additional operation configuration.</p>}</section>
    <DocumentationStructure title="Input contract" fields={runtimeMappableInputs(node, contract)}/>
    <DocumentationStructure title="Output contract" fields={contract.output}/>
    <section><h3>Errors and runtime policy</h3><div className="documentation-errors">{contract.errors.map((error) => <article key={error.type}><code>{error.type}</code><span>{error.description}</span></article>)}</div><p>Use the Errors tab to choose propagate, continue, or transition handling. The Advanced tab controls automatic payload logging and retry behavior for outbound calls.</p></section>
    <section><h3>Mapping rules</h3><p>Every mappable field accepts a typed constant, an environment property such as <code>{'${properties.connections.http.host}'}</code>, a function expression, or a field selected from the hierarchical execution-path data tree. String constants require matching single or double quotes. Press Enter to validate; invalid mappings appear in dark red.</p></section>
    <ActivityEditorGuidance type={node.type}/>
    <section><h3>Mapping function reference</h3><div className="documentation-fields">{mapperFunctionCatalog.map(definition => <article key={definition.name}><b>{definition.signature}</b><code>{definition.category}</code><p>{definition.description}</p></article>)}</div></section>
  </div>;
}

function ActivityEditorGuidance({ type }: { type: string }) {
  const groups = ["ActivityEditor", "InputEditor", "MappingContextMenu", "ExpandedInputMappingDialog", "OutputEditor", "AdvancedEditor", "ErrorEditor"];
  if (["mapper", "transform", "ai_transform", "dataweave"].includes(type)) groups.push("TransformSchemaEditor", "TransformPoliciesEditor", "AIMappingAssistance", "TransformInputEditor", "TransformOutputEditor", "TransformMapTestEditor");
  if (type === "dataweave") groups.push("DataWeaveScriptEditor", "DataWeaveTestEditor");
  if (type === "timer") groups.push("SchedulerEditor");
  if (type === "jdbc") groups.push("JdbcDesigner");
  if (type === "call_task") groups.push("CallTaskRoutingEditor");
  if (type === "catch") groups.push("CatchAIEditor");
  if (["start", "end"].includes(type)) groups.push("TaskBoundarySchemaEditor");
  if (["xml", "json", "flat"].includes(type)) groups.push("DataContractSchemaEditor");
  const wording = [...new Set(groups.flatMap(group => activityGuidance[group] || []))];
  return <section className="activity-editor-guidance"><h3>Editor guidance</h3>{wording.map(text => <p key={text}>{text}</p>)}</section>;
}

export function activityInputMappingTypes(node:any, task:any, tasks:any[], schemas:any[], resources:any[]) {
  const fields = runtimeMappableInputs(node, resolvedActivityContract(node, task, tasks, schemas, resources));
  return Object.fromEntries(dataTreeRows(fields).map(field => [field.path, field.validationType || field.type || 'any']));
}

export function activityMappingIssues(node:any, task:any, tasks:any[], schemas:any[], resources:any[]) {
  const config = node.config || {}, issues:Array<{path:string; error:string}> = [];
  const mapper = isMapperActivity(node.type);
  const fields = mapper ? transformSchemaFields(config) : [];
  const types = mapper ? Object.fromEntries(fields.map(field => [field.path, field.type])) : activityInputMappingTypes(node, task, tasks, schemas, resources);
  const paths = mappingCompletionPaths(upstreamActivitySources(node, task, tasks, schemas, resources));
  const check = (path:string, value:any, constant = false) => {
    const expression = constant && typeof value === 'string' ? JSON.stringify(value) : value && typeof value === 'object' ? JSON.stringify(value) : value;
    const error = validateMapping(expression, types[path] || 'any', paths);
    if (error) issues.push({path,error});
  };
  const rules = mapper ? config.mappings || [] : activityMappingRules(config.inputMappings || {});
  for (const rule of rules) {
    if (rule.enabled === false) continue;
    const operator = rule.operator || rule.$rule;
    if (['for-each','for-each-group'].includes(operator)) continue;
    if (rule.constant !== undefined) {check(rule.target,rule.constant,true);continue;}
    if (operator === 'choose') {
      let branches = rule.whens;
      if (!branches) {try {branches = JSON.parse(rule.source || '[]');} catch {branches = [];}}
      if (!Array.isArray(branches) || !branches.length) {issues.push({path:rule.target,error:'At least one When condition is required.'});continue;}
      for (const branch of branches) {
        if (!String(branch.condition || '').trim()) issues.push({path:rule.target,error:'Enter a When condition.'});
        check(rule.target,branch.source);
      }
    } else {
      if (['if','when-otherwise'].includes(operator) && !String(rule.condition || '').trim()) issues.push({path:rule.target,error:'Enter a condition.'});
      check(rule.target,rule.select || rule.source);
    }
    if (rule.otherwise !== undefined) check(rule.target,rule.otherwise);
  }
  return issues;
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
  navigateTask,
  createConnection,
  tab,
  update,
}: any) {
  const mappingSources = useActivityMappingSources(node, task, tasks, schemas, resources);
  const contract = useMemo(() => resolvedActivityContract(node, task, tasks, schemas || [], resources || []),
    [node, task, tasks, schemas, resources]),
    storedConfig = node.config || {},
    selectedTargetSchema = isMapperActivity(node.type) && storedConfig.targetSchemaId ? (schemas || []).find((schema: any) => schema.id === storedConfig.targetSchemaId) : undefined,
    cfg = selectedTargetSchema ? { ...storedConfig, targetSchema: {}, targetSchemaText: selectedTargetSchema.content } : storedConfig,
    selectedSapConnection = node.type === "sap" ? resources.find((resource: any) => resource.id === cfg.resourceId) : null,
    selectedSapConfig = selectedSapConnection?.config || {},
    derivedConfiguration = node.type === "sap" && cfg.operation === "idoc_listener" ? {
      ...cfg,
      release: cfg.release || selectedSapConfig.release || selectedSapConfig.selectedIdoc?.release || "",
      programId: cfg.programId || selectedSapConfig.programId || "",
      messagingSource: cfg.messagingSource || "NoMessaging",
      tidManagerId: selectedSapConfig.tidStorePath || "Managed by SAP JCo durable TID store",
      extensionType: cfg.extensionType || selectedSapConfig.selectedIdoc?.extensionType || "",
      invocationProtocol: "tRFC",
    } : cfg,
    upstreamSources = mappingSources.sources,
    groupVariables = mappingSources.variables,
    [mapperOpen, setMapperOpen] = useState(false),
    set = (key: string, value: any, createdResource?: SharedConnection) => {
      if (node.type === "sap" && cfg.operation === "idoc_listener" && key === "messagingSource") {
        update({ config: { ...cfg, messagingSource: value, messagingResourceId: "", messagingDestination: value === "NoMessaging" ? "" : cfg.messagingDestination || "" } });
        return;
      }
      if (node.type === "sap" && key === "resourceId") {
        const connection = createdResource || resources.find((resource: any) => resource.id === value);
        const connectionConfig = connection?.config || {};
        update({ config: {
          ...cfg,
          resourceId: value,
          ...(cfg.operation === "idoc_listener" ? {
            release: connectionConfig.release || connectionConfig.selectedIdoc?.release || "",
            programId: connectionConfig.programId || "",
            messagingSource: cfg.messagingSource || "NoMessaging",
            tidManagerId: connectionConfig.tidStorePath || "Managed by SAP JCo durable TID store",
            extensionType: connectionConfig.selectedIdoc?.extensionType || "",
            invocationProtocol: "tRFC",
          } : {}),
        } });
        return;
      }
      update({ config: { ...cfg, [key]: value } });
    };
  const exceptionTypes = possibleTaskExceptions(task, tasks, schemas || []);
  const nameField = <ActivityNameField key={node.id} node={node} task={task} update={update}/>;
  if (tab === "documentation") return <ActivityDocumentation node={node} contract={contract} />;
  if (tab === "configuration")
    return (
      <div className="activity-tab contract-config">
        <div className="contract-heading">
          <SettingsTitle
            title="Activity configuration"

          />
        </div>
        <div className="contract-grid">
          {isParseRender(node) ? <span className="contract-label">{node.name}</span> : nameField}
          {node.type !== "timer" && contract.configuration.filter((field) => !(node.type === "call_task" && field.key === "dynamicTaskId") && (!field.when || field.when(derivedConfiguration))).map((field) => field.type === "dataFormat" ? (
            <label key={field.key}>{field.label}
              <select value={cfg.dataFormatId || ""} onChange={event => {
                const mapping = { ...(cfg.inputMappings || {}) };
                for (const [target, expression] of Object.entries(sharedDataFormatMappings(cfg.dataFormatId, schemas || []))) {
                  if (mapping[target] === expression) delete mapping[target];
                }
                const generated = sharedDataFormatMappings(event.target.value, schemas || []);
                if ("delimiter" in mapping) delete generated["formatOptions.delimiter"];
                const next = { ...cfg, dataFormatId: event.target.value, inputMappings: { ...generated, ...mapping } };
                if (event.target.value) {
                  for (const key of "format delimiter separatorRule lineSeparator lineEnding header fields fieldTypes widths fieldOffsets lineLength fillCharacter strictColumns trimValues skipBlankLines blankLinePolicy includeFinalLineSeparator rootElement recordElement fileEncoding".split(" ")) delete next[key];
                }
                update({ config: next });
              }}>
                <option value="">Configure inline</option>
                {(schemas || []).filter((asset: any) => sharedDataFormat(asset.id, [asset])).map((asset: any) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
                {cfg.dataFormatId && !sharedDataFormat(cfg.dataFormatId, schemas || []) && <option value={cfg.dataFormatId}>Missing Data Format asset</option>}
              </select>
              <small>{field.help}</small>
            </label>
          ) : field.type === "schema" ? (
            <EndpointSchemaPicker
              key={`${node.id}:${field.key}`}
              label={field.key === "requestSchema" ? "Request" : "Response"}
              schemas={schemas || []}
              value={savedSchemaChoice(cfg[field.key], cfg[`${field.key}Name`], schemas || [])}
              onChange={choice => {
                const validationKey = field.key === "requestSchema" ? "validateRequest" : "validateResponse";
                const next = { ...cfg };
                if (choice.source) {
                  next[field.key] = choice.text;
                  next[`${field.key}Name`] = schemaChoiceName(choice, schemas || []);
                  next[validationKey] ??= true;
                } else {
                  delete next[field.key];
                  delete next[`${field.key}Name`];
                  if (!next.openApiDocument) delete next[validationKey];
                }
                update({ config: next });
              }}
            />
          ) : field.type === "requestParameters" ? (
            <HttpRequestParameters key={node.id} path={String(cfg.path || "")}
              value={Array.isArray(cfg.requestParameters) ? cfg.requestParameters : []}
              onChange={value => set(field.key, value)}/>
          ) : field.type === "mediaTypes" ? (
            <HttpContentTypeCheckboxes key={`${node.id}:${field.key}`} label={field.label}
              response={field.key === "responseContentTypes"}
              value={savedContentTypes(cfg[field.key], cfg[field.key === "requestContentTypes" ? "contentType" : "responseType"])}
              onChange={value => {
                const next = { ...cfg, [field.key]: value };
                delete next[field.key === "requestContentTypes" ? "contentType" : "responseType"];
                update({ config: next });
              }}/>
          ) : field.type === "mediaType" ? (
            <HttpContentTypePicker key={`${node.id}:${field.key}`} label={field.label}
              value={String(cfg[field.key] ?? "")} onChange={value => set(field.key, value)}/>
          ) : (
            <FieldEditor
              key={field.key}
              field={node.type === "catch" && field.key === "errorType" ? { ...field, type: "select", options: ["", ...exceptionTypes] } : field}
              value={derivedConfiguration[field.key] ?? (field.type === "methods" ? cfg.method || "POST" :
                ((["validateRequest", "validateResponse"].includes(field.key) && derivedConfiguration.openApiDocument)
                  || (node.type === "json" && cfg.schemaType === "XSD" && ["validateOutput", "validateInput"].includes(field.key))) ? true
                  : field.key === "blankLinePolicy" ? (cfg.skipBlankLines === false ? "Stop" : "Skip") : undefined)}
              set={set}
              resources={resources}
              tasks={tasks}
              properties={properties}
              selectedResourceId={cfg.resourceId}
              navigateTask={navigateTask}
              createConnection={createConnection}
              httpRole={node.type === "http_listener" || (node.type === "rest" && cfg.operation !== "invoke") || (node.type === "soap" && cfg.operation === "service") ? "http_server" : "http_client"}
            />
          ))}
        </div>
        {node.type === "jdbc" && <JdbcDesigner config={cfg} resource={resources.find((resource: any) => resource.id === cfg.resourceId)} properties={properties} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>}
        {node.type === "timer" && <SchedulerEditor config={cfg} set={set}/>}
        {node.type === "call_task" && <CallTaskRoutingEditor config={cfg} tasks={tasks} properties={properties} set={set}/>}
        {node.type === "catch" && <CatchAIEditor nodeId={`${task?.id}:${node.id}`} exceptionTypes={exceptionTypes} handleExceptions={handleExceptions}/>}
        {isMapperActivity(node.type) && (
          <>
            <TransformSchemaEditor config={cfg} schemas={schemas || []} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>
            <TransformPoliciesEditor config={cfg} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>

          </>
        )}
        {node.type === "dataweave" && <DataWeaveScriptEditor config={cfg} schemas={schemas || []} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>}
        {(node.type === "start" || node.type === "end") && (
          <TaskBoundarySchemaEditor node={node} config={cfg} schemas={schemas || []} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>
        )}

      </div>
    );
  if (tab === "input")
    return isMapperActivity(node.type) ? (
      <TransformInputEditor actions={<>
        <button type="button" className="edit-input-mapping ai-mapper-launcher" aria-label="Open visual AI Mapper" onClick={() => setMapperOpen(true)}>
              <WandSparkles /> AI Mapper
            </button>
        {mapperOpen && (
          <MapperStudio
            config={cfg}
            sources={upstreamSources}
            customFunctions={customFunctions}
            schemas={schemas || []}
            onClose={() => setMapperOpen(false)}
            onSave={(next: any) => {
              update({ config: { ...cfg, ...next } });
              setMapperOpen(false);
            }}
          />
        )}</>} config={cfg} schemas={schemas || []} setSourceCoercions={(value:any) => set("sourceCoercions", value)} properties={properties} sources={upstreamSources} runtimeVariables={groupVariables} customFunctions={customFunctions} updateCustomFunctions={updateCustomFunctions} setMappings={(value: any) => set("mappings", value)}/>
    ) : (
      <InputEditor
        node={node}
        fields={node.type === "http" || (node.type === "rest" && cfg.operation === "invoke") ? contract.input : runtimeMappableInputs(node, contract)}
        mappings={node.type === "http" || (node.type === "rest" && cfg.operation === "invoke") ? httpInputMappings(cfg) : isParseRender(node) ? formatInputMappings(cfg, contract).values : cfg.inputMappings || {}}
        set={(v: any) => {
          const config = {...cfg,inputMappings:v,inputMappingTypes:activityInputMappingTypes({...node,config:{...cfg,inputMappings:v}},task,tasks,schemas || [],resources || [])};
          if (isParseRender(node)) for (const [key] of formatInputMappings(cfg, contract).legacy) delete config[key];
          if (node.type === "http" || (node.type === "rest" && cfg.operation === "invoke")) {
            for (const key of ["host","port","scheme","url","method","body","bodyType","query","pathParameters","headers","accept","contentType","timeout","socketTimeoutMs","activityTimeoutSeconds","followRedirects","requestEntityProcessing","sendBodyMode","successStatusCodes","raiseForStatus"]) delete config[key];
            config.requestModel="tree";config.responseMode="envelope";
          }
          update({config});
        }}
        properties={properties}
        sources={upstreamSources}
        runtimeVariables={groupVariables}
        customFunctions={customFunctions}
        updateCustomFunctions={updateCustomFunctions}
        before={isParseRender(node) ? <><div className="contract-grid">{nameField}</div>{cfg.operation !== "parse" && !(node.type === "json" && cfg.schemaType === "Generic") && <DataContractSchemaEditor node={node} config={cfg} schemas={schemas || []} direction="input" setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>}</> : null}
      />
    );
  if (tab === "map_test" && isMapperActivity(node.type))
    return <TransformMapTestEditor node={node} config={cfg} schemas={schemas || []} customFunctions={customFunctions} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>;
  if (tab === "map_test" && node.type === "dataweave")
    return <DataWeaveTestEditor config={cfg} setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/>;
  if (tab === "output")
    return isMapperActivity(node.type) ? <TransformOutputEditor config={cfg} schemas={schemas}/> : <OutputEditor fields={contract.output} config={cfg} set={set} before={(["xml", "json", "flat"].includes(node.type) && cfg.operation === "parse" && !(node.type === "json" && cfg.schemaType === "Generic")) ? <DataContractSchemaEditor node={node} config={cfg} schemas={schemas || []} direction="output" setConfig={(next: any) => update({ config: { ...cfg, ...next } })}/> : null}/>;
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
  const subtasks = (tasks || []).filter((task: any) => task.kind === "subtask");
  const expression = String(config.dynamicTaskId || ""), literal = expression && !expression.startsWith("${");
  const resolvedDesignTime = resolveWorkspaceSubtask(subtasks, literal ? expression : config.taskId || "");
  return <section className="call-task-routing">
    <header><Workflow/><span><b>DYNAMIC SUB TASK ROUTING</b></span><i>{expression ? "OVERRIDE ACTIVE" : "STATIC FALLBACK"}</i></header>
    <div><label>Dynamic ID/name expression<input value={expression} onChange={(event) => set("dynamicTaskId", event.target.value)} placeholder="${properties.routing.targetTask}"/></label><label>Insert project property<select value="" onChange={(event) => event.target.value && set("dynamicTaskId", `\${properties.${event.target.value}}`)}><option value="">Browse properties…</option>{(properties || []).map((property: any) => <option key={property.key} value={property.key}>{property.key}</option>)}</select></label></div>
    <footer><span><b>Design-time interface</b>{resolvedDesignTime ? `${resolvedDesignTime.name} (${resolvedDesignTime.id})` : "No valid fallback Sub Task selected"}</span><span><b>Runtime precedence</b>dynamic override → selected fallback → TASK_NOT_FOUND</span></footer>
  </section>;
}

function CatchAIEditor({ nodeId, exceptionTypes, handleExceptions }: any) {
  const [selected, setSelected] = useState<string[]>([]);
  const exceptionKey = exceptionTypes.join("|");
  useEffect(() => setSelected([]), [nodeId, exceptionKey]);
  const toggle = (type: string) => setSelected((current) => current.includes(type) ? current.filter((item) => item !== type) : [...current, type]);
  return <section className="catch-ai-editor">
    <header><WandSparkles/><span><b>Catch AI · Task exception analyzer</b></span><i>{exceptionTypes.length} FOUND</i></header>
    <div className="catch-ai-actions"><button type="button" onClick={() => setSelected(exceptionTypes)}>Select all</button><button type="button" onClick={() => setSelected([])}>Clear</button></div>
    <div className="catch-ai-types">{exceptionTypes.map((type: string) => <label key={type} className={selected.includes(type) ? "selected" : ""}><input type="checkbox" checked={selected.includes(type)} onChange={() => toggle(type)}/><ShieldAlert/><span><b>{type}</b></span></label>)}</div>
    <footer><span>Generated Throw activities map the caught error type, code, message, details, and stack trace automatically.</span><button type="button" disabled={!selected.length} onClick={() => handleExceptions?.(selected)}><WandSparkles/> Handle {selected.length || "selected"} exception{selected.length === 1 ? "" : "s"}</button></footer>
  </section>;
}

function SchedulerEditor({ config, set }: any) {
  const mode = config.scheduleMode || "dateTime";
  return <section className="scheduler-editor">
    <header><CalendarClock/><span><b>Scheduler trigger</b></span></header>
    <div className="scheduler-mode-tabs" role="tablist">
      <button type="button" className={mode === "dateTime" ? "active" : ""} onClick={() => set("scheduleMode", "dateTime")}>Date &amp; time</button>
      <button type="button" className={mode === "cron" ? "active" : ""} onClick={() => set("scheduleMode", "cron")}>Cron</button>
    </div>
    {mode === "dateTime" ? <div className="scheduler-fields">
      <label>First execution date and time<input type="datetime-local" value={config.scheduledDateTime || ""} onChange={(event) => set("scheduledDateTime", event.target.value)}/></label>
      <label>Time zone<select value={config.timezone || "local"} onChange={(event) => set("timezone", event.target.value)}><option value="local">Machine local time</option><option value="UTC">UTC</option></select></label>
      <label className="scheduler-check"><input type="checkbox" checked={!!config.repeatEnabled} onChange={(event) => set("repeatEnabled", event.target.checked)}/> Repeat after the first execution</label>
      {config.repeatEnabled && <><label>Every<input type="number" min="1" value={config.interval || 1} onChange={(event) => set("interval", Number(event.target.value))}/></label><label>Interval unit<select value={config.unit || "minutes"} onChange={(event) => set("unit", event.target.value)}><option>seconds</option><option>minutes</option><option>hours</option><option>days</option></select></label></>}
    </div> : <div className="scheduler-fields cron-fields">
      <label>Cron expression<input value={config.cronExpression || "0 * * * *"} onChange={(event) => set("cronExpression", event.target.value)} placeholder="minute hour day month weekday"/></label>
      <label>Time zone<select value={config.timezone || "local"} onChange={(event) => set("timezone", event.target.value)}><option value="local">Machine local time</option><option value="UTC">UTC</option></select></label>
    </div>}
    <label className="scheduler-run-once"><input type="checkbox" checked={config.runOnceOnLocalStart !== false} onChange={(event) => set("runOnceOnLocalStart", event.target.checked)}/><span><b>Run once now for local Run/Debug</b></span></label>
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
    <header><Braces/><span><b>DATAWEAVE TRANSFORM</b></span><button type="button" onClick={generate}><Sparkles/> AI generate</button></header>
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
    <header><FlaskConical/><span><b>Transform · Test</b></span></header>
    <main><section className="dataweave-test-inputs"><label><span>INPUT PAYLOAD · {config.inputMimeType || "application/json"}</span><textarea value={input} onChange={(event) => { setInput(event.target.value); setState("idle"); }} spellCheck={false}/></label><details><summary>Message attributes</summary><textarea aria-label="Sample message attributes" value={attributes} onChange={(event) => { setAttributes(event.target.value); setState("idle"); }} spellCheck={false}/></details><details><summary>Flow variables</summary><textarea aria-label="Sample flow variables" value={variables} onChange={(event) => { setVariables(event.target.value); setState("idle"); }} spellCheck={false}/></details></section><label><span>GENERATED OUTPUT · {config.outputTarget || "payload"}</span><pre>{output || "Run the transform to generate output."}</pre></label></main>
    <footer className={state}><span>{state === "valid" ? <CheckCircle2/> : state === "error" ? <AlertTriangle/> : <FlaskConical/>}{message}</span><button type="button" disabled={state === "running" || !String(config.script || "").trim()} onClick={run}>{state === "running" ? "Running…" : "Run transform"}</button></footer>
  </div>;
}

function InlineMapperFields({ text, save }: { text: string; save: (text: string) => void }) {
  const [path, setPath] = useState("");
  const [type, setType] = useState("string");
  const [required, setRequired] = useState(false);
  const [repeating, setRepeating] = useState(false);
  const [nilPolicy, setNilPolicy] = useState("keep");
  const [message, setMessage] = useState("");
  const xsd = text.trimStart().startsWith("<");
  const update = (remove: boolean) => {
    try {
      const fields = path.trim().split('.');
      if (fields.some(name => !/^[A-Za-z_][\w-]*$/.test(name) || ['__proto__','constructor','prototype'].includes(name))) throw new Error("Enter a field path such as order.items.price");
      if (xsd) {
        save(editMapperXsd(text, fields, type, required, repeating, remove, nilPolicy === "keep" ? undefined : nilPolicy === "allow"));
        setMessage(remove ? "Element removed" : "Element saved");
        return;
      }
      const schema = JSON.parse(text);
      if (!schema || Array.isArray(schema) || typeof schema !== 'object' || schema.$ref || schema.type && schema.type !== 'object' || !schema.properties && Object.keys(schema).length && schema.type !== 'object') {
        throw new Error("Use an inline JSON Schema object to edit fields here");
      }
      let parent = schema;
      const name = fields.pop()!;
      for (const part of fields) {
        const child = parent.properties?.[part];
        if (!child) throw new Error(`Create the parent field ${part} first`);
        parent = child.type === 'array' ? child.items : child;
        if (parent?.type !== 'object' || parent.$ref) throw new Error(`${part} must be an inline object or repeating object`);
      }
      parent.properties ??= {};
      if (remove) delete parent.properties[name];
      else {
        const previous = parent.properties[name];
        const previousItem = previous?.type === 'array' ? previous.items : previous;
        const item = previousItem?.type === type ? previousItem : {type, ...(type === 'object' ? {properties:{}} : {})};
        parent.properties[name] = repeating ? {...(previous?.type === 'array' ? previous : {}), type:'array', items:item} : item;
      }
      const names = Array.isArray(parent.required) ? parent.required.filter((entry: string) => entry !== name) : [];
      if (!remove && required) names.push(name);
      if (names.length) parent.required = names;
      else delete parent.required;
      save(JSON.stringify({...schema, type:'object'}, null, 2));
      setMessage(remove ? "Field removed" : "Field saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };
  return <details><summary>{xsd ? "Edit inline XSD elements" : "Edit inline JSON Schema fields"}</summary><div className="transform-policy-grid">
    <label>Field path<input value={path} onChange={event => setPath(event.target.value)} placeholder="order.items.price"/></label>
    <label>Field type<select value={type} onChange={event => setType(event.target.value)}>{['string','integer','number','boolean','object','null'].map(kind => <option key={kind}>{kind}</option>)}</select></label>
    <label><input type="checkbox" checked={required} onChange={event => setRequired(event.target.checked)}/> Required</label>
    <label><input type="checkbox" checked={repeating} onChange={event => setRepeating(event.target.checked)}/> Repeating</label>
    {xsd && <label>Nillable element<select value={nilPolicy} onChange={event => setNilPolicy(event.target.value)}>
      <option value="keep">Keep existing setting</option><option value="allow">Allow xsi:nil</option><option value="disallow">Disallow xsi:nil</option>
    </select></label>}
    <button type="button" onClick={() => update(false)}>Add or update field</button><button type="button" onClick={() => update(true)}>Remove field</button>
    <span role="status">{message}</span>
  </div></details>;
}

function TransformSchemaEditor({ config, schemas, setConfig }: any) {
  const choose = (id: string) => {
    if (id === "inline") {
      setConfig({ targetSchemaId: "", targetSchemaText: config.targetSchemaText || "{\n  \"type\": \"object\",\n  \"properties\": {}\n}" });
      return;
    }
    const schema = schemas.find((item: any) => item.id === id);
    if (schema) setConfig({ targetSchemaId: schema.id, targetSchema: {}, targetSchemaText: selectXsdStructure(schema.content) });
  };
  const id = config.targetSchemaId || "inline", text = id === "inline" ? config.targetSchemaText || JSON.stringify(config.targetSchema || {}, null, 2) : "";
  return <div className="transform-schema-editor"><div className="transform-schema-heading"><Braces/><span><b>TARGET TRANSFORMATION CONTRACT</b></span></div><div className="transform-schema-columns single"><section><header><span><b>Target schema</b></span><select aria-label="Target schema" value={id} onChange={(event) => choose(event.target.value)}><option value="inline">Inline schema…</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></header><XsdStructurePicker label="Target structure" text={schemas.find((schema:any)=>schema.id===config.targetSchemaId)?.content ? selectedSchemaText(schemas.find((schema:any)=>schema.id===config.targetSchemaId).content,config.targetSchemaText) : text} onChange={targetSchemaText=>setConfig({targetSchemaText})}/>{id === "inline" && <><InlineMapperFields text={text} save={targetSchemaText => setConfig({targetSchemaId:"", targetSchemaText})}/><details><summary>Edit inline schema</summary><textarea aria-label="Target inline schema" value={text} onChange={(event) => setConfig({ targetSchemaId: "", targetSchemaText: event.target.value })} placeholder="Paste target JSON Schema or XSD here…" spellCheck={false}/></details><SchemaHierarchyPreview text={text}/></>}</section></div></div>;
}

const mapperSourceTypes = ["string", "int", "integer", "long", "short", "byte", "number", "decimal", "double", "float", "boolean", "date", "datetime", "time"];

function MapperSourceTypes({ value, onChange }: {value: unknown; onChange: (value: any) => void}) {
  const [path, setPath] = useState("");
  const [type, setType] = useState("string");
  let entries: Record<string, string> = {};
  let valid = true;
  try {
    const overrides = typeof value === "string" ? JSON.parse(value || "{}") : value || {};
    valid = typeof overrides === "object" && !Array.isArray(overrides) && overrides !== null;
    if (valid) entries = overrides;
  } catch { valid = false; }
  const source = path.trim().replace(/^\$\{(.+)\}$/, "$1");
  return <details><summary>Source type overrides</summary><div className="transform-policy-grid">
    <label>Source path<input value={path} placeholder="input.order.amount" onChange={event => setPath(event.target.value)}/></label>
    <label>Scalar source type<select value={type} onChange={event => setType(event.target.value)}>
      {mapperSourceTypes.map(item => <option key={item}>{item}</option>)}
    </select></label>
    <button type="button" disabled={!valid || !/^[\w@#-]+(?:\[\d+\]|\.[\w@#-]+)*$/.test(source)}
      onClick={() => onChange({...entries, [source]:type})}>Add or update source type</button>
    <button type="button" disabled={!valid || !Object.prototype.hasOwnProperty.call(entries, source)} onClick={() => {
      const next = {...entries}; delete next[source]; onChange(next);
    }}>Remove source type</button>
    {Object.entries(entries).map(([key, item]) => <button type="button" key={key} onClick={() => {setPath(key); setType(item);}}>{key} → {String(item)}</button>)}
    <label>Source type overrides JSON<textarea value={typeof value === "string" ? value : JSON.stringify(value || {}, null, 2)}
      onChange={event => onChange(event.target.value)} spellCheck={false}/></label>
  </div></details>;
}

function TransformPoliciesEditor({ config, setConfig }: any) {
  const change = (key: string, value: any) => setConfig({ [key]: value });
  return <section className="transform-policies">
    <header><WandSparkles/><span><b>INTEGRATION MAPPING POLICIES</b></span></header>
    <div className="transform-policy-grid">
      <label>XPath version<select value={config.xpathVersion || "1.0"} onChange={(event) => change("xpathVersion", event.target.value)}><option>1.0</option><option>2.0</option></select></label>
      <label>Null and missing values<select value={config.nullPolicy || "omit"} onChange={(event) => change("nullPolicy", event.target.value)}><option value="omit">Omit target field</option><option value="preserve">Preserve null / xsi:nil</option><option value="empty-string">Emit empty string</option><option value="default">Use configured default</option></select></label>
      <label>Type coercion<select value={config.typeCoercion || "safe"} onChange={(event) => change("typeCoercion", event.target.value)}><option value="strict">Strict schema types</option><option value="safe">Safe automatic coercion</option><option value="off">No coercion</option></select></label>
      <label>Mapping error behavior<select value={config.onMappingError || "fail"} onChange={(event) => change("onMappingError", event.target.value)}><option value="fail">Fail activity</option><option value="skip-field">Skip failed field</option><option value="use-null">Map null and continue</option></select></label>
      <label>Maximum output size (KB)<input type="number" min="0" step="1" value={config.maxOutputSizeKb || 0} onChange={(event) => change("maxOutputSizeKb", Math.max(0, Number(event.target.value) || 0))}/></label>
      {config.nullPolicy === "default" && <label>Default null value<input value={config.defaultValue ?? ""} onChange={(event) => change("defaultValue", event.target.value)} placeholder="Schema-compatible fallback"/></label>}
      <label className="policy-switch"><input type="checkbox" checked={config.validateOutput !== false} onChange={(event) => change("validateOutput", event.target.checked)}/><span><b>Validate target output</b></span></label>
      <label className="policy-switch"><input type="checkbox" checked={config.trimStrings === true} onChange={(event) => change("trimStrings", event.target.checked)}/><span><b>Trim mapped strings</b></span></label>
      <label className="policy-switch"><input type="checkbox" checked={config.removeEmptyStructures === true} onChange={(event) => change("removeEmptyStructures", event.target.checked)}/><span><b>Remove empty structures</b></span></label>
      <label className="policy-switch"><input type="checkbox" checked={config.copyNil !== false} onChange={(event) => change("copyNil", event.target.checked)}/><span><b>Copy nil semantics</b></span></label>
    </div>
    <details>
      <summary>XML expressions and runtime binding</summary>
      <div className="transform-policy-grid">
        <label>XML source<input value={config.xmlSource || ""} placeholder="Defaults to previous activity output" onChange={event => change("xmlSource", event.target.value)}/></label>
        <label>XPath namespaces<textarea value={typeof config.xmlNamespaces === "object" && config.xmlNamespaces ? JSON.stringify(config.xmlNamespaces, null, 2) : config.xmlNamespaces || ""} placeholder={'{"ord":"urn:orders"}'} onChange={event => change("xmlNamespaces", event.target.value)} spellCheck={false}/></label>
        <label>XPath variables<textarea value={typeof config.xmlVariables === "object" && config.xmlVariables ? JSON.stringify(config.xmlVariables, null, 2) : config.xmlVariables || ""} placeholder={'{"minimum":"${input.minimum}"}'} onChange={event => change("xmlVariables", event.target.value)} spellCheck={false}/></label>
        <MapperSourceTypes value={config.sourceTypeOverrides} onChange={value => change("sourceTypeOverrides", value)}/>
        <label>Import XSLT binding<input type="file" accept=".xsl,.xslt" onChange={async event => {
          const file = event.target.files?.[0];
          if (file) setConfig({xmlStylesheet: await file.text(), generatedXmlBinding:false});
        }}/></label>
        <label>Runtime XSLT 1.0 or 2.0 binding<textarea value={config.xmlStylesheet || ""} onChange={event => setConfig({xmlStylesheet:event.target.value, generatedXmlBinding:false})} spellCheck={false}/></label>
      </div>
      <p>{config.generatedXmlBinding ? "Runtime XSLT is generated from the current visual rules. Editing the stylesheet here switches to a manual binding." : "An XSLT binding executes the stylesheet and produces XML. Clear the binding to execute the visual rules."}</p>
    </details>
  </section>;
}

export function AIMappingAssistance({ config, setConfig, scopeOptions }: any) {
  const change = (key: string, value: any) => setConfig({ [key]: value });
  return <div className="ai-policy-panel">
    <header><Sparkles/><span><b>AI MAPPING ASSISTANCE</b></span></header>
    <div>
      <label>Minimum confidence<input type="range" min="40" max="100" value={config.threshold ?? 70} onChange={event => change("threshold", Number(event.target.value))}/><b aria-hidden="true">{config.threshold ?? 70}%</b></label>
      <label>Matching strategy<select value={config.aiStrategy || "balanced"} onChange={event => setConfig({ aiStrategy: event.target.value, threshold: event.target.value === "exact" ? 90 : 70 })}>
        <option value="balanced">Similar names, types, and hierarchy</option><option value="exact">Exact names</option>
        <option value="strict">Strict schema and type match</option><option value="semantic">Semantic business-name match</option>
      </select></label>
      {scopeOptions && (["source", "target"] as const).map(side => {
        const label = side === "source" ? "Source" : "Target", paths: string[] = scopeOptions[side];
        const scope = paths.includes(config[side + "MatchScope"]) ? config[side + "MatchScope"] : "";
        return <React.Fragment key={side}>
          <label>{label} branch<select value={scope} onChange={event => change(side + "MatchScope", event.target.value)}>
            <option value="">Entire schema</option>{paths.map(path => <option key={path}>{path}</option>)}
          </select></label>
          <label>{label} matching level<select disabled={!scope} value={config[side + "MatchLevel"] ?? 4} onChange={event => change(side + "MatchLevel", Number(event.target.value))}>
            {Array.from({length:10}, (_, index) => <option key={index}>{index + 1}</option>)}
          </select></label>
        </React.Fragment>;
      })}
      <label className="policy-switch"><input type="checkbox" checked={config.requireAiReview !== false} onChange={event => change("requireAiReview", event.target.checked)}/><span><b>Require approval</b></span></label>
      <label className="policy-switch"><input type="checkbox" checked={config.autoMapRepeating !== false} onChange={event => change("autoMapRepeating", event.target.checked)}/><span><b>Infer repeating structures</b></span></label>
    </div>
  </div>;
}

function ActivityNameField({node,task,update}: any) {
  const [draft,setDraft] = useState(node.name);
  useEffect(() => setDraft(node.name), [node.name]);
  const candidate = activityReferenceName(draft);
  const conflict = (task.activities || []).some((item:any) => item.id !== node.id &&
    [activityReferenceName(item.name),item.id].some(name => name.toLowerCase() === candidate.toLowerCase()));
  const error = !draft.trim() ? "Enter an activity name." : conflict ? "An activity with this name already exists in this task." : "";
  const commit = () => {
    if (error) return;
    setDraft(candidate);
    if (candidate !== node.name) update({name:candidate});
  };
  return <label>Display name<b>*</b><input value={draft} aria-invalid={!!error}
    onChange={event => setDraft(event.target.value)} onBlur={commit}
    onKeyDown={event => { if (event.key === "Enter") event.currentTarget.blur(); if (event.key === "Escape") setDraft(node.name); }}/>
    {error && <small className="endpoint-setup-error" role="alert">{error}</small>}</label>;
}

function TaskBoundarySchemaEditor({ node, config, schemas, setConfig }: any) {
  const choose = (id: string) => {
    if (!id) { setConfig({ interfaceSchemaId: "", interfaceSchemaText: "" }); return; }
    if (id === "inline") {
      setConfig({ interfaceSchemaId: "", interfaceSchemaText: config.interfaceSchemaText || "{\n  \"type\": \"object\",\n  \"properties\": {}\n}" });
      return;
    }
    const schema = schemas.find((item: any) => item.id === id);
    if (schema) setConfig({ interfaceSchemaId: schema.id, interfaceSchemaText: selectXsdStructure(schema.content) });
  };
  const selected = config.interfaceSchemaId || (config.interfaceSchemaText ? "inline" : ""), start = node.type === "start";
  return <div className="transform-schema-editor task-interface-editor"><div className="transform-schema-heading"><Braces/><span><b>{start ? "TASK INPUT INTERFACE" : "TASK RETURN INTERFACE"}</b></span></div><div className="transform-schema-columns single"><section><header><span><b>{start ? "Input schema" : "Output schema"}</b></span><select aria-label={start ? "Task input schema" : "Task output schema"} value={selected} onChange={(event) => choose(event.target.value)}><option value="">Generic object</option><option value="inline">Inline schema…</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></header><XsdStructurePicker label={start ? "Task input structure" : "Task output structure"} text={schemas.find((schema:any)=>schema.id===selected)?.content ? selectedSchemaText(schemas.find((schema:any)=>schema.id===selected).content,config.interfaceSchemaText) : config.interfaceSchemaText || ""} onChange={interfaceSchemaText=>setConfig({interfaceSchemaText})}/>{selected === "inline" && <><details><summary>Edit inline schema</summary><textarea aria-label={start ? "Task input inline schema" : "Task output inline schema"} value={config.interfaceSchemaText || ""} onChange={(event) => setConfig({ interfaceSchemaId: "", interfaceSchemaText: event.target.value })} placeholder="Paste JSON Schema or XSD here…" spellCheck={false}/></details><SchemaHierarchyPreview text={config.interfaceSchemaText || ""}/></>}</section></div></div>;
}

function DataContractSchemaEditor({ node, config, schemas, direction, setConfig }: any) {
  const selected = config.schemaId || (config.schemaText ? "inline" : "");
  const projectSchema = activitySchemaAsset(node, schemas);
  const text = activitySchemaText(node,schemas);
  const format = node.type === "flat" ? "data record" : node.type.toUpperCase();
  const choose = (id: string) => {
    if (!id) { setConfig({ schemaId: "", schemaText: "" }); return; }
    if (id === "inline") {
      setConfig({ schemaId: "", schemaText: config.schemaText || "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<xs:schema xmlns:xs=\"http://www.w3.org/2001/XMLSchema\">\n  <xs:element name=\"root\" type=\"xs:string\"/>\n</xs:schema>" });
      return;
    }
    const asset=schemas.find((schema:any)=>schema.id===id);
    setConfig({ schemaId: id, schemaText: selectXsdStructure(asset?.content || "") });
  };
  return <div className="transform-schema-editor data-contract-editor"><div className="transform-schema-heading"><Braces/><span><b>{direction === "input" ? "INPUT EDITOR" : "OUTPUT EDITOR"} · {format} CONTRACT</b></span></div><div className="transform-schema-columns single"><section><header><span><b>Structure schema</b></span><select aria-label={`${direction} structure schema`} value={selected} onChange={(event) => choose(event.target.value)}><option value="">{!selected && projectSchema ? `From shared Data Format: ${projectSchema.name}` : "Select schema…"}</option><option value="inline">Inline schema…</option>{schemas.filter((schema:any) => !sharedDataFormat(schema.id, [schema])).map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></header><XsdStructurePicker label={`${direction} structure`} text={text} onChange={schemaText=>setConfig({schemaText})}/>{selected === "inline" && <details><summary>Edit inline schema</summary><textarea aria-label={`Inline ${direction} schema`} value={config.schemaText || ""} onChange={(event) => setConfig({ schemaId: "", schemaText: event.target.value })} placeholder="Paste an inline XSD or JSON Schema here…" spellCheck={false}/></details>}<SchemaHierarchyPreview text={text} schemaPath={projectSchema?.source_path || projectSchema?.name} schemaDocuments={schemas}/></section></div></div>;
}

function SchemaHierarchyPreview({ text, schemaPath, schemaDocuments }: { text: string; schemaPath?: string; schemaDocuments?: any[] }) {
  const fields = useMemo(() => transformSchemaFields({ targetSchemaText: text, schemaPath, schemaDocuments }), [text,schemaPath,schemaDocuments]);
  const branches = useMemo(() => new Set(fields.filter(field => field.depth > 0).map(field => field.path.slice(0,field.path.lastIndexOf(".")))), [fields]);
  const tree = useTreeCollapse();
  return <div className="schema-hierarchy-preview"><header><Braces/><span><b>Tree preview</b><small>{fields.length} schema elements</small></span></header>{fields.map((field) => { if (!tree.visible(field.path)) return null; const group = branches.has(field.path); return <div className={group ? "tree-branch-row" : ""} key={field.path} style={{ "--schema-depth": field.depth } as React.CSSProperties}>{group ? <TreeToggle path={field.path} label={field.name} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <i className="tree-elbow"/>}<span><b>{field.name}</b><small>{field.type}</small></span></div>; })}{!fields.length && <p>No schema elements are available yet.</p>}</div>;
}

function JdbcDesigner({ config, resource, properties, setConfig }: any) {
  const [metadata, setMetadata] = useState<any>(null), [preview, setPreview] = useState<any>(null), [status, setStatus] = useState(""), [busy, setBusy] = useState(false);
  const propertyValues = Object.fromEntries((properties || []).map((item: any) => [item.key, item.value]));
  const runtimeResource = resource ? { ...resource, config: Object.fromEntries(Object.entries(resource.config || {}).map(([key, value]) => { const match = typeof value === "string" ? value.match(/^\$\{properties\.([^}]+)\}$/) : null; return [key, match ? propertyValues[match[1]] : value]; })) } : null;
  const parameterTypes = ["string", "integer", "number", "decimal", "boolean", "date", "time", "timestamp", "binary", "json",
    ...(["postgresql", "postgres"].includes(String(runtimeResource?.config?.driver).toLowerCase()) ? ["jsonb"] : [])];
  const samples: Record<string, string> = {
    query: "SELECT id, customer_name, status\nFROM orders\nWHERE status = :status AND created_at >= :fromDate",
    insert: "INSERT INTO orders (id, customer_name, status)\nVALUES (:orderId, :customerName, :status)",
    update: "UPDATE orders\nSET status = :status\nWHERE id = :orderId",
    delete: "DELETE FROM orders\nWHERE id = :orderId",
    dynamic: "SELECT * FROM orders WHERE customer_id = :customerId",
  };
  const configuredParameters = Array.isArray(config.preparedParameters) ? config.preparedParameters : [];
  const sqlTokens = /--[^\r\n]*|\/\*[\s\S]*?\*\/|\$(?<tag>[A-Za-z_][A-Za-z0-9_]*|)\$[\s\S]*?\$\k<tag>\$|\bq'\[[\s\S]*?\]'|\bq'\{[\s\S]*?\}'|\bq'\([\s\S]*?\)'|\bq'<[\s\S]*?>'|\bq'(?<delimiter>[^\s'])[\s\S]*?\k<delimiter>'|'(?:''|\\[\s\S]|[^'])*'|"(?:""|[^"])*"|`(?:``|[^`])*`|(?<!:):(?<name>[A-Za-z_][A-Za-z0-9_]*)|(?<position>(?<!\?)\?(?![|&?]))/gi;
  const updateSql = (sql: string) => {
    const tokens = [...sql.matchAll(sqlTokens)];
    const named = tokens.flatMap(token => token.groups?.name ? [token.groups.name] : []);
    const count = tokens.filter(token => token.groups?.position).length;
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
  const tableSelect = (table: {schema?: string; name: string}) => {
    const quote = ["mysql", "mariadb"].includes(String(runtimeResource?.config?.driver).toLowerCase()) ? "`" : '"';
    const identifier = (value: string) => quote + value.split(quote).join(quote + quote) + quote;
    return "SELECT * FROM " + (table.schema ? identifier(table.schema) + "." : "") + identifier(table.name);
  };
  const run = async () => { const output = await request("/api/jdbc/test-query", { resource: runtimeResource, operation: config.operation, config: { ...config, parameters: Object.fromEntries((config.preparedParameterNames || []).map((name: string) => [name, null])) } }); if (output) { setPreview(output); const columns = output.columns || Object.keys(output.rows?.[0] || {}).map((name) => ({ name, dataType: typeof output.rows[0][name] })); setConfig({ outputColumns: columns }); setStatus(`${output.rowCount ?? output.noOfUpdates ?? 0} rows returned/affected. Output schema refreshed.`); } };
  return <section className="jdbc-designer"><header><span><Database/><b>JDBC SQL DESIGNER</b></span><span><button type="button" onClick={fetchMetadata} disabled={busy || !resource}><RefreshCw/> Fetch metadata</button><button type="button" onClick={run} disabled={busy || !resource || (!String(config.sql || "").trim() && config.operation !== "call")}><FlaskConical/> Run &amp; fetch</button></span></header>{config.operation !== "call" && <><div className="jdbc-editor-toolbar"><span><b>SQL statement</b></span><button type="button" onClick={() => updateSql(samples[config.operation] || samples.query)}>Insert sample {config.operation || "query"}</button></div><div className="jdbc-code-editor"><span aria-hidden="true">SQL</span><textarea aria-label="JDBC SQL statement" value={config.sql || ""} onChange={(event) => updateSql(event.target.value)} placeholder={samples[config.operation] || samples.query} spellCheck={false}/></div></>} {!!configuredParameters.length && <div className="jdbc-parameters"><header><b>Derived input parameters</b></header>{configuredParameters.map((parameter: any, index: number) => <label key={`${parameter.name}-${index}`}><code>{index + 1}</code><span><b>:{parameter.name}</b><small>parameters.{parameter.name}</small></span><select aria-label={`Datatype for ${parameter.name}`} value={parameter.type || "string"} onChange={(event) => setParameterType(parameter.name, event.target.value)}>{parameterTypes.map((type) => <option key={type}>{type}</option>)}</select></label>)}</div>} {metadata && <div className="jdbc-schema-browser">{metadata.tables?.map((table: any) => <button type="button" key={`${table.schema}.${table.name}`} onClick={["query", "dynamic"].includes(config.operation) ? () => updateSql(tableSelect(table)) : undefined}><span><b>{table.name}</b><small>{table.schema} · {table.type}</small></span><code>{table.columns?.length || 0} columns</code></button>)}</div>} {preview && <pre>{JSON.stringify(preview, null, 2)}</pre>} {status && <p>{status}</p>}</section>;
}

function FieldEditor({ field, value, set, resources, tasks, properties = [], selectedResourceId, navigateTask, createConnection, httpRole }: any) {
  const change = (v: any) => set(field.key, v);
  const propertyPanel = useRef<HTMLDetailsElement>(null);
  const [propertySearch, setPropertySearch] = useState("");
  const mappedKey = typeof value === "string" ? value.match(/^\$\{properties\.([^}]+)\}$/)?.[1] : "";
  const mappedProperty = mappedKey ? properties.find((property: any) => property.key === mappedKey) : null;
  const compatibleProperties = properties.filter((property: any) => {
    if (field.type === "number") return ["integer", "long", "number"].includes(property.data_type);
    return ["string", "dateTime", "integer", "long", "number"].includes(property.data_type);
  }).filter((property: any) => !propertySearch || property.key.toLowerCase().includes(propertySearch.toLowerCase()));
  return (
    <label
      className={field.type === "textarea" ? "wide" : ""}
    >
      {field.label}
      {field.required && <b>*</b>}
      {field.type === "textarea" ? (
        <textarea
          value={value || ""}
          readOnly={field.readOnly}
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
        <SharedConnectionSelect
          value={value || ""}
          resources={resources}
          kinds={field.resourceTypes ?? [field.resourceType === "http" ? httpRole : field.resourceType]}
          onChange={(id, resource) => set(field.key, id, resource)}
          onCreate={createConnection}
        />
      ) : field.type === "artifact" ? (
        <span className="artifact-picker"><input value={value || ""} placeholder={`Select a ${field.artifactType} artifact…`} onChange={(e) => change(e.target.value)}/><button type="button" onClick={async () => { const selected = await window.minaDesktop?.selectCodeArtifact(field.artifactType || "java"); if (selected?.path) change(selected.path); }}>Browse…</button></span>
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
        <span className="task-reference-picker"><select value={value || ""} onChange={(e) => change(e.target.value)} onDoubleClick={() => value && navigateTask?.(value)}>
            <option value="">Select Sub Task…</option>
            {tasks.filter((t: any) => t.kind === "subtask").map((t: any) => <option value={t.id} key={t.id}>{`${t.package_path || "Default"}/${t.name}`}</option>)}
          </select>{value && <button type="button" title="Open selected Sub Task" aria-label="Open selected Sub Task" onClick={() => navigateTask?.(value)}><ExternalLink/></button>}</span>
      ) : (
        field.propertyBrowse ? <span className="configuration-property-field">
          <input
            type={field.type === "number" && !mappedKey ? "number" : "text"}
            value={value ?? ""}
            readOnly={field.readOnly}
            onChange={(e) => change(field.type === "number" && !e.target.value.startsWith("${") ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)}
          />
          <details ref={propertyPanel} className="configuration-property-picker" onToggle={(event) => { const panel = event.currentTarget; if (panel.open) { setPropertySearch(""); window.setTimeout(() => panel.querySelector<HTMLInputElement>("input")?.focus(), 0); } }}>
            <summary aria-label={`Browse environment properties for ${field.label}`} title={`Browse environment properties for ${field.label}`}><DataNodeIcon/></summary>
            <div><header><DataNodeIcon/><span><b>ENVIRONMENT PROPERTY</b><small>Map {field.label}</small></span></header><input aria-label={`Search properties for ${field.label}`} value={propertySearch} onChange={(event) => setPropertySearch(event.target.value)} placeholder="Search active environment…"/>
              <section>{compatibleProperties.map((property: any) => <button type="button" key={property.key} onClick={() => { change(`\${properties.${property.key}}`); if (propertyPanel.current) propertyPanel.current.open = false; }}><DataNodeIcon/><span><b>{property.key}</b><small>{property.data_type} · {String(property.value ?? "") || "empty"}</small></span></button>)}{!compatibleProperties.length && <p>No compatible properties match.</p>}</section>
            </div>
          </details>
          {mappedProperty && <small className="configuration-property-resolution">{mappedProperty.key} = {String(mappedProperty.value ?? "") || "empty"}</small>}
        </span> : <input
        type={field.type === "number" ? "number" : "text"}
        value={value ?? ""}
        readOnly={field.readOnly}
        onChange={(e) => change(field.type === "number" ? Number(e.target.value) : e.target.value)}
        />
      )}{" "}

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
type ActivitySource = { activity: any; distance: number; fields: DataField[]; scope?: string };
function useActivityMappingSources(node:any, task:any, tasks:any[] = [], schemas:any[] = [], resources:any[] = []) {
  const cache = useRef<{keys:any[]; sources:ActivitySource[]; variables:any[]} | null>(null);
  const keys = [node.id, task.id, task.transitions, task.groups, task.input_schema, task.output_schema, schemas, resources,
    ...tasks.filter(item => item.id !== task.id), ...(task.activities || []).filter((item:any) => item.id !== node.id)];
  if (!cache.current || cache.current.keys.length !== keys.length || keys.some((key,index) => key !== cache.current!.keys[index])) {
    cache.current = {keys, sources:upstreamActivitySources(node,task,tasks,schemas,resources), variables:activityGroupVariables(node,task,tasks,schemas,resources)};
  }
  return cache.current;
}
export function upstreamActivitySources(node: any, task: any, tasks: any[] = [], schemas: any[] = [], resources: any[] = []): ActivitySource[] {
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
      ? mapperOutputFields(activity.config || {}, schemas).map((field) => ({ key: field.path, label: field.name, type: field.type, repeating: field.repeating, minOccurs: field.minOccurs, maxOccurs: field.maxOccurs }))
      : resolvedActivityContract(activity, task, tasks, schemas, resources).output;
    return { activity, distance: pathDistance, fields };
  }).filter(Boolean).sort((a: any, b: any) => a.distance - b.distance) as ActivitySource[];
}

function activityGroupVariables(node: any, task: any, tasks: any[] = [], schemas: any[] = [], resources: any[] = []) {
  const groups = task?.groups || [], byId = new Map<string, any>(groups.map((group: any) => [group.id, group])), direct = groups.find((group: any) => group.member_activity_ids?.includes(node.id));
  const active: any[] = [];
  const visited = new Set<string>();
  let current: any = direct;
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    active.unshift(current);
    current = current.parent_group_id ? byId.get(current.parent_group_id) : null;
  }
  const variables: any[] = [];
  const add = (variable: any) => { if (!variables.some((item) => item.name === variable.name)) variables.push(variable); };
  active.forEach((group) => {
    const config = group.config || {}, looping = ["iterate", "for_each", "while", "repeat", "repeat_on_error"].includes(group.type);
    if (looping) add({ name: config.indexVariable || "index", label: `${group.name} · iteration index`, type: "integer", scope: group.name });
    if (["iterate", "for_each"].includes(group.type)) {
      const name = config.currentElementName || config.itemVariable || "currentElement", source = String(config.source || config.collection || ""), match = source.match(/^\$\{activities\.([^.}]+)\.output(?:\.([^}]+))?\}$/) || source.match(/^\$\{([^.}]+)(?:\.([^}]+))?\}$/);
      let fields: any[] = [];
      if (match) {
        const sourceActivity = (task.activities || []).find((item: any) => item.id === match[1] || activityReferenceName(item.name) === match[1]), root = match[2] || "";
        if (sourceActivity) fields = resolvedActivityContract(sourceActivity, task, tasks, schemas, resources).output.filter((field: any) => !root || field.key.startsWith(`${root}.`)).map((field: any) => ({ ...field, key: root ? field.key.slice(root.length + 1) : field.key })).filter((field: any) => field.key);
      }
      add({ name, label: `${group.name} · current element`, type: "object", scope: group.name, fields });
      if (name !== "currentElement") add({ name: "currentElement", label: `${group.name} · current element alias`, type: "object", scope: group.name, fields });
      if (config.accumulateOutput) add({ name: config.accumulatorVariable || `${group.id}Results`, label: `${group.name} · accumulated output`, type: "array", scope: group.name });
    }
    if (group.type === "repeat_on_error") add({ name: "error", label: `${group.name} · current error`, type: "object", scope: group.name });
  });
  return variables;
}
export function DataSourcePane({ properties, sources = [], customFunctions = [], updateCustomFunctions, runtimeVariables = [], coercions = {} }: any) {
  customFunctions = customFunctions.length ? customFunctions : properties?.customFunctions || [];
  updateCustomFunctions = updateCustomFunctions || properties?.updateCustomFunctions;
  const [tab, setTab] = useState<"data" | "functions" | "constants">("data"), [search, setSearch] = useState(""), [selectedSource, setSelectedSource] = useState("");
  const tree = useTreeCollapse();
  const item = (label: string, expression: string, type = "object", showExpression = true, depth = 0, group = false, enabled = true, treePath = expression, repeating = /\[\]|array/i.test(type)) => {
    const branch = group ? <TreeToggle path={treePath} label={label} collapsed={tree.collapsed.has(treePath)} toggle={tree.toggle}/> : <i className="tree-elbow"/>;
    return enabled ? <button className={`source-tree-node ${group ? "tree-group-node" : ""} ${selectedSource === expression ? "source-selected" : ""}`} aria-pressed={selectedSource === expression} style={{ "--tree-depth": depth } as React.CSSProperties} data-expression={expression} key={`${label}-${expression}`} draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData("expression", expression); event.dataTransfer.setData("sourceType", type); event.dataTransfer.setData("sourceLabel", label); event.dataTransfer.setData("sourceComplex", String(group || /^(?:object|complex)(?:\[\])?$/.test(type.toLowerCase()))); event.dataTransfer.setData("sourceRepeating", String(repeating)); setSelectedSource(expression); }} onClick={() => setSelectedSource(expression)} title={`Drag ${label} onto the desired target field`}>{branch}<Braces/><span><b>{label}</b>{showExpression && <small>{expression}</small>}</span><code>{type}</code></button> : <div className="source-tree-node tree-group-node" style={{ "--tree-depth": depth } as React.CSSProperties} key={`${label}-${depth}`}>{branch}<Braces/><span><b>{label}</b></span><code>{type}</code></div>;
  };
  const functionItems = mapperFunctionCatalog.filter((definition) => !search || `${definition.name} ${definition.signature} ${definition.description} ${definition.category}`.toLowerCase().includes(search.toLowerCase()));
  const functionItem = (definition: (typeof mapperFunctionCatalog)[number]) => {
    const expression = functionExpression(definition, selectedSource || "${last}");
    return <button className="source-tree-node mapper-function-source" key={definition.name} draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData("expression", expression); event.dataTransfer.setData("sourceType", "function"); }} onClick={() => setSelectedSource(expression)} title={definition.signature}><DataNodeIcon/><span><b>{definition.name}</b><small>{definition.signature}</small></span><code>fx</code></button>;
  };
  const constantItem = (label: string, value: any, type: string) => <button className="source-tree-node constant-source" key={label} draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData("expression", `__mina_constant__:${JSON.stringify(value)}`); event.dataTransfer.setData("sourceType", type); }} title={`Drag ${label} onto a simple target field`}><Braces/><span><b>{label}</b><small>{JSON.stringify(value)}</small></span><code>{type}</code></button>;
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
  const renderData = () => <div className="source-list">
    <h4>EXECUTION PATH OUTPUTS · {visibleSources.length}</h4>
    {!query && item("Initial task input", "${input}", "object", false)}
    {Object.entries(coercions).filter(([name]) => !query || name.toLowerCase().includes(query)).map(([name, value]: [string, any]) => {
      const fields = sourceCoercionFields(value);
      const reference = "coerced." + name;
      const occurrence = value.cardinality || "?";
      const type = occurrence === "*" || occurrence === "+" ? "object[]" : "object";
      return <details className="activity-source" key={reference} open>
        <summary><Braces/><span><b>{name} ({occurrence})</b><small>{value.path}{value.type ? ` · ${value.type}` : ""}</small></span></summary>
        {item(name, "${" + reference + "}", type, false)}
        {fields.filter(field => tree.visible(reference + "." + field.path)).map(field => item(field.name,
          "${" + reference + "." + field.path + "}", field.type, false, field.depth + 1,
          fields.some(child => child.path.startsWith(field.path + ".")), true, reference + "." + field.path, field.repeating))}
      </details>;
    })}
    {visibleSources.map((source: ActivitySource) => {
      const sourceRows = dataTreeRows(source.fields), reference = activityReferenceName(source.activity.name);
      return <details className="activity-source" key={source.activity.id} open={source.distance === 1 || !!source.scope || !!query}>
        <summary><span className="tree-disclosure"/><Braces/><span><b>{source.activity.name}</b><small>{source.scope || (source.distance === 1 ? "Immediate predecessor" : `${source.distance} steps upstream`)} · {source.activity.type}</small></span><code>{source.fields.length}</code></summary>
        {item("Output", `\${${reference}}`, "object", false)}
        {sourceRows.map((field) => {
          const path = `${source.activity.id}.${field.path}`;
          return !query && !tree.visible(path) ? null : item(field.label, `\${${reference}.${field.path}}`, field.type, false, field.depth + 1, field.group, true, path, field.repeating);
        })}
      </details>;
    })}
    {!visibleSources.length && <p className="source-empty">No connected upstream activity matches this search.</p>}
    {runtimeVariables.length > 0 && <><h4>GROUP VARIABLES</h4>{runtimeVariables.filter((variable: any) => !query || `${variable.name} ${variable.label}`.toLowerCase().includes(query)).map((variable: any) => variable.fields?.length ? <details className="activity-source group-variable-source" key={variable.name} open><summary><span className="tree-disclosure"/><Braces/><span><b>{variable.label || variable.name}</b><small>{variable.scope || "Current group"} · ${variable.name}</small></span><code>{variable.fields.length}</code></summary>{item("Current element", `\${vars.${variable.name}}`, variable.type || "object", false)}{dataTreeRows(variable.fields).map((field) => item(field.label, `\${vars.${variable.name}.${field.path}}`, field.type, false, field.depth + 1, field.group, true, `${variable.name}.${field.path}`, field.repeating))}</details> : item(variable.label || variable.name, `\${vars.${variable.name}}`, variable.type || "any", true))}</>}
    <h4>PROCESS CONTEXT</h4>{item("Task ID", "${context.taskId}", "string", false)}{item("Environment", "${context.environment}", "string", false)}{item("Current activity ID", "${context.activityId}", "string", false)}
    <h4>GLOBAL VARIABLES</h4>{dataTreeRows(propertyFields).map((property) => { const path = `properties.${property.path}`; return !query && !tree.visible(path) ? null : item(property.label, `\${properties.${property.path}}`, property.type, false, property.depth, property.group, property.explicit, path); })}
  </div>;
  return <aside className="source-pane"><div className="source-tabs"><button className={tab === "data" ? "active" : ""} onClick={() => setTab("data")}>Data</button><button className={tab === "functions" ? "active" : ""} onClick={() => setTab("functions")}>Functions</button><button className={tab === "constants" ? "active" : ""} onClick={() => setTab("constants")}>Constants</button></div><input className="source-search" aria-label={`Search ${tab}`} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${tab}…`}/>{tab === "data" ? renderData() : tab === "functions" ? <div className="source-list function-list"><div className="custom-function-heading"><h4>PROJECT FUNCTIONS · {customFunctions.length}</h4><button onClick={createFunction}><Plus/> New</button></div>{customFunctions.filter((fn: any) => fn.name.toLowerCase().includes(query)).map((fn: any) => item(fn.name, `custom:${fn.name}(${fn.parameters.map((name: string) => `$${name}`).join(", ")})`, "custom", false))}<h4>BUILT-IN FUNCTIONS · {functionItems.length}</h4>{mapperFunctionCategories.map((category) => { const definitions = functionItems.filter((item) => item.category === category); return definitions.length ? <details className="function-category" key={category} open={!!query || category === "String"}><summary><span className="tree-disclosure"/><b>{category}</b><code>{definitions.length}</code></summary>{definitions.map(functionItem)}</details> : null; })}</div> : <div className="source-list constants-list"><h4>TYPED CONSTANTS</h4>{constantItem("Empty string", "", "string")}{constantItem("True", true, "boolean")}{constantItem("False", false, "boolean")}{constantItem("Zero", 0, "integer")}{constantItem("Empty object", {}, "object")}{constantItem("Empty array", [], "array")}{constantItem("Null", null, "null")}</div>}</aside>;
}
function describeMapping(expression: any, sources: ActivitySource[]): string {
  if (expression === undefined || expression === null || expression === "") return "Drop a source field or enter a constant";
  if (typeof expression === "object" && expression?.$rule) return `${expression.$rule} › ${describeMapping(expression.source, sources)}`;
  if (typeof expression !== "string") return `Constant › ${JSON.stringify(expression)}`;
  if (expression.startsWith("__mina_constant__:")) return `Constant › ${expression.slice(20)}`;
  if (expression === "${input}") return "Initial task input";
  const activityPath = expression.match(/^\$\{(?:activities\.([^.}]+)\.output|([^.}]+))(?:\.([^}]+))?\}$/);
  if (activityPath) {
    const source = sources.find((item) => item.activity.id === activityPath[1] || activityReferenceName(item.activity.name) === activityPath[2]);
    if (source) {
      const fieldPath = activityPath[3];
      if (!fieldPath) return `${source.activity.name} › Output`;
      const field = source.fields.find((item) => item.key === fieldPath);
      const parts = fieldPath.split(".");
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
  // A leaf object can be assigned from a complete object source. Only
  // complex schema branches with child fields remain structural nodes.
  return type === "complex" || type === "json" || type.includes("array") || type.endsWith("[]") || type.includes("complex[]") || type.includes("object[]");
}
const completionPathCache = new WeakMap<any[], string[]>();
function mappingCompletionPaths(sources: any[] = []): string[] {
  const cached = completionPathCache.get(sources);
  if (cached) return cached;
  const paths = ["input", "last", ...(sources || []).flatMap((source: ActivitySource) => {
    const root = activityReferenceName(source.activity.name);
    const fields = dataTreeRows(source.fields);
    return [root, ...fields.map(field => `${root}.${field.path}`), ...fields.map(field => `activities.${source.activity.id}.output.${field.path}`),
      ...(source.activity.type === "start" ? fields.map(field => `input.${field.path}`) : []),
      ...(source.distance === 1 ? fields.map(field => `last.${field.path}`) : [])];
  })];
  completionPathCache.set(sources, paths);
  return paths;
}
const MemoizedDataSourcePane = React.memo(DataSourcePane);

function MappingBinding(props: any) {
  const callbacks = useRef(props);
  callbacks.current = props;
  const handlers = useMemo(() => ({
    onChange: (value:any) => callbacks.current.onChange(expandLoopExpression(value, callbacks.current.sourceScope, mappingCompletionPaths(callbacks.current.sources))),
    onConstantChange: (value:any) => (callbacks.current.onConstantChange || callbacks.current.onChange)(value),
  }), []);
  return <MemoizedMappingBinding {...props} onChange={handlers.onChange} onConstantChange={props.onConstantChange ? handlers.onConstantChange : undefined}/>;
}

const MemoizedMappingBinding = React.memo(MappingBindingContent);
function MappingBindingContent({ expression, sources, onChange, onConstantChange, fieldType = "string", validationType = fieldType, structural = false, fieldLabel = "Value", multiline = false, sourceScope }: any) {
  const completionPaths = mappingCompletionPaths(sources);
  const hasValue = expression !== undefined && expression !== null && expression !== "";
  const sourceValue = mappingSource(expression);
  const editableExpression = sourceValue && typeof sourceValue === "object" ? JSON.stringify(sourceValue) : relativeLoopExpression(sourceValue, sourceScope);
  const [conditionsCollapsed, setConditionsCollapsed] = useState(false);
  const mappingError = validateMapping(expandLoopExpression(editableExpression, sourceScope, completionPaths), validationType, completionPaths);
  const commitMapping = (raw: string) => {
    if (validateMapping(expandLoopExpression(raw, sourceScope, completionPaths), validationType, completionPaths)) return false;
    const type = String(fieldType).toLowerCase().replace(/^xs[d]?:/, '');
    if (/^[\[{]/.test(raw.trim()) && /array|\[\]|object|json/.test(String(validationType).toLowerCase())) {
      try { (onConstantChange || onChange)(JSON.parse(raw)); } catch { /* Preserve expressions; they resolve at runtime. */ }
    }
    else if (/^(true|false)$/.test(raw.trim()) && type === "boolean") (onConstantChange || onChange)(raw.trim() === "true");
    else if (/^(number|integer|int|long|short|byte|decimal|double|float)$/.test(type) && Number.isFinite(Number(raw)) && raw.trim()) (onConstantChange || onChange)(Number(raw));
    else if (onConstantChange && /^(['"])[\s\S]*\1$/.test(raw)) onConstantChange(raw.slice(1, -1));
    return true;
  };
  const mappingInput = <MappingExpressionInput value={editableExpression} paths={completionPaths} onChange={onChange} onCommit={commitMapping} error={mappingError} multiline={multiline}/>;

  const statement = expression?.$rule || expression?.operator;
  if (['choose', 'when-otherwise', 'if'].includes(statement)) {
    let branches = expression.whens;
    if (statement === 'choose' && !branches?.length) {
      try { branches = JSON.parse(expression.source || '[]'); } catch { branches = []; }
    }
    if (statement !== 'choose') branches = [{ condition: expression.condition || '', source: expression.select ?? expression.source ?? '' }];
    const updateBranch = (index: number, patch: any) => {
      if (statement !== 'choose') { onChange({...expression, ...patch, ...('source' in patch ? {select: undefined} : {})}); return; }
      const whens = branches.map((branch: any, current: number) => current === index ? {...branch, ...patch} : branch);
      onChange({...expression, whens, source: JSON.stringify(whens)});
    };
    const removeBranch = (index: number) => {
      if ((branches || []).length <= 1) return;
      const whens = (branches || []).filter((_: any, current: number) => current !== index);
      onChange({...expression, $rule: 'choose', operator: 'choose', condition: undefined, select: undefined, whens, source: JSON.stringify(whens)});
    };
    const drop = (event: React.DragEvent, change: (value: string) => void) => {
      event.preventDefault(); event.stopPropagation();
      const value = event.dataTransfer.getData('expression');
      if (value) change(value);
    };
    return <div className="field-condition-tree compact-condition-tree" onContextMenu={event => event.stopPropagation()} onDragOver={event => {event.preventDefault(); event.stopPropagation();}} onDrop={event => {event.preventDefault(); event.stopPropagation();}}>
      <div className="field-condition-heading"><button type="button" aria-label={`${conditionsCollapsed ? "Expand" : "Collapse"} field conditions`} aria-expanded={!conditionsCollapsed} onClick={() => setConditionsCollapsed(!conditionsCollapsed)}>{conditionsCollapsed ? "▸" : "▾"}</button><b>{fieldLabel} · {statement === 'if' ? '[If]' : '[Choose]'}</b><button type="button" title="Remove conditions" onClick={() => onChange('')} aria-label="Remove field conditions">×</button></div>
      {!conditionsCollapsed && (branches || []).map((branch: any, index: number) => <details open className="field-condition-branch" key={index}>
        <summary><span>{statement === 'if' ? '[If]' : `[When ${index + 1}]`}{statement !== 'if' && <button type="button" className="remove-when-branch" disabled={(branches || []).length <= 1} title={(branches || []).length <= 1 ? 'At least one When condition is required' : `Delete When ${index + 1}`} aria-label={`Delete When ${index + 1}`} onClick={event => {event.preventDefault(); event.stopPropagation(); removeBranch(index);}} onKeyDown={event => event.stopPropagation()}>×</button>}</span><div onClick={event => event.stopPropagation()} onKeyDown={event => event.stopPropagation()} onDrop={event => drop(event, condition => updateBranch(index, {condition}))}><MappingExpressionInput multiline label={`When ${index + 1} condition`} value={branch.condition} paths={completionPaths} onChange={(condition: string) => updateBranch(index, {condition})}/></div></summary>
        <div className="condition-value-row" onDrop={event => drop(event, source => updateBranch(index, {source}))}><b>{fieldLabel}</b><MappingBinding multiline sourceScope={sourceScope} fieldLabel={fieldLabel} expression={branch.source ?? ''} fieldType={fieldType} validationType={validationType} sources={sources} onChange={(source: any) => updateBranch(index, {source})}/></div>
      </details>)}
      {!conditionsCollapsed && statement !== 'if' && <details open className="field-condition-branch" onDrop={event => drop(event, otherwise => onChange({...expression, otherwise}))}><summary><span>[Otherwise]</span></summary><div className="condition-value-row"><b>{fieldLabel}</b><MappingBinding multiline sourceScope={sourceScope} fieldLabel={fieldLabel} expression={expression.otherwise ?? ''} fieldType={fieldType} validationType={validationType} sources={sources} onChange={(otherwise: any) => onChange({...expression, otherwise})}/></div></details>}
    </div>;
  }

  return <div className={`mapping-binding compact-mapping-binding ${structural || isComplexSchemaType(fieldType) ? "structural-binding" : ""} ${hasValue ? "mapped" : ""} ${mappingError ? "mapping-invalid" : ""}`}>
    {mappingInput}
    {hasValue && <button type="button" title="Clear value" aria-label="Clear mapping value" onClick={(event) => { event.stopPropagation(); onChange(""); }}>×</button>}
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
        const box = container.getBoundingClientRect(), sourceNodes = new Map(Array.from(container.querySelectorAll<HTMLElement>("[data-expression]")).map(item => [item.dataset.expression, item])), targetNodes = new Map(Array.from(container.querySelectorAll<HTMLElement>("[data-target]")).map(item => [item.dataset.target, item]));
        const next: Array<{ key: string; d: string }> = [];
        Object.entries(mappings || {}).forEach(([target, expression]: any) => {
          if (!expression) return;
          const source = sourceNodes.get(expression), destination = targetNodes.get(target);
          if (!source || !destination || source.offsetParent === null || destination.offsetParent === null) return;
          const a = source.getBoundingClientRect(), b = destination.getBoundingClientRect(), x1 = a.right - box.left, y1 = a.top + a.height / 2 - box.top, x2 = b.left - box.left + 8, y2 = b.top + b.height / 2 - box.top, bend = Math.max(35, (x2 - x1) * .42);
          next.push({ key: target, d: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}` });
        });
        setPaths(previous => previous.length === next.length && previous.every((path, index) => path.key === next[index].key && path.d === next[index].d) ? previous : next);
      });
    };
    draw(); const observer = new ResizeObserver(draw); observer.observe(container); container.addEventListener("scroll", draw, true); container.addEventListener("toggle", draw, true); window.addEventListener("resize", draw);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); container.removeEventListener("scroll", draw, true); container.removeEventListener("toggle", draw, true); window.removeEventListener("resize", draw); };
  }, [root, mappings]);
  return <svg className="field-mapping-lines" aria-hidden="true">{paths.map((path) => <g key={path.key}><path className="mapping-line-glow" d={path.d}/><path d={path.d}/></g>)}</svg>;
}

function ExpandedInputMappingDialog({ title, mappingCount, onClose, onApply, children }: { title: string; mappingCount: number; onClose: () => void; onApply: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  return createPortal(<ModalLayer className="modal-backdrop input-mapper-backdrop" role="presentation">
    <div className="input-mapper-dialog" role="dialog" aria-modal="true" aria-label={`${title} input mapper`}>
      <header><div><Pencil/><span><b>{title}</b></span></div><i>{mappingCount} MAPPED</i><button type="button" aria-label="Close input mapper" title="Close" onClick={onClose}><X/></button></header>
      <div className="input-mapper-content">{children}</div>
      <footer><span>Changes remain local until you apply the mappings.</span><button type="button" onClick={onClose}>Cancel</button><button type="button" className="primary" onClick={onApply}><CheckCircle2/> Apply mappings</button></footer>
    </div>
  </ModalLayer>, document.body);
}

function LoopMappingRow({ row, collapsed, toggle, patch, remove, duplicate, sources, onContextMenu, onLoopDrop }: { row: MappingTreeRow; collapsed: boolean; toggle: (key: string) => void; patch: (value: any) => void; remove: () => void; duplicate?: () => void; sources: any[]; onContextMenu?: React.MouseEventHandler<HTMLDivElement>; onLoopDrop?: (event: React.DragEvent) => boolean }) {
  const grouped = (row.rule.operator || row.rule.$rule) === "for-each-group";
  const paths = ["input", "last", "current-group()", ...(sources || []).flatMap((source: ActivitySource) => [activityReferenceName(source.activity.name), ...source.fields.map(field => `${activityReferenceName(source.activity.name)}.${field.key}`)])];
  return <div className={`mapping-loop-row ${row.kind === "grouping" ? "mapping-grouping-row" : ""}`} data-target={row.kind === "loop" ? `${row.key}:source` : undefined} style={{ paddingLeft: 10 + row.depth * 16 }} onContextMenu={event => {event.stopPropagation(); if (row.kind === "loop") onContextMenu?.(event);}} onDragOver={event => {event.preventDefault();event.stopPropagation();}} onDrop={event => {
    event.preventDefault();event.stopPropagation();const value=event.dataTransfer.getData("expression");if(!value)return;
    if(row.kind === "grouping") {
      const source = String(mappingSource(row.rule) || "").replace(/^\$\{|\}$/g, "");
      const path = value.replace(/^\$\{|\}$/g, "");
      patch({groupBy:path.startsWith(`${source}.`) ? path.slice(source.length+1) : path});
    } else if (!onLoopDrop?.(event)) patch({source:value,select:value});
  }}>
    {row.kind === "loop" ? <TreeToggle path={row.key} label={`${row.field.name} loop`} collapsed={collapsed} toggle={toggle}/> : <i className="tree-elbow"/>}
    <span className="mapping-loop-label"><Braces/><b>{row.kind === "grouping" ? "Grouping" : `${row.field.name} - [${grouped ? "For-Each-Group" : "For-Each"}]`}</b></span>
    <MappingExpressionInput label={row.kind === "grouping" ? `${row.field.name} grouping key` : `${row.field.name} loop source`} paths={paths} value={row.kind === "grouping" ? row.rule.groupBy || "" : mappingSource(row.rule)} onChange={(value: string) => patch(row.kind === "grouping" ? { groupBy: value } : { source: value, select: value })}/>
    {row.kind === "loop" && <span className="mapping-loop-actions">{duplicate && <button type="button" aria-label={`Duplicate ${row.field.name} loop`} onClick={duplicate}><Plus/></button>}<button type="button" aria-label={`Remove ${row.field.name} loop`} onClick={remove}><X/></button></span>}
  </div>;
}

function InputEditor({ node, fields, mappings, set, properties, sources, runtimeVariables = [], customFunctions, updateCustomFunctions, before, expanded = false }: any) {
  properties = useMemo(() => Object.assign([...(properties || [])], { customFunctions, updateCustomFunctions }), [properties, customFunctions, updateCustomFunctions]);
  const requestTree = node.type === "http" || node.type === "http_response" || (node.type === "rest" && node.config?.operation === "invoke");
  const buildRows = (values:DataField[]) => dataTreeRows(values).map(field => ({...field,
    repeating:field.repeating ?? (/array|\[\]/i.test(field.type) || Number(field.maxOccurs) > 1 || field.maxOccurs === "unbounded")}));
  const schemaRows = useMemo(() => buildRows(fields), [fields]);
  const rows = useMemo(() => requestTree ? buildRows(httpRequestOccurrences(fields,mappings)) : schemaRows, [requestTree,fields,mappings,schemaRows]), firstTarget = rows.find((row) => row.explicit)?.path || "";
  const resize = useSourcePaneWidth(expanded ? 350 : undefined), tree = useTreeCollapse(), root = useRef<HTMLDivElement>(null), [selected, setSelected] = useState(firstTarget), [contextMenu, setContextMenu] = useState<any>(null), [dialogOpen, setDialogOpen] = useState(false), [draftMappings, setDraftMappings] = useState<any>({});
  const [repeatingDrop, setRepeatingDrop] = useState<RepeatingDrop | null>(null);
  const rules = useMemo(() => activityMappingRules(mappings), [mappings]);
  const ruleIndex = useMemo(() => new Map(rules.map(rule => [`${rule.occurrenceId || "primary"}:${rule.target}`,rule])), [rules]);
  const displayRows = useMemo(() => mappingTreeRows(rows, rules, schemaRows), [rows,rules,schemaRows]);
  const connectionMappings = useMemo(() => Object.fromEntries(displayRows.filter(row => row.rule && (row.kind === "loop" || row.kind === "field" && !row.loopKey))
    .map(row => [row.kind === "loop" ? row.key + ":source" : row.occurrenceId ? row.key : row.field.path, mappingSource(row.rule)])), [displayRows]);
  const mappingSources = useMemo(() => [...runtimeVariables.filter((variable:any) => variable.fields?.length)
    .map((variable:any) => ({prefix:"vars." + variable.name, fields:variable.fields})),
    ...sources.map((entry:any) => ({...entry, reference:activityReferenceName(entry.activity.name)}))], [sources,runtimeVariables]);
  const openDialog = () => { setDraftMappings(structuredClone(mappings)); setDialogOpen(true); };

  const setValue = (path: string, value: any) => set({ ...mappings, [path]: value });
  const offerDrop = (row:MappingTreeRow, event:React.DragEvent) => {
    const source = event.dataTransfer.getData("expression");
    if (!source || !row.field.repeating || !row.field.group ||
      event.dataTransfer.getData("sourceRepeating") !== "true" || event.dataTransfer.getData("sourceComplex") !== "true") return false;
    setRepeatingDrop({row,source,label:event.dataTransfer.getData("sourceLabel") || source});
    return true;
  };
  const finishDrop = (mode:RepeatingDropMode) => {
    if (!repeatingDrop) return;
    const {row,source} = repeatingDrop;
    set(mapActivityRepeatingDrop(schemaRows,mappings,row.field.path,source,mappingSources,mode,row.occurrenceId));
    const keyPrefix = `${row.occurrenceId || "primary"}:${row.field.path}`;
    if (mode !== "copy-of") for (const key of [keyPrefix,keyPrefix + ":loop"]) {
      if (tree.collapsed.has(key)) tree.toggle(key);
    }
    setRepeatingDrop(null);
  };
  const setRowValue = (path:string, value:any, occurrenceId?:string) => {
    if (!occurrenceId) {setValue(path,value);return;}
    const previous = ruleIndex.get(`${occurrenceId}:${path}`);
    const rule = value && typeof value === "object" && value.$rule
      ? {...value,operator:value.$rule} : {source:value,operator:"direct",select:undefined,autoGenerated:undefined};
    const next = {...previous,...rule,target:path,occurrenceId};
    if (next.operator !== "for-each" && next.operator !== "for-each-group") {delete next.mapChildren; delete next.smartMatch;}
    if (next.operator === "copy-of") delete next.select;
    set(activityMappingsFromRules(previous ? rules.map(item => item === previous ? next : item) : [...rules,next]));
  };
  const patchLoop = (row:MappingTreeRow, patch:any) => {
    const path = row.field.path, previous = row.rule;
    if ((previous?.mapChildren || row.duplicateRoot) && previous?.operator !== "for-each-group" && ("source" in patch || "select" in patch)) {
      set(mapActivityRepeatingDrop(schemaRows,mappings,path,patch.select || patch.source || "",mappingSources,previous.smartMatch ? "smart-map" : "for-each",row.occurrenceId));
    } else setRowValue(path,{...(row.occurrenceId ? previous : mappings[path]),$rule:previous.operator,...patch},row.occurrenceId);
  };
  const deleteRule = (path:string, occurrenceId?:string, duplicateRoot?:boolean) => {
    set(activityMappingsFromRules(removeMappingSubtree(rules,path,occurrenceId,duplicateRoot)));
  };
  const duplicateRow = (path:string, occurrenceId?:string) => {
    const field = schemaRows.find(item => item.path === path);
    if (!field?.repeating) return;
    set(activityMappingsFromRules([...rules,emptyRepeatOccurrence(path,field.type,`occurrence-${crypto.randomUUID()}`,occurrenceId,
      ruleIndex.get(`${occurrenceId || "primary"}:${path}`))]));
  };
  const sourceScope = (row:MappingTreeRow) => {
    let path = row.field.path;
    const owner = row.duplicateRoot ? row.rule?.parentOccurrenceId : row.occurrenceId;
    while (path.includes(".")) {
      path = path.slice(0,path.lastIndexOf("."));
      const rule = ruleIndex.get(`${owner || "primary"}:${path}`);
      if (["for-each","for-each-group"].includes(rule?.operator)) return mappingSource(rule);
    }
  };
  const contentTypePicker = (path: string, label: string) => {
    const expression = mappings[path];
    let literal: string | undefined;
    if (typeof expression === "string") {
      try {
        const parsed = JSON.parse(expression);
        if (typeof parsed === "string") literal = parsed;
      } catch {
        const match = expression.match(/^'([^'\\]*)'$/);
        if (match) literal = match[1];
      }
    }
    return <HttpContentTypePicker label={label} value={literal ?? ""}
      mapped={literal === undefined && expression != null && expression !== ""}
      onChange={value => {
        if (value) setValue(path, JSON.stringify(value));
        else {
          const next = { ...mappings };
          delete next[path];
          set(next);
        }
      }}/>;
  };
  const addOccurrence = (path:string) => {
    const next={...mappings};
    const indices=Object.keys(next).filter(key=>key.startsWith(`${path}.`)).map(key=>key.slice(path.length+1).split('.')[0]).filter(key=>/^\d+$/.test(key)).map(Number);
    if(!indices.length) for(const key of Object.keys(next)) if(key.startsWith(`${path}.`)) {next[`${path}.0${key.slice(path.length)}`]=next[key];delete next[key];}
    const index=indices.length ? Math.max(...indices)+1 : Object.keys(next).some(key=>key.startsWith(`${path}.0`)) ? 1 : 0;
    next[`${path}.${index}`]='{}';set(next);
  };
  const removeOccurrence = (path:string) => set(Object.fromEntries(Object.entries(mappings).filter(([key])=>key!==path && !key.startsWith(`${path}.`))));

  return <><div ref={root} className={`activity-tab mapping-editor resizable-mapper visual-field-mapper ${expanded ? "expanded-input-workspace" : ""}`} style={{ "--source-width": `${resize.width}px` } as React.CSSProperties}>
    <MemoizedDataSourcePane properties={properties} sources={sources} runtimeVariables={runtimeVariables} customFunctions={customFunctions} updateCustomFunctions={updateCustomFunctions}/><div className="source-splitter" title="Drag left or right to resize data sources" onPointerDown={resize.begin}/>
    <section><div className="contract-heading mapping-editor-heading"><SettingsTitle title="Activity input"/>{!expanded && <button type="button" className="edit-input-mapping" onClick={openDialog}><Pencil/> Edit mappings</button>}</div>{before}
      {node.type === "xml" && node.config?.operation === "render" && <FormatCdataPicker fields={fields} expression={mappings["formatOptions.cdataElements"]} set={value => setValue("formatOptions.cdataElements", value)}/>}
      <div className="input-contract-tree"><header><Braces/><b>{node.name}</b></header>{displayRows.map(row => {
        if (row.ancestors.some(key => tree.collapsed.has(key))) return null;
        const field = row.field;
        const mediaLabel = requestTree && field.path === "RestInputRequest.Headers.content-type"
          ? "Request content type"
          : requestTree && field.path === "RestInputRequest.Headers.accept"
            ? "Accept response type"
            : node.type === "http_response" && ["contentType","HTTPHeaders.Content-Type"].includes(field.path) ? "Response content type" : "";
        const showMenu = (event: React.MouseEvent) => { event.preventDefault(); setSelected(field.path); setContextMenu({x:event.clientX, y:event.clientY, path:field.path, label:field.label || field.name,
          occurrenceId:row.occurrenceId,duplicateRoot:row.duplicateRoot,required:field.required, defaultLoopSource:defaultGroupedLoopSource(row, displayRows)}); };
        if (row.kind !== "field") return <LoopMappingRow key={row.key} row={row} collapsed={tree.collapsed.has(row.key)} toggle={tree.toggle} sources={sources}
          onLoopDrop={event => offerDrop(row,event)} onContextMenu={showMenu} duplicate={field.repeating ? () => duplicateRow(field.path,row.occurrenceId) : undefined}
          patch={patch => patchLoop(row,patch)} remove={() => setRowValue(field.path,mappingSource(row.rule),row.occurrenceId)}/>;
        const structural = field.group || isComplexSchemaType(field.validationType || field.type || ''), canMapStructure = structural && (field.group || field.repeating);
        const isCustomHeaders = ["RestInputRequest.CustomHeaders","DynamicHTTPHeaders.Headers"].includes(field.path);
        const isHeaderOccurrence = /^(?:RestInputRequest\.(?:CustomHeaders|mimeEnvelopeElement\.mimePart)|DynamicHTTPHeaders\.Headers)\.\d+$/.test(field.path);
        const addLabel = isCustomHeaders ? "Add header" : `Add ${field.name}`;
        const copy = row.rule?.operator === "copy-of";
        const rowValue = row.occurrenceId ? row.rule : mappings[field.path];
        const change = (value:any) => {
          if (row.duplicateRoot && !value) {
            patchLoop(row,{source:"",select:undefined});
          } else if (row.duplicateRoot && ["for-each","for-each-group"].includes(row.rule?.operator)) patchLoop(row,{source:value,select:value});
          else if (copy && value === "") deleteRule(field.path,row.occurrenceId);
          else setRowValue(field.path,copy && value ? {$rule:"copy-of",source:value} : value,row.occurrenceId);
        };
        const binding = <MappingBinding structural={structural} sourceScope={sourceScope(row)} expression={copy || row.occurrenceId && !["if","choose","when-otherwise"].includes(row.rule?.operator) ? mappingSource(rowValue) : rowValue ?? ""}
          fieldType={field.type} fieldLabel={`${field.label || field.name}${cardinalitySymbol(field)}`}
          validationType={field.validationType || field.type} sources={sources} onChange={change}/>;
        return <div key={row.key} data-target={row.loopKey || (structural && !canMapStructure) ? undefined : row.occurrenceId ? row.key : field.path} className={`input-tree-row ${row.occurrenceId ? "mapping-duplicate-row" : ""} ${row.duplicateRoot ? "mapping-duplicate-root" : ""} ${structural ? "structural-row" : ""} ${selected === field.path ? "selected" : ""}`} style={{"--target-depth":row.depth + 1} as React.CSSProperties} onClick={() => setSelected(field.path)} onContextMenu={showMenu} onDragOver={event => {event.preventDefault();event.dataTransfer.dropEffect="copy";}} onDrop={event => {
          event.preventDefault();const value=event.dataTransfer.getData("expression");if(!value)return;
          if (offerDrop(row,event)) return;
          if(row.loopKey || row.duplicateRoot && row.rule?.operator !== "copy-of") patchLoop(row,{source:value,select:value});
          else if(!row.occurrenceId && canMapStructure && event.dataTransfer.getData("sourceRepeating")==="true") setValue(field.path,{$rule:"for-each",source:value,select:value});
          else change(value);
        }}>
          {row.hasChildren ? <TreeToggle path={row.key} label={field.name} collapsed={tree.collapsed.has(row.key)} toggle={tree.toggle}/> : <i className="tree-elbow"/>}
          <span className="target-tree-field"><b>{row.loopKey ? field.name : field.label || field.name}{copy ? " - [Copy-Of]" : <sup className="cardinality-symbol">{cardinalitySymbol(field)}</sup>}</b><small>{field.type}</small>{row.duplicateRoot && <button type="button" className="remove-duplicate-mapping" aria-label={`Delete duplicate ${field.name}`} onClick={event => {event.stopPropagation(); deleteRule(field.path,row.occurrenceId,true);}}>×</button>}
          {!row.occurrenceId && requestTree && (isCustomHeaders || field.path === "RestInputRequest.mimeEnvelopeElement.mimePart") && !mappings[field.path] && <button type="button" className={isCustomHeaders ? "add-custom-header" : undefined} aria-label={addLabel} title={addLabel} onClick={event=>{event.stopPropagation();addOccurrence(field.path);}}><Plus/>{isCustomHeaders && addLabel}</button>}
          {requestTree && isHeaderOccurrence && <button type="button" aria-label={`Remove ${field.label}`} title={`Remove ${field.label}`} onClick={event=>{event.stopPropagation();removeOccurrence(field.path);}}><X/></button>}
          </span>
          {row.loopKey || (requestTree && isHeaderOccurrence) || (row.hasChildren && !rowValue) ? <span/> : mediaLabel
            ? <div className="input-media-type-controls">{contentTypePicker(field.path, mediaLabel)}{binding}</div>
            : binding}
        </div>;
      })}</div>{!fields.length && <div className="contract-empty">No configurable input.</div>}
    </section><MappingConnections root={root} mappings={connectionMappings}/><MappingContextMenu menu={contextMenu} value={contextMenu ? (contextMenu.occurrenceId ? ruleIndex.get(`${contextMenu.occurrenceId}:${contextMenu.path}`) : mappings[contextMenu.path]) : null}
      canDelete={!!contextMenu && removeMappingSubtree(rules,contextMenu.path,contextMenu.occurrenceId,contextMenu.duplicateRoot).length < rules.length}
      canDuplicate={!!contextMenu && schemaRows.some(row => row.path === contextMenu.path && row.repeating)}
      duplicate={() => contextMenu && duplicateRow(contextMenu.path,contextMenu.occurrenceId)}
      close={() => setContextMenu(null)} change={(value: any) => contextMenu && setRowValue(contextMenu.path,value,contextMenu.occurrenceId)}
      remove={() => contextMenu && deleteRule(contextMenu.path,contextMenu.occurrenceId,contextMenu.duplicateRoot)}/>
  </div>{repeatingDrop && <RepeatingDropDialog drop={repeatingDrop} close={() => setRepeatingDrop(null)} finish={finishDrop}/>}{dialogOpen && <ExpandedInputMappingDialog title={`${node.name} · Input Mapper`} mappingCount={Object.keys(draftMappings).length} onClose={() => setDialogOpen(false)} onApply={() => {set(draftMappings);setDialogOpen(false);}}><InputEditor node={node} fields={fields} mappings={draftMappings} set={setDraftMappings} properties={properties} sources={sources} runtimeVariables={runtimeVariables} customFunctions={customFunctions} updateCustomFunctions={updateCustomFunctions} before={before} expanded/></ExpandedInputMappingDialog>}</>;
}

function FormatCdataPicker({ fields, expression, set }: { fields: DataField[]; expression: unknown; set: (value: string) => void }) {
  const [path, setPath] = useState("");
  const choices = fields.filter(field => !field.key.startsWith("formatOptions.") && !["value","byteEncoding","xmlString"].includes(field.key) && !field.label.startsWith("@"));
  if (!choices.length) return null;
  let selected: string[] | undefined = [];
  if (typeof expression === "string" && expression) {
    try {
      const literal = JSON.parse(expression.replace(/^__mina_constant__:/,""));
      selected = typeof literal === "string" ? literal.split(",").map(value => value.trim()).filter(Boolean) : Array.isArray(literal) ? literal : undefined;
    } catch { selected = undefined; }
  } else if (expression) selected = undefined;
  return <div className="contract-grid">
    <label>Add CDATA schema path
      <select value={path} onChange={event => setPath(event.target.value)} aria-label="Choose a CDATA element">
        <option value="">Select an element…</option>
        {choices.map(field => <option key={field.key} value={field.key}>{field.key}</option>)}
      </select>
    </label>
    <button type="button" disabled={!path || !selected} onClick={() => {
      set(JSON.stringify([...new Set([...(selected || []), path])].join(", "))); setPath("");
    }}>Add CDATA element</button>
  </div>;
}

export { transformSchemaFields };

type SchemaTreeField = { path: string; name: string; type: string; depth: number; repeating: boolean; required?: boolean; minOccurs?: string; maxOccurs?: string };
function transformSchemaFields(config: any): SchemaTreeField[] {
  const text = config.targetSchemaText || JSON.stringify(config.targetSchema || {});
  try {
    const schema = JSON.parse(text), fields: SchemaTreeField[] = [];
    const resolve = (node: any) => {
      if (!node?.$ref?.startsWith("#/")) return node;
      const resolved = node.$ref.slice(2).split("/").reduce((value: any, key: string) => value?.[key.replaceAll("~1", "/").replaceAll("~0", "~")], schema);
      return resolved ? { ...resolved, ...Object.fromEntries(Object.entries(node).filter(([key]) => key !== "$ref")) } : node;
    };
    const walk = (raw: any, prefix = "", depth = 0, active: string[] = []) => {
      if (depth > 32 || raw?.$ref && active.includes(raw.$ref)) return;
      const node = resolve(raw), nextActive = raw?.$ref ? [...active, raw.$ref] : active;
      Object.entries(node?.properties || (node?.type || node?.$defs || node?.definitions || node?.$ref ? {} : node || {})).forEach(([name, rawChild]: any) => {
        const child = resolve(rawChild), path = prefix ? `${prefix}.${name}` : name, repeating = child?.type === "array" || Array.isArray(child), rawItem = repeating ? child?.items || child?.[0] || {} : rawChild, item = resolve(rawItem);
        const scalarType = (value: any) => Array.isArray(value?.type) ? value.type.join("|") : value?.type || (value?.properties ? "object" : value !== null && typeof value !== "object" ? typeof value : "any");
        const required = Array.isArray(node?.required) && node.required.includes(name);
        fields.push({path, name, type: repeating ? `${scalarType(item)}[]` : scalarType(child), depth, repeating, required, minOccurs: repeating ? String(child?.minItems ?? 0) : required ? "1" : "0", maxOccurs: child?.maxItems != null ? String(child.maxItems) : repeating ? "unbounded" : undefined});
        if (item?.properties) walk(rawItem, path, depth + 1, nextActive);
      });
    };
    walk(schema); return fields;
  } catch {
    try {
      const document = new DOMParser().parseFromString(text, "application/xml");
      if (document.querySelector("parsererror")) return [];
      const local = (element: Element) => element.localName.toLowerCase();
      const scope = new Map<Document, string>(), globals = new Map<string, Element>(), roots: Element[] = [];
      const visited = new Set<string>();
      const assets = new Map<string, string | null>();
      const relative = (reference: string, base = "") => {
        const value = decodeURIComponent(reference.replaceAll("\\", "/"));
        if (/^(?:[a-z][\w+.-]*:|\/)|[?#\\]/i.test(value)) return "";
        const parts: string[] = [];
        for (const part of (base + value).split("/")) {
          if (part === "..") { if (!parts.length) return ""; parts.pop(); }
          else if (part && part !== ".") parts.push(part);
        }
        return parts.join("/");
      };
      if (Array.from(document.documentElement.children).some(el => ["import","include"].includes(local(el)))) {
        for (const asset of config.schemaDocuments || []) {
          const name = relative(asset.source_path || asset.name);
          if (name && /\.xsd$/i.test(name)) assets.set(name, assets.has(name) ? null : asset.content);
        }
      }
      const visit = (doc: Document, path: string, fallback = "", entry = true, depth = 0) => {
        if (depth > 32 || visited.size >= 128 || doc.documentElement.namespaceURI !== "http://www.w3.org/2001/XMLSchema") return;
        const ns = doc.documentElement.getAttribute("targetNamespace") || fallback;
        const token = `${path}\0${ns}`;
        if (visited.has(token)) return;
        visited.add(token); scope.set(doc, ns);
        const children = Array.from(doc.documentElement.children);
        for (const child of children) {
          const name = child.getAttribute("name");
          if (!name) continue;
          globals.set(`${ns}\0${local(child)}\0${name}`, child);
          if (entry && local(child) === "element") roots.push(child);
        }
        for (const child of children) {
          const include = local(child) === "include";
          if (!include && local(child) !== "import") continue;
          const location = child.getAttribute("schemaLocation"), target = include ? ns : child.getAttribute("namespace") || "";
          if (location) {
            const key = relative(location, path.slice(0,path.lastIndexOf("/") + 1));
            const body = assets.get(key);
            if (body) visit(new DOMParser().parseFromString(body,"application/xml"), key, target, entry && include, depth+1);
          } else if (!include) {
            const matches: [string, Document][] = [];
            for (const [key, body] of assets) if (body && key !== path) {
              const imported = new DOMParser().parseFromString(body,"application/xml");
              if ((imported.documentElement.getAttribute("targetNamespace") || "") === target) matches.push([key, imported]);
              if (matches.length > 1) break;
            }
            if (matches.length === 1) visit(matches[0][1],matches[0][0],target,false,depth+1);
          }
        }
      };
      visit(document, relative(config.schemaPath || "__inline__.xsd"));
      const resolve = (node: Element, kind: string, value: string | null) => {
        if (!value) return undefined;
        const segments = value.split(":"), name = segments.pop();
        const namespace = node.lookupNamespaceURI(segments[0] || null);
        const fallback = segments.length ? undefined : scope.get(node.ownerDocument);
        return globals.get(`${namespace || ""}\0${kind}\0${name}`) || (fallback ? globals.get(`${fallback}\0${kind}\0${name}`) : undefined);
      };
      const declarations = (container: Element, kind: string, active: Element[] = []): Element[] => {
        if (active.includes(container)) return [];
        return Array.from(container.children).flatMap(child => {
          if (local(child) === kind) return [child];
          if (!["complextype", "complexcontent", "simplecontent", "sequence", "all", "choice", "group", "extension", "restriction", "attributegroup"].includes(local(child))) return [];
          const tag = local(child);
          const base = tag === "extension" ? resolve(child,"complextype",child.getAttribute("base"))
            : ["group","attributegroup"].includes(tag) ? resolve(child,tag,child.getAttribute("ref")) : undefined;
          return [...(base ? declarations(base, kind, [...active, container]) : []), ...declarations(child, kind, [...active, container])];
        });
      };
      const directElements = (container: Element) => declarations(container, "element");
      const fields: SchemaTreeField[] = [];
      const walkElement = (element: Element, prefix = "", depth = 0, active: Element[] = []) => {
        const occurrence = element;
        element = resolve(element,"element",element.getAttribute("ref")) || element;
        const name = element.getAttribute("name") || element.getAttribute("ref")?.split(":").pop() || "element", rawType = element.getAttribute("type") || "complex", baseType = rawType.split(":").pop() || rawType, maxOccurs = occurrence.getAttribute("maxOccurs") || "1", repeating = maxOccurs === "unbounded" || Number(maxOccurs) > 1, type = repeating ? `${baseType}[]` : baseType, path = prefix ? `${prefix}.${name}` : name;
        const minOccurs = occurrence.getAttribute("minOccurs") || "1";
        let required = Number(minOccurs) > 0;
        for (let group = occurrence.parentElement; required && group && !['complextype', 'element', 'schema'].includes(local(group)); group = group.parentElement) {
          if (local(group) === 'choice' || group.getAttribute('minOccurs') === '0') required = false;
        }
        fields.push({ path, name, type, depth, repeating, required, minOccurs, maxOccurs });
        const inline = Array.from(element.children).find((child) => local(child) === "complextype"), referenced = resolve(element,"complextype",rawType);
        const container = inline || referenced || element;
        if (depth >= 32 || active.includes(container) || fields.length >= 16000) return;
        declarations(container, "attribute").forEach((attribute) => { const attributeName = attribute.getAttribute("name") || attribute.getAttribute("ref")?.split(":").pop() || "attribute", required = attribute.getAttribute("use") === "required"; fields.push({ path: `${path}.@${attributeName}`, name: `@${attributeName}`, type: (attribute.getAttribute("type") || "string").split(":").pop() || "string", depth: depth + 1, repeating: false, required, minOccurs: required ? "1" : "0", maxOccurs: "1" }); });
        directElements(container).forEach((child) => walkElement(child, path, depth + 1, [...active, container]));
      };
      const selected = document.documentElement.getAttributeNS("urn:mina:schema-selection","element");
      const entries = selected ? roots.filter(element => `{${scope.get(element.ownerDocument) || ""}}${element.getAttribute("name")}` === selected) : roots.slice(0,1);
      entries.forEach((element) => walkElement(element));
      return fields;
    } catch { return []; }
  }
}
const xpathTemplates = [
  { name: "string", args: ["value"], version: 1 },
  { name: "normalize-space", args: ["value"], version: 1 },
  { name: "concat", args: ["first string", "second string"], version: 1 },
  { name: "contains", args: ["text", "search text"], version: 1 },
  { name: "substring", args: ["text", "start", "length"], version: 1 },
  { name: "sum", args: ["numbers"], version: 1 },
  { name: "count", args: ["items"], version: 1 },
  { name: "upper-case", args: ["value"], version: 2 },
  { name: "lower-case", args: ["value"], version: 2 },
  { name: "string-join", args: ["items", "separator"], version: 2 },
  { name: "exists", args: ["items"], version: 2 },
  { name: "xs:integer", args: ["value"], version: 2 },
  { name: "xs:decimal", args: ["value"], version: 2 },
  { name: "xs:boolean", args: ["value"], version: 2 },
];

const XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema";
function coercionXsd(schema: unknown) {
  if (typeof schema !== "string" || !schema.trimStart().startsWith("<")) return;
  const document = new DOMParser().parseFromString(schema, "application/xml");
  if (document.documentElement.namespaceURI === XSD_NAMESPACE) return document;
}

function sourceCoercionFields(rule: any): SchemaTreeField[] {
  const xml = coercionXsd(rule.schema);
  let schema = rule.schema;
  if (xml && rule.type) {
    const elements = Array.from(xml.documentElement.children).filter(node => node.namespaceURI === XSD_NAMESPACE && node.localName === "element");
    const namespace = xml.documentElement.getAttribute("targetNamespace");
    const prefix = "minaCoercionType";
    if (namespace) xml.documentElement.setAttributeNS("http://www.w3.org/2000/xmlns/", "xmlns:" + prefix, namespace);
    for (const element of elements) {
      for (const child of Array.from(element.children)) if (child.localName === "complexType" || child.localName === "simpleType") child.remove();
      element.setAttribute("type", namespace ? prefix + ":" + rule.type : rule.type);
    }
    schema = new XMLSerializer().serializeToString(xml);
  }
  const fields = transformSchemaFields(typeof schema === "string" ? {targetSchemaText:schema} : {targetSchema:schema});
  return xml ? fields.filter(field => field.depth > 0).map(field => ({ ...field,
    depth:field.depth - 1, path:field.path.slice(field.path.indexOf(".") + 1) })) : fields;
}

function MapperCoercionEditor({ values, schemas, update }: {values:any; schemas:any[]; update:(next:any)=>void}) {
  const [name, setName] = useState(""), [path, setPath] = useState(""), [range, setRange] = useState("?");
  const [schemaId, setSchemaId] = useState(""), [schema, setSchema] = useState(""), [type, setType] = useState("");
  const [message, setMessage] = useState("");
  const document = useMemo(() => coercionXsd(schema), [schema]);
  const types = document ? Array.from(document.documentElement.children).filter(node => node.namespaceURI === XSD_NAMESPACE && node.localName === "complexType")
    .map(node => node.getAttribute("name")).filter(Boolean) : [];
  const save = () => {
    const alias = name.trim(), source = path.trim().replace(/^\$\{(.+)\}$/, "$1");
    if (!/^[A-Za-z_][\w-]*$/.test(alias) || !/^[\w@#-]+(?:\[\d+\]|\.[\w@#-]+)*$/.test(source) || source.startsWith("coerced.")) {
      setMessage("Enter a view name and an original source path."); return;
    }
    if (schema.trim() && !document) {
      try {
        const contract = JSON.parse(schema);
        if (!contract || typeof contract !== "object" || Array.isArray(contract)) throw new Error();
      } catch {setMessage("Choose an XSD or enter a JSON Schema object.");return;}
    }
    update({...values, [alias]:{path:source, cardinality:range, ...(schema.trim() ? {schema} : {}), ...(type ? {type} : {})}});
    setMessage(`Saved ${alias}. Drag the view or one of its fields from Data Sources.`);
  };
  return <details className="mapper-xpath-builder"><summary>Source coercions and cardinality</summary><div className="transform-policy-grid">
    <label>Source view name<input value={name} onChange={event=>setName(event.target.value)}/></label>
    <label>Original source path<input placeholder="input.orders" value={path} onChange={event=>setPath(event.target.value)}/></label>
    <label>Source cardinality<select value={range} onChange={event=>setRange(event.target.value)}>
      <option value="?">Optional (0..1)</option><option value="1">Exactly one (1)</option>
      <option value="*">Repeating (0..unbounded)</option><option value="+">At least one (1..unbounded)</option>
    </select></label>
    <label>Coercion schema<select value={schemaId} onChange={event=>{
      const id = event.target.value;setSchemaId(id);setSchema(selectXsdStructure(schemas.find(asset=>asset.id===id)?.content || ""));setType("");
    }}><option value="">Inline or cardinality only</option>{schemas.map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>
    <XsdStructurePicker label="Source view structure" text={schema} onChange={value=>{setSchema(value);setType("");}}/>
    {!schemaId && <label>Inline coercion contract<textarea value={schema} onChange={event=>{setSchema(event.target.value);setType("");}} spellCheck={false}/></label>}
    {!!types.length && <label>XSD complex type<select value={type} onChange={event=>setType(event.target.value)}>
      <option value="">Declared element type</option>{types.map(item=><option key={item}>{item}</option>)}
    </select></label>}
    <button type="button" onClick={save}>Save source view</button>
    {Object.entries(values).map(([alias, view]:[string,any])=><div key={alias}>
      <button type="button" onClick={()=>{setName(alias);setPath(view.path);setRange(view.cardinality || "?");setSchemaId("");setSchema(typeof view.schema==="string" ? view.schema : view.schema ? JSON.stringify(view.schema) : "");setType(view.type || "");}}>{alias} ({view.cardinality})</button>
      <button type="button" aria-label={`Remove source view ${alias}`} onClick={()=>{const next={...values};delete next[alias];update(next);}}>Remove</button>
    </div>)}
    {message && <output aria-live="polite">{message}</output>}
  </div></details>;
}

function xpathSamplePaths(sample: string) {
  let xml = sample.trim();
  if (!xml.startsWith("<")) {
    try {
      const envelope = JSON.parse(sample);
      xml = envelope?.xmlString || envelope?.xml || envelope?.body || "";
    } catch { return []; }
  }
  if (typeof xml !== "string" || !xml || xml.length > 8 * 1024 * 1024 || /<!DOCTYPE/i.test(xml)) return [];
  const document = new DOMParser().parseFromString(xml, "application/xml");
  if (document.querySelector("parsererror")) return [];
  const literal = (value: string) => !value.includes("'") ? `'${value}'`
    : !value.includes('"') ? `"${value}"` : `concat(${value.split("'").map(piece => `'${piece}'`).join(`, "'", `)})`;
  const fields = new Map<string, string>();
  const stack: {node: Element; path: string; label: string}[] = [{ node: document.documentElement, path: "", label: "" }];
  let visited = 0;
  while (stack.length && visited++ < 2000 && fields.size < 250) {
    const {node, path, label} = stack.pop()!;
    const selector = (item: Element | Attr) => item.namespaceURI
      ? `*[local-name()=${literal(item.localName)} and namespace-uri()=${literal(item.namespaceURI)}]` : item.localName;
    const elementPath = `${path}/${selector(node)}`, elementLabel = `${label}/${node.nodeName}`;
    fields.set(elementPath, elementLabel);
    for (const attribute of Array.from(node.attributes).slice(0, 50)) {
      if (attribute.namespaceURI === "http://www.w3.org/2000/xmlns/") continue;
      fields.set(`${elementPath}/@${selector(attribute)}`, `${elementLabel}/@${attribute.name}`);
    }
    for (const child of Array.from(node.children).slice(0, 250).reverse()) {
      stack.push({node: child, path: elementPath, label: elementLabel});
    }
  }
  return [...fields].map(([path, label]) => ({path, label}));
}

function MapperXPathBuilder({ config, target, targetType, savedSource, apply }: { config: any; target: string; targetType?: string; savedSource?: string; apply?: (source: string) => void }) {
  const [formula, setFormula] = useState("");
  const [sample, setSample] = useState(() => typeof config.sampleInput === "string" ? config.sampleInput : config.sampleInput ? JSON.stringify(config.sampleInput, null, 2) : "");
  const [diagnostic, setDiagnostic] = useState("");
  const [testing, setTesting] = useState(false);
  const [functionName, setFunctionName] = useState("");
  const [argumentsByIndex, setArguments] = useState<string[]>([]);
  const [fieldPath, setFieldPath] = useState("");
  const [open, setOpen] = useState(false);
  const [palette, setPalette] = useState<{version:string; functions:Array<{name:string;args:string[];category:string;signature?:string}>}>();
  const [functionFilter, setFunctionFilter] = useState("");
  const [migration, setMigration] = useState<{key:string; candidate?:string; message:string}>();
  const saved = typeof savedSource === "string" ? savedSource.match(/^xpath([12]?)\(("(?:\\.|[^"\\])*")\)$/s) : null;
  const version = saved?.[1] ? saved[1] + ".0" : config.xpathVersion || "1.0";
  useEffect(() => {
    try {setFormula(saved ? JSON.parse(saved[2]) : "");}
    catch {setFormula("");}
    setDiagnostic("");
  }, [savedSource, target]);
  useEffect(() => {
    if (!open) return;
    const request = new AbortController();
    fetch("/api/mapper/xpath/functions?version=" + version, {signal:request.signal})
      .then(response=>response.ok ? response.json() : null)
      .then(result=>{if (result && !request.signal.aborted) setPalette({version, functions:result.functions});})
      .catch(()=>{});
    return () => request.abort();
  }, [open, version]);
  const templates = xpathTemplates.filter(item => item.version <= Number(version));
  const entries = palette && palette.version === version ? palette.functions : templates.map(item=>({...item, category:"Common XPath", signature:""}));
  const preferred = new Map<string, number>();
  for (const item of entries) if (!preferred.has(item.name)) {
    preferred.set(item.name, templates.find(template=>template.name===item.name)?.args.length ?? item.args.length);
  }
  const functions = entries.map(item=>{
    const template=templates.find(template=>template.name===item.name && template.args.length===item.args.length);
    return {...item,args:template?.args || item.args,
      id:preferred.get(item.name)===item.args.length ? item.name : `${item.name}#${item.args.length}`};
  });
  const selectedFunction = functions.find(item => item.id === functionName);
  const query = (functionFilter || "").trim().toLowerCase();
  const visibleFunctions = functions.filter(item=>item.id===functionName || !query ||
    `${item.name} ${item.category} ${item.signature || ""}`.toLowerCase().includes(query));
  const fields = useMemo(() => xpathSamplePaths(sample), [sample]);
  const setArgument = (index: number, value: string) => setArguments(previous => previous.map((entry, current) => current === index ? value : entry));
  const setExpression = (value: string) => {setFormula(value); setDiagnostic("");};
  const insert = (value: string) => setExpression(formula ? `${formula} ${value}` : value);
  const castType = (targetType || "").replace(/\[\]$/, "").toLowerCase();
  const constructor = ({ string:"string", int:"int", integer:"integer", long:"long", decimal:"decimal",
    number:"decimal", double:"double", float:"float", boolean:"boolean", date:"date", datetime:"dateTime" } as Record<string,string>)[castType];
  const source = `xpath${saved?.[1] || ""}(${JSON.stringify(formula.trim())})`;
  const preview = async (expression:string) => {
    const input = sample.trimStart().startsWith("<") ? {xmlString: sample} : JSON.parse(sample);
    const response = await fetch("/api/mapper/test", {method:"POST", headers:{"content-type":"application/json"}, body:JSON.stringify({
      input, mappings:[{target:"value", source:expression}], options:{xpathVersion:config.xpathVersion, xmlSource:config.xmlSource,
        xmlNamespaces:config.xmlNamespaces, xmlVariables:config.xmlVariables, sourceTypeOverrides:config.sourceTypeOverrides, validateOutput:false},
    })});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "XPath test failed");
    return result.output?.value ?? null;
  };
  const test = async () => {
    setTesting(true);
    try {
      setDiagnostic(JSON.stringify(await preview(source), null, 2));
    } catch (error) {
      setDiagnostic(error instanceof Error ? error.message : String(error));
    } finally { setTesting(false); }
  };
  const alternateVersion = version === "1.0" ? "2.0" : "1.0";
  const migrationKey = JSON.stringify([target, source, sample, version, config.xmlSource, config.xmlNamespaces, config.xmlVariables, config.sourceTypeOverrides]);
  const compareVersions = async () => {
    setTesting(true);
    try {
      const candidate = `xpath${alternateVersion[0]}(${JSON.stringify(formula.trim())})`;
      const [current, alternate] = await Promise.allSettled([preview(source), preview(candidate)]);
      if (alternate.status === "rejected") {
        setMigration({key:migrationKey, message:`XPath ${alternateVersion} could not run this expression. ${String(alternate.reason)}`});
      } else if (current.status === "fulfilled" && JSON.stringify(current.value) !== JSON.stringify(alternate.value)) {
        setMigration({key:migrationKey, message:"The XPath versions returned different results for this sample."});
      } else {
        setMigration({key:migrationKey, candidate, message:current.status === "fulfilled"
          ? "Both XPath versions returned the same result for this sample."
          : `XPath ${alternateVersion} passed this sample. The current version failed.`});
      }
    } finally {setTesting(false);}
  };
  return <details className="mapper-xpath-builder" onToggle={event=>setOpen(event.currentTarget.open)}><summary>XPath expression builder</summary><div className="transform-policy-grid">
    <label>XPath {version}<textarea value={formula} onChange={event => setExpression(event.target.value)}
      onDragOver={event => { if (event.dataTransfer.types.includes("application/x-mina-xpath")) event.preventDefault(); }}
      onDrop={event => {const path = event.dataTransfer.getData("application/x-mina-xpath"); if (path) {event.preventDefault(); insert(path);}}}
      placeholder="string(/orders/order[1]/@id)" spellCheck={false}/></label>
    <label>Sample XML or JSON envelope<textarea value={sample} onChange={event => {setSample(event.target.value); setDiagnostic("");}} spellCheck={false}/></label>
    <label>XPath result or error<textarea readOnly value={diagnostic} aria-live="polite"/></label>
    <button type="button" disabled={testing || !formula.trim() || !sample.trim()} onClick={test}>{testing ? "Testing…" : "Test XPath"}</button>
    <button type="button" disabled={!formula.trim() || !apply} onClick={() => apply?.(source)}>Apply to {target || "selected target"}</button>
    {!config.generatedXmlBinding && <button type="button" disabled={testing || !formula.trim() || !sample.trim()} onClick={compareVersions}>
      Check XPath {alternateVersion} quick fix</button>}
    {migration?.key === migrationKey && <div><output aria-live="polite">{migration.message}</output>
      {migration.candidate && apply && <button type="button" onClick={()=>apply(migration.candidate!)}>Apply XPath {alternateVersion} quick fix</button>}
    </div>}
    {version === "2.0" && constructor && <button type="button" disabled={!formula.trim()} onClick={() => setExpression(`xs:${constructor}(${formula.trim()})`)}>Cast XPath result to {constructor}</button>}
    <label>Filter XPath functions<input value={functionFilter || ""} onChange={event=>setFunctionFilter(event.target.value)}/></label>
    <label>XPath function<select value={selectedFunction?.id || ""} onChange={event => {
      const id = event.target.value;
      setFunctionName(id);
      setArguments(functions.find(item => item.id === id)?.args.map(() => "") || []);
    }}><option value="">Select a function</option>{[...new Set(visibleFunctions.map(item=>item.category))].map(category=>
      <optgroup key={category} label={category}>{visibleFunctions.filter(item=>item.category===category).map(item=>
        <option key={item.id} value={item.id}>{item.id===item.name ? item.name : `${item.name} (${item.args.length} arguments)`}</option>)}</optgroup>)}</select></label>
    {selectedFunction && <div className="mapper-xpath-arguments">
      {selectedFunction.signature && <code>{selectedFunction.signature}</code>}
      {selectedFunction.args.map((label, index) => <label key={label}>{label}<input value={argumentsByIndex[index] || ""}
        placeholder="Drop a field or enter XPath" onChange={event => setArgument(index, event.target.value)}
        onDragOver={event => {if (event.dataTransfer.types.includes("application/x-mina-xpath")) event.preventDefault();}}
        onDrop={event => {const path = event.dataTransfer.getData("application/x-mina-xpath"); if (path) {event.preventDefault(); setArgument(index, path);}}}/>
        <button type="button" disabled={!fieldPath} onClick={() => setArgument(index, fieldPath)}>Use selected field for {label}</button>
      </label>)}
      <button type="button" disabled={argumentsByIndex.some(argument => !argument.trim())}
        onClick={() => setExpression(`${selectedFunction.name}(${argumentsByIndex.join(", ")})`)}>Use function expression</button>
    </div>}
    <div className="mapper-xpath-fields"><b>Sample XML fields</b>
      {fields.length ? fields.map(({path, label}) => <button type="button" key={path} aria-pressed={fieldPath === path}
        draggable onClick={() => setFieldPath(path)} onDoubleClick={() => insert(path)}
        onDragStart={event => {event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData("application/x-mina-xpath", path);}}>{label}</button>)
        : <small>Enter sample XML to select or drag fields into function arguments.</small>}
    </div>
  </div></details>;
}

type RepeatingDrop = { row: MappingTreeRow; source: string; label: string };

function RepeatingDropDialog({ drop, close, finish }: { drop: RepeatingDrop; close: () => void; finish: (mode: RepeatingDropMode) => void }) {
  const [choice, setChoice] = useState<RepeatingDropMode>("copy-of");
  const title = useId();
  const options: [RepeatingDropMode, string, string][] = [
    ["copy-of", `Make a copy of each "${drop.label}"`, "Copy the collection as it is, with one mapping for the whole structure."],
    ["smart-map", "SmartMap", "Match child paths, ignoring case, underscores, and hyphens where the match is unique."],
    ["for-each", `For each "${drop.label}", create a "${drop.row.field.name}"`, "Map children whose names match, ignoring case, and let you edit each binding."],
  ];
  return <ModalLayer className="modal-backdrop">
    <form className="runtime-modal rename-modal mapper-repeat-drop" role="dialog" aria-modal="true" aria-labelledby={title}
      onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); close(); } }}
      onSubmit={event => { event.preventDefault(); finish(choice); }}>
      <header><b id={title}>Drop on repeating component</b><button type="button" aria-label="Close mapping choices" onClick={close}>×</button></header>
      <main><p><code>{drop.source}</code> → <b>{drop.row.field.name}</b></p>
        {options.map(([mode, label, description]) => <label key={mode}>
          <input type="radio" name="repeating-drop-mode" checked={choice === mode} autoFocus={mode === "copy-of"} onChange={() => setChoice(mode)}/>
          <span><b>{label}</b><small>{description}</small></span>
        </label>)}
      </main>
      <footer><button type="button" onClick={close}>Cancel</button><button className="primary" type="submit">Finish</button></footer>
    </form>
  </ModalLayer>;
}

function TransformInputEditor({ config, properties, sources, schemas = [], setSourceCoercions, runtimeVariables = [], setMappings, customFunctions, updateCustomFunctions, expanded = false, actions, editorTitle = "Mapper · Expanded Input Editor" }: any) {
  properties = useMemo(() => Object.assign([...(properties || [])], { customFunctions, updateCustomFunctions }), [properties, customFunctions, updateCustomFunctions]);
  const fields = useMemo<SchemaTreeField[]>(() => mapperSchemaFields(config, schemas), [config.targetSchemaText, config.targetSchema, config.targetSchemaId, schemas]), resize = useSourcePaneWidth(expanded ? 360 : 280), tree = useTreeCollapse(), root = useRef<HTMLDivElement>(null), [selected, setSelected] = useState(fields[0]?.path || ""), [contextMenu, setContextMenu] = useState<any>(null), [dialogOpen, setDialogOpen] = useState(false), [draftMappings, setDraftMappings] = useState<any[]>([]), mappings = Array.isArray(config.mappings) ? config.mappings : [];
  const [targetSearch, setTargetSearch] = useState("");
  const [selectedConnectionsOnly, setSelectedConnectionsOnly] = useState(false);
  const [selectedOccurrence, setSelectedOccurrence] = useState<string>();
  const [repeatingDrop, setRepeatingDrop] = useState<RepeatingDrop | null>(null);
  const mappingSources = useMemo(() => [
    ...Object.entries(config.sourceCoercions || {}).map(([name, value]) => ({
      prefix: "coerced." + name, fields: sourceCoercionFields(value).map(field => ({key:field.path, type:field.type})),
    })),
    ...runtimeVariables.filter((variable: any) => variable.fields?.length).map((variable: any) => ({prefix: "vars." + variable.name, fields: variable.fields})),
    ...sources.map((entry:any) => ({...entry, reference:activityReferenceName(entry.activity.name)})),
  ], [sources, config.sourceCoercions, runtimeVariables]);
  const loopScopes = useMemo(() => new Map(mappings.filter((rule:any) => ['for-each','for-each-group'].includes(rule.operator)).map((rule:any) => [`${rule.occurrenceId || 'primary'}:${rule.target}`, rule.select || rule.source])), [mappings]);
  const sourceScopeFor = (row:MappingTreeRow):string | undefined => {
    let path=row.field.path;
    while(path.includes('.')) { path=path.slice(0,path.lastIndexOf('.')); const scope=loopScopes.get(`${row.occurrenceId || 'primary'}:${path}`); if (typeof scope==='string' && scope !== 'current-group()') return scope; }
  };
  const structuralPaths = useMemo(() => {
    const parents = new Set<string>();
    for (const field of fields) { let path = field.path; while (path.includes('.')) { path = path.slice(0,path.lastIndexOf('.')); parents.add(path); } }
    return parents;
  }, [fields]);
  const mapTo = (target: string, source: any, sourceRepeating = false) => {
    if (typeof source === "string" && source.startsWith("__mina_constant__:")) {
      try { mapConstant(target, JSON.parse(source.slice(20))); } catch { /* Ignore malformed drag data. */ }
      return;
    }
    const targetField = fields.find((field) => field.path === target), explicitlyIndexed = typeof source === "string" && /\[\d+\]/.test(source);
    const targetIsComplex = !!targetField && (structuralPaths.has(targetField.path) || isComplexSchemaType(targetField.type));
    if (targetIsComplex && !targetField?.repeating) return;
    const repeat = !!targetField?.repeating && sourceRepeating && !explicitlyIndexed;
    const next = mappings.filter((rule: any) => !(rule.target === target && !rule.occurrenceId));
    next.push({ target, source, targetType: targetField?.type || "any", ...(repeat ? { select: source, operator: "for-each" } : {}), functions: [], enabled: true });
    setMappings(repeat ? autoMapLoopChildren(fields, next, target, source, mappingSources) : next);
  };
  const mapConstant = (target: string, constant: any) => setMappings([...mappings.filter((rule: any) => !(rule.target === target && !rule.occurrenceId)), { target, constant, targetType: fields.find((field) => field.path === target)?.type || "any", functions: [], enabled: true }]);
  const duplicateOccurrence = (target: string, selectedOccurrence?: string) => {
    const field = fields.find(field => field.path === target);
    if (!field?.repeating) return;
    const selectedRule = mappings.find((rule: any) => rule.target === target && rule.occurrenceId === selectedOccurrence);
    const occurrenceId = `occurrence-${crypto.randomUUID()}`;
    setMappings([...mappings, emptyRepeatOccurrence(target, field.type, occurrenceId, selectedOccurrence, selectedRule)]);
  };
  const removeOccurrence = (occurrenceId: string) => setMappings(removeRepeatOccurrence(mappings, occurrenceId));
  const displayRows = useMemo(() => mappingTreeRows(fields, mappings), [fields, mappings]);
  const updateRule = (target: string, occurrenceId: string | undefined, patch: any) => {
    const previous = mappings.find((item: any) => item.target === target && item.occurrenceId === occurrenceId);
    const next = {...previous, target, occurrenceId, targetType: fields.find(field => field.path === target)?.type || "any", functions: previous?.functions || [], enabled: true, ...patch};
    const updated = previous ? mappings.map((item: any) => item === previous ? next : item) : [...mappings, next];
    setMappings(['for-each','for-each-group'].includes(next.operator) && ('source' in patch || 'select' in patch)
      ? autoMapLoopChildren(fields, updated, target, next.select || next.source, mappingSources, occurrenceId) : updated);
  };
  const connectionMappings = useMemo(() => {
    const loopKeys = new Map(displayRows.filter(row => row.kind === 'loop').map(row => [`${row.occurrenceId || 'primary'}:${row.field.path}`, `${row.key}:source`]));
    return Object.fromEntries(mappings.filter((rule:any) => rule.enabled !== false && typeof rule.source === 'string' && rule.source.startsWith('${')).map((rule:any) => {
      const key = `${rule.occurrenceId || 'primary'}:${rule.target}`;
      return [loopKeys.get(key) || key, rule.select || rule.source];
    }));
  }, [mappings, displayRows]);
  const visibleConnections = useMemo(() => {
    if (!selectedConnectionsOnly) return connectionMappings;
    const keys = new Set(displayRows.filter(row => row.field.path === selected)
      .map(row => row.kind === 'loop' ? `${row.key}:source` : row.key));
    return Object.fromEntries(Object.entries(connectionMappings).filter(([key]) => keys.has(key)));
  }, [connectionMappings, displayRows, selected, selectedConnectionsOnly]);
  const filteredRows = useMemo(() => targetSearch.trim() ? displayRows.filter(row=>row.field.path.toLowerCase().includes(targetSearch.trim().toLowerCase())) : displayRows, [displayRows,targetSearch]);
  const contextValue = contextMenu ? mappings.find((item: any) => item.target === contextMenu.path && item.occurrenceId === contextMenu.occurrenceId) : null;
  const contextField = contextMenu ? fields.find((field) => field.path === contextMenu.path) : null;
  const selectedRule = mappings.find((rule: any) => rule.target === selected && rule.occurrenceId === selectedOccurrence);
  const selectRow = (row: MappingTreeRow) => { setSelected(row.field.path); setSelectedOccurrence(row.occurrenceId); };
  const openDialog = () => { setDraftMappings(structuredClone(mappings)); setDialogOpen(true); };
  const offerRepeatingDrop = (row: MappingTreeRow, event: React.DragEvent) => {
    const source = event.dataTransfer.getData("expression");
    if (!source || !row.field.repeating ||
        !(structuralPaths.has(row.field.path) || isComplexSchemaType(row.field.type)) ||
        event.dataTransfer.getData("sourceRepeating") !== "true" ||
        event.dataTransfer.getData("sourceComplex") !== "true" || /\[\d+\]/.test(source)) return false;
    selectRow(row);
    setRepeatingDrop({row, source, label:event.dataTransfer.getData("sourceLabel") || source});
    return true;
  };
  const finishRepeatingDrop = (mode: RepeatingDropMode) => {
    if (!repeatingDrop) return;
    const {row, source} = repeatingDrop;
    setMappings(mapRepeatingDrop(fields, mappings, row.field.path, source, mappingSources, mode, row.occurrenceId));
    const fieldKey = `${row.occurrenceId || "primary"}:${row.field.path}`;
    if (mode !== "copy-of") for (const key of [fieldKey, `${fieldKey}:loop`]) {
      if (key && tree.collapsed.has(key)) tree.toggle(key);
    }
    setRepeatingDrop(null);
  };
  return <><div ref={root} className={`activity-tab mapping-editor transform-input-editor resizable-mapper visual-field-mapper ${expanded ? "expanded-input-workspace" : ""}`} style={{ "--source-width": `${resize.width}px` } as React.CSSProperties}><MemoizedDataSourcePane properties={properties} sources={sources} runtimeVariables={runtimeVariables} customFunctions={customFunctions} updateCustomFunctions={updateCustomFunctions} coercions={config.sourceCoercions}/><div className="source-splitter" title="Drag left or right to resize data sources" onPointerDown={resize.begin}><span/></div><section><div className="contract-heading mapping-editor-heading"><SettingsTitle title="Target schema mapping" />{!expanded && <button type="button" className="edit-input-mapping" onClick={openDialog}><Pencil/> Edit mappings </button>}{actions}</div><div className="mapper-target-search"><input aria-label="Find target field" placeholder="Find target field…" value={targetSearch} onChange={event=>setTargetSearch(event.target.value)}/><button type="button" onClick={()=>tree.collapseAll(displayRows.filter(row=>row.hasChildren).map(row=>row.key))}>Collapse all</button><button type="button" onClick={tree.expandAll}>Expand all</button><label><input type="checkbox" checked={selectedConnectionsOnly} onChange={event => setSelectedConnectionsOnly(event.target.checked)}/> Selected connections only</label></div>{setSourceCoercions && <MapperCoercionEditor values={config.sourceCoercions || {}} schemas={schemas} update={setSourceCoercions}/>}<MapperXPathBuilder config={config} savedSource={selectedRule?.source} target={selected} targetType={fields.find(field => field.path === selected)?.type} apply={fields.some(field => field.path === selected) && selectedRule?.operator !== "choose" ? source => updateRule(selected,selectedOccurrence,{source,select:undefined,constant:undefined}) : undefined}/><div className="target-schema-tree">{filteredRows.map(row => {
    if (!targetSearch.trim() && row.ancestors.some(key => tree.collapsed.has(key))) return null;
    const field = row.field, rule = row.rule, structural = structuralPaths.has(field.path) || isComplexSchemaType(field.type), canMapStructure = structural && field.repeating;
    const showMenu = (event: React.MouseEvent) => {
      event.preventDefault();
      selectRow(row);
      setContextMenu({x:event.clientX,y:event.clientY,path:field.path,label:field.name,required:field.required,
        occurrenceId:row.occurrenceId,duplicateRoot:row.duplicateRoot,defaultLoopSource:defaultGroupedLoopSource(row, displayRows)});
    };
    if(row.kind !== "field") return <LoopMappingRow key={row.key} row={row} sources={sources} collapsed={tree.collapsed.has(row.key)} toggle={tree.toggle} patch={patch => updateRule(field.path,row.occurrenceId,patch)} duplicate={field.repeating ? () => duplicateOccurrence(field.path,row.occurrenceId) : undefined} onContextMenu={showMenu} onLoopDrop={event => offerRepeatingDrop(row,event)} remove={() => updateRule(field.path,row.occurrenceId,{operator:undefined,select:undefined})}/>;
    const change = (value: any) => {
      if (rule?.operator === "copy-of" && value === "") {
        if (row.duplicateRoot) updateRule(field.path,row.occurrenceId,{operator:"for-each", source:"", select:undefined, constant:undefined});
        else setMappings(mappings.filter((item:any) => item !== rule));
        return;
      }
      if (!row.occurrenceId && rule?.operator !== "copy-of") {mapTo(field.path,value);return;}
      updateRule(field.path,row.occurrenceId,{source:value,constant:undefined,
        ...(["for-each","for-each-group"].includes(rule?.operator) ? {select:value || undefined} : {})});
    };
    return <div key={row.key} data-target={row.loopKey || (structural && !canMapStructure) ? undefined : row.key} className={`schema-tree-row ${row.occurrenceId ? "mapping-duplicate-row" : ""} ${row.duplicateRoot ? "mapping-duplicate-root" : ""} ${structural ? "structural-row" : ""} ${selected === field.path ? "selected" : ""}`} style={{paddingLeft:12+row.depth*18}} onClick={() => selectRow(row)} onContextMenu={showMenu} onDragOver={event => {if(structural&&!canMapStructure)return;event.preventDefault();event.dataTransfer.dropEffect="copy";}} onDrop={event => {event.preventDefault();const value=event.dataTransfer.getData("expression");if(!value)return;const repeating = event.dataTransfer.getData("sourceRepeating") === "true";
      if (offerRepeatingDrop(row,event)) return;
      if(row.loopKey)updateRule(field.path,row.occurrenceId,{source:value,select:value});else if(row.occurrenceId)change(value);else mapTo(field.path,value,repeating);}}>
      {row.hasChildren ? <TreeToggle path={row.key} label={field.name} collapsed={tree.collapsed.has(row.key)} toggle={tree.toggle}/> : <span className="tree-node-dot"/>}
      <span className="tree-field"><b>{field.name}{rule?.operator === "copy-of" && rule.enabled !== false ? " - [Copy-Of]" : <sup className="cardinality-symbol">{cardinalitySymbol(field)}</sup>}{row.duplicateRoot && <button type="button" className="remove-duplicate-mapping" aria-label={`Delete duplicate ${field.name}`} title="Delete duplicate occurrence" onClick={event => {event.stopPropagation(); removeOccurrence(row.occurrenceId!);}}>×</button>}</b><small>{field.type} · {field.minOccurs || "1"}..{field.maxOccurs || "1"}</small></span>
      <span className={`mapping-connection ${rule ? "connected" : ""}`}><i/><ArrowRight/></span>
      {row.loopKey || (structural&&!canMapStructure) ? <span/> : <MappingBinding sourceScope={sourceScopeFor(row)} structural={structural} expression={rule?.operator && rule.operator !== "copy-of" ? {...rule,$rule:rule.operator} : rule && rule.constant !== undefined ? (typeof rule.constant === "string" ? JSON.stringify(rule.constant) : rule.constant) : rule?.source ?? ""} fieldType={field.type} fieldLabel={`${field.name}${cardinalitySymbol(field)}`} sources={sources} onChange={(value: any) => value?.$rule ? updateRule(field.path,row.occurrenceId,{...value,operator:value.$rule}) : change(value)} onConstantChange={(value: any) => row.occurrenceId ? updateRule(field.path,row.occurrenceId,{constant:value,source:undefined}) : mapConstant(field.path,value)}/>}
    </div>;
  })}{!fields.length && <div className="contract-empty">Select a project XSD or enter a valid inline target schema on Configuration.</div>}</div></section><MappingConnections root={root} mappings={visibleConnections}/><MappingContextMenu menu={contextMenu} value={contextValue} canDelete={!!contextMenu && removeMappingSubtree(mappings,contextMenu.path,contextMenu.occurrenceId,contextMenu.duplicateRoot).length < mappings.length} canDuplicate={!!contextField?.repeating} duplicate={() => contextMenu && duplicateOccurrence(contextMenu.path,contextMenu.occurrenceId)} close={() => setContextMenu(null)} change={(value: any) => contextMenu && updateRule(contextMenu.path,contextMenu.occurrenceId,value?.$rule ? {...value,operator:value.$rule} : {source:value,operator:undefined})} remove={() => {if (!contextMenu) return; setMappings(removeMappingSubtree(mappings,contextMenu.path,contextMenu.occurrenceId,contextMenu.duplicateRoot));}}/></div>{repeatingDrop && <RepeatingDropDialog drop={repeatingDrop} close={() => setRepeatingDrop(null)} finish={finishRepeatingDrop}/>}{dialogOpen && <ExpandedInputMappingDialog title={editorTitle} mappingCount={draftMappings.length} onClose={() => setDialogOpen(false)} onApply={() => { setMappings(draftMappings); setDialogOpen(false); }}><TransformInputEditor config={{ ...config, mappings: draftMappings }} schemas={schemas} editorTitle={editorTitle} properties={properties} sources={sources} runtimeVariables={runtimeVariables} setMappings={setDraftMappings} customFunctions={customFunctions} updateCustomFunctions={updateCustomFunctions} expanded/></ExpandedInputMappingDialog>}</>;
}
function mapperSchemaFields(config: any, schemas: any[]) {
  const asset = schemas.find(schema => schema.id === config.targetSchemaId);
  return transformSchemaFields(asset ? {...config, targetSchemaText: selectedSchemaText(asset.content,config.targetSchemaText), schemaPath: asset.source_path || asset.name,
    schemaDocuments: schemas} : config);
}

function mapperOutputFields(config: any, schemas: any[] = []) {
  const fields = mapperSchemaFields(config, schemas);
  if ((config.xmlStylesheet || config.generatedXmlBinding) && !fields.some(field => field.path === "xmlString")) {
    fields.unshift({path:"xmlString", name:"xmlString", type:"string", depth:0, repeating:false, minOccurs:"1"});
  }
  return fields;
}

function TransformOutputEditor({ config, schemas = [] }: any) {
  const fields = useMemo(() => mapperOutputFields(config, schemas), [config.targetSchemaText, config.targetSchema, config.targetSchemaId, config.xmlStylesheet, config.generatedXmlBinding, schemas]);
  const branches = useMemo(() => new Set(fields.filter(field => field.depth > 0).map(field => field.path.slice(0,field.path.lastIndexOf(".")))), [fields]);
  const tree = useTreeCollapse();
  return <div className="activity-tab output-editor"><div className="contract-heading"><SettingsTitle title="Transformer output structure" /></div><div className="output-schema-tree transform-output-schema">{fields.map((field) => { if (!tree.visible(field.path)) return null; const group = branches.has(field.path); return <div className={group ? "tree-parent-target" : ""} key={field.path} style={{ paddingLeft: 14 + field.depth * 18 }}>{group ? <TreeToggle path={field.path} label={field.name} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <span className="tree-node-dot"/>}<code>{field.name}<sup className="cardinality-symbol">{cardinalitySymbol(field)}</sup></code><small>{field.type}</small></div>; })}{!fields.length && <div className="contract-empty">No target schema is configured.</div>}</div></div>;
}

export function mapperXmlSchemaDocuments(schemas: any[]) {
  return Object.fromEntries(schemas.map(asset => [asset.source_path || asset.name, asset.content]).filter(([path]) => /\.xsd$/i.test(path)));
}

function TransformMapTestEditor({ node: _node, config, schemas = [], customFunctions = [], setConfig }: any) {
  const selectedTarget = schemas.find((schema: any) => schema.id === config.targetSchemaId || schema.name === config.targetSchemaId);
  const targetSchemaText = selectedTarget ? selectedSchemaText(selectedTarget.content,config.targetSchemaText) : config.targetSchemaText || "";
  const initialInput = config.sampleInput ?? {};
  const [inputText, setInputText] = useState(() => typeof initialInput === "string" && initialInput.trimStart().startsWith("<") ? initialInput : JSON.stringify(initialInput, null, 2));
  const [outputText, setOutputText] = useState(() => config.lastTestOutputText ?? (config.lastTestOutput !== undefined ? JSON.stringify(config.lastTestOutput, null, 2) : ""));
  const [status, setStatus] = useState<"idle" | "running" | "valid" | "error">("idle");
  const [message, setMessage] = useState("Enter representative input data, then execute the mappings saved in the Input tab.");
  const mappings = Array.isArray(config.mappings) ? config.mappings : [];
  const xmlSchemaDocuments = useMemo(() => config.xmlStylesheet || config.generatedXmlBinding || config.sourceCoercions
    ? {...config.xmlSchemaDocuments, ...mapperXmlSchemaDocuments(schemas)} : undefined,
    [config.xmlStylesheet, config.generatedXmlBinding, config.sourceCoercions, config.xmlSchemaDocuments, schemas]);
  const xmlTargetSchemaPath = selectedTarget?.source_path || selectedTarget?.name || config.xmlTargetSchemaPath;
  const run = async () => {
    setStatus("running"); setMessage("Executing mapping rules and formulas…");
    try {
      const input = inputText.trimStart().startsWith("<") ? inputText : JSON.parse(inputText);
      const response = await fetch("/api/mapper/test", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input, mappings, targetSchema: targetSchemaText || config.targetSchema || {}, targetSchemaText, options: { ...config, customFunctions, xmlSchemaDocuments, xmlTargetSchemaPath } }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || result.message || "Mapping test failed");
      setOutputText(result.outputText ?? (typeof result.output === "string" ? result.output : JSON.stringify(result.output ?? {}, null, 2)));
      setStatus(result.valid === false ? "error" : "valid");
      setMessage(result.valid === false ? (result.validationErrors || []).join(" · ") || "Output validation failed." : config.xmlStylesheet ? "XSLT binding executed successfully." : `${result.mappingCount ?? mappings.length} mapping rule${(result.mappingCount ?? mappings.length) === 1 ? "" : "s"} executed successfully.`);
      setConfig({ sampleInput: input, lastTestOutput: result.output ?? {}, lastTestOutputText: result.outputText });
    } catch (error: any) {
      setStatus("error"); setMessage(error.message || "Mapping test failed"); setOutputText("");
    }
  };
  return <div className="activity-tab transform-map-test">
    <header><FlaskConical/><span><b>Mapper · Map &amp; Test</b></span><i>{mappings.length} RULE{mappings.length === 1 ? "" : "S"}</i></header>
    <main>
      <section className="map-test-input"><header><span><b>TEST INPUT</b></span><button type="button" onClick={() => { setInputText(JSON.stringify(initialInput, null, 2)); setStatus("idle"); }}>Reset</button></header><textarea aria-label="Transform test input" value={inputText} onChange={(event) => { setInputText(event.target.value); setStatus("idle"); }} spellCheck={false}/></section>
      <section className="map-test-rules"><header><span><b>APPLIED MAPPINGS &amp; FORMULAS</b></span></header><div>{mappings.map((rule: any, index: number) => <article key={`${rule.target}-${index}`} className={rule.enabled === false ? "disabled" : ""}><em>{index + 1}</em><span><code>{rule.source ?? ("constant" in rule ? JSON.stringify(rule.constant) : "No source")}</code><ArrowRight/><b>{rule.target || "result"}</b><small>{[rule.operator, ...(rule.functions || []).map((fn: any) => typeof fn === "string" ? fn : fn.name)].filter(Boolean).join(" → ") || "Direct mapping"}</small></span></article>)}{!mappings.length && <p>No mappings are saved. Configure target mappings in the Input tab first.</p>}</div></section>
      <section className="map-test-output"><header><span><b>GENERATED OUTPUT</b></span></header><textarea aria-label="Generated mapping output" readOnly spellCheck={false} value={outputText} placeholder="Run the mapping test to generate output."/></section>
    </main>
    <TransformationTools config={{...config, xmlSchemaDocuments, xmlTargetSchemaPath}} setConfig={setConfig} customFunctions={customFunctions}/>
    <footer className={status}><span>{status === "valid" ? <CheckCircle2/> : status === "error" ? <AlertTriangle/> : <FlaskConical/>}<b>{message}</b></span><button type="button" className="run-map-test" disabled={status === "running" || (!mappings.length && !config.xmlStylesheet)} onClick={run}><FlaskConical/>{status === "running" ? "Running…" : "Run mapping test"}</button></footer>
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
        </header>
        {rows.map((field) => { if (!tree.visible(field.path)) return null; const group = field.group || hasTreeChildren(rows, field); return field.explicit ? (
          <div className={field.group ? "tree-parent-target" : ""} key={field.path} style={{ "--output-depth": field.depth } as React.CSSProperties}>
            <code>{group ? <TreeToggle path={field.path} label={field.label} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/> : <i className="tree-elbow"/>}{field.label}</code>
            <span>{field.type}</span>
            <span>{field.required ? "1" : "0..1"}</span>
          </div>
        ) : <div className="schema-tree-group" key={field.path} style={{ "--output-depth": field.depth } as React.CSSProperties}><code><TreeToggle path={field.path} label={field.label} collapsed={tree.collapsed.has(field.path)} toggle={tree.toggle}/><Braces/>{field.label}</code><span>object</span><span>group</span></div>; })}
      </div>
      {!fields.length && (
        <div className="contract-empty">No output schema is published.</div>
      )}
    </div>
  );
}
function AdvancedEditor({ node, value, properties, set }: any) {
  const [logPropertySearch, setLogPropertySearch] = useState("");
  const logPropertyPanel = useRef<HTMLDetailsElement>(null);
  const propertyRows = dataTreeRows(properties.filter((p: any) => p.key.startsWith("advanced.")).map((p: any) => d(p.key, p.key.split(".").pop() || p.key, p.data_type)));
  const propertyTree = useTreeCollapse();
  const defaults = {
      logPayload: "${properties.advanced.logPayload}",
      retryEnabled: "${properties.advanced.retryEnabled}",
      retryCount: "${properties.advanced.retryCount}",
      retryIntervalSeconds: "${properties.advanced.retryIntervalSeconds}",
      retryBackoff: "fixed",
      retryMaxIntervalSeconds: "",
      retryMaxElapsedSeconds: 0,
      retryJitter: false,
      retryFaultTypes: "",
    },
    advanced = { ...defaults, ...value },
    change = (key: string, next: any) => set({ ...advanced, [key]: next }),
    mappedLogPropertyKey = String(advanced.logPayload).match(/^\$\{properties\.([^}]+)\}$/)?.[1] || "",
    mappedLogProperty = properties.find((property: any) => property.key === mappedLogPropertyKey),
    visibleLogProperties = properties.filter((property: any) => {
      const query = logPropertySearch.trim().toLowerCase();
      return !query || property.key.toLowerCase().includes(query) || String(property.value ?? "").toLowerCase().includes(query);
    }),
    operation = node.config?.operation || "",
    outbound =
      ["http", "jdbc", "snowflake", "ftp", "sftp"].includes(
        node.type,
      ) ||
      (node.type === "amqp" && ["send", "get", "dead_letter"].includes(operation)) ||
      (node.type === "jms" && ["send_message", "get_queue_message", "request_reply", "reply_message"].includes(operation)) ||
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
    Object.keys(applicable).filter(key => key.startsWith("retry")).forEach(key => delete applicable[key]);
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

        />
      </div>
      <datalist id="advanced-property-values">
        {suggestions.map((item: string) => (
          <option value={item} key={item} />
        ))}
      </datalist>
      <section className="advanced-settings-tree">
        <div className="advanced-tree-root"><Braces/><span><b>Advanced</b></span></div>
        <article className="advanced-tree-branch">
          <header>
            <Braces />
            <span>
              <b>Automatic payload logging</b>

            </span>
          </header>
          <label className="advanced-tree-field">
            Log Payload{" "}
            <span className="configuration-property-field advanced-property-input">
              <input
                list="advanced-property-values"
                value={advanced.logPayload}
                onChange={(e) => change("logPayload", e.target.value)}
              />
              <details ref={logPropertyPanel} className="configuration-property-picker" onToggle={(event) => { const panel = event.currentTarget; if (panel.open) { setLogPropertySearch(""); window.setTimeout(() => panel.querySelector<HTMLInputElement>("input")?.focus(), 0); } }}>
                <summary aria-label="Browse environment properties for Log Payload" title="Browse environment properties for Log Payload"><DataNodeIcon/></summary>
                <div>
                  <header><DataNodeIcon/><span><b>ENVIRONMENT PROPERTY</b></span></header>
                  <input aria-label="Search properties for Log Payload" value={logPropertySearch} onChange={(event) => setLogPropertySearch(event.target.value)} placeholder="Search active environment…"/>
                  <section>{visibleLogProperties.map((property: any) => <button type="button" key={property.key} onClick={() => { change("logPayload", `\${properties.${property.key}}`); if (logPropertyPanel.current) logPropertyPanel.current.open = false; }}><DataNodeIcon/><span><b>{property.key}</b><small>{property.data_type} · {String(property.value ?? "") || "empty"}</small></span></button>)}{!visibleLogProperties.length && <p>No matching environment properties.</p>}</section>
                </div>
              </details>
              {mappedLogProperty && <small className="configuration-property-resolution">{mappedLogProperty.key} = {String(mappedLogProperty.value ?? "") || "empty"}</small>}
            </span>

          </label>
        </article>
        {outbound && <article className="advanced-tree-branch">
          <header>
            <RefreshCw />
            <span>
              <b>Outbound retry policy</b>

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

            </label>
            <label className="advanced-tree-field">
              Retry count{" "}
              <input
                disabled={retryDisabled}
                value={advanced.retryCount}
                onChange={(e) => change("retryCount", e.target.value)}
              />

            </label>
            <label className="advanced-tree-field">
              Retry interval (seconds){" "}
              <input
                disabled={retryDisabled}
                value={advanced.retryIntervalSeconds}
                onChange={(e) => change("retryIntervalSeconds", e.target.value)}
              />

            </label>
            <label className="advanced-tree-field">Retry backoff<select disabled={retryDisabled} value={advanced.retryBackoff} onChange={e => change("retryBackoff", e.target.value)}><option value="fixed">Fixed interval</option><option value="exponential">Exponential backoff</option></select></label>
            <label className="advanced-tree-field">Maximum retry interval (seconds)<input disabled={retryDisabled} value={advanced.retryMaxIntervalSeconds} placeholder="300 or the base interval, whichever is greater" onChange={e => change("retryMaxIntervalSeconds", e.target.value)}/></label>
            <label className="advanced-tree-field">Retry time budget (seconds, 0 unlimited)<input disabled={retryDisabled} value={advanced.retryMaxElapsedSeconds} onChange={e => change("retryMaxElapsedSeconds", e.target.value)}/></label>
            <label className="advanced-tree-field">Randomize retry delay<input type="checkbox" disabled={retryDisabled} checked={advanced.retryJitter === true || String(advanced.retryJitter).toLowerCase() === "true"} onChange={e => change("retryJitter", e.target.checked)}/></label>
            <label className="advanced-tree-field">Retry fault types or codes<input disabled={retryDisabled} value={advanced.retryFaultTypes} placeholder="All faults, or comma-separated names" onChange={e => change("retryFaultTypes", e.target.value)}/></label>
          </div>
          <p>Up to 100 additional attempts. The retry budget prevents starting another attempt after its limit; it does not interrupt an in-flight request. Enable retries for writes only when the destination can safely handle duplicates.</p>
        </article>}
      </section>
      <aside>
        <b>PROJECT-GLOBAL PROPERTY MAPPINGS</b>

        <div>
          {propertyRows.map((row) => { if (!propertyTree.visible(row.path)) return null; return row.explicit ? (
            <button key={row.path} className="advanced-property-leaf" style={{ "--tree-depth": row.depth } as React.CSSProperties} onClick={() => navigator.clipboard?.writeText("${properties." + row.path + "}")}><i className="tree-elbow"/><Braces/><span>{row.label}<small>{row.type} · {String(properties.find((property: any) => property.key === row.path)?.value)}</small></span></button>
          ) : <div key={row.path} className="advanced-property-group" style={{ "--tree-depth": row.depth } as React.CSSProperties}><TreeToggle path={row.path} label={row.label} collapsed={propertyTree.collapsed.has(row.path)} toggle={propertyTree.toggle}/><Braces/><span><b>{row.label}</b></span></div>; })}
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
function SettingsTitle({ title }: any) {
  return (
    <>
      <div>
        <Database />
        <span>
          <b>{title}</b>
        </span>
      </div>
    </>
  );
}
