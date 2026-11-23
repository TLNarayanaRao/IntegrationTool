import { useEffect, useRef, useState } from "react";
import "./debug-input-cases.css";

type Fixture = {name: string; input: unknown; expected: "accept" | "reject"};
type Result = Fixture & {id: string; actual: "accept" | "reject" | "unchecked"; errors: string[]};
type Report = {
  taskId: string; activityId: string; contract: string; mode: "task-input" | "starter-output" | "bench-only"; note: string; cases: Result[];
};

export default function DebugInputCases({ sessionId, taskId, currentTaskId, currentActivityId, paused, liveListener, busy, onLoad, onApply, onDownload }: {
  sessionId: string; taskId: string; currentTaskId?: string; currentActivityId?: string;
  paused: boolean; liveListener: boolean; busy: boolean;
  onLoad: (input: unknown) => void;
  onApply: (action: "load_task_input" | "mock_step", taskId: string, activityId: string, input: unknown) => void;
  onDownload: (blob: Blob, filename: string) => void;
}) {
  const request = useRef<AbortController | null>(null);
  const [report, setReport] = useState<Report>();
  const [selection, setSelection] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => () => request.current?.abort(), []);

  const check = async (file?: File) => {
    const controller = new AbortController();
    request.current?.abort();
    request.current = controller;
    setWorking(true);
    setError("");
    try {
      const saved = file ? JSON.parse((await file.text()).replace(/^\uFEFF/, "")) : null;
      if (file && (!saved || !Array.isArray(saved.cases) || !saved.cases.length)) throw new Error("Choose a saved test case file with a non-empty cases list.");
      const response = await fetch(`/api/debug/${encodeURIComponent(sessionId)}/input-cases`, {
        method: "POST", headers: {"Content-Type": "application/json"}, signal: controller.signal,
        body: JSON.stringify({task_id: taskId, cases: saved?.cases}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "The input cases could not be checked.");
      if (!controller.signal.aborted) { setReport(result); setSelection(result.cases[0]?.id || ""); }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof SyntaxError ? "The saved test case file contains invalid JSON." : failure instanceof Error ? failure.message : String(failure));
    } finally {
      if (!controller.signal.aborted) setWorking(false);
    }
  };
  const selected = report?.cases.find(item => item.id === selection);
  const checked = report?.cases.filter(item => item.actual !== "unchecked") || [];
  const passed = checked.filter(item => item.actual === item.expected).length;
  const canApply = paused && !liveListener && report?.mode !== "bench-only" && report?.taskId === currentTaskId &&
    report?.activityId === currentActivityId && selected?.expected === "accept" && selected.actual !== "reject";
  const inactive = busy || working;

  return <div className="debug-input-cases">
    <h4>Generated input cases</h4>
    <p>Build and check sample payloads against the selected task’s input contract. These checks do not run activities.</p>
    <div className="debug-input-case-actions">
      <button type="button" disabled={inactive || !taskId} onClick={() => void check()}>{working ? "Checking…" : "Generate and check cases"}</button>
      <label>Check saved cases<input type="file" accept=".json,application/json" disabled={inactive || !taskId} onChange={event => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = "";
        if (file) void check(file);
      }}/></label>
      {!!report?.cases.length && <button type="button" disabled={inactive} onClick={() => {
        const cases = report.cases.map(({name, input, expected}) => ({name, input, expected}));
        onDownload(new Blob([JSON.stringify({taskId: report.taskId, contract: report.contract, cases}, null, 2)], {type: "application/json"}), "debug-input-cases.json");
      }}>Download cases</button>}
    </div>
    {error && <p role="alert">{error}</p>}
    {report && <p role="status">{report.contract} · {passed}/{checked.length} checked cases matched expectations
      {report.cases.length > checked.length ? ` · ${report.cases.length - checked.length} unchecked` : ""}</p>}
    {report?.note && <p>{report.note}</p>}
    {selected && report && <>
      <label>Input case<select value={selected.id} onChange={event => setSelection(event.target.value)}>
        {report.cases.map(item => <option key={item.id} value={item.id}>
          {item.actual === "unchecked" ? "Unchecked" : item.actual === item.expected ? "Pass" : "Fail"} · {item.name}
        </option>)}
      </select></label>
      <p>Expected {selected.expected} · Actual {selected.actual}</p>
      {!!selected.errors.length && <ul>{selected.errors.map((message, index) => <li key={index}>{message}</li>)}</ul>}
      <label>Generated payload<textarea readOnly rows={4} value={JSON.stringify(selected.input, null, 2)} spellCheck={false}/></label>
      <div className="debug-input-case-actions">
        <button type="button" disabled={inactive} onClick={() => onLoad(selected.input)}>Load in Test Bench</button>
        {canApply && <button type="button" disabled={inactive} onClick={() =>
          onApply(report.mode === "starter-output" ? "mock_step" : "load_task_input", report.taskId, report.activityId, selected.input)}>
          {report.mode === "starter-output" ? "Mock starter and step" : "Use as paused task input"}
        </button>}
      </div>
    </>}
  </div>;
}
