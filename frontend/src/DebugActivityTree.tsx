import React, { useState } from "react";
import { Activity, ChevronDown, ChevronRight, Search, Workflow } from "lucide-react";
import { debugCallTarget, debugTaskMatches } from "./debugTaskTree";

export default function DebugActivityTree({ tasks, taskId, activityId, busy, onSelect, records, expandCalls = false }: any) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const term = query.trim().toLowerCase();
  const matches = (value: any) => `${value.name} ${value.id} ${value.type || ""}`.toLowerCase().includes(term);
  const visible = tasks.filter((task: any) => debugTaskMatches(tasks, task, term));
  const toggle = (key: string, expanded: boolean, name: string) => <button type="button" aria-label={`${expanded ? "Collapse" : "Expand"} ${name}`} aria-expanded={expanded} onClick={() => setCollapsed(current => ({ ...current, [key]: expanded }))}>{expanded ? <ChevronDown/> : <ChevronRight/>}</button>;
  const select = (task: any, activity?: any) => {
    const selected = taskId === task.id && activityId === (activity?.id || "");
    const Icon = !activity || activity.type === "call_task" ? Workflow : Activity;
    const captured = activity ? records?.[task.id]?.activities?.[activity.id] : records?.[task.id];
    return <button type="button" disabled={busy} className={selected ? "selected" : ""} aria-pressed={selected} onClick={() => onSelect(task.id, activity?.id || "")}><Icon/><span>{activity?.name || task.name}<small>{activity ? activity.type === "call_task" ? "Call Sub Task" : activity.type : `${task.kind === "subtask" ? "Subprocess" : "Process"} · ${task.activities.length} activities`}{records ? captured ? " · captured" : " · not captured" : ""}</small></span></button>;
  };
  const renderTask = (task: any, path: string[], ancestors: string[], showAll = false): React.ReactNode => {
    const key = JSON.stringify(path);
    const expanded = !!term || !collapsed[key];
    const cycle = ancestors.includes(task.id);
    const all = showAll || matches(task);
    return <li key={key}>
      <div className="debug-tree-process">{!cycle && toggle(key, expanded, task.name)}{select(task)}</div>
      {cycle ? <p className="debug-tree-note">Recursive reference — expand this task from its root to inspect it.</p> : expanded && <ul>{task.activities.map((activity: any) => {
        const capturedTarget = records?.[task.id]?.activities?.[activity.id]?.calledTaskId;
        const { target, deferred } = activity.type === "call_task" ? debugCallTarget(tasks, capturedTarget ? { ...activity, config: { taskId: capturedTarget } } : activity) : { target: null, deferred: false };
        if (!all && !matches(activity) && !(target && debugTaskMatches(tasks, target, term))) return null;
        const callPath = [...path, activity.id];
        const callKey = JSON.stringify(callPath);
        const callOpen = !!term || !(collapsed[callKey] ?? !expandCalls);
        return <li key={activity.id}>
          {target ? <div className="debug-tree-process">{toggle(callKey, callOpen, activity.name)}{select(task, activity)}</div> : select(task, activity)}
          {activity.type === "call_task" && deferred && <p className="debug-tree-note">{target ? "Configured fallback shown; runtime target may differ." : "Dynamic target — determined at runtime."}</p>}
          {activity.type === "call_task" && !target && !deferred && <p className="debug-tree-note">Called subtask is missing or not configured.</p>}
          {target && callOpen && <ul>{renderTask(target, [...callPath, target.id], [...ancestors, task.id], all || matches(activity))}</ul>}
        </li>;
      })}</ul>}
    </li>;
  };
  return <aside className="debug-test-tree" aria-label="Processes and activities">
    <h3>PROCESSES & ACTIVITIES</h3>
    <label className="debug-tree-search"><Search/><input aria-label="Search test processes and activities" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search processes or activities…"/></label>
    <nav aria-label="Test target selection"><ul>{visible.map((task: any) => renderTask(task, [task.id], []))}</ul>{!visible.length && <p>No matching processes or activities.</p>}</nav>
  </aside>;
}
