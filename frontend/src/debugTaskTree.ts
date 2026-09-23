// Resolve only known design-time targets. Dynamic expressions must not be guessed.
export function debugCallTarget(tasks: any[], activity: any) {
  const dynamic = String(activity.config?.dynamicTaskId || "").trim();
  const deferred = dynamic.includes("${");
  const targetId = (deferred ? activity.config?.taskId : dynamic || activity.config?.taskId) || "";
  const target = tasks.find(task => task.kind === "subtask" &&
    (task.id === targetId || task.name.toLowerCase() === String(targetId).toLowerCase()));
  return { target, deferred };
}

export function debugTaskMatches(tasks: any[], task: any, term: string, ancestors: string[] = []): boolean {
  if (ancestors.includes(task.id)) return false;
  const matches = (item: any) => `${item.name} ${item.id} ${item.type || ""}`.toLowerCase().includes(term);
  if (matches(task)) return true;
  return task.activities.some((activity: any) => {
    if (matches(activity)) return true;
    const { target } = activity.type === "call_task" ? debugCallTarget(tasks, activity) : {};
    return target && debugTaskMatches(tasks, target, term, [...ancestors, task.id]);
  });
}
