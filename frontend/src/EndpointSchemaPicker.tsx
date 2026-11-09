import { useEffect, useRef, useState } from "react";
import type { SchemaDoc } from "./SchemaStudio";
import "./http-endpoint-setup.css";

export type SchemaChoice = { source: string; text: string; name?: string };

export function schemaText(choice: SchemaChoice, schemas: SchemaDoc[], label: string) {
  if (!choice.source) return undefined;
  const content = (choice.source.startsWith("@") ? choice.text : schemas.find(schema => schema.id === choice.source)?.content)?.trim();
  if (!content) throw new Error(`Provide a ${label.toLowerCase()} schema or select No schema.`);
  if (content.startsWith("<") && choice.source !== "@inline") {
    const doc = new DOMParser().parseFromString(content, "application/xml");
    if (doc.querySelector("parsererror") || doc.documentElement.localName !== "schema" ||
        doc.documentElement.namespaceURI !== "http://www.w3.org/2001/XMLSchema") {
      throw new Error(`${label} schema must be a well-formed XSD document.`);
    }
  } else {
    try {
      const parsed = JSON.parse(content);
      if (typeof parsed !== "boolean" && (!parsed || typeof parsed !== "object" || Array.isArray(parsed))) throw new Error();
    } catch {
      throw new Error(choice.source === "@inline"
        ? "Enter a valid JSON Schema. Use Browse for XSD files."
        : `${label} schema must be a JSON Schema object, boolean, or XSD document.`);
    }
  }
  return content;
}

export function schemaChoiceName(choice: SchemaChoice, schemas: SchemaDoc[]) {
  return choice.name || schemas.find(schema => schema.id === choice.source)?.name
    || (choice.source === "@inline" ? "Inline JSON Schema" : undefined);
}

export function savedSchemaChoice(value: unknown, name: string | undefined, schemas: SchemaDoc[]): SchemaChoice {
  if (value === undefined || value === null || value === "") return { source: "", text: "" };
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const projectSchema = name && schemas.find(schema => schema.name === name && schema.content.trim() === text.trim());
  return { source: projectSchema ? projectSchema.id : "@saved", text, name: name || (text.trimStart().startsWith("<") ? "Saved XSD" : "Saved JSON Schema") };
}

export default function EndpointSchemaPicker({ label, value, schemas, onChange }: {
  label: string; value: SchemaChoice; schemas: SchemaDoc[]; onChange: (value: SchemaChoice) => void;
}) {
  const [jsonDraft, setJsonDraft] = useState<string | null>(null);
  const [error, setError] = useState("");
  const pendingRead = useRef(0);
  const latestChange = useRef(onChange);
  latestChange.current = onChange;
  useEffect(() => () => { pendingRead.current++; }, []);

  const commit = (choice: SchemaChoice) => {
    try {
      const text = schemaText(choice, schemas, label) || "";
      latestChange.current({ ...choice, text });
      setJsonDraft(null);
      setError("");
    } catch (error) {
      setError((error as Error).message);
    }
  };
  const choose = (source: string) => {
    pendingRead.current++;
    setError("");
    if (source === "@selected") {
      setJsonDraft(null);
      return;
    }
    if (source === "@inline") {
      setJsonDraft(value.text.trimStart().startsWith("<") ? "" : value.text);
      return;
    }
    commit(source === value.source ? value : { source, text: "" });
  };
  const browse = async (file: File) => {
    const read = ++pendingRead.current;
    setJsonDraft(null);
    setError("");
    try {
      if (file.size > 8 * 1024 * 1024) throw new Error("Select a schema file up to 8 MiB.");
      const text = await file.text();
      if (read === pendingRead.current) commit({ source: "@file", text, name: file.name });
    } catch (error) {
      if (read === pendingRead.current) setError((error as Error).message);
    }
  };
  const selected = value.source.startsWith("@") ? "@selected" : value.source;
  return (
    <div className="endpoint-schema-choice">
      <label>{label} schema
        <select value={jsonDraft === null ? selected : "@inline"} onChange={event => choose(event.target.value)}>
          <option value="">No schema</option>
          {selected === "@selected" && <option value="@selected">{schemaChoiceName(value, schemas)}</option>}
          {schemas.map(schema => <option key={schema.id} value={schema.id}>{schema.name}</option>)}
          <option value="@inline">Enter JSON Schema…</option>
        </select>
      </label>
      <label className="endpoint-schema-browse">
        Browse {label.toLowerCase()} schema…
        <input type="file" accept=".xsd,.json,application/xml,application/json" onChange={event => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (file) void browse(file);
        }}/>
      </label>
      {jsonDraft !== null && <>
        <label>Inline {label.toLowerCase()} JSON Schema
          <textarea rows={5} spellCheck={false} value={jsonDraft} onChange={event => setJsonDraft(event.target.value)}/>
        </label>
        <div className="endpoint-schema-actions">
          <button type="button" onClick={() => { setJsonDraft(null); setError(""); }}>Cancel</button>
          <button type="button" onClick={() => commit({ source: "@inline", text: jsonDraft })}>Use JSON schema</button>
        </div>
      </>}
      {error && <small role="alert" className="endpoint-setup-error">{error}</small>}
    </div>
  );
}
