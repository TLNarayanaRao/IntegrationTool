export function studioObjectName(value: string): string {
  return value.trim().replace(/\s+/g, "-");
}
