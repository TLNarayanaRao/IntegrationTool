import { useEffect, useRef, useState } from "react";
import { Ticket } from "lucide-react";
import ModalLayer from "./ModalLayer";
import type { Project, Task } from "./main";
import "./jira-story.css";

type Preview = { project: Project | null; provider: string; summary: string };
export type JiraStoryChange =
  | { scope: "project"; draft: Project }
  | { scope: "task"; draft: Project; baseline: Project; taskId: string; transitionId: string; connectionBindings: Record<string, string> };

export function jiraInsertionTransitions(task?: Task) {
  if (!task || task.library_origin) return [];
  const grouped = new Set((task.groups || []).flatMap(group => group.member_activity_ids));
  return task.transitions.filter(edge => (!edge.type || edge.type === "success") && !edge.condition &&
    !grouped.has(edge.source) && !grouped.has(edge.target) && edge.source !== edge.target);
}

async function jiraRequest<T>(action: "read" | "design", payload: unknown, signal: AbortSignal): Promise<T> {
  const response = await fetch(`/api/ai/jira/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal,
  });
  const result = await response.json().catch(() => null);
  if (!response.ok || !result) {
    throw new Error(typeof result?.detail === "string" ? result.detail : "MINA could not process the request. Check the Studio runtime.");
  }
  return result;
}

export default function JiraStoryDialog({ project, preferredTransition, onClose, onApply, onDownload }: {
  project?: Project;
  preferredTransition?: string;
  onClose: () => void;
  onApply: (change: JiraStoryChange) => void;
  onDownload: (blob: Blob, filename: string) => void;
}) {
  const [source, setSource] = useState<"paste" | "jira">("paste");
  const [scope, setScope] = useState<"project" | "task" | "analyze">("project");
  const [taskId, setTaskId] = useState(project?.active_task_id || "");
  const [transitionId, setTransitionId] = useState(preferredTransition || "");
  const [url, setUrl] = useState(""), [email, setEmail] = useState(""), [token, setToken] = useState("");
  const [story, setStory] = useState(""), [name, setName] = useState("");
  const [issueKey, setIssueKey] = useState("");
  const [acceptanceField, setAcceptanceField] = useState("");
  const [includeRelated, setIncludeRelated] = useState(false);
  const [readNotice, setReadNotice] = useState("");
  const [busy, setBusy] = useState<"read" | "design" | "">("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [change, setChange] = useState<JiraStoryChange | null>(null);
  const [provider, setProvider] = useState<"openai" | "local-blueprint" | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const status = new AbortController();
    fetch("/api/ai/status", { signal: status.signal }).then(response => {
      if (!response.ok) throw new Error();
      return response.json();
    }).then(result => setProvider(result.provider)).catch(() => {});
    return () => { request.current?.abort(); status.abort(); };
  }, []);

  const tasks = (project?.tasks || []).filter(item => !item.library_origin);
  const task = tasks.find(item => item.id === taskId) || tasks[0];
  const transitions = jiraInsertionTransitions(task);
  const transition = transitions.find(item => item.id === transitionId) || transitions[0];
  const activityName = (id: string) => task?.activities.find(item => item.id === id)?.name || id;
  const invalidate = () => { setPreview(null); setChange(null); setError(""); };
  const makeRequest = async (action: "read" | "design") => {
    const controller = new AbortController();
    request.current = controller;
    invalidate();
    setBusy(action);
    try {
      if (action === "read") {
        setIssueKey(""); setReadNotice("");
        const result = await jiraRequest<{ key: string; title: string; story: string; notice?: string }>(
          action, { url, email, token, acceptance_field: acceptanceField, include_related: includeRelated }, controller.signal,
        );
        setIssueKey(result.key); setName(result.title); setStory(result.story);
        setReadNotice(result.notice || "");
      } else {
        const flow = scope !== "project" && task ? {
          name: task.name, source: scope === "task" ? transition?.source : undefined,
          target: scope === "task" ? transition?.target : undefined,
          activities: task.activities.map(item => ({
            id: item.id, name: item.name, type: item.type, operation: String(item.config.operation || ""),
          })),
          transitions: task.transitions.map(edge => [edge.source, edge.target, edge.type || "success"]),
        } : undefined;
        const result = await jiraRequest<Preview>(action, { story, name, scope, flow, issue_key: source === "jira" ? issueKey : "" }, controller.signal);
        setPreview(result);
        if (!result.project) return;
        if (scope === "project") setChange({ scope, draft: result.project });
        else if (scope === "task" && project && task && transition) {
          setChange({ scope, draft: result.project, baseline: project, taskId: task.id, transitionId: transition.id, connectionBindings: {} });
        }
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "The request failed.");
    } finally {
      if (action === "read") setToken("");
      setBusy("");
    }
  };
  const canPreview = !busy && story.trim().length >= 10 &&
    (scope === "analyze" ? task : name.trim() && (scope === "project" || transition));
  const stale = change?.scope === "task" && project !== change.baseline;
  const downloadReview = () => {
    if (!preview) return;
    const review = {
      issue: source === "jira" ? issueKey : "", target: scope, provider: preview.provider, summary: preview.summary,
      task: scope !== "project" ? task?.name : undefined,
      insertion: scope === "task" && transition ? [activityName(transition.source), activityName(transition.target)] : undefined,
      proposedTasks: preview.project?.tasks.map(item => ({ name: item.name, activities: item.activities.map(activity => ({
        name: activity.name, type: activity.type, operation: activity.config.operation,
      })) })),
      connections: preview.project?.resources.map(item => ({
        name: item.name, type: item.type,
        reuse: change?.scope === "task" ? project?.resources.find(existing => existing.id === change.connectionBindings[item.id])?.name : undefined,
      })),
    };
    onDownload(new Blob([JSON.stringify(review, null, 2)], { type: "application/json" }), "MINA-Jira-review.json");
  };

  return <ModalLayer><div className="runtime-modal jira-story-dialog" role="dialog" aria-modal="true" aria-labelledby="jira-story-title"
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } }}>
    <header><span><Ticket aria-hidden="true"/><b id="jira-story-title">Jira Story</b></span><button type="button" aria-label="Close Jira Story" onClick={onClose}>×</button></header>
    <main>
      <div className="jira-story-selectors">
        <label>Story source<select autoFocus value={source} disabled={!!busy} onChange={event => {
          setSource(event.target.value as typeof source); setToken(""); invalidate();
        }}><option value="paste">Paste story</option><option value="jira">Read Jira Cloud issue</option></select></label>
        <label>Integration target<select value={scope} disabled={!!busy} onChange={event => {
          setScope(event.target.value as typeof scope); invalidate();
        }}><option value="project">New project</option><option value="analyze" disabled={!tasks.length}>Review existing flow</option><option value="task" disabled={!tasks.length}>Extend existing flow</option></select></label>
      </div>
      {source === "jira" && <fieldset disabled={!!busy}>
        <legend>Jira Cloud</legend>
        <label>Issue URL<input type="url" value={url} placeholder="https://example.atlassian.net/browse/INT-123" onChange={event => {
          setUrl(event.target.value); setIssueKey(""); setReadNotice(""); invalidate();
        }}/></label>
        <div className="jira-story-selectors">
          <label>Jira email<input type="email" autoComplete="off" value={email} onChange={event => setEmail(event.target.value)}/></label>
          <label>API token<input type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)}/></label>
        </div>
        <label>Acceptance criteria field ID <small>(optional)</small><input value={acceptanceField} maxLength={40}
          placeholder="customfield_10042" onChange={event => setAcceptanceField(event.target.value)}/></label>
        <label className="jira-checkbox"><input type="checkbox" checked={includeRelated} onChange={event => setIncludeRelated(event.target.checked)}/>
          Include status, issue type, and parent and subtask summaries</label>
        <p>For a public issue, leave both credential fields blank. MINA clears the token after the read.</p>
        <button type="button" disabled={!url.trim() || !!email.trim() !== !!token.trim()} onClick={() => void makeRequest("read")}>
          {busy === "read" ? "Reading issue…" : "Read issue"}
        </button>
        {issueKey && <span role="status"> Loaded {issueKey}</span>}
        {readNotice && <p role="status">{readNotice}</p>}
      </fieldset>}
      {scope !== "project" && <fieldset disabled={!!busy}>
        <legend>Existing flow</legend>
        <div className="jira-story-selectors">
          <label>Task<select value={task?.id || ""} onChange={event => { setTaskId(event.target.value); setTransitionId(""); invalidate(); }}>
            {tasks.map(item => <option key={item.id} value={item.id}>{item.package_path || "Default"}/{item.name}</option>)}
          </select></label>
          {scope === "task" && <label>Insert on transition<select value={transition?.id || ""} disabled={!transitions.length} onChange={event => { setTransitionId(event.target.value); invalidate(); }}>
            {!transitions.length && <option value="">No eligible success transition</option>}
            {transitions.map(item => <option key={item.id} value={item.id}>{activityName(item.source)} → {activityName(item.target)}</option>)}
          </select></label>}
        </div>
        {scope === "task" && <p>Choose a success transition outside groups. Review the downstream mappings, especially expressions that use <code>{"${last}"}</code>.</p>}
      </fieldset>}
      {scope !== "analyze" && <label>{scope === "project" ? "Project name" : "Change name"}<input value={name} maxLength={160} disabled={!!busy} onChange={event => { setName(event.target.value); invalidate(); }}/></label>}
      <label>Story and acceptance criteria<textarea value={story} maxLength={20000} disabled={!!busy}
        placeholder="Describe the trigger, data contract, destinations, and acceptance criteria."
        onChange={event => { setStory(event.target.value); invalidate(); }}/></label>
      {provider === "openai" && <p>Generating a preview sends the story and selected flow metadata to the configured OpenAI model.</p>}
      {provider === "local-blueprint" && <p>Local blueprint mode matches supported activity keywords. Review story coverage and complete the connections and mappings in Studio.</p>}
      {error && <p role="alert" className="jira-story-error">{error}</p>}
      {stale && <p role="alert" className="jira-story-error">The project changed. Generate a fresh preview before applying.</p>}
      {preview && <section className="jira-story-preview" aria-label="Design preview" aria-live="polite">
        <h3>{scope === "analyze" ? "Flow review" : "Design preview"}</h3>
        <p>{preview.summary}</p>
        {scope === "task" && !!preview.project?.tasks.length && transition && <p>Insert between <strong>{activityName(transition.source)}</strong> and <strong>{activityName(transition.target)}</strong>.</p>}
        {preview.project && (preview.project.tasks.length === 0 ? <p>No applicable changes were generated.</p> : <>
          {preview.project.tasks.map(item => <article key={item.id}>
            {scope === "project" && <strong>{item.name}</strong>}
            <ol>{item.activities.map(activity => <li key={activity.id}>{activity.name} <small>({activity.type})</small></li>)}</ol>
          </article>)}
          {!!preview.project.resources.length && <p>Connections to review: {preview.project.resources.map(item => item.name).join(", ")}</p>}
          {change?.scope === "task" && preview.project.resources.map(item => {
            const candidates = project?.resources.filter(existing => existing.type === item.type && !existing.library_origin) || [];
            return candidates.length > 0 && <label key={item.id}>{item.name}
              <select value={change.connectionBindings[item.id] || ""} onChange={event => {
                const id = event.target.value;
                setChange({ ...change, connectionBindings: { ...change.connectionBindings, [item.id]: id } });
              }}>
                <option value="">Create draft connection</option>
                {candidates.map(existing => <option key={existing.id} value={existing.id}>Reuse {existing.package_path || "Default"}/{existing.name}</option>)}
              </select>
            </label>;
          })}
          <details><summary>View draft configuration and mappings</summary><pre>{JSON.stringify({
            tasks: preview.project.tasks, resources: preview.project.resources, schemas: preview.project.schemas,
          }, null, 2)}</pre></details>
        </>)}
        <button type="button" onClick={downloadReview}>Download review</button>
      </section>}
    </main>
    <footer>
      <button type="button" onClick={onClose}>Cancel</button>
      <button type="button" disabled={!canPreview} onClick={() => void makeRequest("design")}>{busy === "design" ? "Analyzing story…" : scope === "analyze" ? "Review flow" : "Generate preview"}</button>
      {scope !== "analyze" && <button type="button" className="primary" disabled={!!busy || !change || !preview?.project?.tasks.length || stale} onClick={() => {
        if (!change) return;
        try { onApply(change); } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to apply the design."); }
      }}>{scope === "project" ? "Create project" : "Insert activities"}</button>}
    </footer>
  </div></ModalLayer>;
}
