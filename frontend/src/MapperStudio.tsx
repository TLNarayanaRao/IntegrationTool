import XsdStructurePicker from "./XsdStructurePicker";
import {selectXsdStructure, selectedSchemaText} from "./xsdSelection";
import ModalLayer from "./ModalLayer";
import TransformationTools from "./TransformationTools";
import MappingPlanReview from "./MappingPlanReview";
import {schemaFromActivityFields} from "./mapper-assistant-ui";
import { transformSchemaFields, AIMappingAssistance, mapperXmlSchemaDocuments } from "./ActivityEditor";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, Copy, FlaskConical, Plus, Power, Sparkles, Trash2, X } from "lucide-react";
import { mapperFunctionCatalog, mapperFunctionCategories, type MapperFunctionDefinition } from "./mapper-functions";
import { emptyRepeatOccurrence, removeRepeatOccurrence } from "./mapperLoopMappings";

type Rule = { [key: string]: any; target: string; targetType?: string; source?: string; select?: string; operator?: string; constant?: any; functions?: any[]; confidence?: number; enabled?: boolean; pending?: boolean };
const EMPTY_ITEMS:any[]=[];

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
  if (!text.trim()) return {};
  try { return JSON.parse(text); } catch {
    const root = new DOMParser().parseFromString(text, "application/xml").documentElement;
    if (root.localName !== "schema" || root.namespaceURI !== "http://www.w3.org/2001/XMLSchema") throw new Error("Schema must be valid JSON, sample JSON, or XSD.");
    return text;
  }
}
function pathsFrom(text: string) {
  return transformSchemaFields({targetSchemaText: text}).map(field => field.path);
}
const schemaText = (value: any) => typeof value === "string" ? value : JSON.stringify(value || {}, null, 2);
const parseMapperSample = (text: string) => text.trimStart().startsWith("<") ? text : JSON.parse(text);

export default function MapperStudio({ config, schemas = EMPTY_ITEMS, sources: upstreamSources = EMPTY_ITEMS, customFunctions = EMPTY_ITEMS, onClose, onSave }: any) {
  const bindingInput = useRef<HTMLInputElement>(null);
  const selectedSource = schemas.find((schema: any) => schema.id === config.sourceSchemaId);
  const selectedTarget = schemas.find((schema: any) => schema.id === config.targetSchemaId);
  const [sourceId, setSourceId] = useState(config.sourceSchemaId || "inline"), [targetId, setTargetId] = useState(config.targetSchemaId || "inline");
  const [sourceText, setSourceText] = useState((selectedSource ? selectedSchemaText(selectedSource.content,config.sourceSchemaText) : "") || config.sourceSchemaText || schemaText(config.sourceSchema));
  const [targetText, setTargetText] = useState((selectedTarget ? selectedSchemaText(selectedTarget.content,config.targetSchemaText) : "") || config.targetSchemaText || schemaText(config.targetSchema || {}));
  const [inputText, setInputText] = useState(() => {
    const nearest = upstreamSources.filter((entry:any)=>entry.distance===1);
    const sample = config.sampleInput ?? (nearest.length===1 ? nearest[0]?.activity?.config?.lastTestOutput : undefined) ?? {};
    return typeof sample === "string" && sample.trimStart().startsWith("<") ? sample : JSON.stringify(sample, null, 2);
  });
  const [rules, setRules] = useState<Rule[]>(Array.isArray(config.mappings) ? config.mappings : []), [threshold, setThreshold] = useState(config.threshold ?? 70);
  const [toolkitConfig, setToolkitConfig] = useState<any>(config);
  const [mappingPlan,setMappingPlan] = useState<any>(null), [undoPlan,setUndoPlan] = useState<any>(null);
  const [fieldSearch,setFieldSearch] = useState(""), [unmappedOnly,setUnmappedOnly] = useState(false), [rowLimit,setRowLimit] = useState(100);
  const planRequest = useRef<AbortController | null>(null), reviewedChoices = useRef<Record<string,string>>({});
  const rulesRef = useRef(rules); rulesRef.current = rules;
  const vocabulary = toolkitConfig.mappingVocabulary || "general", aliases = toolkitConfig.mappingAliases || [];
  useEffect(() => {
    planRequest.current?.abort(); setMappingPlan(null); setBusy(false); reviewedChoices.current = {};
    return () => planRequest.current?.abort();
  }, [sourceText,targetText,inputText,rules,threshold,vocabulary,toolkitConfig.mappingAliases,toolkitConfig.sourceMatchScope,toolkitConfig.targetMatchScope,toolkitConfig.sourceMatchLevel,toolkitConfig.targetMatchLevel,toolkitConfig.aiStrategy,toolkitConfig.autoMapRepeating,upstreamSources,schemas]);
  const [selectedRule, setSelectedRule] = useState(0);
  const [result, setResult] = useState(config.lastTestOutputText ?? (config.lastTestOutput !== undefined ? schemaText(config.lastTestOutput) : "")), [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [testValid, setTestValid] = useState<boolean | null>(null);
  const [resultStale,setResultStale] = useState(false);
  const previewInitialized=useRef(false), previewRevision=useRef(0), previewRequest=useRef<AbortController | null>(null);
  useEffect(()=>{
    if(!previewInitialized.current){previewInitialized.current=true;return;}
    previewRevision.current+=1;previewRequest.current?.abort();setResult("");setTestValid(null);setResultStale(true);
    setToolkitConfig((previous:any)=>{
      if(previous.lastTestOutput===undefined && previous.lastTestOutputText===undefined)return previous;
      const next={...previous};delete next.lastTestOutput;delete next.lastTestOutputText;return next;
    });
  },[rules,inputText,sourceText,targetText,toolkitConfig.xmlStylesheet,toolkitConfig.generatedXmlBinding,toolkitConfig.xmlVariables,toolkitConfig.xmlNamespaces,
    toolkitConfig.xmlBindingPreferences,toolkitConfig.sourceCoercions,toolkitConfig.sourceTypeOverrides,toolkitConfig.nullPolicy,toolkitConfig.typeCoercion,
    toolkitConfig.copyNil,toolkitConfig.removeEmptyStructures,toolkitConfig.trimStrings,toolkitConfig.lookupTables,toolkitConfig.customFunctions,
    toolkitConfig.onMappingError,toolkitConfig.maxExecutionMs,toolkitConfig.maxIterations,toolkitConfig.maxOutputSizeKb,customFunctions]);
  useEffect(()=>()=>previewRequest.current?.abort(),[]);
  const assetPath = (id: string) => {
    const asset = id === "inline" ? undefined : schemas.find((item: any) => item.id === id || item.name === id);
    return asset?.source_path || asset?.name || "";
  };
  const sourceSchemaPath = assetPath(sourceId), targetSchemaPath = assetPath(targetId);
  const sourceFields = useMemo(() => transformSchemaFields({targetSchemaText:sourceText, schemaPath:sourceSchemaPath, schemaDocuments:schemas}).map(field => field.path), [sourceText, sourceSchemaPath, schemas]);
  const immediateSources = useMemo(()=>upstreamSources.filter((entry:any)=>entry.distance===1 && entry.fields?.length),[upstreamSources]);
  const inferredSource = useMemo(()=>immediateSources.length===1 ? schemaFromActivityFields(immediateSources[0].fields) : undefined,[immediateSources]);
  const inputFields = useMemo(() => pathsFrom(inputText), [inputText]);
  const upstreamFields = useMemo(() => upstreamSources.flatMap((entry: any) => (entry.fields || []).map((field: any) => `${String(entry.activity.name || entry.activity.id).replace(/[^A-Za-z0-9_-]+/g, "-")}.${field.key}`)), [upstreamSources]);
  const sources = useMemo(() => [...new Set([...sourceFields, ...inputFields, ...upstreamFields, ...rules.map(rule => rule.select || rule.source).filter((value: any) => typeof value === "string" && value)])], [sourceFields, inputFields, upstreamFields, rules]);
  const targetFields = useMemo(() => transformSchemaFields({targetSchemaText:targetText, schemaPath:targetSchemaPath, schemaDocuments:schemas}), [targetText, targetSchemaPath, schemas]);
  const targets = useMemo(() => targetFields.map(field => field.path), [targetFields]);
  const scopeOptions = {source: sourceFields.length ? sourceFields : inputFields.length ? inputFields : inferredSource ? immediateSources[0].fields.map((field:any)=>field.key) : [], target: targets};
  const xmlSchemaDocuments = useMemo(() => ({...config.xmlSchemaDocuments, ...mapperXmlSchemaDocuments(schemas)}), [config.xmlSchemaDocuments, schemas]);
  const mappedTargets = useMemo(() => new Map(rules.map(rule => [rule.target, rule])), [rules]);
  const activeMappings = useMemo(()=>rules.filter(rule=>rule.enabled!==false && !rule.pending &&
    (rule.constant!==undefined || rule.source!=null && rule.source!=="" || !!rule.select)),[rules]);
  const activeTargets = useMemo(()=>new Set(activeMappings.map(rule=>rule.target)),[activeMappings]);
  const activeCopies = useMemo(()=>activeMappings.filter(rule=>rule.operator==="copy-of").map(rule=>rule.target),[activeMappings]);
  const query = fieldSearch.trim().toLowerCase();
  const visibleRules = useMemo(() => rules.map((rule,index)=>({rule,index})).filter(({rule}) => !query || `${rule.target} ${rule.source || rule.select || ""}`.toLowerCase().includes(query)),[rules,query]);
  const visibleTargets = useMemo(() => targetFields.filter(field => (!query || field.path.toLowerCase().includes(query)) &&
    (!unmappedOnly || !activeTargets.has(field.path) && !activeCopies.some(path=>field.path.startsWith(path+".")))),[targetFields,query,unmappedOnly,activeTargets,activeCopies]);
  useEffect(()=>{if(visibleRules.length && !visibleRules.some(entry=>entry.index===selectedRule)) setSelectedRule(visibleRules[0].index);},[visibleRules,selectedRule]);
  const chooseSchema = (side: "source" | "target", id: string) => {
    const schema = schemas.find((item: any) => item.id === id);
    if (side === "source") { setSourceId(id); if (schema) setSourceText(selectXsdStructure(schema.content)); }
    else { setTargetId(id); if (schema) setTargetText(selectXsdStructure(schema.content)); }
  };
  const sourceSchemaForLearning = () => {
    if (sourceFields.length) return schemaObject(sourceText);
    const sample = parseMapperSample(inputText);
    if (typeof sample === "string") throw new Error("Select a source XSD to analyze XML test data.");
    if (!Object.keys(sample || {}).length && !inferredSource) throw new Error("Select a source schema or provide JSON test input. Multiple incoming branches are not chosen automatically.");
    return Object.keys(sample || {}).length ? sample : inferredSource;
  };
  const matchingSchemas = () => ({sourceSchema: sourceSchemaForLearning(), targetSchema: schemaObject(targetText), sourceSchemaPath, targetSchemaPath,
    ...(sourceText.trimStart().startsWith("<") || targetText.trimStart().startsWith("<") ? {xmlSchemaDocuments} : {})});
  const shareReviewed = async () => {
    setBusy(true);
    try {
      const sourcePaths = new Set(scopeOptions.source);
      const targetPaths = new Set(targets);
      const mappings = rules.flatMap(rule => {
        if (rule.pending || rule.enabled === false || rule.operator || rule.select || rule.functions?.length
            || rule.condition || rule.whens || rule.otherwise !== undefined || "constant" in rule) return [];
        let path = (rule.source || "").replace(/^\$\{(.*)\}$/, "$1");
        if (!sourcePaths.has(path)) path = path.replace(/^(?:last|input)\./, "");
        return sourcePaths.has(path) && targetPaths.has(rule.target) ? [{ source: path, target: rule.target }] : [];
      });
      const response = await fetch("/api/mapper/share", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...matchingSchemas(), mappings }) });
      const output = await response.json();
      if (!response.ok) throw new Error(output.detail || "Could not share mappings");
      setMessage(output.shared ? `Shared ${output.shared} reviewed field pairs with this Studio server.` : "No reviewed, direct mappings between compatible schema fields to share.");
    } catch (error: any) { setMessage(error.message); }
    finally { setBusy(false); }
  };
  const bindingRequest = async (payload: object) => {
    const response = await fetch("/api/mapper/binding", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
    const output = await response.json();
    if (!response.ok) throw new Error(output.detail || "Could not process the XSLT binding");
    return output;
  };
  const bindingPreferences = toolkitConfig.xmlBindingPreferences ?? (targetText.trimStart().startsWith("<")
    ? { implicitExistence:true, omitOptionalNil:false, copyNil:toolkitConfig.copyNil !== false } : undefined);
  const generatedBinding = async () => (await bindingRequest({
    mappings: rules, targetSchemaText: /^\s*\{\s*\}\s*$/.test(targetText) ? "" : targetText,
    sourceSchemaText: sourceText.trimStart().startsWith("<") ? sourceText : "",
    preferences: bindingPreferences
  })).xmlStylesheet;
  const runtimeBinding = () => toolkitConfig.generatedXmlBinding ? generatedBinding() : toolkitConfig.xmlStylesheet;
  const downloadBinding = async () => {
    try {
      const stylesheet = await runtimeBinding() || await generatedBinding();
      const url = URL.createObjectURL(new Blob([stylesheet], { type: "application/xslt+xml" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "mapper-binding.xsl";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error: any) { setMessage(error.message); }
  };
  const openBinding = async (file: File) => {
    try {
      if (file.size > 8 * 1024 * 1024) throw new Error("Select a binding of at most 8 MiB.");
      const binding = await bindingRequest({ stylesheet: await file.text() });
      const editable = Array.isArray(binding.mappings);
      if (editable) {
        setRules(binding.mappings);
        setTargetId("inline");
        setTargetText(binding.targetSchemaText || "{}");
        if (binding.sourceSchemaText) {
          setSourceId("inline");
          setSourceText(binding.sourceSchemaText);
        }
      }
      setToolkitConfig((previous: any) => ({ ...previous, xmlStylesheet: binding.xmlStylesheet,
        generatedXmlBinding: editable, xmlBindingPreferences: binding.xmlBindingPreferences,
        ...(editable ? { xmlVariables: {}, bwXmlElementVariables: false,
          xmlSource: previous.xmlSource === "<input/>" ? "" : previous.xmlSource } : {}) }));
      setMessage(editable ? "Editable rules restored. Testing and saving will regenerate the runtime binding." : "XSLT loaded. This stylesheet supplies the runtime output.");
    } catch (error: any) { setMessage(error.message); }
  };
  const applyPlan = (output: any) => {
    if (rulesRef.current !== output.baseRules) {setMessage("Mappings changed. Analyze again before applying this plan.");return;}
    if (toolkitConfig.xmlStylesheet && !toolkitConfig.generatedXmlBinding) {setMessage("A manual XSLT stylesheet supplies runtime output. Choose Use visual mappings or Use generated XSLT before applying this plan.");return;}
    setUndoPlan({before:rules,after:output.rules}); setRules(output.rules); setMappingPlan(null);
    setMessage(`${output.summary.suggested} reviewed mappings and ${output.summary.loops} repeating structures applied. Manual mappings preserved.`);
  };
  const suggest = async (choices = reviewedChoices.current) => {
    setBusy(true); setMessage("");
    planRequest.current?.abort();
    const controller = new AbortController(); planRequest.current = controller;
    const baseRules = rules;
    try {
      const strategyWeights = toolkitConfig.aiStrategy === "strict" ? { linguistic: .2, type: .45, ancestor: .25, cardinality: .1 } : toolkitConfig.aiStrategy === "semantic" ? { linguistic: .65, type: .1, ancestor: .15, cardinality: .1 } : undefined;
      const exactNames = toolkitConfig.aiStrategy === "exact";
      const response = await fetch("/api/mapper/plan", { method: "POST", signal:controller.signal, headers: { "content-type": "application/json" }, body: JSON.stringify({
        ...matchingSchemas(), threshold, exactNames, weights: strategyWeights, strategy:toolkitConfig.aiStrategy || "balanced", mappings:rules, profile:vocabulary, aliases, choices,
        autoRepeating:toolkitConfig.autoMapRepeating !== false,
        sourceScope: scopeOptions.source.includes(toolkitConfig.sourceMatchScope) ? toolkitConfig.sourceMatchScope : "",
        targetScope: scopeOptions.target.includes(toolkitConfig.targetMatchScope) ? toolkitConfig.targetMatchScope : "",
        sourceLevel: toolkitConfig.sourceMatchLevel ?? 4, targetLevel: toolkitConfig.targetMatchLevel ?? 4
      }) });
      const output = await response.json();
      if (!response.ok) throw new Error(output.detail || "Mapping suggestions failed");
      if (controller.signal.aborted || rulesRef.current !== baseRules) return;
      const review = {...output,baseRules};
      if (toolkitConfig.requireAiReview === false) applyPlan(review); else setMappingPlan(review);
      setMessage(`${output.summary.suggested} safe suggestions. ${output.summary.ambiguous} ambiguous and ${output.summary.unmatched} unmatched fields remain for review.`);
    } catch (error: any) { if (!controller.signal.aborted) setMessage(error.message); }
    finally {if (planRequest.current === controller) setBusy(false);}
  };
  const test = async () => {
    previewRequest.current?.abort();const controller=new AbortController();previewRequest.current=controller;
    const revision=previewRevision.current;
    try {
      const sampleInput = parseMapperSample(inputText), targetSchema = schemaObject(targetText);
      const xmlStylesheet = toolkitConfig.xmlStylesheet;
      const xmlBinding = xmlStylesheet || toolkitConfig.generatedXmlBinding;
      const contract = xmlBinding && /^\s*\{\s*\}\s*$/.test(targetText) ? "" : targetSchema;
      const response = await fetch("/api/mapper/test", { method: "POST", signal:controller.signal, headers: { "content-type": "application/json" }, body: JSON.stringify({ input: sampleInput, mappings: rules, targetSchema: typeof contract === "string" ? undefined : contract, targetSchemaText: typeof contract === "string" ? contract : targetText, options: { ...toolkitConfig, targetSchema: "", targetSchemaText: "", sourceSchemaText:sourceText, xmlBindingPreferences:bindingPreferences, xmlStylesheet, customFunctions,
        xmlSchemaDocuments: xmlBinding || toolkitConfig.sourceCoercions ? xmlSchemaDocuments : undefined, xmlTargetSchemaPath: targetSchemaPath } }) });
      const output = await response.json(); if (!response.ok) throw new Error(output.detail || "Mapping test failed");
      if(controller.signal.aborted || revision!==previewRevision.current)return;
      setResultStale(false);
      setResult(output.outputText ?? (typeof output.output === "string" ? output.output : JSON.stringify(output.output ?? {}, null, 2))); setTestValid(output.valid !== false); setToolkitConfig((previous: any) => ({...previous, sampleInput, lastTestOutput: output.output, lastTestOutputText: output.outputText}));
      setMessage(output.valid === false ? output.validationErrors.join(" · ") : `${output.mappingCount} rules executed · ${output.diagnostics?.loopCount || 0} loops · ${output.diagnostics?.conditionalCount || 0} conditions`);
    } catch (error: any) { if(!controller.signal.aborted && revision===previewRevision.current){setResultStale(false);setResult(error.message);setTestValid(false);} }
  };
  const update = (index: number, key: string, value: any) => setRules((items) => items.map((rule, current) => current === index ? { ...rule, [key]: value } : rule));
  const duplicateRule = (index: number) => {
    const rule = rules[index];
    const repeated = targetFields.some(field => field.path === rule.target && field.repeating) ||
      ["copy-of", "for-each", "for-each-group"].includes(rule.operator || "");
    if (repeated) {
      const occurrenceId = `occurrence-${crypto.randomUUID()}`;
      setRules(items => [...items, emptyRepeatOccurrence(rule.target, rule.targetType, occurrenceId, rule.occurrenceId, rule)]);
      setSelectedRule(rules.length);
    } else setRules(items => [...items.slice(0, index + 1), {...rule, confidence:undefined, pending:false}, ...items.slice(index + 1)]);
  };
  const deleteRule = (index: number) => setRules(items => {
    const rule = items[index];
    return rule?.duplicateOf && rule.occurrenceId ? removeRepeatOccurrence(items, rule.occurrenceId) : items.filter((_, current) => index !== current);
  });
  const addFunction = (definition: MapperFunctionDefinition) => {
    if (!rules.length) { setMessage("Add or select a mapping before applying a function."); return; }
    const parsed = parseFunctions(definition.pipeline)[0] || definition.name;
    setRules((items) => items.map((rule, index) => index === Math.min(selectedRule, items.length - 1) ? { ...rule, functions: [...(rule.functions || []), parsed] } : rule));
    setMessage(`${definition.signature} added to mapping ${Math.min(selectedRule, rules.length - 1) + 1}.`);
  };
  const save = async () => {
    try {
      const sampleInput = parseMapperSample(inputText), xmlStylesheet = await runtimeBinding();
      const targetContract = xmlStylesheet && /^\s*\{\s*\}\s*$/.test(targetText) ? "" : targetText;
      onSave({ ...toolkitConfig, xmlStylesheet, xmlBindingPreferences:bindingPreferences, sourceSchemaId: sourceId === "inline" ? "" : sourceId, targetSchemaId: targetId === "inline" ? "" : targetId, sourceSchemaText: sourceText, targetSchemaText: targetContract, sourceSchema: sourceFields.length ? schemaObject(sourceText) : typeof sampleInput === "string" ? {} : sampleInput, targetSchema: targetContract ? schemaObject(targetContract) : "", sampleInput, lastTestOutput: toolkitConfig.lastTestOutput, lastTestOutputText: toolkitConfig.lastTestOutputText, threshold, mappings: rules });
    }
    catch (error: any) { setMessage(error.message); }
  };
  const schemaPane = (side: "source" | "target", title: string, id: string, text: string, setText: (value: string) => void, fieldPaths: string[]) => <section className="schema-pane">
    <div className="mapper-schema-title"><span><h3>{side === "source" ? "SOURCE DATA" : "GENERATED TARGET OUTPUT"}</h3><small>{side === "source" ? `${fieldPaths.length} source fields` : schemas.find((item: any) => item.id === id)?.name || "Inline target schema"}</small></span></div>
    {side === "source" ? <><textarea aria-label="Mapper test input" value={inputText} onChange={event => setInputText(event.target.value)} spellCheck={false}/><div className="path-list">{fieldPaths.filter(path=>!query || path.toLowerCase().includes(query)).slice(0,rowLimit).map(path => <code key={path}>{path}</code>)}{fieldPaths.length>rowLimit && <button type="button" onClick={()=>setRowLimit(value=>value+100)}>Show more source fields</button>}</div></> : <pre aria-label="Visual mapper generated output" role="status" aria-live="polite" className={testValid === false ? "invalid" : testValid ? "valid" : ""}>{result || (resultStale ? "Mappings or test input changed. Run mapping test again." : "Run mapping test to generate output from the current mappings.")}</pre>}
    <details className="mapper-schema-details"><summary>{title} schema</summary><select aria-label={`${title} project schema`} value={id} onChange={event => chooseSchema(side, event.target.value)}><option value="inline">Inline schema…</option>{schemas.map((schema: any) => <option key={schema.id} value={schema.id}>{schema.name}</option>)}</select><XsdStructurePicker label={`${title} structure`} text={text} onChange={setText}/>{id === "inline" && <textarea aria-label={`${title} schema editor`} value={text} onChange={event => {setText(event.target.value);side === "source" ? setSourceId("inline") : setTargetId("inline");}} spellCheck={false}/>}</details>
  </section>;
  const updateToolkit = (patch:any) => {
    setToolkitConfig((previous:any)=>({...previous,...patch}));
    if(patch.mappings) setRules(patch.mappings);
    if('targetSchemaText' in patch || 'targetSchema' in patch) {setTargetText(patch.targetSchemaText || JSON.stringify(patch.targetSchema || {},null,2));setTargetId('inline');}
    if('sourceSchemaText' in patch || 'sourceSchema' in patch) {setSourceText(patch.sourceSchemaText || JSON.stringify(patch.sourceSchema || {},null,2));setSourceId('inline');}
  };
  const pendingCount = rules.filter((rule) => rule.pending).length;
  const toolbar = <div className="mapper-toolbar">
    <button className="primary" onClick={() => void suggest()} disabled={busy}><Sparkles/>{busy ? "Analyzing…" : "AI Map"}</button>
    {pendingCount > 0 && <>
      <button onClick={() => setRules(items => items.map(item => item.pending ? { ...item, pending: false, enabled: true } : item))}><Check/> Approve all ({pendingCount})</button>
      <button onClick={() => setRules(items => items.filter(item => !item.pending))}><X/> Reject pending</button>
    </>}
    <button onClick={test}><FlaskConical/> Run mapping test</button>
    <button disabled={!undoPlan || rules !== undoPlan.after} onClick={() => {setRules(undoPlan.before);setUndoPlan(null);setMessage("Previous mappings restored.");}}>Undo AI Map</button>
    <label>Find field<input aria-label="Find Mapper field" value={fieldSearch} onChange={event=>{setFieldSearch(event.target.value);setRowLimit(100);}} placeholder="Name or path"/></label>
    <label><input type="checkbox" checked={unmappedOnly} onChange={event=>setUnmappedOnly(event.target.checked)}/>Unmapped targets only</label>
    <button type="button" onClick={shareReviewed} disabled={busy}>Share reviewed mappings</button>
    <button type="button" onClick={downloadBinding}>Download XSLT</button>
    {!toolkitConfig.generatedXmlBinding && <button type="button" onClick={async () => {
      try {
        const xmlStylesheet = await generatedBinding();
        setToolkitConfig((previous:any) => ({ ...previous, xmlStylesheet, generatedXmlBinding:true, xmlVariables:{},
          bwXmlElementVariables:false, xmlSource: previous.xmlSource === "<input/>" ? "" : previous.xmlSource }));
        setMessage("Runtime XSLT now follows the visual rules.");
      } catch (error:any) { setMessage(error.message); }
    }}>Use generated XSLT</button>}
    <button type="button" onClick={() => bindingInput.current?.click()}>Open XSLT</button>
    <input ref={bindingInput} hidden type="file" accept=".xsl,.xslt,application/xslt+xml" onChange={event => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (file) void openBinding(file);
    }}/>
    {toolkitConfig.xmlStylesheet && <button type="button" onClick={() => {
      setToolkitConfig((previous: any) => ({ ...previous, xmlStylesheet: "", generatedXmlBinding: false }));
      setMessage("Runtime switched to visual mappings.");
    }}>Use visual mappings</button>}
  </div>;
  const xmlBindingOptions = <details className="mapper-ai-options"><summary>Generated XML binding preferences</summary>
    <div className="mapper-xml-preferences">
      {([["implicitExistence", "Check whether optional source elements exist", true],
         ["omitOptionalNil", "Omit optional non-nillable targets when the source is nil", false],
         ["copyNil", "Copy xsi:nil to nillable targets", true]] as const).map(([key, label, fallback]) =>
        <label key={key}><input type="checkbox" checked={bindingPreferences?.[key] ?? fallback}
          onChange={event => updateToolkit({xmlBindingPreferences:{...bindingPreferences, [key]:event.target.checked}})}/>{label}</label>)}
    </div>
  </details>;
  return <ModalLayer className="modal-backdrop mapper-backdrop"><div className="mapper-studio"><header><div><Sparkles/><span><b>Visual AI Mapper</b><small>Schema-aware transformation with executable mapping rules</small></span></div><button aria-label="Close mapper" onClick={onClose}><X/></button></header><details className="mapper-ai-options"><summary>AI mapping options · {threshold}% confidence</summary><AIMappingAssistance scopeOptions={scopeOptions} config={{...toolkitConfig,threshold}} setConfig={(patch: any) => { if (patch.threshold !== undefined) setThreshold(patch.threshold); updateToolkit(patch); }}/>
    <div className="mapper-vocabulary"><label>Business vocabulary<select value={vocabulary} onChange={event=>updateToolkit({mappingVocabulary:event.target.value})}><option value="general">General</option><option value="commerce">Commerce / orders</option><option value="finance">Finance / payments</option></select></label>
    <p>{sourceFields.length ? "Matching the selected source schema." : inputFields.length ? "Matching the test sample structure." : inferredSource ? `Matching the output contract of ${immediateSources[0].activity.name}.` : "Select a source schema or provide JSON test input; an ambiguous predecessor is not selected automatically."}</p><p>Optional field-name equivalents. Matching stays local; payloads are not sent to an external AI service.</p>
    {aliases.map((pair:string[],index:number)=><div key={index}>{pair.map((term,column)=><input key={column} aria-label={`Vocabulary ${index+1} ${column===0 ? "source" : "target"} term`} value={term} onChange={event=>updateToolkit({mappingAliases:aliases.map((entry:string[],i:number)=>i===index ? entry.map((old:string,c:number)=>c===column ? event.target.value : old) : entry)})}/>)}<button onClick={()=>updateToolkit({mappingAliases:aliases.filter((_:any,i:number)=>i!==index)})}>Remove</button></div>)}
    <button disabled={aliases.length>=100} onClick={()=>updateToolkit({mappingAliases:[...aliases,["",""]]})}>Add vocabulary pair</button></div>
    </details>{xmlBindingOptions}{toolbar}<main>{schemaPane("source", "Source", sourceId, sourceText, setSourceText, sources)}<section className="mapping-pane"><datalist id="visual-mapper-sources">{sources.map(path => <option key={path} value={path}/>)}</datalist><datalist id="visual-mapper-targets">{targets.map(path=><option key={path} value={path}/>)}</datalist>{mappingPlan && <MappingPlanReview plan={mappingPlan} query={query} manualBinding={!!toolkitConfig.xmlStylesheet && !toolkitConfig.generatedXmlBinding} onApply={()=>applyPlan(mappingPlan)} onDiscard={()=>setMappingPlan(null)} onChoose={(target:string,source:string)=>{reviewedChoices.current={...reviewedChoices.current,[target]:source};void suggest(reviewedChoices.current);}}/>}<h3>TARGET SCHEMA &amp; MAPPINGS <small>{rules.filter((rule) => rule.enabled !== false).length} active · {rules.length} total</small></h3>{visibleRules.slice(0,rowLimit).map(({rule, index}) => <div className={`map-rule ${rule.pending ? "pending" : ""} ${rule.enabled === false ? "disabled" : ""} ${selectedRule === index ? "selected" : ""}`} key={index} title={(rule.mappingReasons || []).join("; ")} onClick={() => setSelectedRule(index)}><input aria-label={`Source for mapping ${index + 1}`} list="visual-mapper-sources" value={rule.constant !== undefined ? JSON.stringify(rule.constant) : rule.select || rule.source || ""} onChange={event => {update(index, "source", event.target.value); if(rule.select !== undefined) update(index,"select",event.target.value); if(rule.constant !== undefined) update(index,"constant",undefined);}}/><span>→</span><input list="visual-mapper-targets" aria-label={`Target for mapping ${index + 1}`} placeholder="Target path" value={rule.target} onChange={event=>update(index,"target",event.target.value)}/><select title="Mapping statement" value={rule.operator || ""} onChange={(event) => update(index, "operator", event.target.value || undefined)}><option value="">Direct</option><option value="copy-of">Copy-Of</option><option value="for-each">For Each</option><option value="for-each-group">For Each Group</option><option value="if">If</option><option value="when-otherwise">When / Otherwise</option><option value="choose">Choose</option></select><input aria-label={`Function pipeline for mapping ${index + 1}`} title="Comma-separated functions; arguments use function(arg1,arg2)" placeholder={'trim, upperCase, replace("old","new")'} value={formatFunctions(rule.functions)} onChange={(event) => update(index, "functions", parseFunctions(event.target.value))}/>{rule.confidence != null && <i className={rule.confidence >= threshold ? "strong" : ""}>{rule.confidence}%</i>}{rule.pending && <button className="approve-rule" aria-label="Approve AI mapping" title="Approve AI mapping" onClick={() => setRules((items) => items.map((item, current) => current === index ? { ...item, pending: false, enabled: true } : item))}><Check/></button>}<button aria-label={`${rule.enabled === false ? "Enable" : "Disable"} mapping`} title={`${rule.enabled === false ? "Enable" : "Disable"} mapping`} onClick={() => update(index, "enabled", rule.enabled === false)}><Power/></button><button aria-label="Duplicate mapping" title="Duplicate mapping" onClick={() => duplicateRule(index)}><Copy/></button><button aria-label="Delete mapping" onClick={() => deleteRule(index)}><Trash2/></button>{rule.operator === "if" && <input className="mapper-rule-detail" aria-label={`Condition for mapping ${index + 1}`} placeholder="Condition" value={rule.condition || ""} onChange={event=>update(index,"condition",event.target.value)}/>} {rule.operator === "for-each-group" && <input className="mapper-rule-detail" aria-label={`Grouping for mapping ${index + 1}`} placeholder="Grouping expression" value={rule.groupBy || ""} onChange={event=>update(index,"groupBy",event.target.value)}/>} {rule.whens?.map((branch:any,branchIndex:number)=><div className="mapper-rule-detail" key={branchIndex}><b>When {branchIndex+1}</b><code>{branch.condition} → {branch.source}</code></div>)} {rule.otherwise !== undefined && <div className="mapper-rule-detail"><b>Otherwise</b><code>{rule.otherwise}</code></div>}</div>)}{visibleRules.length>rowLimit && <button onClick={()=>setRowLimit(value=>value+100)}>Show more mappings ({visibleRules.length-rowLimit} remaining)</button>}<button className="add-rule" onClick={() => { const target=targets.find(path=>!activeTargets.has(path)) || ""; setRules(items=>[{source:"",target,functions:[],enabled:true},...items]);setSelectedRule(0);setFieldSearch(""); }}><Plus/> Add mapping</button>{message && <p className={`mapper-message ${testValid === false ? "error" : ""}`}>{message}</p>}<details className="mapper-unmapped-targets" open><summary>Target schema fields ({targets.length})</summary>{visibleTargets.slice(0,rowLimit).map(field => <div key={field.path} style={{paddingLeft:field.depth*12}}><code>{field.name}{field.repeating ? Number(field.minOccurs) > 0 ? "+" : "*" : field.minOccurs === "0" ? "?" : ""}</code><small>{field.type}</small><span className="target-field-expression" title={field.path}>{mappedTargets.has(field.path) ? mappedTargets.get(field.path)?.constant !== undefined ? JSON.stringify(mappedTargets.get(field.path)?.constant) : mappedTargets.get(field.path)?.select || mappedTargets.get(field.path)?.source || mappedTargets.get(field.path)?.operator || "No source" : "Unmapped"}</span><button type="button" aria-label={`Map ${field.path}`} onClick={() => {const existing=rules.findIndex(rule=>rule.target===field.path);if(existing>=0)setSelectedRule(existing);else {setRules(items=>[...items,{target:field.path,targetType:field.type,source:"",functions:[],enabled:true}]);setSelectedRule(rules.length);}}}>Map</button></div>)}{visibleTargets.length>rowLimit && <button onClick={()=>setRowLimit(value=>value+100)}>Show more fields ({visibleTargets.length-rowLimit} remaining)</button>}</details><details className="function-library"><summary>Executable function library</summary><header><span><b>Executable function library</b><small>Select a mapping, then click a function to append it to that rule.</small></span><code>{mapperFunctionCatalog.length}</code></header>{mapperFunctionCategories.map((category) => <details key={category} open={category === "String"}><summary>{category}<small>{mapperFunctionCatalog.filter((item) => item.category === category).length}</small></summary><div>{mapperFunctionCatalog.filter((item) => item.category === category).map((definition) => <button type="button" key={definition.name} title={definition.description} onClick={() => addFunction(definition)}><b>{definition.name}</b><small>{definition.signature}</small></button>)}</div></details>)}</details></section>{schemaPane("target", "Target", targetId, targetText, setTargetText, targets)}</main><TransformationTools config={{...toolkitConfig,mappings:rules,targetSchema:targetText,targetSchemaText:targetText,xmlTargetSchemaPath:targetSchemaPath,xmlSchemaDocuments,sourceSchema:sourceText,sourceSchemaText:sourceText,sampleInput:toolkitConfig.sampleInput,lastTestOutput:toolkitConfig.lastTestOutput}} setConfig={updateToolkit} customFunctions={customFunctions}/><footer><span><Check/> Manual overrides remain editable and take precedence.</span><button onClick={onClose}>Cancel</button><button className="primary" onClick={save}>Save mapper</button></footer></div></ModalLayer>;
}
