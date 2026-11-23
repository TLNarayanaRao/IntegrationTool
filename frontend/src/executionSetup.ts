import { taskEntryActivities } from "./taskEntry";

export type LaunchMode = "run" | "debug" | "subtask";
export type SubtaskInputFormat = "json" | "xml";
export type LaunchOptions = { input: unknown; environment: string; capture: boolean; testSubtask?: boolean; inputFormat?: SubtaskInputFormat };
export type SubtaskInputReport = {
  format: "none" | "json" | "xsd";
  name?: string;
  root?: string;
  example?: unknown;
  fields?: {path: string; type: string; required?: boolean; repeating?: boolean}[];
  errors: string[];
};

type Config = Record<string, unknown>;
type LaunchActivity = { id: string; type: string; name: string; config: Config };
export type LaunchTask = {
  id: string; name: string; kind: string; package_path?: string; library_origin?: unknown;
  activities: LaunchActivity[];
  transitions: { target: string; condition?: string }[];
  groups?: { name: string; config: Config }[];
};
type Connection = { id: string; name: string; type: string; config: Config; library_origin?: unknown };
export type LaunchProject = {
  tasks: LaunchTask[];
  resources: Connection[];
  properties: Record<string, { key: string; value: unknown }[]>;
};

export function parseLaunchInput(source: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(source);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Initial input must be a JSON object.");
  return parsed as Record<string, unknown>;
}

const continuousOperations: Record<string, string[]> = {
  timer: ["schedule"], file: ["poll"], ems: ["queue_receiver", "topic_subscriber"], jms: ["receive_message"],
  amqp: ["receive"], kafka: ["receive", "get"], pubsub: ["subscribe"], sap: ["idoc_listener", "rfc_bapi_listener"],
};

export function launchEntry(task: LaunchTask) {
  const [entry, extra] = taskEntryActivities(task.activities, task.transitions);
  if (!entry || extra) return { kind: "invalid" as const };
  const operation = String(entry.config.operation ?? "");
  if (entry.type === "http_listener" || entry.type === "rest" && operation === "receiver" || entry.type === "soap" && operation === "service")
    return { kind: "listener" as const, name: entry.name };
  if (continuousOperations[entry.type]?.includes(operation))
    return { kind: entry.type === "timer" ? "schedule" as const : "listener" as const, name: entry.name };
  return { kind: "once" as const, name: entry.name };
}

export const propertyReferences = (value: unknown) =>
  Array.from((JSON.stringify(value) ?? "").matchAll(/\$\{properties\.([^}]+)\}/g), match => match[1]);

const normalizedName = (name: string) => name.split("/").map(part => part.normalize("NFKC").trim().replace(/\s+/g, "-").toLowerCase()).join("/");
const propertyReference = /^\$\{properties\.([^}]+)\}$/;

export function executionReadiness(project: LaunchProject, task: LaunchTask, environment: string) {
  const properties = new Map((project.properties[environment] || []).map(item => [item.key, item.value]));
  const usedProperties = new Set<string>();
  const resources = new Map(project.resources.map(resource => [resource.id, resource]));
  const connections = new Map<string, {id: string; name: string; type?: string; usedBy: string[]; missing: boolean}>();
  const tasks = new Map(project.tasks.map(item => [item.id, item]));
  const visited = new Set<string>();
  const pending = [task];
  let runtimeDependencies = false;
  const gatherProperties = (config: unknown) => propertyReferences(config).forEach(key => usedProperties.add(key));
  const staticReference = (value: unknown) => {
    if (typeof value !== "string" || !value.trim()) return undefined;
    const binding = value.match(propertyReference);
    if (binding && typeof properties.get(binding[1]) === "string") value = properties.get(binding[1]);
    if (typeof value !== "string" || value.includes("${")) {
      runtimeDependencies = true;
      return undefined;
    }
    return value.trim() || undefined;
  };
  const addConnection = (value: unknown, location: string) => {
    const id = staticReference(value);
    if (!id) return;
    const resource = resources.get(id);
    if (resource?.library_origin) { runtimeDependencies = true; return; }
    const binding = typeof value === "string" ? value.match(propertyReference)?.[1] : undefined;
    const key = resource ? id : binding ? `properties.${binding}` : id;
    let row = connections.get(key);
    if (!row) {
      row = {id: key, name: resource?.name || key, type: resource?.type, usedBy: [], missing: !resource};
      connections.set(key, row);
      gatherProperties(resource?.config);
    }
    if (!row.usedBy.includes(location)) row.usedBy.push(location);
  };
  while (pending.length) {
    const current = pending.pop()!;
    if (visited.has(current.id)) continue;
    if (current.library_origin) { runtimeDependencies = true; continue; }
    visited.add(current.id);
    gatherProperties(current.transitions.map(item => item.condition));
    for (const group of current.groups ?? []) {
      gatherProperties(group.config);
      addConnection(group.config.resourceId, `${current.name} / ${group.name}`);
    }
    for (const activity of current.activities) {
      gatherProperties(activity.config);
      const location = `${current.name} / ${activity.name}`;
      addConnection(activity.config.resourceId, location);
      addConnection(activity.config.messagingResourceId, location);
      if (activity.type !== "call_task") continue;
      const requested = staticReference(activity.config.dynamicTaskId) || staticReference(activity.config.taskId);
      if (!requested) continue;
      const direct = tasks.get(requested);
      const matches = direct ? [direct] : project.tasks.filter(item => item.kind === "subtask" &&
        normalizedName(requested.includes("/") ? `${item.package_path || "Default"}/${item.name}` : item.name) === normalizedName(requested));
      if (matches.length === 1 && matches[0].kind === "subtask") pending.push(matches[0]);
      else runtimeDependencies = true;
    }
  }
  const propertyFindings = [...usedProperties].sort().flatMap(key => {
    const value = properties.get(key);
    if (!properties.has(key)) return [{key, status: "Missing"}];
    if (value == null || typeof value === "string" && !value.trim()) return [{key, status: "Empty"}];
    return [];
  });
  return {taskIds: [...visited], connections: [...connections.values()], propertyCount: usedProperties.size, propertyFindings, runtimeDependencies};
}
