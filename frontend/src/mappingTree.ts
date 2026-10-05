export type MappingTreeField = { path: string; name: string; depth: number; [key: string]: any };
export type MappingTreeRow = { kind: "loop" | "grouping" | "field"; key: string; field: MappingTreeField; rule: any; depth: number; ancestors: string[]; occurrenceId?: string; loopKey?: string; hasChildren: boolean };

/** Statements wrap target nodes; duplicate occurrences include their whole subtree. */
export function mappingTreeRows(fields: MappingTreeField[], mappings: any[] | Record<string, any>): MappingTreeRow[] {
  const rules = Array.isArray(mappings) ? mappings : Object.entries(mappings || {}).map(([target, value]) => ({ target, ...(value && typeof value === "object" && "$rule" in value ? value : { source: value }) }));
  const result: MappingTreeRow[] = [];
  const children = (field: MappingTreeField) => fields.filter(candidate => candidate.path.startsWith(`${field.path}.`) && candidate.depth === field.depth + 1);
  function visit(field: MappingTreeField, depth: number, ancestors: string[], occurrenceId?: string) {
    const rule = rules.find(item => item.target === field.path && item.occurrenceId === occurrenceId);
    const key = `${occurrenceId || "primary"}:${field.path}`, loopKey = `${key}:loop`;
    const loop = ["for-each", "for-each-group"].includes(rule?.operator || rule?.$rule);
    const descendants = children(field);
    if (loop) {
      result.push({ kind: "loop", key: loopKey, field, rule, depth, ancestors, occurrenceId, loopKey, hasChildren: true });
      ancestors = [...ancestors, loopKey]; depth++;
      if ((rule.operator || rule.$rule) === "for-each-group") result.push({ kind: "grouping", key: `${key}:grouping`, field, rule, depth, ancestors, occurrenceId, loopKey, hasChildren: false });
    }
    result.push({ kind: "field", key, field, rule, depth, ancestors, occurrenceId, loopKey: loop ? loopKey : undefined, hasChildren: !!descendants.length });
    descendants.forEach(child => visit(child, depth + 1, [...ancestors, key], occurrenceId));
    if (!occurrenceId) for (const duplicate of rules.filter(item => item.target === field.path && item.occurrenceId && ["for-each", "for-each-group"].includes(item.operator || item.$rule))) {
      visit(field, loop ? depth - 1 : depth, loop ? ancestors.slice(0, -1) : ancestors, duplicate.occurrenceId);
    }
  }
  fields.filter(field => !fields.some(parent => field.path.startsWith(`${parent.path}.`) && parent.depth === field.depth - 1)).forEach(field => visit(field, field.depth, []));
  return result;
}
