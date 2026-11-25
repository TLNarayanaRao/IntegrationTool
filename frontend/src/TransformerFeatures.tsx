import React, {useEffect, useRef, useState} from 'react';
import XsdStructurePicker from './XsdStructurePicker';
import {selectedSchemaText} from './xsdSelection';

export function TransformStreamEditor({config, setConfig}: any) {
  return <details className="mapper-xpath-builder"><summary>Streaming record transformation</summary>
    <label><input type="checkbox" checked={!!config.streamEnabled} onChange={event=>setConfig({streamEnabled:event.target.checked})}/> Transform a file one record at a time</label>
    {config.streamEnabled && <div className="transform-policy-grid">
      <label>Input file (path or expression)<input value={config.streamInputFile || ''} onChange={event=>setConfig({streamInputFile:event.target.value})}/></label>
      <label>Output file (path or expression)<input value={config.streamOutputFile || ''} onChange={event=>setConfig({streamOutputFile:event.target.value})}/></label>
      <label>Input format<select value={config.streamInputFormat || 'jsonl'} onChange={event=>setConfig({streamInputFormat:event.target.value})}><option value="jsonl">JSON Lines</option><option value="json">JSON array</option><option value="csv">CSV</option></select></label>
      <label>Output format<select value={config.streamOutputFormat || 'jsonl'} onChange={event=>setConfig({streamOutputFormat:event.target.value})}><option value="jsonl">JSON Lines</option><option value="json">JSON array</option><option value="csv">CSV</option></select></label>
      <label>Maximum record bytes<input type="number" min="256" max="8388608" value={config.streamMaxRecordBytes || 1048576} onChange={event=>setConfig({streamMaxRecordBytes:Number(event.target.value)})}/></label>
      <label>Maximum records<input type="number" min="1" value={config.streamMaxRecords || 1000000} onChange={event=>setConfig({streamMaxRecords:Number(event.target.value)})}/></label>
      <label>Deadline seconds<input type="number" min="1" value={config.streamTimeoutSeconds || 600} onChange={event=>setConfig({streamTimeoutSeconds:Number(event.target.value)})}/></label>
      <p>Mappings and schemas describe one record. Run returns file metadata. Multiple targets write a JSON envelope per record. A failed transformation preserves the previous output file.</p>
    </div>}
  </details>;
}

function VisualScript({config, setConfig}: any) {
  const [view,setView]=useState<any>(null), [error,setError]=useState('');
  const revision=useRef(0);
  useEffect(()=>{
    const current=++revision.current;
    const controller=new AbortController();
    const timer=setTimeout(async()=>{
      try {
        const response=await fetch('/api/transform-script/visual',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({script:config.script || '%mina 2.0\noutput application/json\n---\npayload'}),signal:controller.signal});
        const result=await response.json();
        if (current!==revision.current) return;
        if (!response.ok) throw new Error(result.detail || 'Unable to read visual mappings');
        setView(result);setError('');
      } catch(error:any) {if(current===revision.current && error.name!=='AbortError'){setError(error.message);setView(null);}}
    },250);
    return ()=>{revision.current++;clearTimeout(timer);controller.abort();};
  },[config.script,setConfig]);
  const save=async(mappings:any[])=>{
    const current=++revision.current;
    setView({...view,mappings});
    try {
      const response=await fetch('/api/transform-script/visual',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({header:view.header,mappings})});
      const result=await response.json();
      if(current!==revision.current)return;
      if(!response.ok)throw new Error(result.detail || 'Visual mapping error');
      setConfig({script:result.script});setError('');
    }catch(error:any){if(current===revision.current)setError(error.message);}
  };
  return <details className="mapper-xpath-builder"><summary>Visual / script mappings</summary>
    <p>Object fields synchronize with the script. Complex expressions remain an editable whole-payload node; script headers and libraries are preserved.</p>
    {view?.mappings.map((row:any,index:number)=><div key={index} className="transform-policy-grid">
      <label>Target path<input aria-label={`Visual target ${index+1}`} value={row.target} onChange={event=>{const mappings=[...view.mappings];mappings[index]={...row,target:event.target.value};setView({...view,mappings});}} onBlur={()=>save(view.mappings)}/></label>
      <label>Expression<input aria-label={`Visual expression ${index+1}`} value={row.expression} onChange={event=>{const mappings=[...view.mappings];mappings[index]={...row,expression:event.target.value};setView({...view,mappings});}} onBlur={()=>save(view.mappings)}/></label>
      <button type="button" onClick={()=>save(view.mappings.filter((_:any,i:number)=>i!==index))}>Remove field</button>
    </div>)}
    {view?.mode==='object' && <button type="button" onClick={()=>save([...view.mappings,{target:`field${view.mappings.length+1}`,expression:'null'}])}>Add field mapping</button>}
    {error && <p role="alert">{error} The script is preserved.</p>}
  </details>;
}

export default function TransformerFeatures({config,schemas,setConfig}: any) {
  const [moduleName,setModuleName]=useState('company::Common');
  const outputs=config.outputs || [];
  const updateOutput=(index:number,change:any)=>setConfig({outputs:outputs.map((row:any,i:number)=>i===index?{...row,...change}:row)});
  const addOutput=()=>{
    const initial=outputs.length ? outputs : [{target:config.outputTarget || 'payload',name:config.outputVariable || '',script:config.script || '%mina 2.0\noutput application/json\n---\npayload'}];
    const names=new Set(initial.filter((row:any)=>row.target==='variable').map((row:any)=>row.name));
    let suffix=1;while(names.has(`result${suffix}`))suffix++;
    setConfig({outputs:[...initial,{target:'variable',name:`result${suffix}`,script:'%mina 2.0\noutput application/json\n---\npayload'}]});
  };
  return <>
    {!outputs.length && <VisualScript config={config} setConfig={setConfig}/>}
    <details className="mapper-xpath-builder"><summary>Reusable script libraries</summary>
      <p>Built-in modules: mina::Core, mina::core::Strings, Arrays, Numbers, mina::util::Math and Coercions. Import named functions, all listed exports, or qualified module functions. See Help for the supported inventory.</p>
      <label>Module name<input value={moduleName} onChange={event=>setModuleName(event.target.value)}/></label>
      <button type="button" disabled={!/^[\w$]+(?:::[\w$]+)*$/.test(moduleName) || !!config.libraries?.[moduleName]} onClick={()=>setConfig({libraries:{...config.libraries,[moduleName]:'fun normalize(value) = upper(trim(value))'}})}>Add library</button>
      {Object.entries(config.libraries || {}).map(([name,source])=><section key={name}>
        <label>{name}<textarea aria-label={`Library ${name}`} value={String(source)} onChange={event=>setConfig({libraries:{...config.libraries,[name]:event.target.value}})} spellCheck={false}/></label>
        <button type="button" onClick={()=>{const libraries={...config.libraries};delete libraries[name];setConfig({libraries});}}>Remove library</button>
      </section>)}
    </details>
    <details className="mapper-xpath-builder"><summary>Multiple output targets · {outputs.length || 'single legacy target'}</summary>
      <p>All targets read the original payload, attributes and variables. Results commit together after every script and schema passes.</p>
      <button type="button" onClick={addOutput}>Add output target</button>
      {outputs.map((output:any,index:number)=><section key={index}>
        <div className="transform-policy-grid">
          <label>Target<select value={output.target} onChange={event=>updateOutput(index,{target:event.target.value})}><option value="payload">Payload</option><option value="attributes">Attributes</option><option value="variable">Variable</option></select></label>
          {output.target==='variable' && <label>Variable name<input value={output.name || ''} onChange={event=>updateOutput(index,{name:event.target.value})}/></label>}
          <label>Target schema<select value={output.targetSchemaId || ''} onChange={event=>updateOutput(index,{targetSchemaId:event.target.value,targetSchemaText:''})}><option value="">No output contract</option>{schemas.map((schema:any)=><option key={schema.id} value={schema.id}>{schema.name}</option>)}</select></label>
        </div>
        <XsdStructurePicker label="Output structure" text={selectedSchemaText(schemas.find((schema:any)=>schema.id===output.targetSchemaId)?.content || '',output.targetSchemaText)} onChange={targetSchemaText=>updateOutput(index,{targetSchemaText})}/>
        <VisualScript config={output} setConfig={(change:any)=>updateOutput(index,change)}/>
        <label>Output script<textarea aria-label={`Output script ${index+1}`} value={output.script || ''} onChange={event=>updateOutput(index,{script:event.target.value})} spellCheck={false}/></label>
        <button type="button" onClick={()=>setConfig({outputs:outputs.filter((_:any,i:number)=>i!==index)})}>Remove output</button>
      </section>)}
    </details>
    <div className="transform-policy-grid">
      <label><input type="checkbox" checked={config.validateSource!==false} onChange={event=>setConfig({validateSource:event.target.checked})}/> Validate selected source schema</label>
      <label><input type="checkbox" checked={config.validateTarget!==false} onChange={event=>setConfig({validateTarget:event.target.checked})}/> Validate selected target schema</label>
    </div>
    <TransformStreamEditor config={config} setConfig={setConfig}/>
  </>;
}
