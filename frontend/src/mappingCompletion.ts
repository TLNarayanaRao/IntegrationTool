export function completeMapping(prefix: string, suffix: string, insertion: string): string {
  const replacement = prefix.replace(/\$\{?[\w.@\[\]-]+$|[\w.@\[\]-]+$/, () => insertion);
  return replacement + (suffix.startsWith("}") && insertion.endsWith("}") ? suffix.slice(1) : suffix);
}
