import type { SubtaskInputFormat, SubtaskInputReport } from "./executionSetup";

export type InputMethod = "form" | "json" | "file" | "xml" | "xml-file" | "empty";
export type FileInputMethod = "file" | "xml-file";
type InputFile = {name: string; text?: string; error?: string};
export type InputField = {
  key: string; path: string[]; label: string; type: string; required: boolean; example: unknown;
};
export type SubtaskInputDraft = {
  method: InputMethod;
  values: Record<string, string>;
  json: string;
  file?: InputFile;
  xml?: string;
  "xml-file"?: InputFile;
};

export function subtaskInputFormat(method: InputMethod): SubtaskInputFormat {
  return method === "xml" || method === "xml-file" ? "xml" : "json";
}

export function selectedSubtaskFile(draft: SubtaskInputDraft) {
  return draft.method === "file" || draft.method === "xml-file" ? draft[draft.method] : undefined;
}

export function decodeSubtaskXmlFile(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  const [a, b, c, d] = bytes;
  if ((a === 0 && b === 0 && c === 0 && (d === 0x3c || d === 0xfe)) ||
      (a === 0xff && b === 0xfe && c === 0 && d === 0) ||
      (a === 0 && b === 0 && c === 0xfe && d === 0xff) ||
      (a === 0x3c && b === 0 && c === 0 && d === 0))
    throw new Error("Save the XML file as UTF-8 or UTF-16 and try again.");
  const header = new TextDecoder("windows-1252").decode(bytes.subarray(0, 512));
  const declared = header.match(/^<\?xml\s[^?]*?\bencoding\s*=\s*["']([^"']+)["']/i)?.[1];
  const encoding = a === 0xff && b === 0xfe || a === 0x3c && b === 0 ? "utf-16le"
    : a === 0xfe && b === 0xff || a === 0 && b === 0x3c ? "utf-16be"
    : a === 0xef && b === 0xbb && c === 0xbf ? "utf-8" : declared || "utf-8";
  return new TextDecoder(encoding, {fatal: true}).decode(buffer);
}

export function guidedInputFields(report: SubtaskInputReport): InputField[] {
  if (report.format === "none" || report.example === undefined) return [];
  const descriptions = new Map(report.fields?.map(field => [field.path, field]));
  const fields: InputField[] = [];
  const visit = (example: unknown, path: string[]) => {
    const label = path.join(".") || "Input value";
    const description = descriptions.get(label);
    const type = Array.isArray(example) ? "array" : description?.type || (example === null ? "null" : typeof example);
    if (example && typeof example === "object" && !Array.isArray(example) && Object.keys(example).length && !type.includes("|")) {
      for (const [key, value] of Object.entries(example)) visit(value, [...path, key]);
    } else {
      fields.push({key: JSON.stringify(path), path, label, type, required: !!description?.required, example});
    }
  };
  visit(report.example, []);
  return fields;
}

export function newSubtaskInputDraft(report?: SubtaskInputReport): SubtaskInputDraft {
  const fields = report && guidedInputFields(report);
  return {method: fields?.length ? "form" : "json", values: {}, json: "{}"};
}

export function inputControl(type: string) {
  if (type === "boolean") return "boolean";
  if (["number", "integer", "decimal", "int", "long", "float", "double"].includes(type)) return "number";
  if (["array", "object", "any", "null"].includes(type) || /[|\[]/.test(type)) return "json";
  return "text";
}

export function exampleFieldValue(field: InputField) {
  return inputControl(field.type) === "json" ? JSON.stringify(field.example, null, 2) : String(field.example ?? "");
}

export function readSubtaskInput(draft: SubtaskInputDraft, fields: InputField[]): unknown {
  const readJson = (text: string, description: string) => {
    try { return JSON.parse(text) as unknown; }
    catch { throw new Error(`${description} must contain valid JSON.`); }
  };
  if (draft.method === "empty") return {};
  if (draft.method === "json") return draft.json.trim() ? readJson(draft.json, "JSON input") : {};
  if (draft.method === "xml") {
    if (!draft.xml?.trim()) throw new Error("Paste XML before validating the input.");
    return draft.xml;
  }
  if (draft.method === "file" || draft.method === "xml-file") {
    const file = draft[draft.method];
    if (file?.error) throw new Error(file.error);
    if (file?.text === undefined) throw new Error(draft.method === "xml-file" ? "Choose an XML file first." : "Choose a JSON file first.");
    return draft.method === "xml-file" ? file.text : readJson(file.text, file.name);
  }
  let payload: unknown = {};
  for (const field of fields) {
    const text = draft.values[field.key];
    if (text === undefined) continue;
    const control = inputControl(field.type);
    const value = control === "text" ? text : readJson(text, field.label);
    if (control === "number" && typeof value !== "number") throw new Error(`${field.label} must be a number.`);
    if (!field.path.length) { payload = value; continue; }
    let parent = payload as Record<string, unknown>;
    for (const key of field.path.slice(0, -1)) {
      if (!Object.prototype.hasOwnProperty.call(parent, key))
        Object.defineProperty(parent, key, {value: {}, enumerable: true, configurable: true, writable: true});
      parent = parent[key] as Record<string, unknown>;
    }
    Object.defineProperty(parent, field.path[field.path.length - 1], {value, enumerable: true, configurable: true, writable: true});
  }
  return payload;
}
