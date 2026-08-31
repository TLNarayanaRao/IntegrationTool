"""Integration Fabric Administrator control plane."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ADMIN_VERSION = "1.0.0"
RUN_ID = uuid4().hex
STARTED_AT = time.time()
DATA_DIR = Path(os.environ.get("FABRIC_ADMIN_DATA_DIR", Path(__file__).parents[1] / "data")).expanduser().resolve()
PACKAGES_DIR, STAGING_DIR, LOGS_DIR = DATA_DIR / "packages", DATA_DIR / "staging", DATA_DIR / "logs"
DEPLOYMENTS_FILE, PACKAGES_FILE = DATA_DIR / "deployments.json", DATA_DIR / "packages.json"
MACHINES_FILE, SECRETS_FILE, AUDIT_FILE, KEY_FILE = DATA_DIR / "machines.json", DATA_DIR / "secrets.json", DATA_DIR / "audit.json", DATA_DIR / ".secret.key"
MAX_PACKAGE_BYTES = int(os.environ.get("FABRIC_ADMIN_MAX_PACKAGE_MB", "250")) * 1024 * 1024
MAX_EXPANDED_BYTES = int(os.environ.get("FABRIC_ADMIN_MAX_EXPANDED_MB", "1024")) * 1024 * 1024
MAX_MEMBERS = int(os.environ.get("FABRIC_ADMIN_MAX_PACKAGE_FILES", "10000"))
RUNTIME_COMMAND = os.environ.get("FABRIC_ADMIN_RUNTIME_COMMAND", "").strip()
API_KEY = os.environ.get("FABRIC_ADMIN_API_KEY", "").strip()
STATE_LOCK = threading.RLock()
PROCESS_HANDLES: dict[str, subprocess.Popen] = {}

app = FastAPI(title="Integration Fabric Enterprise Administrator", version=ADMIN_VERSION)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    with STATE_LOCK:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default


def write_json(path: Path, value: Any) -> None:
    with STATE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass


def safe(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-")
    if not result or result in {".", ".."}:
        raise HTTPException(400, "Invalid identifier")
    return result


def audit(action: str, target: str = "administrator", outcome: str = "success", detail: str = "") -> None:
    events = read_json(AUDIT_FILE, [])
    events.append({"id": str(uuid4()), "time": now(), "actor": "administrator", "action": action, "target": target, "outcome": outcome, "detail": detail})
    write_json(AUDIT_FILE, events[-5000:])


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if API_KEY and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        if not hmac.compare_digest(request.headers.get("x-admin-key", ""), API_KEY):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "A valid Administrator API key is required"})
    return await call_next(request)


def secret_cipher() -> Fernet:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    configured = os.environ.get("FABRIC_ADMIN_SECRET_KEY", "").encode()
    if configured:
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(configured).digest()))
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key())
        try:
            KEY_FILE.chmod(0o600)
        except OSError:
            pass
    return Fernet(KEY_FILE.read_bytes().strip())


def package_environments(manifest: dict) -> list[str]:
    values = manifest.get("environments") or ([manifest.get("environment")] if manifest.get("environment") else [])
    return [str(value) for value in values if value]


def required_secrets(manifest: dict, environment: str) -> list[str]:
    grouped = manifest.get("secretKeysByEnvironment") or {}
    values = grouped.get(environment) if isinstance(grouped, dict) else None
    return sorted(set(values if isinstance(values, list) else manifest.get("secretKeys") or []))


def checked_name(name: str) -> str:
    normalized = str(PurePosixPath(name.replace("\\", "/")))
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or ".." in path.parts or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"Unsafe package path: {name}")
    return normalized


def validate_manifest(manifest: Any, names: set[str]) -> dict:
    if not isinstance(manifest, dict) or manifest.get("format") != "integration-fabric-deployment":
        raise ValueError("manifest.json is not an Integration Fabric deployment descriptor")
    if int(manifest.get("formatVersion", 0)) != 1:
        raise ValueError(f"Unsupported package formatVersion {manifest.get('formatVersion')!r}")
    for field in ("artifact", "version", "applicationName", "target"):
        if not str(manifest.get(field, "")).strip():
            raise ValueError(f"manifest.json is missing {field}")
    if manifest["target"] not in {"on-prem", "cloud"}:
        raise ValueError("target must be on-prem or cloud")
    if "application/project.json" not in names:
        raise ValueError("application/project.json is missing")
    environments = package_environments(manifest)
    if not environments:
        raise ValueError("The package does not declare an environment profile")
    missing = [task_id for task_id in manifest.get("includedTaskIds") or [] if f"application/tasks/{task_id}.json" not in names]
    if missing:
        raise ValueError(f"Task artifacts are missing: {', '.join(missing)}")
    manifest["environments"] = environments
    manifest["secretKeysByEnvironment"] = {environment: required_secrets(manifest, environment) for environment in environments}
    return manifest


def inspect_archive(body: bytes) -> tuple[dict, list[tuple[str, bytes]]]:
    entries: list[tuple[str, bytes]] = []
    expanded = 0
    memory = io.BytesIO(body)
    if body[:2] == b"PK":
        with zipfile.ZipFile(memory) as archive:
            members = [entry for entry in archive.infolist() if not entry.is_dir()]
            if len(members) > MAX_MEMBERS:
                raise ValueError("Package contains too many files")
            for member in members:
                name = checked_name(member.filename)
                expanded += member.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise ValueError("Expanded package exceeds the configured limit")
                entries.append((name, archive.read(member)))
    else:
        with tarfile.open(fileobj=memory, mode="r:*") as archive:
            members = archive.getmembers()
            if len(members) > MAX_MEMBERS:
                raise ValueError("Package contains too many files")
            for member in members:
                if member.issym() or member.islnk() or member.isdev():
                    raise ValueError(f"Package contains a prohibited entry: {member.name}")
                if member.isfile():
                    name = checked_name(member.name)
                    expanded += member.size
                    if expanded > MAX_EXPANDED_BYTES:
                        raise ValueError("Expanded package exceeds the configured limit")
                    source = archive.extractfile(member)
                    entries.append((name, source.read() if source else b""))
    names = [name for name, _ in entries]
    if len(names) != len(set(names)):
        raise ValueError("Package contains duplicate file paths")
    descriptor = next((value for name, value in entries if name == "manifest.json"), None)
    if descriptor is None:
        raise ValueError("manifest.json is missing")
    return validate_manifest(json.loads(descriptor), set(names)), entries


def package_inventory() -> list[dict]:
    values = read_json(PACKAGES_FILE, [])
    known = {value.get("packageId") for value in values}
    discovered = False
    for descriptor in PACKAGES_DIR.glob("*/*/manifest.json") if PACKAGES_DIR.exists() else []:
        manifest = read_json(descriptor, {})
        package_id = f"{manifest.get('artifact', descriptor.parents[1].name)}:{manifest.get('version', descriptor.parent.name)}"
        if package_id not in known:
            manifest.update(packageId=package_id, receivedAt=datetime.fromtimestamp(descriptor.stat().st_mtime, timezone.utc).isoformat(), status="VALIDATED", environments=package_environments(manifest))
            values.append(manifest)
            discovered = True
    if discovered:
        write_json(PACKAGES_FILE, values)
    return sorted(values, key=lambda value: value.get("receivedAt", ""), reverse=True)


def ensure_local_machine() -> None:
    machines = read_json(MACHINES_FILE, [])
    if any(machine.get("id") == "localhost" for machine in machines):
        return
    machines.append({"id": "localhost", "name": "Local runtime host", "host": "127.0.0.1", "driver": "command", "status": "ONLINE", "capacity": 20, "runtimeConfigured": bool(RUNTIME_COMMAND), "lastHeartbeat": now(), "createdAt": now()})
    write_json(MACHINES_FILE, machines)


class DeploymentRequest(BaseModel):
    packageId: str
    environment: str
    machine: str = "localhost"
    instances: int = Field(default=1, ge=1, le=100)
    secrets: dict[str, str] = Field(default_factory=dict)


class MachineRequest(BaseModel):
    id: str | None = None
    name: str
    host: str
    capacity: int = Field(default=10, ge=1, le=10000)
    driver: str = "agent"


class SecretRequest(BaseModel):
    values: dict[str, str]


@app.on_event("startup")
def initialize() -> None:
    for directory in (DATA_DIR, PACKAGES_DIR, STAGING_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    ensure_local_machine()
    reconcile_instances()


@app.get("/api/health")
def health():
    deployments = read_json(DEPLOYMENTS_FILE, [])
    return {"status": "ok", "component": "enterprise-administrator", "version": ADMIN_VERSION, "uptimeSeconds": int(time.time() - STARTED_AT), "runtimeAdapterConfigured": bool(RUNTIME_COMMAND), "packages": len(package_inventory()), "deployments": len([item for item in deployments if item.get("state") != "UNDEPLOYED"]), "failedDeployments": len([item for item in deployments if item.get("state") == "FAILED"])}


@app.get("/api/packages")
def list_packages():
    return package_inventory()


@app.get("/api/packages/{artifact}/{version}")
def get_package(artifact: str, version: str):
    package_id = f"{safe(artifact)}:{safe(version)}"
    item = next((value for value in package_inventory() if value.get("packageId") == package_id), None)
    if not item:
        raise HTTPException(404, "Package not found")
    return item


@app.delete("/api/packages/{artifact}/{version}")
def delete_package(artifact: str, version: str):
    artifact, version = safe(artifact), safe(version)
    package_id = f"{artifact}:{version}"
    active = [item for item in read_json(DEPLOYMENTS_FILE, []) if item.get("packageId") == package_id and item.get("state") != "UNDEPLOYED"]
    if active:
        raise HTTPException(409, "Undeploy every deployment that uses this package first")
    destination = PACKAGES_DIR / artifact / version
    if destination.exists():
        shutil.rmtree(destination)
    write_json(PACKAGES_FILE, [item for item in package_inventory() if item.get("packageId") != package_id])
    audit("package.delete", package_id)
    return {"deleted": True, "packageId": package_id}


@app.post("/api/packages")
async def upload_package(file: UploadFile = File(...)):
    body = await file.read(MAX_PACKAGE_BYTES + 1)
    if len(body) > MAX_PACKAGE_BYTES:
        raise HTTPException(413, f"Package exceeds {MAX_PACKAGE_BYTES // 1024 // 1024} MB")
    stage = STAGING_DIR / uuid4().hex
    try:
        manifest, entries = inspect_archive(body)
        artifact, version = safe(manifest["artifact"]), safe(manifest["version"])
        stage.mkdir(parents=True)
        for name, content in entries:
            target = stage.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        destination = PACKAGES_DIR / artifact / version
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = destination.with_name(destination.name + ".previous")
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            destination.replace(backup)
        try:
            stage.replace(destination)
        except Exception:
            if backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        record = {**manifest, "packageId": f"{artifact}:{version}", "receivedAt": now(), "status": "VALIDATED", "sha256": hashlib.sha256(body).hexdigest(), "archiveBytes": len(body), "expandedBytes": sum(len(value) for _, value in entries), "fileCount": len(entries), "sourceFile": file.filename or "deployment.ifpkg"}
        write_json(PACKAGES_FILE, [item for item in package_inventory() if item.get("packageId") != record["packageId"]] + [record])
        audit("package.upload", record["packageId"], detail=f"Validated {len(entries)} files; sha256={record['sha256']}")
        return record
    except HTTPException:
        raise
    except Exception as exc:
        audit("package.upload", outcome="failure", detail=str(exc))
        raise HTTPException(400, f"Invalid Integration Fabric deployment package: {exc}") from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage)


@app.get("/api/machines")
def list_machines():
    ensure_local_machine()
    machines = read_json(MACHINES_FILE, [])
    changed = False
    current = datetime.now(timezone.utc)
    for machine in machines:
        if machine.get("id") == "localhost" or machine.get("status") not in {"ONLINE", "REGISTERED"}:
            continue
        try:
            age = (current - datetime.fromisoformat(machine["lastHeartbeat"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = 999999
        if age > 90:
            machine["status"] = "OFFLINE"
            changed = True
    if changed:
        write_json(MACHINES_FILE, machines)
    return machines


@app.post("/api/machines")
def register_machine(request: MachineRequest):
    machine_id = safe(request.id or request.name.lower())
    machines = read_json(MACHINES_FILE, [])
    if any(item.get("id") == machine_id for item in machines):
        raise HTTPException(409, "Machine already exists")
    if request.driver not in {"agent", "command"}:
        raise HTTPException(400, "driver must be agent or command")
    item = request.dict()
    item.update(id=machine_id, status="REGISTERED", runtimeConfigured=False, lastHeartbeat=now(), createdAt=now())
    machines.append(item)
    write_json(MACHINES_FILE, machines)
    audit("machine.register", machine_id, detail=request.host)
    return item


@app.post("/api/machines/{machine_id}/heartbeat")
def machine_heartbeat(machine_id: str):
    machines = read_json(MACHINES_FILE, [])
    item = next((value for value in machines if value.get("id") == machine_id), None)
    if not item:
        raise HTTPException(404, "Machine not found")
    item.update(status="ONLINE", runtimeConfigured=True, lastHeartbeat=now())
    write_json(MACHINES_FILE, machines)
    return item


def save_deployment_secrets(deployment_id: str, values: dict[str, str]) -> None:
    store = read_json(SECRETS_FILE, {})
    cipher = secret_cipher()
    store[deployment_id] = {safe(key): cipher.encrypt(str(value).encode()).decode() for key, value in values.items() if str(value)}
    write_json(SECRETS_FILE, store)


def deployment_secret_values(deployment_id: str) -> dict[str, str]:
    cipher, output = secret_cipher(), {}
    for key, value in read_json(SECRETS_FILE, {}).get(deployment_id, {}).items():
        try:
            output[key] = cipher.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise HTTPException(500, "Administrator secret encryption key does not match stored secrets") from exc
    return output


@app.get("/api/deployments")
def list_deployments():
    reconcile_instances()
    return read_json(DEPLOYMENTS_FILE, [])


@app.get("/api/deployments/{deployment_id}")
def get_deployment(deployment_id: str):
    reconcile_instances()
    item = next((value for value in read_json(DEPLOYMENTS_FILE, []) if value.get("id") == deployment_id), None)
    if not item:
        raise HTTPException(404, "Deployment not found")
    configured = set(read_json(SECRETS_FILE, {}).get(deployment_id, {}))
    return {**item, "secrets": [{"name": name, "configured": name in configured} for name in item.get("requiredSecrets", [])]}


@app.post("/api/deployments")
def create_deployment(request: DeploymentRequest):
    package = next((item for item in package_inventory() if item.get("packageId") == request.packageId), None)
    if not package:
        raise HTTPException(404, "Package not found")
    if package.get("target") != "on-prem":
        raise HTTPException(400, "Cloud packages are deployed with the generated Kubernetes descriptors")
    environments = package_environments(package)
    if request.environment not in environments:
        raise HTTPException(400, f"Environment must be one of: {', '.join(environments)}")
    machine = next((item for item in list_machines() if item.get("id") == request.machine), None)
    if not machine:
        raise HTTPException(404, "Machine not found")
    if request.instances > int(machine.get("capacity", 1)):
        raise HTTPException(409, "Requested instances exceed machine capacity")
    required = required_secrets(package, request.environment)
    missing = [name for name in required if not request.secrets.get(name)]
    if missing:
        raise HTTPException(422, f"Required secrets are missing: {', '.join(missing)}")
    deployment_id = str(uuid4())
    item = {"id": deployment_id, "packageId": request.packageId, "application": package.get("applicationName"), "environment": request.environment, "machine": request.machine, "desiredInstances": request.instances, "instances": [], "requiredSecrets": required, "state": "DEPLOYED", "createdAt": now(), "updatedAt": now(), "message": "Validated and ready to start.", "lastError": None}
    deployments = read_json(DEPLOYMENTS_FILE, [])
    deployments.append(item)
    write_json(DEPLOYMENTS_FILE, deployments)
    save_deployment_secrets(deployment_id, request.secrets)
    audit("deployment.create", deployment_id, detail=f"{request.packageId} / {request.environment} / {request.machine}")
    return item


@app.put("/api/deployments/{deployment_id}/secrets")
def update_secrets(deployment_id: str, request: SecretRequest):
    item = get_deployment(deployment_id)
    unknown = set(request.values) - set(item.get("requiredSecrets", []))
    if unknown:
        raise HTTPException(400, f"Unknown secret keys: {', '.join(sorted(unknown))}")
    current = deployment_secret_values(deployment_id)
    current.update(request.values)
    save_deployment_secrets(deployment_id, current)
    audit("deployment.secrets.update", deployment_id, detail=f"Updated {len(request.values)} secret values")
    return {"updated": sorted(request.values), "valuesExposed": False}


def deployment_package_path(item: dict) -> Path:
    artifact, version = item["packageId"].split(":", 1)
    return PACKAGES_DIR / safe(artifact) / safe(version)


def runtime_arguments(item: dict, instance_id: str) -> list[str] | str:
    package_path = deployment_package_path(item)
    command = RUNTIME_COMMAND
    for marker, value in {"{application}": str(package_path / "application"), "{package}": str(package_path), "{environment}": item["environment"], "{deployment_id}": item["id"], "{instance_id}": instance_id}.items():
        command = command.replace(marker, value)
    # CreateProcess performs Windows command-line parsing itself; passing the
    # configured string preserves quoted executable paths. POSIX requires argv.
    return command if os.name == "nt" else shlex.split(command)


def start_instances(item: dict) -> None:
    if not RUNTIME_COMMAND:
        raise HTTPException(409, "No runtime adapter is configured. Set FABRIC_ADMIN_RUNTIME_COMMAND; see the Administrator Guide.")
    machine = next((value for value in list_machines() if value.get("id") == item.get("machine")), None)
    if not machine or machine.get("driver") != "command" or item.get("machine") != "localhost":
        raise HTTPException(409, "This build can execute only the localhost command adapter")
    item["instances"] = []
    for ordinal in range(int(item["desiredInstances"])):
        instance_id = f"{item['id'][:8]}-{ordinal + 1}"
        log_path = LOGS_DIR / f"{instance_id}.log"
        environment = os.environ.copy()
        environment.update({"FABRIC_DEPLOYMENT_ID": item["id"], "FABRIC_INSTANCE_ID": instance_id, "FABRIC_ENVIRONMENT": item["environment"], "FABRIC_APPLICATION_DIR": str(deployment_package_path(item) / "application"), **deployment_secret_values(item["id"])})
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        with log_path.open("ab") as log_handle:
            process = subprocess.Popen(runtime_arguments(item, instance_id), cwd=deployment_package_path(item), env=environment, stdout=log_handle, stderr=subprocess.STDOUT, creationflags=flags)
        PROCESS_HANDLES[instance_id] = process
        item["instances"].append({"id": instance_id, "ordinal": ordinal + 1, "pid": process.pid, "ownerRunId": RUN_ID, "state": "RUNNING", "startedAt": now(), "stoppedAt": None, "log": str(log_path)})


def process_alive(pid: int) -> bool:
    try:
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def terminate_instances(item: dict, force: bool = False) -> None:
    for instance in item.get("instances", []):
        pid = int(instance.get("pid") or 0)
        process = PROCESS_HANDLES.pop(instance.get("id", ""), None)
        if process and process.poll() is None:
            process.kill() if force else process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        elif instance.get("ownerRunId") == RUN_ID and process_alive(pid):
            try:
                os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM) if force else signal.SIGTERM)
            except OSError:
                pass
        instance.update(state="STOPPED", stoppedAt=now())


def reconcile_instances() -> None:
    deployments = read_json(DEPLOYMENTS_FILE, [])
    changed = False
    for item in deployments:
        if item.get("state") != "RUNNING":
            continue
        dead = []
        for instance in item.get("instances", []):
            if instance.get("state") == "RUNNING" and instance.get("ownerRunId") != RUN_ID:
                instance.update(state="FAILED", stoppedAt=now())
                dead.append(instance["id"])
                changed = True
            elif instance.get("state") == "RUNNING" and not process_alive(int(instance.get("pid") or 0)):
                instance.update(state="FAILED", stoppedAt=now())
                dead.append(instance["id"])
                changed = True
        if dead:
            item.update(state="FAILED", updatedAt=now(), lastError=f"Runtime instances exited unexpectedly: {', '.join(dead)}", message="One or more runtime instances failed")
    if changed:
        write_json(DEPLOYMENTS_FILE, deployments)


ALLOWED_ACTIONS = {"start": {"DEPLOYED", "STOPPED", "FAILED"}, "stop": {"RUNNING"}, "restart": {"RUNNING", "STOPPED", "FAILED"}, "kill": {"RUNNING"}, "undeploy": {"DEPLOYED", "STOPPED", "FAILED"}}


@app.post("/api/deployments/{deployment_id}/{action}")
def lifecycle(deployment_id: str, action: str):
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(400, "Unsupported lifecycle action")
    deployments = read_json(DEPLOYMENTS_FILE, [])
    item = next((value for value in deployments if value.get("id") == deployment_id), None)
    if not item:
        raise HTTPException(404, "Deployment not found")
    if item.get("state") not in ALLOWED_ACTIONS[action]:
        raise HTTPException(409, f"Cannot {action} a deployment in {item.get('state')} state")
    try:
        if action in {"stop", "kill", "restart"} and item.get("state") == "RUNNING":
            terminate_instances(item, action == "kill")
        if action in {"start", "restart"}:
            start_instances(item)
            item.update(state="RUNNING", message=f"{len(item['instances'])} runtime instance(s) started", lastError=None)
        elif action in {"stop", "kill"}:
            item.update(state="STOPPED", message="Runtime instances stopped")
        else:
            item.update(state="UNDEPLOYED", instances=[], message="Deployment removed from the runtime inventory")
            secrets = read_json(SECRETS_FILE, {}); secrets.pop(deployment_id, None); write_json(SECRETS_FILE, secrets)
        item["updatedAt"] = now()
        write_json(DEPLOYMENTS_FILE, deployments)
        audit(f"deployment.{action}", deployment_id, detail=item["message"])
        return item
    except HTTPException as exc:
        item.update(state="FAILED" if action in {"start", "restart"} else item.get("state"), updatedAt=now(), lastError=str(exc.detail), message=f"{action.title()} failed")
        write_json(DEPLOYMENTS_FILE, deployments)
        audit(f"deployment.{action}", deployment_id, "failure", str(exc.detail))
        raise
    except Exception as exc:
        item.update(state="FAILED", updatedAt=now(), lastError=str(exc), message=f"{action.title()} failed")
        write_json(DEPLOYMENTS_FILE, deployments)
        audit(f"deployment.{action}", deployment_id, "failure", str(exc))
        raise HTTPException(500, f"Runtime adapter failed: {exc}") from exc


@app.get("/api/deployments/{deployment_id}/logs")
def deployment_logs(deployment_id: str, lines: int = 300):
    item = get_deployment(deployment_id)
    output = []
    for instance in item.get("instances", []):
        log_path = Path(instance.get("log", ""))
        if log_path.exists() and LOGS_DIR in log_path.resolve().parents:
            output.append({"instanceId": instance["id"], "lines": log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-min(max(lines, 1), 2000):]})
    return output


@app.get("/api/audit")
def list_audit(limit: int = 250):
    return list(reversed(read_json(AUDIT_FILE, [])[-min(max(limit, 1), 1000):]))


@app.get("/api/monitoring")
def monitoring():
    deployments, machines = list_deployments(), list_machines()
    states: dict[str, int] = {}
    for item in deployments:
        states[item.get("state", "UNKNOWN")] = states.get(item.get("state", "UNKNOWN"), 0) + 1
    return {"time": now(), "deploymentStates": states, "runningInstances": sum(1 for item in deployments for instance in item.get("instances", []) if instance.get("state") == "RUNNING"), "machines": {"total": len(machines), "online": len([item for item in machines if item.get("status") == "ONLINE"])}, "runtimeAdapterConfigured": bool(RUNTIME_COMMAND), "recentFailures": [item for item in deployments if item.get("state") == "FAILED"][-20:]}


static_candidates = [Path(os.environ["FABRIC_ADMIN_WEB"]) if os.environ.get("FABRIC_ADMIN_WEB") else None, Path(getattr(sys, "_MEIPASS", "")) / "web" if getattr(sys, "_MEIPASS", None) else None, Path(__file__).parents[1] / "web"]
WEB_DIR = next((candidate for candidate in static_candidates if candidate and candidate.exists()), None)
if WEB_DIR:
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="administrator")
