/** Repair only dangling local references with one unambiguous legacy Copy target. */
export function repairCopiedTask<T extends { activities: any[]; transitions?: any[]; groups?: any[] }>(source: T): T {
  const existing = new Set(source.activities.flatMap(item => [item.id, item.name]));
  const candidates = new Map<string, Set<string>>();
  for (const item of source.activities) {
    let previous = String(item.id);
    while (/-Copy(?:-\d+)?$/i.test(previous)) {
      previous = previous.replace(/-Copy(?:-\d+)?$/i, "");
      if (!previous) break;
      const targets = candidates.get(previous) || new Set<string>();
      targets.add(item.id); candidates.set(previous, targets);
    }
  }
  const reserved = new Set(['input', 'last', 'vars', 'properties', 'context', 'tasks', 'activities']);
  const replacement = (id: string) => {
    const targets = candidates.get(id);
    return !existing.has(id) && targets?.size === 1 ? [...targets][0] : id;
  };
  const rewrite = (value: any): any => {
    if (typeof value === 'string') return value.replace(/\$\{([^{}]+)\}/g, (whole, path: string) => {
      const parts = path.split('.');
      if (parts[0] === 'activities' && parts.length > 1) parts[1] = replacement(parts[1]);
      else if (!reserved.has(parts[0])) parts[0] = replacement(parts[0]);
      return '${' + parts.join('.') + '}';
    });
    if (Array.isArray(value)) return value.map(rewrite);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, rewrite(item)]));
    return value;
  };
  return {
    ...structuredClone(source),
    activities: source.activities.map(item => ({ ...structuredClone(item), config: rewrite(item.config) })),
    ...(source.transitions ? { transitions: source.transitions.map(item => ({ ...rewrite(item), source: replacement(item.source), target: replacement(item.target) })) } : {}),
    ...(source.groups ? { groups: source.groups.map(item => ({ ...rewrite(item), member_activity_ids: (item.member_activity_ids || []).map(replacement) })) } : {}),
  };
}
