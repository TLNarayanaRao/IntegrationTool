import {useEffect, useState} from "react";
import {Activity, AlertCircle, CheckCircle2, LoaderCircle} from "lucide-react";
import ModalLayer from "./ModalLayer";

export type StartupStatus = {step:number; total:number; label:string; elapsedMs:number; failed:boolean; timings?:{label:string;durationMs:number}[]};
type RuntimeActivity = {taskId:string; taskName:string; activityId:string; activityName:string; startedAt:string};
type RuntimeSnapshot = {projectId:string; status:string; activities:RuntimeActivity[]};

export default function RuntimeStatus({work = "", projectId, watching = false, debugStatus, debugActivities = []}: {
  work?:string; projectId?:string; watching?:boolean; debugStatus?:string; debugActivities?:string[];
}) {
  const [startup,setStartup] = useState<StartupStatus>();
  const [health,setHealth] = useState<"checking"|"ready"|"unavailable">("checking");
  const [snapshot,setSnapshot] = useState<RuntimeSnapshot>();
  const [open,setOpen] = useState(false);
  const [progressUnavailable,setProgressUnavailable] = useState(false);
  const debugging = !!debugStatus;
  const knownActive = !!snapshot && snapshot.projectId === projectId && ["running","listening"].includes(snapshot.status);
  const [longTask,setLongTask] = useState<{duration:number; at:number}>();
  useEffect(() => {
    if (!globalThis.PerformanceObserver?.supportedEntryTypes?.includes("longtask")) return;
    const observer = new PerformanceObserver(list => {
      const entries = list.getEntries().filter(item => item.duration >= 100);
      const entry = entries[entries.length - 1];
      if (entry) setLongTask({duration:Math.round(entry.duration), at:performance.timeOrigin + entry.startTime});
    });
    observer.observe({entryTypes:["longtask"]});
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let cancelled = false;
    const bridge = window.minaDesktop;
    const update = (next:StartupStatus) => { if (!cancelled) setStartup(current => current && current.elapsedMs > next.elapsedMs ? current : next); };
    const unsubscribe = bridge?.onStartupStatus?.(update);
    void bridge?.getStartupStatus?.().then(update).catch(() => {});
    return () => {cancelled = true; unsubscribe?.();};
  }, []);
  useEffect(() => {
    let cancelled = false;
    let timer:number | undefined;
    let lastHealthCheck = 0;
    let available = false;
    let progressSupported = true;
    const controller = new AbortController();
    const request = async (url:string) => {
      const bounded = new AbortController();
      const abort = () => bounded.abort();
      controller.signal.addEventListener("abort",abort,{once:true});
      const timeout = window.setTimeout(abort,4000);
      try {
        const response = await fetch(url,{cache:"no-store",signal:bounded.signal});
        return {ok:response.ok,status:response.status,body:await response.json()};
      }
      finally {window.clearTimeout(timeout); controller.signal.removeEventListener("abort",abort);}
    };
    const checkHealth = async () => {
      try {
        const result = await request("/api/health");
        available = result.ok && result.body.status === "ok";
      } catch {available = false;}
      lastHealthCheck = Date.now();
      if (!cancelled) {
        setHealth(available ? "ready" : "unavailable");
        if (!available) setSnapshot(undefined);
      }
    };
    const poll = async () => {
      if (!available || Date.now() - lastHealthCheck >= 10000) await checkHealth();
      if (cancelled) return;
      if (available && projectId && !debugging && (watching || open || knownActive) && progressSupported) {
        try {
          const response = await request(`/api/projects/${encodeURIComponent(projectId)}/runtime-progress`);
          if (response.status === 404 || response.status === 405) progressSupported = false;
          if (!response.ok) throw Error("Activity progress is unavailable");
          const result = response.body;
          if (!cancelled) {
            setSnapshot({projectId,status:result.status,activities:result.activities || []});
            setProgressUnavailable(false);
          }
        } catch {
          if (!cancelled) {
            setSnapshot(undefined);
            setProgressUnavailable(true);
          }
          // An optional progress endpoint may be missing on an older runtime.
          // Only the health endpoint can establish runtime availability.
          await checkHealth();
        }
      }
      if (!cancelled) timer = window.setTimeout(poll,!available ? 2000 : watching || open || knownActive ? 1000 : 5000);
    };
    void poll();
    return () => {cancelled = true; controller.abort(); window.clearTimeout(timer);};
  }, [projectId,watching,open,debugging,knownActive]);

  const current = !debugging && snapshot?.projectId === projectId ? snapshot : undefined;
  const activities = current?.activities ?? [];
  const starting = health === "checking" || !!(startup && startup.step < startup.total && !startup.failed);
  const failed = health === "unavailable";
  const activeDebug = debugStatus === "running" || debugStatus === "starting";
  const running = current?.status === "running" || activeDebug;
  const label = failed ? "Runtime unavailable"
    : starting ? startup?.label || "Checking runtime connection"
    : debugStatus === "paused" ? "Debugger paused" + (debugActivities[0] ? ` · ${debugActivities[0]}` : "")
    : activeDebug && debugActivities[0] ? `Debugging · ${debugActivities[0]}`
    : activities.length ? activities.length === 1 ? activities[0].activityName : `${activities.length} active activities`
    : running ? "Running task"
    : current?.status === "listening" || debugStatus === "listening" ? "Listening for events" : "Runtime ready";
  const busy = !failed && (starting || running || !!work);
  const Icon = failed ? AlertCircle : busy ? LoaderCircle : current?.status === "listening" ? Activity : CheckCircle2;
  const close = () => setOpen(false);
  return <>
    <button className={`runtime-status-button ${busy ? "busy" : ""} ${failed ? "failed" : ""}`} type="button"
      aria-label={`Runtime status: ${label}${work ? `; Studio: ${work}` : ""}`} title={`${label}${work ? ` · ${work}` : ""}`}
      onClick={() => setOpen(true)}>
      <Icon/><span className="runtime-status-text">{failed || starting || activities.length || activeDebug || debugStatus === "paused" ? label : work || label}</span>
      {busy && <progress aria-label="Runtime or designer progress" max={starting && startup ? startup.total : undefined} value={starting ? startup?.step : undefined}/>}
    </button>
    {open && <ModalLayer className="modal-backdrop">
      <section className="runtime-modal runtime-status-modal" role="dialog" aria-modal="true" aria-labelledby="runtime-status-title"
        onKeyDown={event => {if (event.key === "Escape") close();}}>
        <header><b id="runtime-status-title">Runtime and designer status</b><button autoFocus aria-label="Close runtime status" onClick={close}>×</button></header>
        <main>
          <p><b>Designer:</b> {work || (starting ? "Opening Studio" : "Ready")}</p>
          {longTask && <p><b>Last slow designer operation:</b> {longTask.duration} ms at {new Date(longTask.at).toLocaleTimeString()}</p>}
          <p role="status"><b>Runtime:</b> {label}</p>
          {progressUnavailable && !failed && <p>Runtime health check passed. Activity progress details are unavailable from this runtime.</p>}
          {startup && <p><b>Desktop startup:</b> {startup.step} of {startup.total} stages complete · {(startup.elapsedMs / 1000).toFixed(2)} s to last stage</p>}
          {!!startup?.timings?.length && <ul aria-label="Completed startup stages">{startup.timings.map(timing =>
            <li key={timing.label}>{timing.label} · {(timing.durationMs / 1000).toFixed(2)} s</li>)}</ul>}
          {activities.length > 0 && <ul aria-label="Active runtime activities">{activities.map((activity,index) =>
            <li key={`${activity.taskId}:${activity.activityId}:${activity.startedAt}:${index}`}>{activity.taskName} / {activity.activityName}</li>)}</ul>}
          {!!debugActivities.length && <p><b>Debugger:</b> {debugActivities.join(", ")}</p>}
        </main>
        <footer><button onClick={close}>Close</button></footer>
      </section>
    </ModalLayer>}
  </>;
}
