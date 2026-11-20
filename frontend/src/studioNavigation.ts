export type NavigationPackage = "tasks" | "resources" | "schemas";
export type StudioLocation =
  | { kind: "project" }
  | { kind: "task"; id: string; activityId?: string }
  | { kind: "resource" | "schema"; id: string }
  | { kind: "package"; category: NavigationPackage; path: string };

export type StudioNavigation = { entries: StudioLocation[]; index: number };
export type NavigationActions = {
  back?: () => void; forward?: () => void; up?: () => void; upLabel: string;
  recent: { index: number; label: string }[];
  jump: (index: number) => void;
};

export const NAVIGATION_LIMIT = 15;
export const locationKey = (location: StudioLocation): string => {
  if (location.kind === "project") return "project";
  if (location.kind === "package") return JSON.stringify([location.kind, location.category, location.path]);
  return JSON.stringify([location.kind, location.id, location.kind === "task" ? location.activityId : undefined]);
};

export function rememberLocation(history: StudioNavigation, location: StudioLocation): StudioNavigation {
  const current = history.entries[history.index];
  if (current && locationKey(current) === locationKey(location)) return history;
  const entries = [...history.entries.slice(0, history.index + 1), location].slice(-(NAVIGATION_LIMIT + 1));
  return { entries, index: entries.length - 1 };
}

export function navigationIndex(history: StudioNavigation, direction: -1 | 1, available: (location: StudioLocation) => boolean) {
  for (let index = history.index + direction; index >= 0 && index < history.entries.length; index += direction) {
    if (available(history.entries[index])) return index;
  }
  return -1;
}

export function recentNavigationEntries(history: StudioNavigation, labelFor: (location: StudioLocation) => string | undefined) {
  return history.entries.flatMap((location, index) => {
    if (index === history.index) return [];
    const label = labelFor(location);
    return label === undefined ? [] : [{ index, label }];
  }).reverse().slice(0, NAVIGATION_LIMIT);
}

export function isTaskSelectionChange<T extends { active_task_id: string }>(previous: T, next: T): boolean {
  const keys = Object.keys(next) as (keyof T)[];
  return previous.active_task_id !== next.active_task_id && keys.length === Object.keys(previous).length &&
    keys.every(key => key === "active_task_id" || Object.is(previous[key], next[key]));
}
