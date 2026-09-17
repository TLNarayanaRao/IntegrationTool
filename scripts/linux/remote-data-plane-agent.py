#!/usr/bin/env python3
"""Remote Integration Fabric data-plane agent.

Polls the Control Plane, downloads assigned packages, reconciles desired
instances, starts/stops local runtime workers, and reports health/log tails.
"""
import configparser, json, os, shlex, shutil, signal, subprocess, sys, time, urllib.error, urllib.request, zipfile
from pathlib import Path

try:
    import fcntl
except ImportError:  # The remote agent runs on Linux; keep source importable elsewhere.
    fcntl = None

HERE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("FABRIC_CONFIG_FILE", HERE / "integration-fabric-control-plane.ini"))
cfg = configparser.ConfigParser(); cfg.read(CONFIG)
TEAM_MAPPING = dict(cfg["data-teams"]) if "data-teams" in cfg else {}
cp = cfg["control-plane"]; dp = cfg["data-plane"]; runtime_cfg = cfg["runtime"] if "runtime" in cfg else {}
BASE = os.environ.get("CONTROL_PLANE_URL", cp.get("control_plane_url", f"http://{cp.get('host','127.0.0.1')}:{cp.get('port','19080')}" )).rstrip("/")
KEY = os.environ.get("ADMIN_KEY", cp.get("admin_key", ""))
PLANE = os.environ.get("DATA_PLANE_ID", dp.get("id", "")); NAMESPACE = os.environ.get("DATA_PLANE_NAMESPACE", dp.get("namespace", "default"))
INTERVAL = int(os.environ.get("HEARTBEAT_SECONDS", dp.get("heartbeat_seconds", "30")))
CAPACITY = int(os.environ.get("AVAILABLE_CAPACITY", dp.get("available_capacity", "20")))
VERSION = os.environ.get("AGENT_VERSION", dp.get("agent_version", "1.0.0"))
ROOT = Path(os.environ.get("FABRIC_AGENT_ROOT", f"/opt/tibco/esb/IntegrationFabricSoftware/agent/{PLANE}"))
APP_ROOT = ROOT / "applications"; LOG_ROOT = ROOT / "logs"; APP_ROOT.mkdir(parents=True, exist_ok=True); LOG_ROOT.mkdir(parents=True, exist_ok=True)
COMMAND = os.environ.get("FABRIC_RUNTIME_COMMAND", cp.get("runtime_command", "")) or f"{ROOT.parent.parent}/runtime/integration-fabric-runtime --application {{application}} --environment {{environment}}"
workers = {}
_cpu_sample = None

# Telemetry must never compete with the runtime for memory.  Runtime logs can
# grow indefinitely, so do not use Path.read_text() and then slice the result:
# that still reads the complete file into memory.
MAX_TELEMETRY_LOGS = 8
MAX_TELEMETRY_LOG_BYTES = 256 * 1024
MAX_REPORT_LOG_BYTES = 128 * 1024

def tail_log_lines(path, line_count, byte_limit):
    """Return a bounded UTF-8 tail of a log without loading its full contents."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - byte_limit))
            payload = handle.read(byte_limit)
    except OSError:
        return []
    # A partial first line is expected when reading from the middle of a file.
    return payload.decode("utf-8", errors="replace").splitlines()[-line_count:]

def acquire_agent_lock():
    """Allow only one reconciliation agent for a data plane on this host."""
    if fcntl is None:
        return None
    ROOT.mkdir(parents=True, exist_ok=True)
    handle = (ROOT / ".data-plane-agent.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SystemExit(f"A data-plane agent is already running for {PLANE}; stop it before starting another one.")
    handle.seek(0); handle.truncate(); handle.write(str(os.getpid())); handle.flush()
    return handle

def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, method=method, headers={"X-Admin-Key": KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()

def json_call(method, path, body=None): return json.loads(call(method, path, body).decode())

def system_telemetry():
    """Collect Linux host capacity without requiring a third-party package."""
    global _cpu_sample
    memory = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1); memory[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    cpu_percent = None
    try:
        values = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        total_ticks, idle_ticks = sum(values), values[3] + (values[4] if len(values) > 4 else 0)
        if _cpu_sample:
            total_delta, idle_delta = total_ticks - _cpu_sample[0], idle_ticks - _cpu_sample[1]
            if total_delta > 0: cpu_percent = round((1 - idle_delta / total_delta) * 100, 2)
        _cpu_sample = (total_ticks, idle_ticks)
    except (OSError, ValueError, IndexError):
        pass
    total = memory.get("MemTotal", 0); available = memory.get("MemAvailable", memory.get("MemFree", 0)); used = max(0, total - available)
    disk = shutil.disk_usage(ROOT)
    try: load = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError): load = None
    return {"cpuPercent": cpu_percent, "memoryPercent": round(used * 100 / total, 2) if total else None, "memoryUsedBytes": used, "memoryAvailableBytes": available, "memoryTotalBytes": total, "diskPercent": round((disk.used * 100 / disk.total), 2) if disk.total else None, "diskFreeBytes": disk.free, "loadAverage": load, "processCount": sum(1 for state in workers.values() for process in state["processes"] if process.poll() is None)}

def execution_telemetry():
    """Summarize runtime JSON logs for project, task, and activity observability."""
    tasks, activities = {}, {}
    try:
        logs = sorted(LOG_ROOT.glob("*.log"), key=lambda log: log.stat().st_mtime, reverse=True)[:MAX_TELEMETRY_LOGS]
    except OSError:
        logs = []
    for log in logs:
        lines = tail_log_lines(log, 4000, MAX_TELEMETRY_LOG_BYTES)
        for line in lines:
            try: event = json.loads(line)
            except (json.JSONDecodeError, TypeError): continue
            if event.get("kind") != "activity": continue
            task_name = str(event.get("taskId") or "runtime"); activity_name = str(event.get("activityName") or event.get("activityType") or "activity")
            message = str(event.get("message") or "").lower(); failed = "failed" in message; completed = "completed" in message
            for name, target in ((task_name, tasks), (activity_name, activities)):
                bucket = target.setdefault(name, {"total": 0, "completed": 0, "failed": 0})
                if completed or failed: bucket["total"] += 1
                if completed: bucket["completed"] += 1
                if failed: bucket["failed"] += 1
    values = lambda source: [{"name": name, **counts} for name, counts in sorted(source.items(), key=lambda item: -item[1]["total"])[:12]]
    return {"tasks": values(tasks), "activities": values(activities)}

def heartbeat():
    system = system_telemetry()
    return json_call("POST", f"/api/data-planes/{PLANE}/heartbeat", {"agentVersion": VERSION, "availableCapacity": CAPACITY, **system, "telemetry": {"system": system, "execution": execution_telemetry()}})

def safe_zip_extract(blob, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(__import__("io").BytesIO(blob)) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve(): raise RuntimeError("Unsafe package path")
        archive.extractall(destination)

def stop(deployment_id):
    state = workers.pop(deployment_id, None)
    if not state: return
    for worker in state["processes"]:
        if worker.poll() is None:
            # The runtime starts Java/JCo bridge children. Terminating only
            # the Python parent leaves those children orphaned and the SAP
            # Program ID remains owned after an application stop. Every
            # worker is started in its own process group so the full runtime
            # tree can be cleaned up safely.
            if os.name == "posix":
                try: os.killpg(worker.pid, signal.SIGTERM)
                except ProcessLookupError: pass
            else:
                worker.terminate()
            try: worker.wait(timeout=8)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try: os.killpg(worker.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                else:
                    worker.kill()
                worker.wait(timeout=5)

def start(deployment):
    deployment_id = deployment["id"]; stop(deployment_id)
    package_dir = APP_ROOT / deployment_id
    if not (package_dir / "application" / "project.json").exists() and not (package_dir / "application" / "python" / "project.py").exists():
        blob = call("GET", f"/api/data-planes/{PLANE}/agent/deployments/{deployment_id}/package")
        if package_dir.exists(): __import__("shutil").rmtree(package_dir)
        safe_zip_extract(blob, package_dir)
    processes = []
    enabled = json.dumps([key for key, value in (deployment.get("starterStates") or {}).items() if value != "STOPPED"])
    for ordinal in range(int(deployment.get("desiredInstances", 1))):
        instance_id = f"{deployment_id[:8]}-{ordinal + 1}"; log = LOG_ROOT / f"{instance_id}.log"
        command = COMMAND.replace("{application}", str(package_dir / "application")).replace("{package}", str(package_dir)).replace("{environment}", str(deployment.get("environment", "local"))).replace("{deployment_id}", deployment_id).replace("{instance_id}", instance_id)
        env = os.environ.copy(); env.update({"FABRIC_DEPLOYMENT_ID": deployment_id, "FABRIC_INSTANCE_ID": instance_id, "FABRIC_ENVIRONMENT": deployment.get("environment", "local"), "FABRIC_ENABLED_STARTERS": enabled})
        env.update({str(k): str(v) for k, v in (deployment.get("secrets") or {}).items()})
        handle = log.open("ab")
        try:
            process = subprocess.Popen(
                shlex.split(command), cwd=package_dir, env=env,
                stdout=handle, stderr=subprocess.STDOUT,
                start_new_session=(os.name == "posix"),
            )
        finally:
            # The child owns the duplicated descriptor; the agent must not
            # keep every worker log file open for its entire lifetime.
            handle.close()
        processes.append(process)
    workers[deployment_id] = {"processes": processes, "package": package_dir}

def report(deployment, error=None):
    state = workers.get(deployment["id"]); instances=[]; logs=[]; healthy=True
    if state:
        for index, process in enumerate(state["processes"], 1):
            alive = process.poll() is None; healthy &= alive; instance_id=f"{deployment['id'][:8]}-{index}"; log=LOG_ROOT / f"{instance_id}.log"
            instances.append({"id":instance_id,"ordinal":index,"pid":process.pid,"state":"RUNNING" if alive else "FAILED"})
            logs.append({"instanceId":instance_id,"lines":tail_log_lines(log, 200, MAX_REPORT_LOG_BYTES)})
    desired = "RUNNING" if state and healthy else deployment.get("state", "DEPLOYED")
    if error: desired="FAILED"
    json_call("POST", f"/api/data-planes/{PLANE}/agent/deployments/{deployment['id']}/report", {"state":desired,"instances":instances,"message":error or ("Remote runtime instances started" if healthy and state else "Remote runtime pending"),"lastError":error,"health":{"status":"HEALTHY" if healthy and state else "UNHEALTHY" if state else "PENDING","message":error or "Remote agent health report"},"logs":logs})

def reconcile(deployments):
    wanted={item["id"]:item for item in deployments}
    for deployment_id in list(workers):
        if deployment_id not in wanted or wanted[deployment_id].get("state") in {"STOPPED","UNDEPLOYED"}: stop(deployment_id)
    for deployment in deployments:
        try:
            if deployment.get("state") in {"DEPLOYED","RUNNING"} and deployment["id"] not in workers: start(deployment)
            if deployment.get("state") in {"STOPPED","UNDEPLOYED"}: stop(deployment["id"])
            report(deployment)
        except Exception as exc:
            report(deployment, str(exc))

def main():
    if not PLANE or not KEY: raise SystemExit("Set [data-plane] id and [control-plane] admin_key in the INI")
    agent_lock = acquire_agent_lock()
    print(f"Remote data-plane agent started: {PLANE}/{NAMESPACE} -> {BASE}; data teams: {', '.join(TEAM_MAPPING.values()) or 'all assigned teams'}", flush=True)
    while True:
        stage = "heartbeat"
        try:
            heartbeat()
            stage = "deployment polling"
            deployments = json_call("GET", f"/api/data-planes/{PLANE}/agent/deployments")
            stage = "deployment reconciliation"
            reconcile(deployments)
        except Exception as exc:
            # Some network exceptions have an empty str(), which previously
            # produced an unhelpful "agent cycle failed:" line. Include the
            # exception class and repr so operators can act on the cause.
            print(f"agent cycle failed during {stage} [{type(exc).__name__}]: {exc!r}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: [stop(key) for key in list(workers)]
