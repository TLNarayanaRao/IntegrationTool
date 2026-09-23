import React, { useState } from "react";
import { Database } from "lucide-react";
import DebugActivityTree from "./DebugActivityTree";
import DebugPayloadEditor from "./DebugPayloadEditor";

export default function DebugJobData({ state, tasks, onClose }: any) {
  const [selection, setSelection] = useState({ taskId: state.currentTaskId || state.callStack?.[0]?.taskId || tasks[0]?.id || "", activityId: "" });
  // Activity IDs are task-local. Never use the flattened activityOutputs map here.
  const records = state.taskOutputs || {};
  const task = tasks.find((item: any) => item.id === selection.taskId);
  const taskRecord = records[selection.taskId];
  const selected = selection.activityId ? taskRecord?.activities?.[selection.activityId] : taskRecord;
  const activity = task?.activities.find((item: any) => item.id === selection.activityId);
  const start = task?.activities.find((item: any) => item.type === "start");
  const input = selection.activityId ? selected?.input : selected?.input ?? (start ? taskRecord?.activities?.[start.id]?.input : undefined);
  return <div className="modal-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <div className="runtime-modal debug-job-data-dialog">
      <header><span><Database/><span><b>Debug Job Data</b><small>Expand task calls to inspect nested activity inputs and outputs</small></span></span><button aria-label="Close job data" onClick={onClose}>×</button></header>
      <main>
        <DebugActivityTree tasks={tasks} taskId={selection.taskId} activityId={selection.activityId} records={records} expandCalls onSelect={(taskId: string, activityId: string) => setSelection({ taskId, activityId })}/>
        <section className="debug-job-payloads">
          <div className="debug-job-heading"><span><b>{task?.name}{activity ? ` / ${activity.name}` : " / Process data"}</b><small>{selection.taskId}{selection.activityId ? ` / ${selection.activityId}` : ""}</small></span></div>
          {selected ? <div className="debug-job-columns" key={`${selection.taskId}/${selection.activityId}`}><DebugPayloadEditor title="INPUT" value={input}/><DebugPayloadEditor title="OUTPUT" value={selected.output}/></div> : <div className="debug-job-empty">No data captured for this selection yet. Continue or step through the flow.</div>}
        </section>
      </main>
      <footer><span>Latest captured values per task/activity. Repeated calls show the latest invocation, not a full invocation history.</span><button className="primary" onClick={onClose}>Close</button></footer>
    </div>
  </div>;
}
