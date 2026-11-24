import { useEffect, useMemo, useRef, useState } from "react";

export type ExecutionLogEntry = {
  level?: string;
  message?: string;
  time?: string;
  kind?: string;
  taskId?: string;
  runtimeActivityId?: string;
  activityId?: string;
  activityName?: string;
  correlationId?: string;
  runId?: string;
  threadId?: string;
  transitionId?: string;
  durationMs?: number;
  payload?: unknown;
};

const pageSize = 200;
const severity = (entry: ExecutionLogEntry) => {
  const level = String(entry.level || "INFO").toUpperCase();
  if (["WARN", "WARNING"].includes(level)) return "WARN";
  if (["ERROR", "CRITICAL", "FATAL"].includes(level)) return "ERROR";
  return level;
};

export function filterExecutionLogs(entries: ExecutionLogEntry[], level: string, query: string, correlation: string) {
  const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  return entries.filter(entry => {
    if (level && severity(entry) !== level) return false;
    if (correlation && entry.correlationId !== correlation) return false;
    if (!terms.length) return true;
    const text = [entry.message, entry.activityName, entry.taskId, entry.activityId, entry.runtimeActivityId,
      entry.kind, entry.correlationId, entry.runId, entry.threadId, entry.transitionId].join(" ").toLowerCase();
    return terms.every(term => text.includes(term));
  });
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

export default function ExecutionLogView({ entries, active, onDownload, resolveActivity, onOpenActivity }: {
  entries: ExecutionLogEntry[];
  active: boolean;
  onDownload: (report: string) => void;
  resolveActivity: (entry: ExecutionLogEntry) => { taskId: string; activityId: string } | undefined;
  onOpenActivity: (taskId: string, activityId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState("");
  const [correlation, setCorrelation] = useState("");
  const [follow, setFollow] = useState(true);
  const [limit, setLimit] = useState(pageSize);
  const scroll = useRef<HTMLDivElement>(null);
  const matches = useMemo(() => filterExecutionLogs(entries, level, query, correlation), [entries, level, query, correlation]);
  const offset = Math.max(0, matches.length - limit);
  const lastMatch = matches[matches.length - 1];
  useEffect(() => {
    if (follow && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [follow, lastMatch]);
  return <section className="execution-log-view" aria-label="Log monitor">
    <div className="execution-log-controls">
      <input type="search" aria-label="Search execution logs" placeholder="Search logs or IDs" value={query}
        onChange={event => { setQuery(event.target.value); setLimit(pageSize); }}/>
      <select aria-label="Log level" value={level} onChange={event => { setLevel(event.target.value); setLimit(pageSize); }}>
        <option value="">All levels</option><option value="ERROR">Errors</option><option value="WARN">Warnings</option>
        <option value="INFO">Info</option><option value="DEBUG">Debug</option><option value="TRACE">Trace</option>
      </select>
      <button type="button" aria-pressed={follow} onClick={() => setFollow(!follow)}>{follow ? "Following latest" : "Follow latest"}</button>
      <button type="button" disabled={!matches.length} title="Download timing and identifiers for all matching rows" onClick={() => onDownload(executionLogReport(matches))}>Export metadata</button>
      {!!offset && <button type="button" onClick={() => { setFollow(false); setLimit(limit + pageSize); }}>Show older matches</button>}
      {correlation && <button type="button" className="execution-correlation" title={correlation}
        onClick={() => { setCorrelation(""); setLimit(pageSize); }}>Clear correlation filter</button>}
      <small>{matches.length - offset} shown · {matches.length} matching · {entries.length} available</small>
    </div>
    <div className="execution-log-list" ref={scroll} role="log" aria-label="Execution logs" aria-live="off" onScroll={event => {
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
    </div>
  </section>;
}
