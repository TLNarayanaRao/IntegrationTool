import {useEffect,useState} from "react";
import {CheckCircle2,FileUp,Globe,Play,ShieldCheck,X} from "lucide-react";
import ModalLayer from "./ModalLayer";
import {DEFAULT_PACKAGE, PackageDialog, packagePaths} from "./ProjectPackages";
import "./api-blueprint.css";

const SAMPLE=`openapi: 3.0.3
info:
  title: Orders API
  version: 1.0.0
paths:
  /orders/{id}:
    get:
      operationId: getOrder
      summary: Get an order
      parameters:
        - in: path
          name: id
          required: true
          schema: {type: string}
      responses:
        '200':
          description: Order found
          content:
            application/json:
              schema:
                type: object
                required: [id, status]
                properties:
                  id: {type: string}
                  status: {type: string}
              example: {id: '10001', status: accepted}
  /health:
    get:
      operationId: health
      responses:
        '200':
          description: API health
          content:
            application/json:
              example: {status: ok}
`;

async function api(path:string,body:any){
  const response=await fetch(path,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok)throw new Error(typeof result.detail==="string"?result.detail:JSON.stringify(result.detail||"API Blueprint request failed"));
  return result;
}

export default function ApiBlueprint({resources,packages,projectId,onPrepareUpdate,onUpdated,onClose,onApply,onHost}: {resources:any[];packages:string[];projectId:string;onPrepareUpdate:()=>Promise<unknown>;onUpdated:(project:any)=>void;onClose:()=>void;onApply:(plan:any)=>Promise<void>;onHost:(taskId:string)=>Promise<any>}){
  const servers=resources.filter(resource=>resource.type==="http"&&resource.config?.connectorMode!=="client");
  const [document,setDocument]=useState("");const [validated,setValidated]=useState<any>(null);const [selected,setSelected]=useState<string[]>([]);
  const [operationFilter,setOperationFilter]=useState("");
  const visibleOperations=(validated?.operations||[]).filter((operation:any)=>`${operation.method} ${operation.path} ${operation.operationId} ${operation.summary}`.toLowerCase().includes(operationFilter.trim().toLowerCase()));
  const [documents,setDocuments]=useState<Record<string,string>>({});const [documentPath,setDocumentPath]=useState("");
  const referenceDocuments=Object.fromEntries(Object.entries(documents).filter(([path])=>path!==documentPath));
  const [connectionId,setConnectionId]=useState(servers[0]?.id||"new");const [host,setHost]=useState("127.0.0.1");const [port,setPort]=useState("8080");
  const [scheme,setScheme]=useState("http");const [certificateFile,setCertificateFile]=useState("");const [privateKeyFile,setPrivateKeyFile]=useState("");
  const [name,setName]=useState("");const [mode,setMode]=useState("stub");const [working,setWorking]=useState("");const [error,setError]=useState("");
  const [applied,setApplied]=useState<any>(null);const [endpoints,setEndpoints]=useState<any[]>([]);
  const [apiPackage,setApiPackage]=useState(DEFAULT_PACKAGE);const [newPackages,setNewPackages]=useState<string[]>([]);
  const [packageDialog,setPackageDialog]=useState<{parent?:string}|null>(null);
  const [updateTarget,setUpdateTarget]=useState('new');const [preview,setPreview]=useState<any>(null);const [reviewed,setReviewed]=useState(false);
  const [prepared,setPrepared]=useState(false);
  const updating=updateTarget!=='new';
  const resetPreview=()=>{setPreview(null);setReviewed(false);};
  const chooseOperations=(values:string[])=>{setSelected(values);resetPreview();};
  const destinations=packagePaths([...packages,...newPackages]);
  useEffect(()=>{const listener=(event:KeyboardEvent)=>{if(event.key==="Escape"&&!working&&!packageDialog)onClose();};window.addEventListener("keydown",listener);return()=>window.removeEventListener("keydown",listener);},[onClose,working,packageDialog]);
  const updateDocument=(text:string)=>{setDocument(text);setValidated(null);setSelected([]);setOperationFilter("");setError("");resetPreview();};
  const load=async(file?:File)=>{if(!file)return;if(file.size>8*1024*1024){setError("The API document limit is 8 MiB.");return;}setWorking("Loading API document…");try{const text=await file.text();setDocuments({[file.name]:text});setDocumentPath(file.name);updateDocument(text);}catch{setError("The API document could not be read.");}finally{setWorking("");}};
  const loadFolder=async(files:FileList|null)=>{
    if(!files?.length)return;
    const supported=Array.from(files).filter(file=>/\.(?:raml|ya?ml|json|xml|xsd|txt|md)$/i.test(file.name));
    if(!supported.length||supported.length>16){setError("Select an API folder containing 1–16 contract, library, schema or example files.");return;}
    if(supported.some(file=>file.size>8*1024*1024)||supported.reduce((size,file)=>size+file.size,0)>32*1024*1024){setError("API files must each fit in 8 MiB, with a total limit of 32 MiB.");return;}
    setWorking("Loading API folder…");
    try{
      const loaded:Record<string,string>={};
      for(const file of supported){const path=file.webkitRelativePath?file.webkitRelativePath.split('/').slice(1).join('/'):file.name;if(path in loaded)throw new Error(`Duplicate document path: ${path}`);loaded[path]=await file.text();}
      const paths=Object.keys(loaded).sort();const entry=paths.find(path=>/^(?:openapi|swagger|api)\.(?:raml|ya?ml|json)$/i.test(path))||paths.find(path=>/\.raml$/i.test(path)&&/^#%RAML 1\.0\s*\n/.test(loaded[path]))||paths[0];
      setDocuments(loaded);setDocumentPath(entry);updateDocument(loaded[entry]);
    }catch(error:any){setError(error.message||"The API folder could not be read.");}finally{setWorking("");}
  };
  const chooseDocument=(path:string)=>{if(documentPath)setDocuments(current=>({...current,[documentPath]:document}));setDocumentPath(path);updateDocument(documents[path]);};
  const validate=async()=>{setWorking("Validating YAML and API contract…");setError("");try{const result=await api("/api/api-blueprint/validate",{document,referenceDocuments,documentPath});setValidated(result);setName(result.name);setSelected(result.operations.map((operation:any)=>operation.operationId));}catch(error:any){setValidated(null);setSelected([]);setError(error.message);}finally{setWorking("");}};
  const create=async()=>{
    setWorking("Creating and hosting the API…");setError("");
    try{
      let plan=applied;
      if(!plan){
        if(connectionId==="new"&&(!host.trim()||!Number.isInteger(Number(port))||Number(port)<1||Number(port)>65535))throw new Error("Supply a bind host and a port between 1 and 65535.");
        const connection=connectionId==="new"?{type:"http",name:"API server",config:{connectorMode:"server",scheme,host,port:Number(port),tlsEnabled:scheme==="https",certificateFile,privateKeyFile}}:servers.find(resource=>resource.id===connectionId);
        plan=await api("/api/api-blueprint/plan",{document,referenceDocuments,documentPath,operationIds:selected,connection,name,responseMode:mode,packagePath:apiPackage});
        await onApply(plan);setApplied(plan);
      }
      const result=await onHost(plan.tasks[0].id);setEndpoints(result.endpoints||[]);
    }catch(error:any){setError(error.message);}finally{setWorking("");}
  };
  const selectTarget=(id:string)=>{
    setUpdateTarget(id);setApplied(null);setEndpoints([]);setPrepared(false);resetPreview();
    if(id==='new'){setConnectionId('new');return;}
    const resource=resources.find(resource=>resource.id===id);
    setConnectionId(id);setApiPackage(resource.package_path||DEFAULT_PACKAGE);setDocuments({});setDocumentPath('');
    updateDocument(JSON.stringify(resource.config.openApiDocument,null,2));
  };
  const updateRequest=()=>({document,referenceDocuments,documentPath,operationIds:selected,resourceId:updateTarget,responseMode:mode});
  const previewUpdate=async()=>{
    setWorking('Saving current edits and previewing API update…');setError('');
    try{if(!prepared){await onPrepareUpdate();setPrepared(true);}setPreview(await api(`/api/projects/${encodeURIComponent(projectId)}/api-blueprint/preview`,updateRequest()));setReviewed(false);}
    catch(error:any){setError(error.message);resetPreview();}finally{setWorking('');}
  };
  const applyUpdate=async()=>{
    setWorking('Applying reviewed API update…');setError('');
    try{
      const result=await api(`/api/projects/${encodeURIComponent(projectId)}/api-blueprint/apply`,{...updateRequest(),expectedRevision:preview.revision,previewToken:preview.token,reviewed});
      onUpdated(result.project);
      const tasks=result.project.tasks.filter((task:any)=>task.activities.some((activity:any)=>activity.type==='rest'&&activity.config?.operation==='receiver'&&activity.config?.resourceId===updateTarget));
      setApplied({tasks,warnings:result.changes.warnings});setPreview(null);
    }catch(error:any){setError(error.message);}finally{setWorking('');}
  };
  return <><ModalLayer className="modal-backdrop api-blueprint-layer"><section className="api-blueprint" role="dialog" aria-modal="true" aria-labelledby="api-blueprint-title" inert={!!packageDialog}>
    <header><div><Globe/><h2 id="api-blueprint-title">MINA API Blueprint</h2></div><button aria-label="Close API Blueprint" onClick={onClose} disabled={!!working}><X/></button></header>
    <main>
      <p>Load a RAML 1.0, OpenAPI or Swagger contract, validate its operations, then create or safely update editable API flows. One Run hosts all selected operations together.</p>
      <label>API action<select aria-label="API action" value={updateTarget} disabled={!!working||!!applied} onChange={event=>selectTarget(event.target.value)}><option value="new">Create a new API</option>{servers.filter(resource=>resource.config?.apiBlueprintId).map(resource=><option key={resource.id} value={resource.id}>Update {resource.name}</option>)}</select></label>
      <div className="api-blueprint-columns"><section>
        <div className="api-blueprint-tools"><label className="api-blueprint-file"><FileUp/> Load RAML / YAML / JSON<input type="file" aria-label="Load API YAML or JSON" accept=".raml,.yaml,.yml,.json" disabled={!!working||!!applied} onChange={event=>{void load(event.target.files?.[0]);event.target.value="";}}/></label><label className="api-blueprint-file"><FileUp/> Load API folder<input type="file" aria-label="Load API folder" multiple ref={input=>{input?.setAttribute('webkitdirectory','');}} disabled={!!working||!!applied} onChange={event=>{void loadFolder(event.target.files);event.target.value="";}}/></label><button disabled={!!working||!!applied} onClick={()=>{setDocuments({});setDocumentPath("");updateDocument(SAMPLE);}}>Load example</button><button disabled={!document.trim()||!!working||!!applied} onClick={()=>void validate()}><ShieldCheck/> Validate YAML</button></div>
        {Object.keys(documents).length>1&&<label>Entry API document<select aria-label="Entry API document" value={documentPath} disabled={!!working||!!applied} onChange={event=>chooseDocument(event.target.value)}>{Object.keys(documents).sort().map(path=><option key={path}>{path}</option>)}</select></label>}
        <label>API contract<textarea autoFocus aria-label="API YAML or JSON document" value={document} disabled={!!working||!!applied} onChange={event=>updateDocument(event.target.value)} spellCheck={false} placeholder="Load a .yaml file or paste your API contract here…"/></label>
        <p className="api-blueprint-hint">Validation does not start a listener. Load an API folder to resolve local references, then select its entry document. {Object.keys(referenceDocuments).length} reference documents supplied. Import does not fetch remote URLs or read other files from your machine.</p>
      </section><section>
        {validated?<><p className="api-blueprint-valid"><CheckCircle2/> Valid contract · {selected.length} selected / {validated.operations.length} operations</p><label>API name<input value={name} disabled={!!working||!!applied||updating} onChange={event=>setName(event.target.value)} maxLength={128}/></label><label>Find operations<input type="search" aria-label="Find API operations" value={operationFilter} disabled={!!working||!!applied} onChange={event=>setOperationFilter(event.target.value)} placeholder="Method, path, or operation ID…"/></label><div className="api-blueprint-tools"><button disabled={!!working||!!applied} onClick={()=>chooseOperations(validated.operations.map((operation:any)=>operation.operationId))}>Select all</button><button disabled={!!working||!!applied} onClick={()=>chooseOperations([])}>Clear selection</button></div><div className="api-blueprint-operations" aria-label="API operations">{visibleOperations.map((operation:any)=><label key={operation.operationId}><input type="checkbox" checked={selected.includes(operation.operationId)} disabled={!!working||!!applied} onChange={event=>chooseOperations(event.target.checked?[...selected,operation.operationId]:selected.filter(id=>id!==operation.operationId))}/><b>{operation.method}</b><span>{operation.path}<small>{operation.summary||operation.operationId} · {operation.hasExample?`Mock ${operation.example.statusCode}`:'No success example; mock returns 501'}</small></span></label>)}{!visibleOperations.length&&<p>No operations match your search.</p>}</div></>:<p>Validate the document to inspect and select API operations.</p>}
        <label>API package<select aria-label="API package" value={apiPackage} disabled={!!working||!!applied||updating} onChange={event=>setApiPackage(event.target.value)}>{destinations.map(path=><option key={path}>{path}</option>)}</select></label>
        <div className="api-blueprint-tools"><button disabled={!!working||!!applied||updating} onClick={()=>setPackageDialog({})}>New package</button><button disabled={!!working||!!applied||updating} onClick={()=>setPackageDialog({parent:apiPackage})}>New subpackage</button></div>
        <p className="api-blueprint-hint">Generated API tasks and the API-specific server connection are saved in this package. New folders are saved when you create the API.</p>
        <label>HTTP server connection<select value={connectionId} disabled={!!working||!!applied||updating} onChange={event=>setConnectionId(event.target.value)}><option value="new">Create a new API server connection</option>{servers.map(resource=><option value={resource.id} key={resource.id}>{resource.name}</option>)}</select></label>
        {connectionId==="new"?<div className="api-blueprint-server"><label>Bind host<input value={host} disabled={!!working||!!applied} onChange={event=>setHost(event.target.value)}/></label><label>Port<input type="number" min="1" max="65535" value={port} disabled={!!working||!!applied} onChange={event=>setPort(event.target.value)}/></label><label>Protocol<select value={scheme} disabled={!!working||!!applied} onChange={event=>setScheme(event.target.value)}><option value="http">HTTP</option><option value="https">HTTPS</option></select></label>{scheme==="https"&&<><label>Server certificate chain path<input value={certificateFile} disabled={!!working||!!applied} onChange={event=>setCertificateFile(event.target.value)} placeholder="Runtime PEM file path or property"/></label><label>Server private key path<input value={privateKeyFile} disabled={!!working||!!applied} onChange={event=>setPrivateKeyFile(event.target.value)} placeholder="Runtime PEM key path or property"/></label></>}</div>:<p className="api-blueprint-hint">Connection settings are copied to an API-specific shared server connection. Property bindings and authentication settings are preserved.</p>}
        <label>Initial responses<select value={mode} disabled={!!working||!!applied} onChange={event=>{setMode(event.target.value);resetPreview();}}><option value="stub">501 placeholders — implement business logic</option><option value="example">Declared response examples — mock testing</option></select></label>
        <p className="api-blueprint-hint">A contract defines the API interface. It does not implement your business logic. Examples are explicitly for mock testing; operations without examples return 501.</p>
      </section></div>
      {preview&&!applied&&<section className="api-blueprint-update" aria-label="API update preview">
        <h3>Review API update</h3><p>Existing activity IDs, business flows, mappings and connection settings are retained. Review schema or route changes before applying.</p>
        {(['added','updated','unchanged','removed'] as const).map(kind=><details key={kind} open={kind!=='unchanged'}><summary>{kind[0].toUpperCase()+kind.slice(1)} · {preview[kind].length}</summary><ul>{preview[kind].map((item:any)=><li key={item.taskId}>{item.method} {item.path} · {item.operationId}{item.previousPath&&item.previousPath!==item.path&&<small> · previously {item.previousMethod} {item.previousPath}</small>}</li>)}</ul></details>)}
        {preview.warnings.map((warning:string,index:number)=><p key={index}>{warning}</p>)}
        {preview.conflicts.map((conflict:string,index:number)=><p key={index} role="alert" className="api-blueprint-error">{conflict}</p>)}
        {!!preview.requiresReview&&!preview.conflicts.length&&<label className="api-blueprint-review"><input type="checkbox" aria-label="I reviewed the API contract changes" checked={reviewed} disabled={!!working} onChange={event=>setReviewed(event.target.checked)}/>I reviewed the contract changes and will check retained mappings against changed schemas.</label>}
      </section>}
      {error&&<p role="alert" className="api-blueprint-error">{error}</p>}
      {applied&&<div className="api-blueprint-result"><b>{applied.tasks.length} editable API tasks saved.</b>{applied.warnings.map((warning:string)=><p key={warning}>{warning}</p>)}{endpoints.map(endpoint=><p key={endpoint.activityId+endpoint.taskId}><b>{endpoint.methods.join(", ")}</b> <code>{endpoint.configuredUrl}</code></p>)}{endpoints.length>0&&<p>API is listening. Use Studio Stop to release its ports.</p>}</div>}
    </main>
    <footer><span role="status">{working|| (applied?`API tasks saved in ${apiPackage}.`:updating?"Preview first. Existing implementations are preserved.":"No API tasks or server connections are changed until you create the API.")}</span><button disabled={!!working} onClick={onClose}>Close</button>{updating&&preview&&!applied&&<button disabled={!!working} onClick={()=>void previewUpdate()}>Refresh preview</button>}<button className="primary" disabled={!!working||!validated||!selected.length||endpoints.length>0||!!(updating&&!applied&&preview&&(preview.conflicts.length||(preview.requiresReview&&!reviewed)))} onClick={()=>void (updating&&!applied?(preview?applyUpdate():previewUpdate()):create())}><Play/>{applied?"Host API":updating?(preview?"Apply reviewed update":"Preview update"):"Create & host API"}</button></footer>
  </section></ModalLayer>{packageDialog&&<PackageDialog paths={destinations} parent={packageDialog.parent} onClose={()=>setPackageDialog(null)} onSave={path=>{setNewPackages(current=>[...current,path]);setApiPackage(path);setPackageDialog(null);}}/>}</>;
}
