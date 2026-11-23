export const groupCatalog = {
  scope: { label: "Scope", category: "Scopes", help: "Run a set of activities once. Add local variables or fault handlers in Advanced." },
  none: { label: "None", category: "Scopes", help: "Run the enclosed activities once." },
  critical_section: { label: "Critical Section", category: "Scopes", help: "Let one job at a time enter this group. Leave the lock name blank for a lock dedicated to this group." },
  transaction_jdbc: { label: "JDBC Transaction", category: "Scopes", help: "Commit or roll back JDBC work together. Select the connection used by the enclosed JDBC activities." },
  if: { label: "If", category: "Conditions and loops", help: "Run the group once when its condition is true. Otherwise, skip to the next activity." },
  while: { label: "While True", category: "Conditions and loops", help: "Check the condition before each pass. The group can run zero times." },
  repeat: { label: "Repeat Until True", category: "Conditions and loops", help: "Run the group at least once. Stop when the condition becomes true." },
  repeat_on_error: { label: "Repeat on Error", category: "Conditions and loops", help: "Retry the whole group after an unhandled fault, up to the retry limit." },
  for_each: { label: "For Each", category: "Conditions and loops", help: "Run the group for each collection item or number in a counter range." },
  iterate: { label: "Iterate", category: "Conditions and loops", help: "Run the group once per collection item or batch." },
  parallel_for_each: { label: "Parallel For Each", category: "Routing", help: "Process collection items concurrently and return their results in input order." },
  pick_first: { label: "Pick First", category: "Routing", help: "Choose the first eligible branch based on its transitions." },
  first_successful: { label: "First Successful", category: "Routing", help: "Try branches in incoming transition order until one completes successfully." },
  scatter_gather: { label: "Scatter-Gather", category: "Routing", help: "Run separate branches concurrently and wait for their results before continuing." },
  async: { label: "Background Scope", category: "Routing", help: "Start the enclosed activities as a background job and let the main task continue." },
} as const;

export type GroupType = keyof typeof groupCatalog;
export const groupCategories = ["Scopes", "Conditions and loops", "Routing"] as const;
export const groupTypes = Object.keys(groupCatalog) as GroupType[];

type Edge = { source: string; target: string; type?: string };

export function describeGroupWiring(type: GroupType, members: ReadonlySet<string>, edges: readonly Edge[]) {
  const entering = edges.filter(edge => !members.has(edge.source) && members.has(edge.target));
  const leaving = edges.filter(edge => members.has(edge.source) && !members.has(edge.target));
  const internal = edges.filter(edge => members.has(edge.source) && members.has(edge.target));
  const internalTargets = new Set(internal.map(edge => edge.target));
  const entryIds = [...new Set(entering.length ? entering.map(edge => edge.target) : [...members].filter(id => !internalTargets.has(id)))];
  const nextIds = [...new Set(leaving.map(edge => edge.target))];
  const multi = type === "scatter_gather" || type === "first_successful";
  const routed = multi || type === "parallel_for_each" || type === "async";
  const success = (edge: Edge) => !edge.type || edge.type === "success";
  const issues: string[] = [];
  if (!members.size) issues.push("Select at least one activity or include a child group.");
  else if (multi && (entryIds.length < 2 || new Set(entering.map(edge => edge.source)).size !== 1 || entering.some(edge => !success(edge)))) {
    issues.push("Connect one preceding activity to two or more route starts using Success transitions.");
  } else if (!multi && type !== "pick_first" && entryIds.length !== 1) {
    issues.push("Give the group a single entry activity.");
  }
  if (members.size && routed && (nextIds.length !== 1 || leaving.some(edge => !success(edge)))) {
    issues.push("Connect each route exit to the same activity outside the group using Success transitions.");
  }
  if (members.size && !multi && type !== "pick_first") {
    const internalSources = new Set(internal.map(edge => edge.source));
    const exits = new Set(leaving.length ? leaving.map(edge => edge.source) : [...members].filter(id => !internalSources.has(id)));
    if (exits.size !== 1) issues.push("Give the group a single exit activity.");
  }
  if (multi && entryIds.length > 1) {
    const next = new Map<string, string[]>();
    for (const {source, target} of internal) next.set(source, [...(next.get(source) ?? []), target]);
    const reached = new Set<string>();
    const exitSources = new Set(leaving.map(edge => edge.source));
    let overlap = false;
    let missingExit = false;
    for (const entry of entryIds) {
      const route = new Set<string>();
      const stack = [entry];
      while (stack.length) {
        const id = stack.pop()!;
        if (route.has(id)) continue;
        route.add(id);
        if (reached.has(id)) overlap = true;
        reached.add(id);
        for (const target of next.get(id) ?? []) stack.push(target);
      }
      if (![...route].some(id => exitSources.has(id))) missingExit = true;
    }
    if (overlap) issues.push("Keep routes separate inside the group. Join them at the activity outside it.");
    if (reached.size < members.size) issues.push("Connect every group activity to a route start.");
    if (missingExit) issues.push("Connect each route to the continuation.");
  }
  return { entryIds, nextIds, issues };
}
