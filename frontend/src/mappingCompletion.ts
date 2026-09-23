export function mappingPathSuggestions(paths: string[], prefix: string): string[] {
  const token = prefix.match(/[\w.@\[\]-]+$/)?.[0] || "";
  if (!token) return [];
  const candidates = new Set<string>();
  for (const path of paths) {
    // Include intermediate objects even when metadata lists only leaf fields.
    const parts = path.split(".");
    for (let count = 1; count <= parts.length; count++) candidates.add(parts.slice(0, count).join("."));
  }
  return [...candidates].filter(path => path.toLowerCase().startsWith(token.toLowerCase()) && path !== token)
    .sort((a, b) => a.split(".").length - b.split(".").length || a.localeCompare(b)).slice(0, 30);
}

export function completeMapping(prefix: string, suffix: string, insertion: string): string {
  const replacement = prefix.replace(/\$\{?[\w.@\[\]-]+$|[\w.@\[\]-]+$/, () => insertion);
  return replacement + (suffix.startsWith("}") && insertion.endsWith("}") ? suffix.slice(1) : suffix);
}
