const supportedMethods = new Set(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"]);

export function endpointRequestFile(value: unknown, methods: unknown): string | null {
  if (typeof value !== "string" || !Array.isArray(methods) || /[\x00-\x20\x7f]/.test(value)) return null;
  let url: URL;
  try { url = new URL(value); } catch { return null; }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  const verbs = [...new Set(methods.map(item => typeof item === "string" ? item.toUpperCase() : ""))]
    .filter(item => supportedMethods.has(item));
  if (!verbs.length) return null;
  const parameters = new Set<string>();
  const path = url.pathname.replace(/%7B([a-zA-Z_][a-zA-Z0-9_.-]*)%7D/gi, (_match, name: string) => {
    parameters.add(name);
    return "{{" + name + "}}";
  });
  return [
    "# MINA HTTP requests",
    "# Fill in required query parameters, headers, credentials, and body before sending.",
    ...Array.from(parameters, name => "@" + name + " = replace-me"),
    ...verbs.map(method => "\n### " + method + "\n" + method + " " + url.origin + path),
    "",
  ].join("\n");
}
