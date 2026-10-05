/** Design-time checks only; dynamic expression results are checked at runtime. */
export function validateMapping(value: unknown, fieldType: string, paths: string[] = []): string {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const stack: string[] = [];
  let quote = "", escaped = false, unquoted = "";
  for (const character of text) {
    if (quote) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === quote) quote = "";
      unquoted += " ";
      continue;
    }
    if (character === "'" || character === '"') { quote = character; unquoted += " "; continue; }
    unquoted += character;
    if ("([{".includes(character)) stack.push(character);
    else if (")]}".includes(character) && stack.pop() !== ({ ")": "(", "]": "[", "}": "{" } as Record<string, string>)[character]) return "Check the expression's brackets and parentheses.";
  }
  if (quote) return "Close the string with a matching quote.";
  if (stack.length) return "Close the expression's brackets and parentheses.";
  for (const match of unquoted.matchAll(/\$\{([^}]*)\}/g)) {
    const path = match[1].trim();
    if (!/^[\w@-]+(?:\.[\w@-]+|\[\d+\])*$/.test(path)) return "Enter a valid source field path inside ${…}.";
    const root = path.split(/[.[]/)[0];
    if (["properties", "vars", "context", "tasks"].includes(root)) continue;
    if (root === "activities") {
      const activityRoot = path.split('.').slice(0, 3).join('.');
      const fields = paths.filter(candidate => candidate.startsWith(`${activityRoot}.`));
      if (fields.length && !fields.some(candidate => candidate === path || candidate.startsWith(`${path}.`))) return `Source field not found: ${path}.`;
      continue;
    }
    const normalized = path.replace(/\[\d+\]/g, "").replace(/\.\d+(?=\.|$)/g, "");
    const candidates = paths.filter(candidate => candidate === root || candidate.startsWith(`${root}.`));
    if (!candidates.length) return `Unknown mapping source: ${root}.`;
    if (candidates.length > 1 && !candidates.some(candidate => candidate === normalized || candidate.startsWith(`${normalized}.`))) return `Source field not found: ${path}.`;
  }
  if (unquoted.includes("${") || /[\w:-]+\s*\(/.test(unquoted)) return "";
  if (/^\$/.test(text)) return "Use ${source.field} for a field mapping.";
  const types = fieldType.toLowerCase().replace(/\bxs[d]?:/g, "").split("|");
  const quoted = /^(?:"(?:[^"\\]|\\[\s\S])*"|'(?:[^'\\]|\\[\s\S])*')$/.test(text);
  let literal: unknown = quoted ? text.slice(1, -1) : text;
  if (!quoted) { try { literal = JSON.parse(text); } catch { /* Plain text is a string constant. */ } }
  const valid = types.some(type => {
    if (["string", "binary", "normalizedstring", "token", "date", "datetime", "time", "anyuri", "language", "name", "ncname", "id", "idref", "hexbinary", "base64binary"].includes(type)) return quoted;
    if (type === "any" || type === "anytype") return quoted || typeof literal !== "string";
    if (type.includes("array") || type.endsWith("[]")) return Array.isArray(literal);
    if (["object", "json", "complex"].includes(type)) return literal !== null && typeof literal === "object" && !Array.isArray(literal);
    if (type === "boolean") return literal === true || literal === false;
    if (["integer", "int", "long", "short", "byte", "nonnegativeinteger", "positiveinteger"].includes(type)) return !quoted && /^-?\d+$/.test(text) && Number.isSafeInteger(Number(text)) && (type !== "nonnegativeinteger" || Number(text) >= 0) && (type !== "positiveinteger" || Number(text) > 0);
    if (["number", "decimal", "double", "float"].includes(type)) return !quoted && /^-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(text) && Number.isFinite(Number(text));
    return true;
  });
  if (valid) return "";
  if (types.some(type => ["string", "binary", "normalizedstring", "token", "date", "datetime", "time", "anyuri", "language", "name", "ncname", "id", "idref", "hexbinary", "base64binary"].includes(type)) || ((types.includes("any") || types.includes("anytype")) && typeof literal === "string")) return "String constants must be enclosed in matching single or double quotes.";
  return `Enter a valid ${fieldType} value or map a source field.`;
}
