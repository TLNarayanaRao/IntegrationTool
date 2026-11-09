import {useEffect,useState} from "react";
import {CheckCircle2,FileUp,Globe,Play,ShieldCheck,X} from "lucide-react";
import ModalLayer from "./ModalLayer";
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

export default function ApiBlueprint({resources,onClose,onApply,onHost}: {resources:any[];onClose:()=>void;onApply:(plan:any)=>Promise<void>;onHost:(taskId:string)=>Promise<any>}){
  const servers=resources.filter(resource=>resource.type==="http"&&resource.config?.connectorMode!=="client");
  const [document,setDocument]=useState("");const [validated,setValidated]=useState<any>(null);const [selected,setSelected]=useState<string[]>([]);
  const [connectionId,setConnectionId]=useState(servers[0]?.id||"new");const [host,setHost]=useState("127.0.0.1");const [port,setPort]=useState("8080");
  const [scheme,setScheme]=useState("http");const [certificateFile,setCertificateFile]=useState("");const [privateKeyFile,setPrivateKeyFile]=useState("");
  const [name,setName]=useState("");const [mode,setMode]=useState("stub");const [working,setWorking]=useState("");const [error,setError]=useState("");
  const [applied,setApplied]=useState<any>(null);const [endpoints,setEndpoints]=useState<any[]>([]);
  useEffect(()=>{const listener=(event:KeyboardEvent)=>{if(event.key==="Escape"&&!working)onClose();};window.addEventListener("keydown",listener);return()=>window.removeEventListener("keydown",listener);},[onClose,working]);
  const updateDocument=(text:string)=>{setDocument(text);setValidated(null);setSelected([]);setError("");};
  const load=async(file?:File)=>{if(!file)return;if(file.size>8*1024*1024){setError("The API document limit is 8 MiB.");return;}try{updateDocument(await file.text());}catch{setError("The API document could not be read.");}};
  const validate=async()=>{setWorking("Validating YAML and API contract…");setError("");try{const result=await api("/api/api-blueprint/validate",{document});setValidated(result);setName(result.name);setSelected(result.operations.map((operation:any)=>operation.operationId));}catch(error:any){setValidated(null);setSelected([]);setError(error.message);}finally{setWorking("");}};
  const create=async(hostNow:boolean)=>{
    setWorking(hostNow?"Creating and hosting the API…":"Creating API tasks…");setError("");
    try{
      let plan=applied;
      if(!plan){
        if(connectionId==="new"&&(!host.trim()||!Number.isInteger(Number(port))||Number(port)<1||Number(port)>65535))throw new Error("Supply a bind host and a port between 1 and 65535.");
        const connection=connectionId==="new"?{type:"http",name:"API server",config:{connectorMode:"server",scheme,host,port:Number(port),tlsEnabled:scheme==="https",certificateFile,privateKeyFile}}:servers.find(resource=>resource.id===connectionId);
        plan=await api("/api/api-blueprint/plan",{document,operationIds:selected,connection,name,responseMode:mode});
        await onApply(plan);setApplied(plan);
      }
      if(hostNow){const result=await onHost(plan.tasks[0].id);setEndpoints(result.endpoints||[]);}
    }catch(error:any){setError(error.message);}finally{setWorking("");}
  };
  return <ModalLayer className="modal-backdrop api-blueprint-layer"><section className="api-blueprint" role="dialog" aria-modal="true" aria-labelledby="api-blueprint-title">
    <header><div><Globe/><h2 id="api-blueprint-title">MINA API Blueprint</h2></div><button aria-label="Close API Blueprint" onClick={onClose} disabled={!!working}><X/></button></header>
    <main>
      <p>Load an OpenAPI YAML or JSON document, validate its operations, then create editable REST Receiver → HTTP Response tasks. One Run hosts all selected operations together.</p>
      <div className="api-blueprint-columns"><section>
        <div className="api-blueprint-tools"><label className="api-blueprint-file"><FileUp/> Load YAML / JSON<input type="file" aria-label="Load API YAML or JSON" accept=".yaml,.yml,.json" disabled={!!working||!!applied} onChange={event=>{void load(event.target.files?.[0]);event.target.value="";}}/></label><button disabled={!!working||!!applied} onClick={()=>updateDocument(SAMPLE)}>Load example</button><button disabled={!document.trim()||!!working||!!applied} onClick={()=>void validate()}><ShieldCheck/> Validate YAML</button></div>
        <label>API contract<textarea autoFocus aria-label="API YAML or JSON document" value={document} disabled={!!working||!!applied} onChange={event=>updateDocument(event.target.value)} spellCheck={false} placeholder="Load a .yaml file or paste your API contract here…"/></label>
        <p className="api-blueprint-hint">Validation does not start a listener. External references must be supplied inline before import. Uploaded files remain local to this project workflow.</p>
      </section><section>
        {validated?<><p className="api-blueprint-valid"><CheckCircle2/> Valid contract · {validated.operations.length} operations</p><label>API name<input value={name} disabled={!!working||!!applied} onChange={event=>setName(event.target.value)} maxLength={128}/></label><div className="api-blueprint-operations" aria-label="API operations">{validated.operations.map((operation:any)=><label key={operation.operationId}><input type="checkbox" checked={selected.includes(operation.operationId)} disabled={!!working||!!applied} onChange={event=>setSelected(current=>event.target.checked?[...current,operation.operationId]:current.filter(id=>id!==operation.operationId))}/><b>{operation.method}</b><span>{operation.path}<small>{operation.summary||operation.operationId}</small></span></label>)}</div></>:<p>Validate the document to inspect and select API operations.</p>}
        <label>HTTP server connection<select value={connectionId} disabled={!!working||!!applied} onChange={event=>setConnectionId(event.target.value)}><option value="new">Create a new API server connection</option>{servers.map(resource=><option value={resource.id} key={resource.id}>{resource.name}</option>)}</select></label>
        {connectionId==="new"?<div className="api-blueprint-server"><label>Bind host<input value={host} disabled={!!working||!!applied} onChange={event=>setHost(event.target.value)}/></label><label>Port<input type="number" min="1" max="65535" value={port} disabled={!!working||!!applied} onChange={event=>setPort(event.target.value)}/></label><label>Protocol<select value={scheme} disabled={!!working||!!applied} onChange={event=>setScheme(event.target.value)}><option value="http">HTTP</option><option value="https">HTTPS</option></select></label>{scheme==="https"&&<><label>Server certificate chain path<input value={certificateFile} disabled={!!working||!!applied} onChange={event=>setCertificateFile(event.target.value)} placeholder="Runtime PEM file path or property"/></label><label>Server private key path<input value={privateKeyFile} disabled={!!working||!!applied} onChange={event=>setPrivateKeyFile(event.target.value)} placeholder="Runtime PEM key path or property"/></label></>}</div>:<p className="api-blueprint-hint">Connection settings are copied to an API-specific shared server connection. Property bindings and authentication settings are preserved.</p>}
        <label>Initial responses<select value={mode} disabled={!!working||!!applied} onChange={event=>setMode(event.target.value)}><option value="stub">501 placeholders — implement business logic</option><option value="example">Declared response examples — mock testing</option></select></label>
        <p className="api-blueprint-hint">A contract defines the API interface. It does not implement your business logic. Examples are explicitly for mock testing; operations without examples return 501.</p>
      </section></div>
      {error&&<p role="alert" className="api-blueprint-error">{error}</p>}
      {applied&&<div className="api-blueprint-result"><b>{applied.tasks.length} editable API tasks saved.</b>{applied.warnings.map((warning:string)=><p key={warning}>{warning}</p>)}{endpoints.map(endpoint=><p key={endpoint.activityId+endpoint.taskId}><b>{endpoint.methods.join(", ")}</b> <code>{endpoint.configuredUrl}</code></p>)}{endpoints.length>0&&<p>API is listening. Use Studio Stop to release its ports.</p>}</div>}
    </main>
    <footer><span role="status">{working|| (applied?"API tasks are available in the project tree.":"No API tasks or server connections are changed until you create the API.")}</span><button disabled={!!working} onClick={onClose}>Close</button><button disabled={!!working||!validated||!selected.length||!!applied} onClick={()=>void create(false)}>Create API tasks</button><button className="primary" disabled={!!working||!validated||!selected.length||endpoints.length>0} onClick={()=>void create(true)}><Play/>{applied?"Host API":"Create & host API"}</button></footer>
  </section></ModalLayer>;
}
