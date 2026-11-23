import { useEffect, useId, useMemo, useRef, useState, type SetStateAction } from "react";
import { X } from "lucide-react";
import ModalLayer from "./ModalLayer";
import SubtaskInputEditor from "./SubtaskInputEditor";
import { decodeSubtaskXmlFile, guidedInputFields, newSubtaskInputDraft, readSubtaskInput, selectedSubtaskFile, subtaskInputFormat, type FileInputMethod, type SubtaskInputDraft } from "./subtaskInput";
import { executionReadiness, launchEntry, parseLaunchInput, type LaunchMode, type LaunchOptions, type LaunchProject, type SubtaskInputFormat, type SubtaskInputReport } from "./executionSetup";
import type { ValidationIssue } from "./ValidationReview";
import "./execution-setup.css";

export default function ExecutionSetupDialog({ project, initialTask, initialMode, activeEnvironment, busy, validate, checkSubtaskInput, onFinding, onConnection, onProperties, onStart, onClose }: {
  project: LaunchProject;
  initialTask: string;
  initialMode: LaunchMode;
  activeEnvironment: string;
  busy: boolean;
  validate: (taskIds: string[], environment: string) => ValidationIssue[];
  checkSubtaskInput: (taskId: string, input?: unknown, format?: SubtaskInputFormat, signal?: AbortSignal) => Promise<SubtaskInputReport>;
  onFinding: (issue: ValidationIssue) => void;
  onConnection: (id: string, environment: string) => void;
  onProperties: (environment: string) => void;
  onStart: (mode: LaunchMode, taskId: string, options: LaunchOptions) => void;
  onClose: () => void;
}) {
  const title = useId();
  const [mode, setMode] = useState(initialMode);
  const [taskId, setTaskId] = useState(initialTask);
  const [environment, setEnvironment] = useState(activeEnvironment);
  const [payload, setPayload] = useState("{}");
  const [capture, setCapture] = useState(true);
  const [error, setError] = useState("");
  const [inputReport, setInputReport] = useState<SubtaskInputReport>();
  const [subtaskDraft, setSubtaskDraft] = useState(() => newSubtaskInputDraft());
  const [inputCheck, setInputCheck] = useState<string[]>();
  const [checking, setChecking] = useState(false);
  const [contractError, setContractError] = useState("");
  const inputFileRevision = useRef({file:0, "xml-file":0});
  const checkInput = useRef(checkSubtaskInput);
  checkInput.current = checkSubtaskInput;
  const [view, setView] = useState<"launch" | "readiness">("launch");
  const environments = Object.keys(project.properties);
  const profile = environments.includes(environment) ? environment : environments[0] || "";
  const choices = project.tasks.filter(task => !task.library_origin && (mode === "debug" || task.kind === (mode === "subtask" ? "subtask" : "starter")));
  const task = choices.find(item => item.id === taskId) ?? choices[0];
  const selectedId = task?.id;
  const entry = task && launchEntry(task);
  const acceptsInput = !!task && (mode !== "run" || entry?.kind === "once");
  const readiness = useMemo(() => view === "readiness" && task && profile ? executionReadiness(project, task, profile) : null, [project, task, profile, view]);
  const findings = useMemo(() => readiness ? validate(readiness.taskIds, profile) : [], [profile, readiness, validate]);
  const inputFields = useMemo(() => inputReport ? guidedInputFields(inputReport) : [], [inputReport]);
  useEffect(() => {
    setInputReport(undefined);
    setInputCheck(undefined);
    setContractError("");
    if (mode !== "subtask" || !selectedId) return;
    const controller = new AbortController();
    checkInput.current(selectedId, undefined, undefined, controller.signal).then(report => {
      if (!controller.signal.aborted) {
        setInputReport(report);
        setSubtaskDraft(newSubtaskInputDraft(report));
      }
    }).catch(problem => {
      if (!controller.signal.aborted) setContractError(problem instanceof Error ? problem.message : String(problem));
    });
    return () => { controller.abort(); inputFileRevision.current.file++; inputFileRevision.current["xml-file"]++; };
  }, [mode, selectedId]);
  const updateSubtaskDraft = (update: SetStateAction<SubtaskInputDraft>) => {
    setSubtaskDraft(update);
    setError("");
    setInputCheck(undefined);
  };
  const loadSubtaskFile = async (file: File, method: FileInputMethod) => {
    const revision = ++inputFileRevision.current[method];
    updateSubtaskDraft(current => ({...current, [method]:{name:file.name}}));
    try {
      const text = (method === "xml-file" ? decodeSubtaskXmlFile(await file.arrayBuffer()) : await file.text()).replace(/^\uFEFF/, "");
      if (revision === inputFileRevision.current[method]) updateSubtaskDraft(current => ({...current, [method]:{name:file.name, text}}));
    } catch {
      if (revision === inputFileRevision.current[method]) updateSubtaskDraft(current => ({
        ...current, [method]:{name:file.name, error:method === "xml-file" ? "Could not read this XML file. Check its encoding or save it as UTF-8." : "The selected file could not be read."},
      }));
    }
  };
  const changePayload = (text: string) => { setPayload(text); setError(""); setInputCheck(undefined); };
  const parseInput = (text: string) => {
    try { return mode === "subtask" ? JSON.parse(text) as unknown : parseLaunchInput(text); }
    catch (problem) {
      setError(problem instanceof SyntaxError ? "Enter valid JSON before launching." : "Enter a JSON object for the initial task input.");
      return undefined;
    }
  };
  const selectedFile = selectedSubtaskFile(subtaskDraft);
  const readingFile = !!selectedFile && selectedFile.text === undefined && !selectedFile.error;
  const blocked = busy || checking || !task || !profile || mode === "run" && entry?.kind === "invalid" || mode === "subtask" && (!inputReport || readingFile);
  const start = async (validateOnly = false) => {
    if (blocked || !task) return;
    let input: unknown;
    try {
      input = mode === "subtask" ? readSubtaskInput(subtaskDraft, inputFields) : acceptsInput && payload.trim() ? parseInput(payload) : {};
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
      setView("launch");
      return;
    }
    if (input === undefined) { setView("launch"); return; }
    const inputFormat = mode === "subtask" ? subtaskInputFormat(subtaskDraft.method) : undefined;
    if (mode === "subtask") {
      setError("");
      setChecking(true);
      try {
        const result = await checkSubtaskInput(task.id, input, inputFormat);
        setInputCheck(result.errors);
        if (result.errors.length) { setView("launch"); return; }
      } catch (problem) {
        setError(problem instanceof Error ? problem.message : String(problem));
        setView("launch");
        return;
      } finally { setChecking(false); }
    }
    if (!validateOnly) onStart(mode, task.id, {input, environment: profile, capture, testSubtask: mode === "subtask", inputFormat});
  };

  return <ModalLayer><form className="execution-setup" role="dialog" aria-modal="true" aria-labelledby={title}
    onSubmit={event => { event.preventDefault(); void start(); }}
    onKeyDown={event => {
      event.stopPropagation();
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key === "Tab") {
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:enabled, input:enabled, select:enabled, textarea:enabled"));
        const last = controls[controls.length - 1];
        const edge = event.shiftKey ? controls[0] : last;
        if (document.activeElement === edge) {
          event.preventDefault();
          (event.shiftKey ? last : controls[0])?.focus();
        }
      }
    }}>
    <header><h2 id={title}>Execution Setup</h2><button type="button" aria-label="Close execution setup" onClick={onClose}><X aria-hidden="true"/></button></header>
    <div className="execution-setup-controls">
      <label>Mode<select autoFocus disabled={checking} value={mode} onChange={event => {setMode(event.target.value as LaunchMode); setError("");}}>
        <option value="run">Run</option><option value="subtask">Test Subtask</option><option value="debug">Debug with Input</option>
      </select></label>
      <label>Task<select disabled={checking} value={task?.id || ""} onChange={event => {setTaskId(event.target.value); setError("");}}>
        {!choices.length && <option value="">No eligible tasks</option>}
        {choices.map(item => <option key={item.id} value={item.id}>{item.package_path ? `${item.package_path} / ` : ""}{item.name}</option>)}
      </select></label>
      <label>Environment<select disabled={checking} value={profile} onChange={event => setEnvironment(event.target.value)}>
        {!environments.length && <option value="">No environment profiles</option>}
        {environments.map(name => <option key={name}>{name}</option>)}
      </select></label>
    </div>
    <nav aria-label="Execution setup views">
      <button type="button" aria-pressed={view === "launch"} onClick={() => setView("launch")}>Launch</button>
      <button type="button" aria-pressed={view === "readiness"} onClick={() => setView("readiness")}>Readiness</button>
    </nav>
    <main>
      {view === "launch" && <>
        {mode === "debug" && task && <p>Debug starts paused at the selected task entry. No live listener is started.</p>}
        {mode === "run" && entry?.kind === "invalid" && <p role="alert">This Starter Task needs exactly one entry activity. Review its flow before running.</p>}
        {mode === "run" && entry?.kind === "listener" && <p><strong>{entry.name}</strong> will start a live receiver. The sender supplies input when an event arrives.</p>}
        {mode === "run" && entry?.kind === "schedule" && <p><strong>{entry.name}</strong> will start the configured schedule. The timer supplies each event.</p>}
        {mode === "run" && !task && <p>Choose Test Subtask to run a Subtask directly, or create a Starter Task for an event flow.</p>}
        {mode === "subtask" && task && <>
          <p>Runs this Subtask from its Start activity using the selected environment. Its activities execute normally.</p>
          {!inputReport && !contractError && <p role="status">Loading Start input structure…</p>}
          {contractError && <p role="alert">{contractError}</p>}
          {inputReport?.format === "none" && <p>Start has no input schema. Choose No input to run with an empty object.</p>}
          {inputReport && inputReport.format !== "none" && <details>
            <summary>{inputReport.name} · {inputReport.format === "xsd" ? "XSD structure" : "JSON Schema"}</summary>
            {inputReport.format === "xsd" && <p>Paste or load XML, or use JSON with the selected XML root as its top-level field.</p>}
            {!!inputReport.fields?.length && <ul>{inputReport.fields.map(field => <li key={field.path}>
              <code>{field.path}</code><span>{field.type}{field.repeating ? " · repeating" : ""}{field.required ? " · required" : ""}</span>
            </li>)}</ul>}
          </details>}
          {inputReport && <SubtaskInputEditor key={selectedId} report={inputReport} fields={inputFields}
            draft={subtaskDraft} update={updateSubtaskDraft} loadFile={(file, method) => void loadSubtaskFile(file, method)} disabled={checking}
            onError={setError} validate={() => void start(true)} validationDisabled={blocked}/>}
        </>}
        {acceptsInput && mode !== "subtask" && <>
          <label>Initial task input (JSON)<textarea disabled={checking} value={payload} onChange={event => changePayload(event.target.value)} spellCheck={false}/></label>
          <div className="execution-setup-actions">
            <label>Load JSON file<input disabled={checking} type="file" accept=".json,application/json" onChange={async event => {
              const file = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (!file) return;
              try { changePayload((await file.text()).replace(/^\uFEFF/, "")); }
              catch { setError("The selected file could not be read."); }
            }}/></label>
            <button type="button" disabled={checking} onClick={() => {
              const value = parseInput(payload);
              if (value !== undefined) changePayload(JSON.stringify(value, null, 2));
            }}>Format JSON</button>
            <button type="button" disabled={checking} onClick={() => changePayload("{}")}>Reset input</button>
          </div>
        </>}
        {mode === "debug" && <label className="execution-setup-capture"><input type="checkbox" checked={capture} onChange={event => setCapture(event.target.checked)}/> Record thread paths</label>}
        {error && <p role="alert">{error}</p>}
        {inputCheck && (inputCheck.length ? <ul role="alert">{inputCheck.map((message, index) => <li key={index}>{message}</li>)}</ul>
          : <p role="status">Input is valid.</p>)}
      </>}
      {view === "readiness" && readiness && <>
        <p>Configuration check for <strong>{profile}</strong>. Live connectivity is tested from each connection editor.</p>
        <h3>Shared connections</h3>
        {readiness.connections.length ? <ul>{readiness.connections.map(connection => <li key={connection.id}>
          <span><strong>{connection.name}</strong> · {connection.missing ? "Missing" : connection.type}<small>{connection.usedBy.join(", ")}</small></span>
          {!connection.missing && <button type="button" onClick={() => onConnection(connection.id, profile)}>Open connection</button>}
        </li>)}</ul> : <p>No statically referenced shared connections.</p>}
        <h3>Environment properties</h3>
        <p>{readiness.propertyCount} referenced {readiness.propertyCount === 1 ? "property" : "properties"}{!readiness.propertyFindings.length ? " · no missing or empty values" : ""}.</p>
        {readiness.propertyFindings.length > 0 && <ul>{readiness.propertyFindings.map(({key, status}) => <li key={key}><code>{key}</code><strong>{status}</strong></li>)}</ul>}
        <button type="button" onClick={() => onProperties(profile)}>Open {profile}.properties</button>
        <h3>Flow and mapping findings</h3>
        <p>{readiness.taskIds.length} {readiness.taskIds.length === 1 ? "task" : "tasks"} checked · {findings.length} {findings.length === 1 ? "finding" : "findings"}</p>
        {findings.length > 0 && <ul>{findings.map(issue => <li key={issue.id}><span><strong>{issue.severity} · {issue.category}</strong><small>{issue.message}</small></span>
          <button type="button" onClick={() => onFinding(issue)}>Open finding</button>
        </li>)}</ul>}
        {readiness.runtimeDependencies && <p>Some task or connection dependencies resolve at runtime. The list covers references Studio can resolve for this environment.</p>}
      </>}
      {view === "readiness" && !readiness && <p>Select a task and an environment to review dependencies.</p>}
    </main>
    <footer>
      <button type="button" onClick={onClose}>Cancel</button>
      <button type="submit" className="primary" disabled={blocked}>
        {checking ? "Validating…" : mode === "subtask" ? "Run Subtask test" : mode === "debug" ? "Start paused" : entry?.kind === "listener" ? "Start listener" : entry?.kind === "schedule" ? "Start schedule" : "Run task"}
      </button>
    </footer>
  </form></ModalLayer>;
}
