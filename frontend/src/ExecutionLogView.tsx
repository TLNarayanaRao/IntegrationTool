import { useEffect, useMemo, useRef, useState } from "react";

export type ExecutionLogEntry = {
  level?: string;
  message?: string;
  time?: string;
  kind?: string;
  taskId?: string;
  taskName?: string;
  runtimeActivityId?: string;
  activityId?: string;
  activityName?: string;
  correlationId?: string;
  runId?: string;
  threadId?: string;
  transitionId?: string;
  durationMs?: number;
  timingScope?: string;
  payload?: unknown;
};

const pageSize = 200;
const severity = (entry: ExecutionLogEntry) => {
  const level = String(entry.level || "INFO").toUpperCase();
  if (["WARN", "WARNING"].includes(level)) return "WARN";
  if (["ERROR", "CRITICAL", "FATAL"].includes(level)) return "ERROR";
  return level;
};

type ActivityLocation = { taskId: string; activityId: string };

export function filterExecutionLogs(entries: ExecutionLogEntry[], level: string, query: string, correlation: string, activity?: ActivityLocation) {
  const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  return entries.filter(entry => {
    if (level && severity(entry) !== level) return false;
    if (correlation && entry.correlationId !== correlation) return false;
    if (activity && (entry.taskId !== activity.taskId || (entry.runtimeActivityId || entry.activityId) !== activity.activityId)) return false;
    if (!terms.length) return true;
    const text = [entry.message, entry.activityName, entry.taskName, entry.taskId, entry.activityId, entry.runtimeActivityId,
      entry.kind, entry.correlationId, entry.runId, entry.threadId, entry.transitionId].join(" ").toLowerCase();
    return terms.every(term => text.includes(term));
  });
}

export function summarizeActivityTimings(entries: ExecutionLogEntry[]) {
  const timings = new Map<string, ActivityLocation & {
    activityName: string; taskName: string; scope: string; invocations: number; failures: number; totalMs: number; maxMs: number;
  }>();
  for (const entry of entries) {
    const { taskId, durationMs } = entry;
    const activityId = entry.runtimeActivityId || entry.activityId;
    if (entry.kind !== "activity" || !taskId || !activityId ||
      typeof durationMs !== "number" || !Number.isFinite(durationMs) || durationMs < 0) continue;
    const scope = entry.timingScope || "";
    const key = JSON.stringify([taskId, activityId, scope]);
    const result = timings.get(key) || { taskId, activityId, activityName: entry.activityName || activityId,
      taskName: entry.taskName || taskId, scope, invocations: 0, failures: 0, totalMs: 0, maxMs: 0 };
    result.invocations += 1;
    if (severity(entry) === "ERROR") result.failures += 1;
    result.totalMs += durationMs;
    result.maxMs = Math.max(result.maxMs, durationMs);
    timings.set(key, result);
  }
  return [...timings.values()];
}

export function executionLogReport(entries: ExecutionLogEntry[]) {
  return entries.map(({ time, level, kind, taskId, runtimeActivityId, activityId, activityName, correlationId, runId, threadId, transitionId, durationMs }) =>
    JSON.stringify({ time, level, kind, taskId, runtimeActivityId, activityId, activityName, correlationId, runId, threadId, transitionId, durationMs }),
  ).join("\n") + "\n";
}

function LogPayload({ value }: { value: unknown }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Payload</summary>
    {open && <pre>{JSON.stringify(value, null, 2)}</pre>}
  </details>;
}

export default function ExecutionLogView({ entries, active, onDownload, resolveActivity, onOpenActivity, taskName }: {
  entries: ExecutionLogEntry[];
  active: boolean;
  onDownload: (report: string) => void;
  resolveActivity: (entry: ExecutionLogEntry) => { taskId: string; activityId: string } | undefined;
  onOpenActivity: (taskId: string, activityId: string) => void;
  taskName?: (taskId: string) => string | undefined;
}) {
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState("");
  const [correlation, setCorrelation] = useState("");
  const [follow, setFollow] = useState(true);
  const [limit, setLimit] = useState(pageSize);
  const [view, setView] = useState<"logs" | "timings">("logs");
  const [activity, setActivity] = useState<(ActivityLocation & { activityName: string })>();
  const [order, setOrder] = useState<"maxMs" | "totalMs" | "failures">("maxMs");
  const scroll = useRef<HTMLDivElement>(null);
  const matches = useMemo(() => filterExecutionLogs(entries, level, query, correlation, activity), [entries, level, query, correlation, activity]);
  const timings = useMemo(() => view === "timings" ? summarizeActivityTimings(matches)
    .sort((left, right) => right[order] - left[order] || right.maxMs - left.maxMs) : [], [matches, order, view]);
  const offset = Math.max(0, matches.length - limit);
  const lastMatch = matches[matches.length - 1];
  useEffect(() => {
    if (view === "logs" && follow && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [view, follow, lastMatch]);
  return <section className="execution-log-view" aria-label="Log monitor">
    <div className="execution-log-controls">
      <input type="search" aria-label="Search execution logs" placeholder="Search logs or IDs" value={query}
        onChange={event => { setQuery(event.target.value); setLimit(pageSize); }}/>
      <select aria-label="Log level" value={level} onChange={event => { setLevel(event.target.value); setLimit(pageSize); }}>
        <option value="">All levels</option><option value="ERROR">Errors</option><option value="WARN">Warnings</option>
        <option value="INFO">Info</option><option value="DEBUG">Debug</option><option value="TRACE">Trace</option>
      </select>
      <select aria-label="Execution view" value={view} onChange={event => setView(event.target.value === "timings" ? "timings" : "logs")}>
        <option value="logs">Logs</option><option value="timings">Activity timings</option>
      </select>
      {view === "timings" ? <select aria-label="Sort activity timings" value={order} onChange={event => setOrder(event.target.value as typeof order)}>
        <option value="maxMs">Longest invocation</option><option value="totalMs">Total time</option><option value="failures">Most failures</option>
      </select> : <button type="button" aria-pressed={follow} onClick={() => setFollow(!follow)}>{follow ? "Following latest" : "Follow latest"}</button>}
      <button type="button" disabled={!matches.length} title="Download timing and identifiers for all matching rows" onClick={() => onDownload(executionLogReport(matches))}>Export metadata</button>
      {view === "logs" && !!offset && <button type="button" onClick={() => { setFollow(false); setLimit(limit + pageSize); }}>Show older matches</button>}
      {correlation && <button type="button" className="execution-correlation" title={correlation}
        onClick={() => { setCorrelation(""); setLimit(pageSize); }}>Clear correlation filter</button>}
      {activity && <button type="button" onClick={() => { setActivity(undefined); setLimit(pageSize); }}>Clear activity filter ({activity.activityName})</button>}
      {view === "logs" && <small>{matches.length - offset} shown · {matches.length} matching · {entries.length} available</small>}
    </div>
    {view === "timings" ? <div className="execution-timing-list">
      <p>Based on matching activity completion and failure logs. {Math.min(100, timings.length)} of {timings.length} timing groups shown.</p>
      {timings.length > 0 && <table aria-label="Activity timings">
        <thead><tr><th scope="col">Task / Activity</th><th scope="col">Invocations</th><th scope="col">Failures</th>
          <th scope="col">Average (ms)</th><th scope="col">Longest (ms)</th><th scope="col">Total (ms)</th><th scope="col">Actions</th></tr></thead>
        <tbody>{timings.slice(0, 100).map(result => <tr key={JSON.stringify([result.taskId, result.activityId, result.scope])}>
          <th scope="row">{result.activityName}<small>{taskName?.(result.taskId) || result.taskName}{result.scope ? " · " + result.scope.replace(/_/g, " ") : ""}</small></th>
          <td>{result.invocations}</td><td>{result.failures}</td><td>{(result.totalMs / result.invocations).toFixed(1)}</td>
          <td>{result.maxMs.toFixed(1)}</td><td>{result.totalMs.toFixed(1)}</td>
          <td className="execution-log-links">
            <button type="button" onClick={() => { setActivity(result); setLimit(pageSize); setView("logs"); }}>Show logs</button>
            {resolveActivity(result) && <button type="button" onClick={() => onOpenActivity(result.taskId, result.activityId)}>Open activity</button>}
          </td>
        </tr>)}</tbody>
      </table>}
    </div> : <div className="execution-log-list" ref={scroll} role="log" aria-label="Execution logs" aria-live="off" onScroll={event => {
      const log = event.currentTarget;
      if (follow && log.scrollHeight - log.clientHeight - log.scrollTop > 32) setFollow(false);
    }}>
      {!matches.length && <p className="execution-log-empty">{entries.length ? "No logs match the filters." :
        active ? "Waiting for execution logs…" : "No runtime logs recorded."}</p>}
      {matches.slice(offset).map((entry, index) => {
        const activity = resolveActivity(entry);
        return <div className={`log ${severity(entry).toLowerCase()}`}
          key={`${entry.time || ""}:${entry.runId || ""}:${entry.runtimeActivityId || ""}:${offset + index}`}>
          <small>{entry.time ? new Date(entry.time).toLocaleTimeString() : ""} {entry.level}
            {typeof entry.durationMs === "number" ? ` · ${entry.durationMs.toFixed(1)} ms` : ""}</small>
          <p>{entry.message}</p>
          <div className="execution-log-links">
            {entry.correlationId && <button type="button" title="Show logs for this correlation ID" aria-pressed={correlation === entry.correlationId}
              onClick={() => { setCorrelation(entry.correlationId || ""); setLimit(pageSize); }}>{entry.correlationId}</button>}
            {activity && <button type="button" onClick={() => onOpenActivity(activity.taskId, activity.activityId)}>Open activity</button>}
          </div>
          {entry.payload !== undefined && entry.payload !== null && entry.payload !== "" && <LogPayload value={entry.payload}/>}
        </div>;
      })}
    </div>}
  </section>;
}
