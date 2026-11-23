import { useEffect, useState } from "react";
import ModalLayer from "./ModalLayer";

type Counts = Record<string, number>;
type ActivityMetric = {
  taskId: string; activityId: string; activityName: string; count: number;
  failures: number; mocked: number; received: number; totalMs: number; avgMs: number; minMs: number; maxMs: number;
};
type TraceEvent = {
  sequence: number; job: number; threadId: number; taskId: string; kind: string;
  elapsedMs: number; workerThreadId: number; activityId?: string; activityName?: string;
  targetActivityId?: string; targetTaskId?: string; targetThreadId?: number;
  transitionId?: string; transitionType?: string; transitionLabel?: string; reason?: string; outcome?: string; durationMs?: number;
  groups?: { id: string; iteration: number }[];
};
type TraceThread = {
  id: number; parentId: number | null; job: number; kind: string; taskId: string;
  taskName: string; entryActivityId: string | null; status: string; steps: number;
};
type Report = {
  status: string; olderBefore: number | null; threads: TraceThread[]; events: TraceEvent[];
  metrics: {
    capture: boolean; activeMs: number; activityMs: number; lastJobMs: number; maxJobMs: number;
    jobs: Counts; activities: Counts; jobsPerSecond: number; wallJobsPerSecond: number; wallWindowMs: number; activitiesPerSecond: number;
    droppedEvents: number; droppedThreads: number; omittedActivitySamples: number; byActivity: ActivityMetric[];
    threadCount: number; eventCount: number;
  };
};
type TraceTask = { id: string; name: string; activities: { id: string; name: string }[] };
type Props = {
  sessionId: string; live: boolean; activeThreadId?: number; tasks: TraceTask[];
  initialTab: "threads" | "metrics"; onClose: () => void; onInspect: (taskId: string, activityId: string) => void;
};

const time = (ms: number) => ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms.toFixed(2)} ms`;

export default function DebugTraceDialog({ sessionId, live, activeThreadId, tasks, initialTab, onClose, onInspect }: Props) {
  const [tab, setTab] = useState(initialTab);
  const [thread, setThread] = useState("");
  const [cursors, setCursors] = useState<number[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const before: number | undefined = cursors[cursors.length - 1];
  const url = `/api/debug/${encodeURIComponent(sessionId)}/trace`;

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ limit: "150" });
    if (thread) query.set("thread", thread);
    if (before !== undefined) query.set("before", String(before));
    let pending = false;
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const response = await fetch(`${url}?${query}`, { signal: controller.signal });
        if (!response.ok) throw new Error(response.status === 404 ? "This debug session has expired." : "Could not load the trace.");
        const next = await response.json();
        if (!controller.signal.aborted) { setReport(next); setError(""); }
      } catch (error) {
        if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Could not load the trace.");
      } finally { pending = false; }
    };
    setReport(null);
    setError("");
    void load();
    const timer = live && before === undefined ? window.setInterval(load, 1000) : undefined;
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [before, live, refresh, thread, url]);

  const taskName = (taskId: string) => tasks.find(task => task.id === taskId)?.name || taskId;
  const activityName = (taskId: string, activityId?: string) =>
    tasks.find(task => task.id === taskId)?.activities.find(activity => activity.id === activityId)?.name || activityId;
  const inspect = (taskId: string, activityId?: string, label?: string) => activityId
    ? <button type="button" className="debug-trace-link" onClick={() => onInspect(taskId, activityId)}>{label || activityName(taskId, activityId)}</button>
    : null;
  const selectThread = (id: string) => { setThread(id); setCursors([]); };
  const metrics = report?.metrics;

  return <ModalLayer className="modal-backdrop"><div className="runtime-modal debug-trace-dialog" role="dialog" aria-modal="true" aria-labelledby="debug-trace-title">
    <header><b id="debug-trace-title">Debug Trace & Metrics</b><button type="button" onClick={onClose} aria-label="Close trace">×</button></header>
    <main>
      <nav className="debug-trace-tabs" aria-label="Debug report views">
        <button type="button" aria-pressed={tab === "threads"} onClick={() => setTab("threads")}>Thread paths</button>
        <button type="button" aria-pressed={tab === "metrics"} onClick={() => setTab("metrics")}>Metrics</button>
        <span>{report?.status}</span>
      </nav>
      {error && <p role="alert">{error}</p>}
      {!report && !error && <p role="status">Loading debug report…</p>}
      {report && metrics && tab === "threads" && <>
        <p>Workflow threads represent jobs, branches, and subtask calls. Debug steps through parallel branches in order.</p>
        {!metrics.capture && <p>Path recording was turned off when this session started. Metrics are available.</p>}
        {metrics.capture && <>
          <div className="debug-trace-toolbar">
            <label>Workflow thread <select value={thread} onChange={event => selectThread(event.target.value)}>
              <option value="">All threads</option>
              {thread && !report.threads.some(item => String(item.id) === thread) && <option value={thread}>Thread {thread}</option>}
              {report.threads.map(item => <option key={item.id} value={String(item.id)}>
                {item.id === activeThreadId ? "Current · " : ""}Job {item.job} · #{item.id} {item.kind} · {item.taskName} · {item.status}
              </option>)}
            </select></label>
            {activeThreadId && <button type="button" onClick={() => selectThread(String(activeThreadId))}>Current thread</button>}
            <span>{metrics.threadCount} threads · {metrics.eventCount} events</span>
          </div>
          {thread && report.threads.filter(item => String(item.id) === thread).map(item =>
            <p key={item.id}>Thread #{item.id} · {item.steps} activity visits
              {item.parentId && <> · <button type="button" className="debug-trace-link" onClick={() => selectThread(String(item.parentId))}>Parent #{item.parentId}</button></>}
              {item.entryActivityId && <> · Entry {inspect(item.taskId, item.entryActivityId)}</>}
            </p>)}
          {(metrics.droppedEvents > 0 || metrics.droppedThreads > 0) &&
            <p role="status">Retention limit reached. {metrics.droppedEvents} older events and {metrics.droppedThreads} thread summaries expired.</p>}
          <div className="debug-trace-toolbar">
            <button type="button" disabled={!report.olderBefore} onClick={() => {
              const next = report.olderBefore;
              if (next) setCursors(current => [...current, next]);
            }}>Older events</button>
            <button type="button" disabled={!cursors.length} onClick={() => setCursors(current => current.slice(0, -1))}>Newer events</button>
            <button type="button" onClick={() => { setCursors([]); setRefresh(current => current + 1); }}>Refresh latest</button>
          </div>
          {!report.events.length ? <p>No recorded steps in this view yet.</p> : <div className="debug-trace-table">
            <table><caption>Execution in recorded order</caption><thead><tr>
              <th scope="col">Event</th><th scope="col">Worker TID</th><th scope="col">Since start</th>
              <th scope="col">Execution path</th><th scope="col">Result</th>
            </tr></thead><tbody>{report.events.map(event => <tr key={event.sequence}>
              <td>{event.sequence} · #{event.threadId}</td><td>{event.workerThreadId}</td><td>{time(event.elapsedMs)}</td>
              <td><small>{taskName(event.taskId)}</small> {inspect(event.taskId, event.activityId, event.activityName)}
                {event.targetActivityId && <> → {inspect(event.targetTaskId || event.taskId, event.targetActivityId)}</>}
                {event.targetThreadId && <> · <button type="button" className="debug-trace-link" onClick={() => selectThread(String(event.targetThreadId))}>#{event.targetThreadId}</button></>}
                {event.transitionId && <small>{event.transitionLabel ? `${event.transitionLabel} · ` : ""}{event.transitionId}</small>}
                {event.groups?.map(group => <small key={group.id}>{group.id} · iteration {group.iteration}</small>)}</td>
              <td>{event.transitionType?.replaceAll("_", " ") || event.reason || event.kind.replaceAll("_", " ")}
                {event.outcome && <> · {event.outcome}</>}{event.durationMs !== undefined && <> · {time(event.durationMs)}</>}</td>
            </tr>)}</tbody></table>
          </div>}
        </>}
      </>}
      {metrics && tab === "metrics" && <>
        <p>Active time excludes pauses, listener idle time, and standalone tests. The elapsed job window includes gaps between jobs and time spent paused.</p>
        <dl className="debug-trace-metrics">
          {[
            ["Jobs completed / started", `${metrics.jobs.completed} / ${metrics.jobs.started}`],
            ["Jobs failed / stopped", `${metrics.jobs.failed} / ${metrics.jobs.stopped}`],
            ["Jobs per active second", metrics.jobsPerSecond],
            ["Jobs per elapsed second", metrics.wallJobsPerSecond],
            ["Activity visits per second", metrics.activitiesPerSecond],
            ["Active time", time(metrics.activeMs)],
            ["Elapsed job window", time(metrics.wallWindowMs)],
            ["Last job / slowest job", `${time(metrics.lastJobMs)} / ${time(metrics.maxJobMs)}`],
            ["Activity time", time(metrics.activityMs)],
            ["Activity failures / mocks / events", `${metrics.activities.failed} / ${metrics.activities.mocked} / ${metrics.activities.received}`],
          ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
        {!!metrics.omittedActivitySamples && <p>{metrics.omittedActivitySamples} visits exceeded the per-activity summary limit. Session totals include them.</p>}
        {metrics.byActivity.length > 0 && <div className="debug-trace-table"><table>
          <caption>Activity timings by total duration</caption>
          <thead><tr>{["Activity", "Visits", "Failed", "Mocked", "Received", "Total", "Average", "Minimum", "Maximum"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
          <tbody>{metrics.byActivity.map(item => <tr key={JSON.stringify([item.taskId, item.activityId])}>
            <td><small>{taskName(item.taskId)}</small> {inspect(item.taskId, item.activityId, item.activityName)}</td>
            <td>{item.count}</td><td>{item.failures}</td><td>{item.mocked}</td><td>{item.received}</td>
            <td>{time(item.totalMs)}{metrics.activityMs > 0 && <meter className="debug-trace-time-share" min={0} max={metrics.activityMs} value={item.totalMs} aria-label="Share of measured activity time"/>}</td>
            <td>{time(item.avgMs)}</td><td>{time(item.minMs)}</td><td>{time(item.maxMs)}</td>
          </tr>)}</tbody>
        </table></div>}
      </>}
    </main>
    <footer><a href={`${url}?download=true`} download>Download report (JSON)</a><button type="button" onClick={onClose}>Close</button></footer>
  </div></ModalLayer>;
}
