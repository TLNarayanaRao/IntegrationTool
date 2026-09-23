/** A task is a separate activity namespace. Preserve its internal graph verbatim. */
export function copyTask<T extends { id: string; name: string }>(source: T, id: string, name: string): T {
  return { ...structuredClone(source), id, name };
}
