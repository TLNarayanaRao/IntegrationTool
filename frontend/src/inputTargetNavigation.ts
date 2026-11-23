import type { MappingTreeRow } from "./mappingTree";

export type InputTarget = { path: string; occurrenceId?: string };

/** Keep matching rows in schema order and retain the ancestors that give them context. */
export function filterInputTargets(rows: MappingTreeRow[], query: string) {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return { rows, count: 0 };
  const visible = new Set<string>();
  let count = 0;
  for (const row of rows) {
    const text = `${row.field.path} ${row.field.name} ${row.field.label ?? ""}`.toLowerCase();
    if (!terms.every(term => text.includes(term))) continue;
    visible.add(row.key);
    for (const ancestor of row.ancestors) visible.add(ancestor);
    if (row.kind === "field") count++;
  }
  return { rows: rows.filter(row => visible.has(row.key)), count };
}

export function locateInputTarget(rows: MappingTreeRow[], target: InputTarget) {
  const locate = (path: string) => {
    while (path) {
      const field = rows.find(row => row.kind === "field" && row.field.path === path && row.occurrenceId === target.occurrenceId);
      if (field) return field.loopKey ? rows.find(row => row.key === field.loopKey) ?? field : field;
      const dot = path.lastIndexOf(".");
      path = dot < 0 ? "" : path.slice(0, dot);
    }
  };
  return locate(target.path) ?? locate(target.path.replace(/^(?:payload|result)\./, ""));
}
