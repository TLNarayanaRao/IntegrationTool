export type CloseEditorsMode = "one" | "left" | "right" | "others" | "all";

export function rememberClosedTaskEditors(history: string[], before: string[], after: string[], activeId: string) {
  const remaining = new Set(after);
  const closed = before.filter(id => !remaining.has(id));
  const newest = closed.includes(activeId)
    ? [activeId, ...closed.filter(id => id !== activeId).reverse()]
    : closed.reverse();
  return [...new Set([...newest, ...history.filter(id => !remaining.has(id))])].slice(0, 15);
}

export function closeTaskEditors(ids: string[], activeId: string, targetId: string, mode: CloseEditorsMode) {
  const index = ids.indexOf(targetId);
  const openIds = mode === "all" ? [] : index < 0 ? ids
    : mode === "others" ? [targetId]
      : mode === "left" ? ids.slice(index)
        : mode === "right" ? ids.slice(0, index + 1)
          : ids.filter(id => id !== targetId);
  const activeTaskId = openIds.includes(activeId) ? activeId : mode !== "one" && openIds.includes(targetId) ? targetId : openIds[Math.min(Math.max(index, 0), openIds.length - 1)] || null;
  return {openIds, activeTaskId};
}
