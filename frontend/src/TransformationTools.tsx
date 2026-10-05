import {useState} from 'react';
import './transformation-tools.css';

async function post(path: string, body: any) {
  const response = await fetch(`/api/mapper/${path}`, {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || 'Transformation operation failed');
  return result;
}

export default function TransformationTools({config, setConfig, customFunctions = []}: any) {
  const [name, setName] = useState('Regression case'), [input, setInput] = useState(JSON.stringify(config.sampleInput ?? {}, null, 2));
  const [expected, setExpected] = useState(JSON.stringify(config.lastTestOutput ?? {}, null, 2));
  const [tables, setTables] = useState(JSON.stringify(config.lookupTables || {}, null, 2));
  const [templateName, setTemplateName] = useState(config.templateName || 'Transformation'), [version, setVersion] = useState(config.templateVersion || '1.0.0');
  const [report, setReport] = useState<any>(null), [message, setMessage] = useState(''), [busy, setBusy] = useState(false);
  const cases = config.testCases || [];
  const current = () => ({...config, customFunctions:[...new Map([...(config.customFunctions || []), ...customFunctions].map((item:any)=>[item.name,item])).values()]});
  const schemaOf = (value:any) => value.targetSchema && Object.keys(value.targetSchema).length ? value.targetSchema : value.targetSchemaText;
  const run = async (operation: () => Promise<void>) => {
    setBusy(true); setMessage('');
    try {await operation();} catch (error: any) {setMessage(error.message);} finally {setBusy(false);}
  };
  const capture = () => {
    try {
      if (!name.trim()) throw new Error('Enter a case name');
      if (cases.length >= 200 && !cases.some((item:any) => item.name === name)) throw new Error('A suite supports up to 200 cases');
      const next = {name:name.trim(), input:JSON.parse(input), expected:JSON.parse(expected)};
      setConfig({testCases:[...cases.filter((item:any) => item.name !== next.name), next]});
      setMessage('Case saved. Expected output is kept separately from generated output.');
    } catch (error:any) {setMessage(error.message);}
  };
  const saveTables = () => {
    try {
      const value = JSON.parse(tables);
      if (!value || Array.isArray(value) || typeof value !== 'object' || Object.values(value).some(item => !item || Array.isArray(item) || typeof item !== 'object')) throw new Error('Each named lookup table must be a JSON object');
      setConfig({lookupTables:value}); setMessage('Lookup tables saved.');
    } catch (error:any) {setMessage(error.message);}
  };
  const exportTemplate = () => run(async () => {
    const asset = await post('template', {config:current(), name:templateName, version});
    const existing = (config.templateHistory || []).find((item:any)=>item.name===asset.name && item.version===asset.version);
    if(existing && existing.sha256 !== asset.sha256) throw new Error('This template version already exists with different content. Increase its version.');
    const history = [...(config.templateHistory || []).filter((item:any) => item.name !== asset.name || item.version !== asset.version), asset].slice(-20);
    setConfig({templateHistory:history, templateName:asset.name, templateVersion:asset.version});
    const url = URL.createObjectURL(new Blob([JSON.stringify(asset, null, 2)], {type:'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = `${asset.name.replace(/[^\w-]/g,'-')}-${asset.version.replace(/[^\w.-]/g,'-')}.mtemplate.json`; link.click(); URL.revokeObjectURL(url);
    setMessage('Versioned template exported with its schemas, mappings, tables and test cases.');
  });
  const importTemplate = (file?: File) => {
    if (!file) return;
    return run(async () => {
      if (file.size > 2 * 1024 * 1024) throw new Error('Template exceeds 2 MB');
      const asset = JSON.parse(await file.text());
      const result = await post('template', {asset});
      const impact = await post('schema-impact', {previous:schemaOf(config), current:schemaOf(result.config), mappings:config.mappings});
      setConfig({...result.config, targetSchemaId:'', sourceSchemaId:'', templateName:result.name, templateVersion:result.version});
      setTables(JSON.stringify(result.config.lookupTables || {}, null, 2)); setTemplateName(result.name); setVersion(result.version); setReport({schemaImpact:impact});
      setMessage('Template imported. Review the schema impact and run its saved tests.');
    });
  };
  return <section className="transformation-tools">
    <details><summary>Saved transformation tests · {cases.length}</summary>
      <label>Case name<input value={name} onChange={event=>setName(event.target.value)}/></label>
      <div className="transformation-test-pair"><label>Input JSON<textarea aria-label="Regression input JSON" value={input} onChange={event=>setInput(event.target.value)}/></label><label>Expected output JSON<textarea aria-label="Regression expected JSON" value={expected} onChange={event=>setExpected(event.target.value)}/></label></div>
      <button type="button" onClick={capture}>Save case</button><button type="button" disabled={busy || !cases.length} onClick={()=>run(async()=>setReport(await post('suite',{config:current(),cases})))}>Run saved suite</button>
      {cases.map((item:any,index:number)=><div className="transformation-case" key={index}><b>{item.name}</b><button type="button" onClick={()=>{setName(item.name);setInput(JSON.stringify(item.input,null,2));setExpected(JSON.stringify(item.expected,null,2));}}>Load</button><button type="button" onClick={()=>setConfig({testCases:cases.filter((_:any,i:number)=>i!==index)})}>Delete</button></div>)}
    </details>
    <details><summary>Lookup tables and execution limits</summary>
      <label>Named lookup tables JSON<textarea aria-label="Lookup tables JSON" value={tables} onChange={event=>setTables(event.target.value)}/></label><button type="button" onClick={saveTables}>Save tables</button>
      <p>Use lookupTable(${'{'}input.code{'}'}, "countries", "Unknown") in a mapping. Keys are case-sensitive.</p>
      {[['maxIterations','Maximum evaluation steps',100000],['maxExecutionMs','Execution limit (ms)',30000],['maxOutputSizeKb','Output limit (KB)',0]].map(([key,label,fallback])=><label key={String(key)}>{label}<input type="number" min={key==='maxOutputSizeKb'?0:1} value={config[String(key)] ?? fallback} onChange={event=>{const value=Number(event.target.value); if(Number.isInteger(value)&&value>=(key==='maxOutputSizeKb'?0:1))setConfig({[String(key)]:value});}}/></label>)}
    </details>
    <details><summary>Versioned templates and schema changes</summary>
      <label>Template name<input value={templateName} onChange={event=>setTemplateName(event.target.value)}/></label><label>Version<input value={version} onChange={event=>setVersion(event.target.value)}/></label>
      <button type="button" disabled={busy} onClick={exportTemplate}>Export template</button><label>Import template<input type="file" accept=".json" disabled={busy} onChange={event=>{void importTemplate(event.target.files?.[0]);event.target.value='';}}/></label>
      <button type="button" onClick={()=>{setConfig({contractBaseline:schemaOf(config)});setMessage('Contract baseline captured.');}}>Capture contract baseline</button>
      <button type="button" disabled={busy || !config.contractBaseline} onClick={()=>run(async()=>setReport({schemaImpact:await post('schema-impact',{previous:config.contractBaseline,current:schemaOf(config),mappings:config.mappings})}))}>Compare contract</button>
      {(config.templateHistory || []).map((asset:any,index:number)=><div className="transformation-case" key={index}><b>{asset.name} · {asset.version}</b><button type="button" disabled={busy} onClick={()=>run(async()=>{const result=await post('template',{asset});setConfig({...result.config,targetSchemaId:'',sourceSchemaId:'',templateName:result.name,templateVersion:result.version});setTables(JSON.stringify(result.config.lookupTables || {},null,2));setTemplateName(result.name);setVersion(result.version);setMessage('Template version restored. Run saved tests before deployment.');})}>Restore</button></div>)}
    </details>
    {message && <p role="status">{message}</p>}
    {report?.results && <div className="transformation-results" role="status"><b>{report.passed?'Suite passed':'Suite failed'} · {report.count} cases</b>{report.results.map((item:any,index:number)=><article className={item.passed?'valid':'invalid'} key={index}><b>{item.name} · {item.passed?'passed':'failed'}</b>{item.error && <p>{item.error}</p>}{item.validationErrors?.map((error:string)=><p key={error}>{error}</p>)}{item.differences?.map((difference:any,i:number)=><p key={i}><code>{difference.path}</code> · {difference.kind}: expected {JSON.stringify(difference.expected)}, received {JSON.stringify(difference.actual)}</p>)}</article>)}</div>}
    {report?.schemaImpact && <pre aria-label="Schema change report">{JSON.stringify(report.schemaImpact,null,2)}</pre>}
  </section>;
}
