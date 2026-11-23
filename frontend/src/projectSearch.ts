import { resolveWorkspaceSubtask, type NamedPackageObject } from "./studioObjectName";
import type { StudioLocation, NavigationPackage } from "./studioNavigation";

export type ReferenceTarget = { kind: "task" | "resource" | "schema" | "property"; id: string };
export type SearchLocation = StudioLocation | { kind: "property"; key: string; environment: string } | { kind: "library" };
type SearchAsset = NamedPackageObject & { type?: string; config?: object; content?: string; library_origin?: {alias: string; public: boolean} | null };
type Activity = { id: string; name: string; type: string; config: Record<string, unknown> };
type SearchTask = SearchAsset & { kind: string; activities: Activity[]; groups?: {name: string; config: object}[];
  transitions?: {id: string; source: string; condition?: unknown}[] };
export type SearchProject = {
  tasks: SearchTask[];
  resources: SearchAsset[];
  schemas: SearchAsset[];
  properties: Record<string, {key: string; value: unknown}[]>;
  active_environment: string;
};
export type ProjectSearchRow = {
  key: string;
  name: string;
  kind: string;
  detail: string;
  location: SearchLocation;
  target?: ReferenceTarget;
};

const assetKinds = { tasks: "task", resources: "resource", schemas: "schema" } as const;
export const projectSearchKinds = ["Task", "Activity", "Folder", "Connection", "Schema", "Property"];
const visible = (item: SearchAsset) => !item.library_origin || item.library_origin.public;
const assetLabel = (kind: ReferenceTarget["kind"]) => kind === "resource" ? "Connection" : kind === "schema" ? "Schema" : "Task";
const assetPath = (asset: SearchAsset) => `${asset.package_path || "Default"}/${asset.name}`;

export function projectSearchIndex(project: SearchProject, packages: Partial<Record<NavigationPackage,string[]>>): ProjectSearchRow[] {
  const results: ProjectSearchRow[] = [];
  for (const category of ["tasks", "resources", "schemas"] as const) {
    const kind = assetKinds[category];
    for (const item of project[category].filter(visible)) {
      results.push({
        key: JSON.stringify([kind, item.id]), name: item.name, kind: assetLabel(kind),
        detail: [item.package_path || "Default", item.type, item.library_origin?.alias].filter(Boolean).join(" · "),
        location: item.library_origin ? {kind: "library"} : {kind, id: item.id}, target: {kind, id: item.id},
      });
    }
    for (const path of packages[category] || []) results.push({
      key: JSON.stringify(["folder", category, path]), name: path, kind: "Folder",
      detail: category === "tasks" ? "Tasks" : category === "resources" ? "Connections" : "Schemas",
      location: {kind: "package", category, path},
    });
  }
  for (const task of project.tasks.filter(item => !item.library_origin)) {
    for (const activity of task.activities) results.push({
      key: JSON.stringify(["activity", task.id, activity.id]), name: activity.name,
      kind: "Activity", detail: [assetPath(task), activity.type, activity.config.operation].filter(Boolean).join(" · "),
      location: {kind: "task", id: task.id, activityId: activity.id},
    });
  }
  for (const [environment, properties] of Object.entries(project.properties)) {
    for (const property of properties) results.push({
      key: JSON.stringify(["property", environment, property.key]), name: property.key, kind: "Property",
      detail: `${environment}.properties`, location: {kind: "property", environment, key: property.key},
      target: {kind: "property", id: property.key},
    });
  }
  return results;
}

export function searchProject(rows: ProjectSearchRow[], query: string, kind: string): ProjectSearchRow[] {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return rows.filter(row => {
    if (kind && row.kind !== kind) return false;
    const text = `${row.name} ${row.detail} ${row.kind}`.toLowerCase();
    return tokens.every(token => text.includes(token));
  });
}

export function projectReferences(project: SearchProject, target: ReferenceTarget): ProjectSearchRow[] {
  const profiles = Object.entries(project.properties).map(([environment, entries]) =>
    [environment, new Map(entries.map(item => [item.key, item.value]))] as const);
  const results: ProjectSearchRow[] = [];
  const assets = target.kind === "resource" ? project.resources : target.kind === "schema" ? project.schemas : [];
  const asset = assets.find(item => item.id === target.id);
  const properties = /\$\{properties\.([^}]+)\}/g;

  const matchesSelector = (value: string) => {
    if (target.kind === "task") return resolveWorkspaceSubtask(project.tasks, value.trim())?.id === target.id;
    if (value === target.id) return true;
    return target.kind === "schema" && asset?.name === value &&
      !assets.some(item => item.id === value && item.id !== target.id) &&
      assets.filter(item => item.name === value).length === 1;
  };
  const scan = (config: unknown, path: string, matches: Set<string>) => {
    if (typeof config === "string") {
      if (target.kind === "property") {
        if ([...config.matchAll(properties)].some(match => match[1] === target.id)) matches.add(path);
        return;
      }
      const field = path.slice(path.lastIndexOf(".") + 1).toLowerCase();
      const selector = target.kind === "task" ? /^(?:dynamic)?taskid$/ :
        target.kind === "resource" ? /(?:resourceid|connectionid|managerid)$/ :
        /(?:schemaid|formatassetid|dataformatid)$/;
      if (!selector.test(field)) return;
      if (matchesSelector(config)) matches.add(path);
      const key = /^\$\{properties\.([^}]+)\}$/.exec(config)?.[1];
      if (key) {
        const environments = profiles.filter(([, values]) => {
          const value = values.get(key);
          return typeof value === "string" && matchesSelector(value);
        }).map(([environment]) => environment);
        if (environments.length) matches.add(`${path} (${environments.join(", ")})`);
      }
    } else if (Array.isArray(config)) {
      for (const child of config) scan(child, path, matches);
    } else if (config && typeof config === "object") {
      for (const [field, child] of Object.entries(config)) scan(child, path ? `${path}.${field}` : field, matches);
    }
  };

  const add = (row: Omit<ProjectSearchRow, "detail">, config: unknown, path: string, context: string) => {
    const matches = new Set<string>();
    scan(config, path, matches);
    if (matches.size) results.push({...row, detail: [context, ...matches].filter(Boolean).join(" · ")});
  };
  for (const task of project.tasks.filter(item => !item.library_origin)) {
    for (const activity of task.activities) add({
      key: JSON.stringify([task.id, activity.id]), name: activity.name, kind: "Activity",
      location: {kind: "task", id: task.id, activityId: activity.id},
    }, activity.config, "", assetPath(task));
    for (const [index, group] of (task.groups || []).entries()) add({
      key: JSON.stringify([task.id, "group", index]), name: group.name, kind: "Group",
      location: {kind: "task", id: task.id},
    }, group.config, "", assetPath(task));
    for (const edge of task.transitions || []) add({
      key: JSON.stringify([task.id, "transition", edge.id]), name: "Transition condition", kind: "Transition",
      location: {kind: "task", id: task.id, activityId: edge.source},
    }, edge.condition, "condition", assetPath(task));
  }
  for (const resource of project.resources.filter(item => !item.library_origin)) add({
    key: JSON.stringify(["connection", resource.id]), name: resource.name, kind: "Connection",
    location: {kind:"resource", id:resource.id},
  }, resource.config, "", resource.package_path || "Default");
  if (target.kind === "schema" || target.kind === "property") {
    for (const schema of project.schemas.filter(item => !item.library_origin)) {
      const content = schema.content?.trimStart();
      if (!content?.startsWith("{") || !content.includes('"dataFormat"')) continue;
      try {
        const document = JSON.parse(content);
        if (document?.dataFormat && typeof document.dataFormat === "object") add({
          key: JSON.stringify(["data-format", schema.id]), name: schema.name, kind: "Data Format",
          location: {kind: "schema", id: schema.id},
        }, {dataFormat: document.dataFormat, inputMappings: document.inputMappings}, "", schema.package_path || "Default");
      } catch (error) {
        if (!(error instanceof SyntaxError)) throw error;
      }
    }
  }
  return results;
}
