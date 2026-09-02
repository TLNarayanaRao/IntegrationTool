import React, { useMemo, useState } from "react";
import { Check, Copy, FlaskConical, Plus, Power, Sparkles, Trash2, X } from "lucide-react";
import { mapperFunctionCatalog, mapperFunctionCategories, type MapperFunctionDefinition } from "./mapper-functions";

type Rule = { target: string; targetType?: string; source?: string; select?: string; operator?: string; constant?: any; functions?: any[]; confidence?: number; enabled?: boolean; pending?: boolean };
const sampleSource = { customer: { id: "C-100", firstName: "Ada", lastName: "Lovelace", postalCode: "85001" }, order: { total: 42.5 } };
const sampleTarget = { account: { identifier: "", givenName: "", familyName: "", zip: "" }, amount: 0 };
const seeded = (value: any, fallback: any) => value && typeof value === "object" && Object.keys(value).length ? value : fallback;

function splitPipeline(value: string) {
  const output: string[] = []; let start = 0, depth = 0, quote = "";
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (quote) { if (character === quote && value[index - 1] !== "\\") quote = ""; }
    else if (character === "\"" || character === "'") quote = character;
    else if (character === "(") depth += 1;
    else if (character === ")") depth = Math.max(0, depth - 1);
    else if (character === "," && depth === 0) { output.push(value.slice(start, index).trim()); start = index + 1; }
  }
  if (value.slice(start).trim()) output.push(value.slice(start).trim());
  return output;
}
function parseArgument(value: string): any {
  const text = value.trim();
  if (/^(['"]).*\1$/.test(text)) return text.slice(1, -1);
  if (/^-?\d+(?:\.\d+)?$/.test(text)) return Number(text);
  if (text === "true" || text === "false") return text === "true";
  if (text === "null") return null;
  try { return JSON.parse(text); } catch { return text; }
}
function parseFunctions(value: string): any[] {
  return splitPipeline(value).map((token) => {
    const match = token.match(/^([\w-]+)(?:\((.*)\))?$/s);
    return match ? (match[2] === undefined || !match[2].trim() ? match[1] : { name: match[1], args: splitPipeline(match[2]).map(parseArgument) }) : token;
  });
}
function formatFunctions(functions: any[] = []) {
  return functions.map((item) => typeof item === "string" ? item : `${item.name}(${(item.args || []).map((arg: any) => typeof arg === "string" ? JSON.stringify(arg) : JSON.stringify(arg)).join(",")})`).join(", ");
}

function schemaObject(text: string): any {
  try { return JSON.parse(text); } catch {
    if (!/<(?:xs|xsd):schema\b/i.test(text)) throw new Error("Schema must be valid JSON, sample JSON, or XSD containing xs:element declarations.");
    return text;
  }
}
function pathsFrom(text: string) {
  try {
    if (/<(?:xs|xsd):schema\b/i.test(text)) {
      const document = new DOMParser().parseFromString(text, "application/xml"), local = (element: Element) => element.localName || element.tagName.split(":").pop() || "";
      if (document.querySelector("parsererror")) throw new Error("Invalid XSD");
      const directElements = (container: Element): Element[] => Array.from(container.children).flatMap((child: Element): Element[] => local(child) === "element" ? [child] : ["sequence", "choice", "all", "complexType"].includes(local(child)) ? directElements(child) : []);
      const paths: string[] = [];
      const walk = (element: Element, prefix = "") => {
        const name = element.getAttribute("name") || element.getAttribute("ref")?.split(":").pop(); if (!name) return;
        const path = prefix ? `${prefix}.${name}` : name; paths.push(path);
        const complex = Array.from(element.children).find((child) => local(child) === "complexType");
        if (complex) {
          Array.from(complex.getElementsByTagNameNS("*", "attribute")).forEach((attribute) => { const attributeName = attribute.getAttribute("name"); if (attributeName) paths.push(`${path}.@${attributeName}`); });
          directElements(complex).forEach((child) => walk(child, path));
        }
      };
      Array.from(document.documentElement.children).filter((element) => local(element) === "element").forEach((element) => walk(element));
      return [...new Set(paths)];
    }
    const walk = (value: any, prefix = ""): string[] => value && typeof value === "object" && !Array.isArray(value)
      ? Object.entries(value.properties || value).flatMap(([key, child]: any) => {
        const path = `${prefix}${key}`;
        if (child?.type === "array") return [path, ...walk(child.items || {}, `${path}.`)];
        if (child && typeof child === "object" && (child.properties || (!child.type && !Array.isArray(child)))) return [path, ...walk(child, `${path}.`)];
        return [path];
      }) : [];
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
  const [selectedRule, setSelectedRule] = useState(0);
  const [result, setResult] = useState(""), [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [testValid, setTestValid] = useState<boolean | null>(null);
  const sources = useMemo(() => pathsFrom(sourceText), [sourceText]), targets = useMemo(() => pathsFrom(targetText), [targetText]);
  const chooseSchema = (side: "source" | "target", id: string) => {
    const schema = schemas.find((item: any) => item.id === id);
    if (side === "source") { setSourceId(id); if (schema) setSourceText(schema.content); }
    else { setTargetId(id); if (schema) setTargetText(schema.content); }
  };
  const suggest = async () => {
    setBusy(true); setMessage("");
    try {
      const strategyWeights = config.aiStrategy === "strict" ? { linguistic: .2, type: .45, ancestor: .25, cardinality: .1 } : config.aiStrategy === "semantic" ? { linguistic: .65, type: .1, ancestor: .15, cardinality: .1 } : undefined;
      const response = await fetch("/api/mapper/suggest", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sourceSchema: schemaObject(sourceText), targetSchema: schemaObject(targetText), threshold, weights: strategyWeights }) });
      const output = await response.json(), selected = (output.recommendations || []).filter((item: any) => item.selected);
      const recommended: Rule[] = [];
      selected.forEach((item: any) => {
        if (config.autoMapRepeating !== false && item.operator && item.sourceRepeatPath && item.targetRepeatPath && !recommended.some((rule) => rule.target === item.targetRepeatPath && rule.operator === "for-each")) {
          recommended.push({ source: item.sourceRepeatPath, select: item.sourceRepeatPath, target: item.targetRepeatPath, targetType: "object[]", operator: "for-each", confidence: item.confidence, functions: [], enabled: config.requireAiReview === false, pending: config.requireAiReview !== false });
        }
        recommended.push({ source: item.selected, target: item.target, targetType: item.targetType, confidence: item.confidence, functions: [], enabled: config.requireAiReview === false, pending: config.requireAiReview !== false });
      });
      setRules((current) => {
        const manual = current.filter((rule) => !rule.pending);
        const protectedTargets = new Set(manual.map((rule) => rule.target));
        return [...manual, ...recommended.filter((rule) => !protectedTargets.has(rule.target))];
      });
      setMessage(`${selected.length} mappings recommended. Existing manual mappings were preserved.`);
    } catch (error: any) { setMessage(error.message); }
    setBusy(false);
  };
  const test = async () => {
    try {
      const targetSchema = schemaObject(targetText), response = await fetch("/api/mapper/test", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input: JSON.parse(inputText), mappings: rules, targetSchema: typeof targetSchema === "string" ? undefined : targetSchema, targetSchemaText: typeof targetSchema === "string" ? targetSchema : targetText, options: config }) });
      const output = await response.json(); if (!response.ok) throw new Error(output.detail || "Mapping test failed");
      setResult(JSON.stringify(output.output || {}, null, 2)); setTestValid(output.valid !== false);
      setMessage(output.valid === false ? output.validationErrors.join(" · ") : `${output.mappingCount} rules executed · ${output.diagnostics?.loopCount || 0} loops · ${output.diagnostics?.conditionalCount || 0} conditions`);
    } catch (error: any) { setResult(error.message); setTestValid(false); }
  };
  const update = (index: number, key: string, value: any) => setRules((items) => items.map((rule, current) => current === index ? { ...rule, [key]: value } : rule));
  const duplicateRule = (index: number) => setRules((items) => [...items.slice(0, index + 1), { ...items[index], confidence: undefined, pending: false }, ...items.slice(index + 1)]);
  const addFunction = (definition: MapperFunctionDefinition) => {
    if (!rules.length) { setMessage("Add or select a mapping before applying a function."); return; }
    const parsed = parseFunctions(definition.pipeline)[0] || definition.name;
    setRules((items) => items.map((rule, index) => index === Math.min(selectedRule, items.length - 1) ? { ...rule, functions: [...(rule.functions || []), parsed] } : rule));
    setMessage(`${definition.signature} added to mapping ${Math.min(selectedRule, rules.length - 1) + 1}.`);
  };
  const save = () => {
    try { onSave({ sourceSchemaId: sourceId === "inline" ? "" : sourceId, targetSchemaId: targetId === "inline" ? "" : targetId, sourceSchemaText: sourceText, targetSchemaText: targetText, sourceSchema: schemaObject(sourceText), targetSchema: schemaObject(targetText), sampleInput: JSON.parse(inputText), threshold, mappings: rules, language: "JSONPath / functions" }); }
    catch (error: any) { setMessage(error.message); }
  };
  const schemaPane = (side: "source" | "target", title: string, id: string, text: string, setText: (value: string) => void, fieldPaths: string[]) => <section className="schema-pane"><div className="mapper-schema-title"><span><h3>{side === "source" ? "INPUT DATA STRUCTURE" : `${title} STRUCTURE`}</h3><small>{fieldPaths.length} addressable fields</small></span><select aria-label={`${title} project schema`} value={id} onChange={(event) => chooseSchema(side, event.target.value)}><option value="inline">Inline schema…</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></div><textarea aria-label={`${title} schema editor`} value={text} onChange={(event) => { setText(event.target.value); side === "source" ? setSourceId("inline") : setTargetId("inline"); }} spellCheck={false}/><div className="path-list">{fieldPaths.map((path) => <code key={path}>{path}</code>)}</div>{side === "target" && <><h3>TEST INPUT / OUTPUT</h3><textarea aria-label="Mapper test input" value={inputText} onChange={(event) => setInputText(event.target.value)} spellCheck={false}/><pre className={testValid === false ? "invalid" : testValid ? "valid" : ""}>{result || "Run Test mapping to preview output."}</pre></>}</section>;
  const pendingCount = rules.filter((rule) => rule.pending).length;
  return <div className="modal-backdrop mapper-backdrop"><div className="mapper-studio"><header><div><Sparkles/><span><b>Visual AI Mapper</b><small>Schema-aware transformation with executable mapping rules</small></span></div><button aria-label="Close mapper" onClick={onClose}><X/></button></header><div className="mapper-toolbar"><label>Automap threshold <input type="range" min="40" max="100" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))}/><b>{threshold}%</b></label><button className="primary" onClick={suggest} disabled={busy}><Sparkles/>{busy ? "Analyzing…" : "AI Map"}</button>{pendingCount > 0 && <><button onClick={() => setRules((items) => items.map((item) => item.pending ? { ...item, pending: false, enabled: true } : item))}><Check/> Approve all ({pendingCount})</button><button onClick={() => setRules((items) => items.filter((item) => !item.pending))}><X/> Reject pending</button></>}<button onClick={test}><FlaskConical/> Test mapping</button></div><main>{schemaPane("source", "Source", sourceId, sourceText, setSourceText, sources)}<section className="mapping-pane"><h3>MAPPING EXPRESSIONS <small>{rules.filter((rule) => rule.enabled !== false).length} active · {rules.length} total</small></h3>{rules.map((rule, index) => <div className={`map-rule ${rule.pending ? "pending" : ""} ${rule.enabled === false ? "disabled" : ""} ${selectedRule === index ? "selected" : ""}`} key={index} onClick={() => setSelectedRule(index)}><select aria-label={`Source for mapping ${index + 1}`} value={rule.source || ""} onChange={(event) => update(index, "source", event.target.value)}><option value="">Source…</option>{sources.map((path) => <option key={path}>{path}</option>)}</select><span>→</span><select aria-label={`Target for mapping ${index + 1}`} value={rule.target} onChange={(event) => update(index, "target", event.target.value)}><option value="">Target…</option>{targets.map((path) => <option key={path}>{path}</option>)}</select><select title="Mapping statement" value={rule.operator || ""} onChange={(event) => update(index, "operator", event.target.value || undefined)}><option value="">Direct</option><option value="for-each">For Each</option><option value="for-each-group">For Each Group</option><option value="if">If</option><option value="when-otherwise">When / Otherwise</option><option value="choose">Choose</option></select><input aria-label={`Function pipeline for mapping ${index + 1}`} title="Comma-separated functions; arguments use function(arg1,arg2)" placeholder={'trim, upperCase, replace("old","new")'} value={formatFunctions(rule.functions)} onChange={(event) => update(index, "functions", parseFunctions(event.target.value))}/>{rule.confidence != null && <i className={rule.confidence >= threshold ? "strong" : ""}>{rule.confidence}%</i>}{rule.pending && <button className="approve-rule" aria-label="Approve AI mapping" title="Approve AI mapping" onClick={() => setRules((items) => items.map((item, current) => current === index ? { ...item, pending: false, enabled: true } : item))}><Check/></button>}<button aria-label={`${rule.enabled === false ? "Enable" : "Disable"} mapping`} title={`${rule.enabled === false ? "Enable" : "Disable"} mapping`} onClick={() => update(index, "enabled", rule.enabled === false)}><Power/></button><button aria-label="Duplicate mapping" title="Duplicate mapping" onClick={() => duplicateRule(index)}><Copy/></button><button aria-label="Delete mapping" onClick={() => setRules((items) => items.filter((_, current) => current !== index))}><Trash2/></button></div>)}<button className="add-rule" onClick={() => { setRules((items) => [...items, { source: sources[0] || "", target: targets[0] || "", functions: [], enabled: true }]); setSelectedRule(rules.length); }}><Plus/> Add mapping</button>{message && <p className={`mapper-message ${testValid === false ? "error" : ""}`}>{message}</p>}<div className="function-library"><header><span><b>Executable function library</b><small>Select a mapping, then click a function to append it to that rule.</small></span><code>{mapperFunctionCatalog.length}</code></header>{mapperFunctionCategories.map((category) => <details key={category} open={category === "String"}><summary>{category}<small>{mapperFunctionCatalog.filter((item) => item.category === category).length}</small></summary><div>{mapperFunctionCatalog.filter((item) => item.category === category).map((definition) => <button type="button" key={definition.name} title={definition.description} onClick={() => addFunction(definition)}><b>{definition.name}</b><small>{definition.signature}</small></button>)}</div></details>)}</div></section>{schemaPane("target", "Target", targetId, targetText, setTargetText, targets)}</main><footer><span><Check/> Manual overrides remain editable and take precedence.</span><button onClick={onClose}>Cancel</button><button className="primary" onClick={save}>Save mapper</button></footer></div></div>;
}
