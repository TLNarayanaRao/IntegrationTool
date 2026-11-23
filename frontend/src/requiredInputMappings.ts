import type { InputTarget } from "./inputTargetNavigation";

type Field = { path: string; required?: boolean; repeating?: boolean; explicit?: boolean };
type Rule = {
  target: string;
  enabled?: boolean;
  operator?: string;
  source?: unknown;
  select?: unknown;
  constant?: unknown;
  otherwise?: unknown;
  whens?: { source?: unknown }[];
  occurrenceId?: string;
  parentOccurrenceId?: string;
  duplicateOf?: string;
  mapChildren?: boolean;
};
type Branch = Field & { children: Map<string, Branch> };

export const hasInputValue = (value: unknown): boolean =>
  value != null && (typeof value !== "string" || !!value.trim());

function ruleValue(rule: Rule): unknown {
  if (rule.constant !== undefined) return rule.constant;
  if (rule.operator === "choose") {
    let branches = rule.whens;
    if (!branches && typeof rule.source === "string") {
      try { branches = JSON.parse(rule.source); } catch { return undefined; }
    }
    return (Array.isArray(branches) ? branches.find(branch => hasInputValue(branch?.source))?.source : undefined) ?? rule.otherwise;
  }
  return [rule.select, rule.source, rule.otherwise].find(hasInputValue);
}

function literalValue(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const text = value.trim().replace(/^__mina_constant__:/, "");
  try { return JSON.parse(text); } catch { return undefined; }
}

/** Inspect the design. Dynamic object values and collection sizes are checked at runtime. */
export function missingRequiredInputs(fields: Field[], rules: Rule[], defaults: Record<string, unknown> = {}, mapper = false) {
  const tree = new Map<string, Branch>();
  for (const field of fields) {
    let children = tree, path = "";
    for (const part of field.path.split(".")) {
      path = path ? path + "." + part : part;
      if (!children.has(part)) children.set(part, { path, explicit: false, children: new Map() });
      const branch = children.get(part)!;
      if (path === field.path) Object.assign(branch, { ...field, explicit: field.explicit ?? true });
      children = branch.children;
    }
  }

  const mapped = new Map<string | undefined, Map<string, Rule>>();
  const duplicates = new Map<string | undefined, Map<string, Rule[]>>();
  for (const rule of rules) {
    if (!rule?.target || rule.enabled === false || (rule.constant === undefined && !hasInputValue(ruleValue(rule)))) continue;
    if (rule.duplicateOf && rule.occurrenceId) {
      const paths = duplicates.get(rule.parentOccurrenceId) ?? new Map<string, Rule[]>();
      const copies = paths.get(rule.target) ?? [];
      copies.push(rule);
      paths.set(rule.target, copies);
      duplicates.set(rule.parentOccurrenceId, paths);
    } else {
      const paths = mapped.get(rule.occurrenceId) ?? new Map<string, Rule>();
      paths.set(rule.target, rule);
      mapped.set(rule.occurrenceId, paths);
    }
  }
  const missing = new Map<string, InputTarget>();
  const rootRules = new Map<string, Rule>(Object.entries(defaults).filter(([, value]) => hasInputValue(value)).map(([target, constant]) =>
    [target, { target, constant }] as const));
  for (const [path, rule] of mapped.get(undefined) ?? []) rootRules.set(path, rule);
  mapped.set(undefined, rootRules);
  const parentPaths = new Map<string | undefined, Set<string>>();
  for (const owner of new Set([...mapped.keys(), ...duplicates.keys()])) {
    const paths = new Set<string>();
    for (const target of [...(mapped.get(owner)?.keys() ?? []), ...(duplicates.get(owner)?.keys() ?? [])]) {
      for (let end = target.lastIndexOf("."); end > 0; end = target.lastIndexOf(".", end - 1)) paths.add(target.slice(0, end));
    }
    parentPaths.set(owner, paths);
  }

  const visit = (branch: Branch, owner: string | undefined, supplied: unknown, prefix: string) => {
    const { path, children } = branch;
    const bindings = mapped.get(owner);
    const copies = duplicates.get(owner)?.get(path) ?? [];
    const descendants = !!parentPaths.get(owner)?.has(path);
    const rule = bindings?.get(path);
    const name = path.slice(path.lastIndexOf(".") + 1);
    const display = prefix ? prefix + "." + name : name;
    if (!rule && !copies.length && !descendants && supplied === undefined) {
      if (!branch.required) {
        if (!branch.explicit) for (const child of children.values()) visit(child, owner, undefined, display);
        return;
      }
      if (!children.size || branch.repeating) { missing.set(display, { path, occurrenceId: owner }); return; }
      const priorSize = missing.size;
      for (const child of children.values()) visit(child, owner, undefined, display);
      if (priorSize === missing.size) missing.set(display, { path, occurrenceId: owner });
      return;
    }
    const walk = (value: unknown, scope: string | undefined, label: string) => {
      if (Array.isArray(value)) {
        value.forEach((item, index) => walk(item, scope, `${label}[${index + 1}]`));
      } else if (value && typeof value === "object") {
        for (const [key, child] of children) {
          const childValue = Object.prototype.hasOwnProperty.call(value, key) ? (value as Record<string, unknown>)[key] : undefined;
          visit(child, scope, childValue, label);
        }
      }
    };
    const check = (binding: Rule, scope: string | undefined, label: string, hasChildren: boolean) => {
      const loop = binding.operator === "for-each" || binding.operator === "for-each-group";
      if (loop && (binding.mapChildren || hasChildren || mapper && !binding.duplicateOf)) walk({}, scope, label);
      else if (!binding.operator || binding.operator === "direct" || binding.operator === "copy-of") walk(literalValue(ruleValue(binding)), scope, label);
    };
    if (rule) check(rule, owner, display, descendants);
    else if (supplied !== undefined) walk(supplied, owner, display);
    else if (descendants) walk({}, owner, display);
    copies.forEach((copy, index) => check(copy, copy.occurrenceId, `${display} (duplicate ${index + 1})`,
      !!parentPaths.get(copy.occurrenceId)?.has(path)));
  };
  for (const field of tree.values()) visit(field, undefined, undefined, "");
  return [...missing].map(([path, target]) => ({ path, target }));
}
