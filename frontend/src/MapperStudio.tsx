import React, { useMemo, useState } from "react";
import { Check, FlaskConical, Plus, Sparkles, Trash2, X } from "lucide-react";

type Rule = { target: string; source?: string; constant?: any; functions?: any[]; confidence?: number; enabled?: boolean };
const sampleSource = { customer: { id: "C-100", firstName: "Ada", lastName: "Lovelace", postalCode: "85001" }, order: { total: 42.5 } };
const sampleTarget = { account: { identifier: "", givenName: "", familyName: "", zip: "" }, amount: 0 };
const seeded = (value: any, fallback: any) => value && typeof value === "object" && Object.keys(value).length ? value : fallback;

function schemaObject(text: string) {
  try { return JSON.parse(text); } catch {
    const names = Array.from(text.matchAll(/<(?:xs|xsd):element\b[^>]*\bname=["']([^"']+)["'][^>]*>/gi), (match) => match[1]);
    if (!names.length) throw new Error("Schema must be valid JSON, sample JSON, or XSD containing xs:element declarations.");
    return { type: "object", properties: Object.fromEntries(names.map((name) => [name, { type: "string" }])) };
  }
}
function pathsFrom(text: string) {
  try {
    const walk = (value: any, prefix = ""): string[] => value && typeof value === "object" && !Array.isArray(value)
      ? Object.entries(value.properties || value).flatMap(([key, child]: any) => child && typeof child === "object" && (child.properties || (!child.type && !Array.isArray(child))) ? walk(child, `${prefix}${key}.`) : [`${prefix}${key}`]) : [];
    return walk(schemaObject(text));
  } catch { return []; }
}

export default function MapperStudio({ config, schemas = [], onClose, onSave }: any) {
  const selectedSource = schemas.find((schema: any) => schema.id === config.sourceSchemaId);
  const selectedTarget = schemas.find((schema: any) => schema.id === config.targetSchemaId);
  const [sourceId, setSourceId] = useState(config.sourceSchemaId || "inline"), [targetId, setTargetId] = useState(config.targetSchemaId || "inline");
  const [sourceText, setSourceText] = useState(config.sourceSchemaText || selectedSource?.content || JSON.stringify(seeded(config.sourceSchema, sampleSource), null, 2));
  const [targetText, setTargetText] = useState(config.targetSchemaText || selectedTarget?.content || JSON.stringify(seeded(config.targetSchema, sampleTarget), null, 2));
  const [inputText, setInputText] = useState(JSON.stringify(seeded(config.sampleInput, sampleSource), null, 2));
  const [rules, setRules] = useState<Rule[]>(Array.isArray(config.mappings) ? config.mappings : []), [threshold, setThreshold] = useState(config.threshold || 70);
  const [result, setResult] = useState(""), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const sources = useMemo(() => pathsFrom(sourceText), [sourceText]), targets = useMemo(() => pathsFrom(targetText), [targetText]);
  const chooseSchema = (side: "source" | "target", id: string) => {
    const schema = schemas.find((item: any) => item.id === id);
    if (side === "source") { setSourceId(id); if (schema) setSourceText(schema.content); }
    else { setTargetId(id); if (schema) setTargetText(schema.content); }
  };
  const suggest = async () => {
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/mapper/suggest", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sourceSchema: schemaObject(sourceText), targetSchema: schemaObject(targetText), threshold }) });
      const output = await response.json(), selected = (output.recommendations || []).filter((item: any) => item.selected);
      setRules(selected.map((item: any) => ({ source: item.selected, target: item.target, confidence: item.confidence, functions: [], enabled: true })));
      setMessage(`${selected.length} mappings recommended. Review before saving.`);
    } catch (error: any) { setMessage(error.message); }
    setBusy(false);
  };
  const test = async () => {
    try {
      const response = await fetch("/api/mapper/test", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input: JSON.parse(inputText), mappings: rules }) });
      const output = await response.json(); setResult(JSON.stringify(output.output || output, null, 2));
    } catch (error: any) { setResult(error.message); }
  };
  const update = (index: number, key: string, value: any) => setRules((items) => items.map((rule, current) => current === index ? { ...rule, [key]: value } : rule));
  const save = () => {
    try { onSave({ sourceSchemaId: sourceId === "inline" ? "" : sourceId, targetSchemaId: targetId === "inline" ? "" : targetId, sourceSchemaText: sourceText, targetSchemaText: targetText, sourceSchema: schemaObject(sourceText), targetSchema: schemaObject(targetText), sampleInput: JSON.parse(inputText), threshold, mappings: rules, language: "JSONPath / functions" }); }
    catch (error: any) { setMessage(error.message); }
  };
  const schemaPane = (side: "source" | "target", title: string, id: string, text: string, setText: (value: string) => void, fieldPaths: string[]) => <section className="schema-pane"><div className="mapper-schema-title"><span><h3>{side === "source" ? "INPUT DATA STRUCTURE" : `${title} STRUCTURE`}</h3><small>{fieldPaths.length} addressable fields</small></span>{side === "target" ? <select aria-label={`${title} project schema`} value={id} onChange={(event) => chooseSchema(side, event.target.value)}><option value="inline">Inline schema…</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select> : <i>Runtime data source</i>}</div><textarea aria-label={`${title} schema editor`} value={text} onChange={(event) => { setText(event.target.value); side === "source" ? setSourceId("inline") : setTargetId("inline"); }} spellCheck={false}/><div className="path-list">{fieldPaths.map((path) => <code key={path}>{path}</code>)}</div>{side === "target" && <><h3>TEST INPUT / OUTPUT</h3><textarea aria-label="Mapper test input" value={inputText} onChange={(event) => setInputText(event.target.value)} spellCheck={false}/><pre>{result || "Run Test mapping to preview output."}</pre></>}</section>;
  return <div className="modal-backdrop mapper-backdrop"><div className="mapper-studio"><header><div><Sparkles/><span><b>Visual AI Mapper</b><small>Schema-aware transformation with executable mapping rules</small></span></div><button aria-label="Close mapper" onClick={onClose}><X/></button></header><div className="mapper-toolbar"><label>Automap threshold <input type="range" min="40" max="100" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))}/><b>{threshold}%</b></label><button className="primary" onClick={suggest} disabled={busy}><Sparkles/>{busy ? "Analyzing…" : "AI Map"}</button><button onClick={test}><FlaskConical/> Test mapping</button></div><main>{schemaPane("source", "Source", sourceId, sourceText, setSourceText, sources)}<section className="mapping-pane"><h3>MAPPING EXPRESSIONS <small>{rules.length}</small></h3>{rules.map((rule, index) => <div className="map-rule" key={index}><select value={rule.source || ""} onChange={(event) => update(index, "source", event.target.value)}><option value="">Source…</option>{sources.map((path) => <option key={path}>{path}</option>)}</select><span>→</span><select value={rule.target} onChange={(event) => update(index, "target", event.target.value)}><option value="">Target…</option>{targets.map((path) => <option key={path}>{path}</option>)}</select><input title="Functions separated by comma" placeholder="trim, upper" value={(rule.functions || []).map((item: any) => typeof item === "string" ? item : item.name).join(", ")} onChange={(event) => update(index, "functions", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))}/>{rule.confidence != null && <i className={rule.confidence >= threshold ? "strong" : ""}>{rule.confidence}%</i>}<button aria-label="Delete mapping" onClick={() => setRules((items) => items.filter((_, current) => current !== index))}><Trash2/></button></div>)}<button className="add-rule" onClick={() => setRules((items) => [...items, { source: sources[0] || "", target: targets[0] || "", functions: [], enabled: true }])}><Plus/> Add mapping</button>{message && <p className="mapper-message">{message}</p>}<div className="function-library"><b>Functions</b>{["trim", "upper", "lower", "string", "number", "boolean", "replace", "substring", "split", "join", "default"].map((name) => <code key={name}>{name}</code>)}</div></section>{schemaPane("target", "Target", targetId, targetText, setTargetText, targets)}</main><footer><span><Check/> Manual overrides remain editable and take precedence.</span><button onClick={onClose}>Cancel</button><button className="primary" onClick={save}>Save mapper</button></footer></div></div>;
}
