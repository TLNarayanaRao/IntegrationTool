import {useEffect,useMemo,useRef,useState} from 'react';
import ModalLayer from './ModalLayer';
import {analyticsCsv,escapeReport,timingRecords,timingSummary,type Timing} from './executionMetrics';
import './execution-analytics.css';

function download(name:string,body:string,type:string) {
  const url=URL.createObjectURL(new Blob([body],{type})), link=document.createElement('a');
  link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export default function ExecutionAnalytics({projectId,projectName,tasks,logs,runtimeState,debugState,onClose,onInspect}:any) {
  const [history,setHistory]=useState<any[]>(runtimeState?.executions || []),[selected,setSelected]=useState('current'),[search,setSearch]=useState(''),[error,setError]=useState('');
  const chart=useRef<SVGSVGElement>(null);
  useEffect(()=>{let active=true;fetch(`/api/projects/${encodeURIComponent(projectId)}/runtime-state`).then(async response=>{if(!response.ok)throw Error('Unable to load execution history');return response.json()}).then(state=>{if(active)setHistory(state.executions || [])}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[projectId]);
  useEffect(()=>{if(runtimeState?.executions)setHistory(runtimeState.executions)},[runtimeState]);
  const execution=history.find(item=>item.runId===selected);
  const records=useMemo<Timing[]>(()=>{
    const raw=execution ? execution.activityTimings || [] : timingRecords(debugState?.logs || logs || []);
    return raw.map((record:Timing)=>{const task=tasks.find((item:any)=>item.id===record.taskId),activity=task?.activities.find((item:any)=>item.id===record.activityId);return {...record,name:activity?.name || record.name,type:record.type || activity?.type || ''}});
  },[execution,debugState?.logs,logs,tasks]);
  const rows=useMemo(()=>timingSummary(records),[records]);
  const visible=rows.filter(row=>`${row.name} ${row.taskId} ${row.type}`.toLowerCase().includes(search.toLowerCase()));
  const top=visible.slice(0,20),max=Math.max(1,...top.map(row=>row.total)),total=rows.reduce((sum,row)=>sum+row.total,0),failures=records.filter(row=>row.status==='failed').length;
  const invocationMax=records.reduce((maximum,record)=>Math.max(maximum,record.durationMs),1);
  const trend=history.slice(0,30).reverse(),trendMax=trend.reduce((maximum,run)=>Math.max(maximum,Number(run.durationMs) || 0),1);
  const label=execution ? `${execution.runId} · ${execution.status}` : debugState ? `Debug session · ${debugState.status}` : 'Current execution logs';
  const report={project:projectName,generatedAt:new Date().toISOString(),execution:label,wallDurationMs:execution?.durationMs ?? null,notes:'Activity timings include connector waits and retries. Parent subprocess durations include child work; totals may overlap. Debug timing excludes paused time. History is limited to 100 runs retained by the current runtime.',summary:rows,invocations:records};
  const exportHtml=()=>{
    const table=rows.map(row=>`<tr>${[row.name,row.taskId,row.count,row.failures,row.total.toFixed(3),row.mean.toFixed(3),row.p95.toFixed(3)].map(value=>`<td>${escapeReport(value)}</td>`).join('')}</tr>`).join('');
    download('execution-report.html',`<!doctype html><html><head><meta charset="utf-8"><title>Execution report</title><style>body{font:14px Arial;padding:24px;color:#172a3a}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #bbb;text-align:left}svg{width:100%;max-width:1000px}svg text{fill:#172a3a}@media print{body{padding:0}}</style></head><body><h1>${escapeReport(projectName)} · Execution analysis</h1><p>${escapeReport(label)} · ${escapeReport(report.generatedAt)}</p><p>${escapeReport(report.notes)}</p>${chart.current?.outerHTML || ''}<table><thead><tr><th>Activity</th><th>Task</th><th>Invocations</th><th>Failures</th><th>Total ms</th><th>Mean ms</th><th>P95 ms</th></tr></thead><tbody>${table}</tbody></table></body></html>`,'text/html');
  };
  return <ModalLayer><div className="execution-analytics" role="dialog" aria-modal="true" aria-labelledby="execution-analytics-title">
    <header><div><h2 id="execution-analytics-title">Execution analytics</h2><small>{projectName}</small></div><button autoFocus aria-label="Close execution analytics" onClick={onClose}>×</button></header>
    <div className="analytics-controls"><label>Execution <select value={selected} onChange={event=>setSelected(event.target.value)}><option value="current">Current / debug execution</option>{history.map(run=><option key={run.runId} value={run.runId}>{run.startedAt} · {run.status} · {Number(run.durationMs).toFixed(1)} ms</option>)}</select></label><label>Find activity <input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Name, task or type"/></label></div>
    <main><p>{label}</p>{error && <p role="alert">{error}</p>}<div className="analytics-metrics"><article><b>{records.length}</b><span>Invocations</span></article><article><b>{failures}</b><span>Failed invocations</span></article><article><b>{total.toFixed(2)} ms</b><span>Summed activity time</span></article><article><b>{execution?.durationMs != null ? `${Number(execution.durationMs).toFixed(2)} ms` : '—'}</b><span>Run wall time</span></article></div>
    <p className="analytics-note">Activity time includes connector waits and retries. Subprocess timing includes child work, so totals may overlap. Debug timing excludes breakpoint pauses. The current runtime retains up to 100 runs.</p>
    {!!trend.length && <><h3>Run duration trend · latest 30 runs, oldest first</h3><svg className="analytics-chart" viewBox="0 0 900 160" role="img" aria-label="Execution duration trend">{trend.map((run,index)=>{const height=(Number(run.durationMs) || 0)/trendMax*115;return <g key={run.runId}><title>{run.startedAt}: {run.durationMs} ms · {run.status}</title><rect x={index*880/trend.length+10} y={125-height} width={Math.max(4,880/trend.length-5)} height={Math.max(1,height)} fill={run.status==='failed' ? '#b94b66' : '#298faa'}/></g>})}<text x="10" y="150">Peak {trendMax.toFixed(2)} ms · select a run above for details</text></svg></>}
    {!records.length ? <p className="analytics-empty">Run or step through a process to capture activity timings. Historical timings are available for runs captured after this update.</p> : <>
      <h3>Slowest activities · total execution time</h3><svg ref={chart} className="analytics-chart" viewBox={`0 0 900 ${Math.max(48,top.length*36)}`} role="img" aria-label="Slowest activity timing chart">{top.map((row,index)=><g key={`${row.taskId}:${row.activityId}`}><title>{row.name}: {row.total.toFixed(3)} ms across {row.count} invocations</title><text x="0" y={index*36+23}>{row.name.length>27 ? `${row.name.slice(0,25)}…` : row.name}</text><rect x="250" y={index*36+7} height="22" width={Math.max(1,row.total/max*500)} fill={row.failures ? '#b94b66' : '#298faa'}/><text x="765" y={index*36+23}>{row.total.toFixed(2)} ms</text></g>)}</svg>
      <h3>Execution timeline · most recent 200 invocations</h3><div className="analytics-timeline">{records.slice(-200).map((row,index)=><article key={index}><span>{records.length-Math.min(200,records.length)+index+1}</span><b>{row.name}</b><meter min={0} max={invocationMax} value={row.durationMs}/><code>{row.durationMs.toFixed(3)} ms</code><small>{row.status} · {row.endedAt || 'Time unavailable'}</small></article>)}</div>
      <h3>Activity analysis · click an activity to inspect</h3><div className="analytics-table"><table><thead><tr>{['Activity','Task','Calls','Failures','Total ms','Mean ms','Min ms','Max ms','P95 ms'].map(title=><th key={title}>{title}</th>)}</tr></thead><tbody>{visible.map(row=><tr key={`${row.taskId}:${row.activityId}`}><td><button onClick={()=>onInspect(row.taskId,row.activityId)}>{row.name}</button></td><td>{tasks.find((task:any)=>task.id===row.taskId)?.name || row.taskId}</td><td>{row.count}</td><td>{row.failures}</td>{[row.total,row.mean,row.min,row.max,row.p95].map((value,index)=><td key={index}>{value.toFixed(3)}</td>)}</tr>)}</tbody></table></div>
    </>}</main>
    <footer><button disabled={!records.length} onClick={()=>download('execution-timings.csv',analyticsCsv(rows),'text/csv')}>Export CSV</button><button disabled={!records.length} onClick={()=>download('execution-report.json',JSON.stringify(report,null,2),'application/json')}>Export JSON</button><button disabled={!records.length} onClick={exportHtml}>Export graph report</button><button onClick={onClose}>Close</button></footer>
  </div></ModalLayer>;
}
