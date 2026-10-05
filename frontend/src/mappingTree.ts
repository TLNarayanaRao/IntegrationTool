export type MappingTreeField = { path: string; name: string; depth: number; type?: string; validationType?: string; repeating?: boolean; required?: boolean; minOccurs?: string; maxOccurs?: string; [key: string]: any };
export type MappingTreeRow = { kind: "loop" | "grouping" | "field"; key: string; field: MappingTreeField; rule: any; depth: number; ancestors: string[]; occurrenceId?: string; loopKey?: string; hasChildren: boolean; duplicateRoot?: boolean };

/** Statements wrap target nodes; duplicate occurrences include their whole subtree. */
export function mappingTreeRows(fields: MappingTreeField[], mappings: any[] | Record<string, any>): MappingTreeRow[] {
  const rules = Array.isArray(mappings) ? mappings : Object.entries(mappings || {}).map(([target, value]) => ({ target, ...(value && typeof value === "object" && "$rule" in value ? value : { source: value }) }));
  const result: MappingTreeRow[] = [];
  const fieldIndex = new Map(fields.map(field => [field.path, field]));
  const childIndex = new Map<string, MappingTreeField[]>();
  const roots: MappingTreeField[] = [];
  for (const field of fields) {
    let prefix = field.path, parent: MappingTreeField | undefined;
    while (prefix.includes('.')) {
      prefix = prefix.slice(0, prefix.lastIndexOf('.'));
      const candidate = fieldIndex.get(prefix);
      if (candidate?.depth === field.depth - 1) { parent = candidate; break; }
    }
    if (parent) { const children = childIndex.get(parent.path) || []; children.push(field); childIndex.set(parent.path, children); }
    else roots.push(field);
  }
  const ruleIndex = new Map<string, Map<string | undefined, any>>();
  const duplicates = new Map<string, any[]>();
  for (const rule of rules) {
    const occurrences = ruleIndex.get(rule.target) || new Map<string | undefined, any>();
    if (!occurrences.has(rule.occurrenceId)) occurrences.set(rule.occurrenceId, rule);
    ruleIndex.set(rule.target, occurrences);
    if (rule.occurrenceId && ['for-each', 'for-each-group'].includes(rule.operator || rule.$rule)) {
      const copies = duplicates.get(rule.target) || []; copies.push(rule); duplicates.set(rule.target, copies);
    }
  }
  function visit(field: MappingTreeField, depth: number, ancestors: string[], occurrenceId?: string, duplicateRoot = false) {
    const rule = ruleIndex.get(field.path)?.get(occurrenceId);
    const key = `${occurrenceId || "primary"}:${field.path}`, loopKey = `${key}:loop`;
    const loop = ["for-each", "for-each-group"].includes(rule?.operator || rule?.$rule);
    const descendants = childIndex.get(field.path) || [];
    if (loop && !duplicateRoot) {
      result.push({ kind: "loop", key: loopKey, field, rule, depth, ancestors, occurrenceId, loopKey, hasChildren: true });
      ancestors = [...ancestors, loopKey]; depth++;
      if ((rule.operator || rule.$rule) === "for-each-group") result.push({ kind: "grouping", key: `${key}:grouping`, field, rule, depth, ancestors, occurrenceId, loopKey, hasChildren: false });
    }
    result.push({ kind: "field", key, field, rule, depth, ancestors, occurrenceId, loopKey: loop && !duplicateRoot ? loopKey : undefined, hasChildren: !!descendants.length, duplicateRoot });
    if (duplicateRoot && (rule?.operator || rule?.$rule) === 'for-each-group') {
      result.push({kind:'grouping', key:`${key}:grouping`, field, rule, depth:depth+1, ancestors:[...ancestors,key], occurrenceId, hasChildren:false});
    }
    descendants.forEach(child => visit(child, depth + 1, [...ancestors, key], occurrenceId));
    if (!occurrenceId) for (const duplicate of duplicates.get(field.path) || []) {
      visit(field, depth, loop ? ancestors.slice(0, -1) : ancestors, duplicate.occurrenceId, true);
    }
  }
  roots.forEach(field => visit(field, field.depth, []));
  return result;
}
