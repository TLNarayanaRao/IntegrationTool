"""Integration Fabric self-hosted control plane."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
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
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .time_utils import log_timestamp

def administrator_version() -> str:
    override = os.environ.get("FABRIC_ADMIN_VERSION", "").strip()
    if override:
        return override
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parents[1]))
    for candidate in (bundle_root / "build_info.json", Path(__file__).parents[1] / "build_info.json"):
        try:
            value = json.loads(candidate.read_text(encoding="utf-8-sig"))
            if str(value.get("version") or "").strip():
                return str(value["version"]).strip()
        except (OSError, ValueError, AttributeError):
            continue
    return "development"


ADMIN_VERSION = administrator_version()
RUN_ID = uuid4().hex
STARTED_AT = time.time()
DATA_DIR = Path(os.environ.get("FABRIC_ADMIN_DATA_DIR", Path(__file__).parents[1] / "data")).expanduser().resolve()
PACKAGES_DIR, STAGING_DIR, LOGS_DIR = DATA_DIR / "packages", DATA_DIR / "staging", DATA_DIR / "logs"
DEPLOYMENTS_FILE, PACKAGES_FILE = DATA_DIR / "deployments.json", DATA_DIR / "packages.json"
MACHINES_FILE, SECRETS_FILE, AUDIT_FILE, KEY_FILE = DATA_DIR / "machines.json", DATA_DIR / "secrets.json", DATA_DIR / "audit.json", DATA_DIR / ".secret.key"
CAPABILITIES_FILE, RESOURCES_FILE, PRINCIPALS_FILE = DATA_DIR / "capabilities.json", DATA_DIR / "resources.json", DATA_DIR / "principals.json"
TEAMS_FILE, TOKENS_FILE = DATA_DIR / "teams.json", DATA_DIR / "access-tokens.json"
REVISIONS_FILE = DATA_DIR / "revisions.json"
ALERTS_FILE = DATA_DIR / "alerts.json"
PROCESS_STATES_FILE = DATA_DIR / "process-states.json"
TECHNOLOGY_TEAM_ID = "technology-team"
MAX_PACKAGE_BYTES = int(os.environ.get("FABRIC_ADMIN_MAX_PACKAGE_MB", "250")) * 1024 * 1024
MAX_EXPANDED_BYTES = int(os.environ.get("FABRIC_ADMIN_MAX_EXPANDED_MB", "1024")) * 1024 * 1024
MAX_MEMBERS = int(os.environ.get("FABRIC_ADMIN_MAX_PACKAGE_FILES", "10000"))
RUNTIME_COMMAND = os.environ.get("FABRIC_ADMIN_RUNTIME_COMMAND", "").strip()
API_KEY = os.environ.get("FABRIC_ADMIN_API_KEY", "").strip()
STATE_LOCK = threading.RLock()
PROCESS_HANDLES: dict[str, subprocess.Popen] = {}

app = FastAPI(title="Integration Fabric Control Plane", version=ADMIN_VERSION)
REQUEST_METRICS = {"startedAt": log_timestamp(), "total": 0, "errors": 0, "routes": {}, "recentErrors": []}


def now() -> str:
    return log_timestamp()


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


def audit(action: str, target: str = "administrator", outcome: str = "success", detail: str = "", *, actor: str = "administrator", team_id: str = TECHNOLOGY_TEAM_ID) -> None:
    events = read_json(AUDIT_FILE, [])
    events.append({"id": str(uuid4()), "time": now(), "actor": actor, "teamId": team_id, "action": action, "target": target, "outcome": outcome, "detail": detail})
    write_json(AUDIT_FILE, events[-5000:])

def record_revision(asset_type: str, asset_id: str, action: str, snapshot: dict, *, actor: str, team_id: str, detail: str = "") -> dict:
    values = read_json(REVISIONS_FILE, [])
    revision = {
        "id": str(uuid4()), "revision": len([item for item in values if item.get("assetType") == asset_type and item.get("assetId") == asset_id]) + 1,
        "time": now(), "assetType": asset_type, "assetId": asset_id, "teamId": team_id,
        "action": action, "actor": actor, "detail": detail, "snapshot": snapshot,
    }
    values.append(revision); write_json(REVISIONS_FILE, values[-10000:])
    return revision


def operator_process_instances(deployments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = read_json(PROCESS_STATES_FILE, {})
    output = []
    for deployment in deployments:
        for instance in deployment.get("instances", []):
            instance_id = str(instance.get("id"))
            state = values.get(instance_id, {}) if isinstance(values, dict) else {}
            output.append({"id": instance_id, "deploymentId": deployment.get("id"), "application": deployment.get("application"), "taskId": state.get("taskId", "runtime"), "status": state.get("status", instance.get("state", "UNKNOWN")), "startedAt": instance.get("startedAt"), "durationMs": state.get("durationMs"), "correlationId": state.get("correlationId"), "input": state.get("input"), "output": state.get("output"), "fault": state.get("fault"), "dataPlaneId": deployment.get("dataPlaneId") or deployment.get("machine"), "namespace": deployment.get("namespace", "default")})
    return output


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def technology_identity() -> dict[str, Any]:
    return {"principalId":"local-owner", "name":"Technology Team Owner", "teamId":TECHNOLOGY_TEAM_ID, "teamKind":"technology", "controlPlaneAccess":True, "roles":["Owner"]}


def resolve_identity(request: Request) -> dict[str, Any] | None:
    presented = (request.headers.get("x-control-plane-key") or request.headers.get("x-admin-key") or "").strip()
    if API_KEY and presented and hmac.compare_digest(presented, API_KEY):
        return technology_identity()
    if presented:
        digest = token_hash(presented)
        token = next((item for item in read_json(TOKENS_FILE, []) if item.get("tokenHash") == digest and item.get("status") == "ACTIVE"), None)
        if token:
            expires = token.get("expiresAt")
            if expires and datetime.fromisoformat(expires) <= datetime.now(timezone.utc):
                return None
            team = next((item for item in read_json(TEAMS_FILE, []) if item.get("id") == token.get("teamId") and item.get("status") == "ACTIVE"), None)
            if team:
                return {"principalId":token.get("principalId"), "name":token.get("principalName") or token.get("name"), "teamId":team["id"], "teamKind":team.get("kind"), "controlPlaneAccess":bool(team.get("controlPlaneAccess")), "roles":token.get("roles") or ["Application Manager"]}
        return None
    return technology_identity() if not API_KEY else None


def identity(request: Request) -> dict[str, Any]:
    value = getattr(request.state, "identity", None)
    if not value: raise HTTPException(401, "A valid Control Plane credential is required")
    return value


def require_technology(request: Request) -> dict[str, Any]:
    value = identity(request)
    if value.get("teamId") != TECHNOLOGY_TEAM_ID or not value.get("controlPlaneAccess"):
        raise HTTPException(403, "Control Plane governance is restricted to the Technology Team")
    return value


def team_record(team_id: str) -> dict[str, Any]:
    item = next((value for value in read_json(TEAMS_FILE, []) if value.get("id") == team_id and value.get("status") == "ACTIVE"), None)
    if not item: raise HTTPException(404, "Team not found")
    return item


def requested_asset_team(request: Request, requested: str | None = None) -> str:
    caller = identity(request)
    team_id = safe(requested or caller["teamId"])
    if caller.get("teamId") != TECHNOLOGY_TEAM_ID and team_id != caller.get("teamId"):
        raise HTTPException(403, "A delivery team cannot create or access another team's assets")
    team_record(team_id)
    return team_id


def require_application_manager(request: Request) -> dict[str, Any]:
    caller = identity(request)
    if caller.get("teamId") != TECHNOLOGY_TEAM_ID and "Application Manager" not in caller.get("roles", []):
        raise HTTPException(403, "Application Viewer access is read-only")
    return caller


def visible_assets(request: Request, values: list[dict], requested: str | None = None) -> list[dict]:
    caller = identity(request)
    if caller.get("teamId") == TECHNOLOGY_TEAM_ID:
        return [item for item in values if not requested or item.get("teamId", TECHNOLOGY_TEAM_ID) == requested]
    return [item for item in values if item.get("teamId", TECHNOLOGY_TEAM_ID) == caller.get("teamId")]


def require_asset(request: Request, item: dict) -> dict:
    caller = identity(request)
    if caller.get("teamId") != TECHNOLOGY_TEAM_ID and item.get("teamId", TECHNOLOGY_TEAM_ID) != caller.get("teamId"):
        # Use 404 so asset identifiers cannot be probed across teams.
        raise HTTPException(404, "Asset not found")
    return item


def require_application_write(request: Request, item: dict) -> dict:
    require_asset(request, item); caller = identity(request)
    if caller.get("teamId") != TECHNOLOGY_TEAM_ID and "Application Manager" not in caller.get("roles", []):
        raise HTTPException(403, "Application Viewer access is read-only")
    return item


def team_can_use_namespace(team_id: str, data_plane_id: str, namespace: str) -> bool:
    if team_id == TECHNOLOGY_TEAM_ID: return True
    team = team_record(team_id)
    return any(scope.get("dataPlaneId") in (data_plane_id, "*") and scope.get("namespace") in (namespace, "*") for scope in team.get("namespaceScopes", []))


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        request.state.identity = resolve_identity(request)
        if not request.state.identity:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "A valid Control Plane credential is required"})
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        with STATE_LOCK:
            REQUEST_METRICS["total"] += 1
            if response.status_code >= 400:
                REQUEST_METRICS["errors"] += 1
                REQUEST_METRICS["recentErrors"].append({"time": now(), "method": request.method, "path": request.url.path, "status": response.status_code})
                REQUEST_METRICS["recentErrors"] = REQUEST_METRICS["recentErrors"][-200:]
            key = f"{request.method} {request.url.path}"
            REQUEST_METRICS["routes"][key] = REQUEST_METRICS["routes"].get(key, 0) + 1
    return response


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
    # Studio 2.x deployment archives use manifest format version 2. The
    # archive layout and required descriptor files remain compatible with the
    # Administrator's version-1 validator, so reject only unknown versions.
    if int(manifest.get("formatVersion", 0)) not in (1, 2):
        raise ValueError(f"Unsupported package formatVersion {manifest.get('formatVersion')!r}")
    for field in ("artifact", "version", "applicationName", "target"):
        if not str(manifest.get(field, "")).strip():
            raise ValueError(f"manifest.json is missing {field}")
    if manifest["target"] not in {"on-prem", "cloud"}:
        raise ValueError("target must be on-prem or cloud")
    python_source = manifest.get("pythonSource")
    if python_source is not None:
        if not isinstance(python_source, dict) or python_source.get("entrypoint") != "application/python/project.py":
            raise ValueError("Python source package has an invalid entrypoint")
        if "application/python/project.py" not in names:
            raise ValueError("Python source package is missing application/python/project.py")
        task_inventory = manifest.get("taskInventory")
        if not isinstance(task_inventory, list):
            raise ValueError("Python source package is missing taskInventory")
        known_task_ids = {str(task.get("id") or "") for task in task_inventory if isinstance(task, dict)}
        missing = [task_id for task_id in manifest.get("includedTaskIds") or [] if task_id not in known_task_ids]
        if missing: raise ValueError(f"Python source task inventory is missing: {', '.join(missing)}")
    elif "application/project.json" not in names:
        raise ValueError("application/project.json is missing")
    environments = package_environments(manifest)
    if not environments:
        raise ValueError("The package does not declare an environment profile")
    if python_source is None:
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
    changed = False
    for value in values:
        if not value.get("teamId"): value["teamId"] = TECHNOLOGY_TEAM_ID; changed = True
        if not value.get("storagePath"):
            artifact, version = str(value.get("packageId", ":")).split(":", 1)
            value["storagePath"] = str(Path(artifact) / version); changed = True
    known = {(value.get("teamId"), value.get("packageId")) for value in values}
    discovered = False
    for descriptor in PACKAGES_DIR.rglob("manifest.json") if PACKAGES_DIR.exists() else []:
        manifest = read_json(descriptor, {})
        package_id = f"{manifest.get('artifact', descriptor.parents[1].name)}:{manifest.get('version', descriptor.parent.name)}"
        relative = descriptor.parent.relative_to(PACKAGES_DIR)
        team_id = relative.parts[0] if len(relative.parts) >= 3 and any(team.get("id") == relative.parts[0] for team in read_json(TEAMS_FILE, [])) else TECHNOLOGY_TEAM_ID
        if (team_id, package_id) not in known:
            manifest.update(packageId=package_id, teamId=team_id, storagePath=str(relative), receivedAt=datetime.fromtimestamp(descriptor.stat().st_mtime, timezone.utc).isoformat(), status="VALIDATED", environments=package_environments(manifest))
            values.append(manifest)
            discovered = True
    if discovered or changed:
        write_json(PACKAGES_FILE, values)
    return sorted(values, key=lambda value: value.get("receivedAt", ""), reverse=True)

def stored_package_path(item: dict) -> Path:
    target = (PACKAGES_DIR / item.get("storagePath", "")).resolve()
    root = PACKAGES_DIR.resolve()
    if target != root and root not in target.parents: raise HTTPException(400, "Invalid package storage path")
    return target

def package_task_inventory(item: dict) -> list[dict]:
    generated = item.get("taskInventory")
    if isinstance(generated, list): return generated
    root, tasks = stored_package_path(item) / "application" / "tasks", []
    if not root.exists(): return tasks
    starter_ids = set(item.get("starterTaskIds") or [])
    for descriptor in sorted(root.glob("*.json")):
        value = read_json(descriptor, {})
        task_id = str(value.get("id") or descriptor.stem)
        activities = value.get("activities") if isinstance(value.get("activities"), list) else []
        tasks.append({"id":task_id, "name":value.get("name") or task_id, "kind":value.get("kind") or ("starter" if task_id in starter_ids else "subtask"),
                      "starter":task_id in starter_ids or value.get("kind") == "starter", "activityCount":len(activities),
                      "activities":[{"id":activity.get("id"), "name":activity.get("name"), "type":activity.get("type")} for activity in activities]})
    return tasks


def ensure_local_machine() -> None:
    machines = read_json(MACHINES_FILE, [])
    if any(machine.get("id") == "localhost" for machine in machines):
        return
    machines.append({"id": "localhost", "name": "Local data plane", "host": "127.0.0.1", "driver": "command", "type": "on-premises", "region": "local", "namespaces": ["default"], "tags": ["local", "on-premises"], "status": "ONLINE", "tunnelStatus": "CONNECTED", "capacity": 20, "runtimeConfigured": bool(RUNTIME_COMMAND), "lastHeartbeat": now(), "createdAt": now()})
    write_json(MACHINES_FILE, machines)


def ensure_control_plane_defaults() -> None:
    ensure_local_machine()
    teams = read_json(TEAMS_FILE, [])
    if not any(item.get("id") == TECHNOLOGY_TEAM_ID for item in teams):
        teams.append({"id":TECHNOLOGY_TEAM_ID, "name":"Technology Team", "kind":"technology", "description":"Owns and governs the Integration Fabric Control Plane", "controlPlaneAccess":True, "namespaceScopes":[{"dataPlaneId":"*", "namespace":"*"}], "status":"ACTIVE", "createdAt":now(), "updatedAt":now()})
        write_json(TEAMS_FILE, teams)
    capabilities = read_json(CAPABILITIES_FILE, [])
    if not any(item.get("id") == "integration-runtime-local" for item in capabilities):
        capabilities.append({"id":"integration-runtime-local", "name":"Integration Runtime", "type":"integration-runtime", "version":"1.0.0", "dataPlaneId":"localhost", "namespace":"default", "state":"PROVISIONED", "health":"RUNNING", "tags":["core"], "createdAt":now(), "updatedAt":now()})
        write_json(CAPABILITIES_FILE, capabilities)
    principals = read_json(PRINCIPALS_FILE, [])
    if not principals:
        write_json(PRINCIPALS_FILE, [{"id":"local-owner", "name":"Local Owner", "type":"user", "teamId":TECHNOLOGY_TEAM_ID, "permissions":[{"role":"Owner", "scope":"control-plane", "resourceId":"*"}], "status":"ACTIVE", "createdAt":now()}])
    else:
        changed = False
        for principal in principals:
            if not principal.get("teamId"): principal["teamId"] = TECHNOLOGY_TEAM_ID; changed = True
        if changed: write_json(PRINCIPALS_FILE, principals)


def data_plane_inventory() -> list[dict]:
    values = machine_inventory()
    capabilities = read_json(CAPABILITIES_FILE, [])
    deployments = [item for item in read_json(DEPLOYMENTS_FILE, []) if item.get("state") != "UNDEPLOYED"]
    for item in values:
        item.setdefault("type", "on-premises" if item.get("id") == "localhost" else "agent")
        item.setdefault("region", "local")
        item.setdefault("namespaces", ["default"])
        item.setdefault("tags", [])
        item.setdefault("tunnelStatus", "CONNECTED" if item.get("status") == "ONLINE" else "DISCONNECTED")
        item["capabilityCount"] = len([capability for capability in capabilities if capability.get("dataPlaneId") == item.get("id")])
        item["applicationCount"] = len([deployment for deployment in deployments if (deployment.get("dataPlaneId") or deployment.get("machine")) == item.get("id")])
    return values


class DeploymentRequest(BaseModel):
    packageId: str
    teamId: str | None = None
    environment: str
    machine: str = "localhost"
    dataPlaneId: str | None = None
    capabilityId: str | None = None
    namespace: str = "default"
    instances: int = Field(default=1, ge=1, le=100)
    secrets: dict[str, str] = Field(default_factory=dict)


class MachineRequest(BaseModel):
    id: str | None = None
    name: str
    host: str
    capacity: int = Field(default=10, ge=1, le=10000)
    driver: str = "agent"


class DataPlaneRequest(BaseModel):
    id: str | None = None
    name: str
    type: str = "kubernetes"
    host: str = ""
    region: str = "local"
    namespaces: list[str] = Field(default_factory=lambda: ["default"])
    tags: list[str] = Field(default_factory=list)
    capacity: int = Field(default=20, ge=1, le=10000)
    driver: str = "agent"


class CapabilityRequest(BaseModel):
    name: str
    type: str = "integration-runtime"
    version: str = "1.0.0"
    dataPlaneId: str
    namespace: str = "default"
    tags: list[str] = Field(default_factory=list)


class ResourceRequest(BaseModel):
    name: str
    type: str
    dataPlaneId: str = "*"
    scope: str = "data-plane"
    configuration: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class PrincipalRequest(BaseModel):
    id: str | None = None
    name: str
    type: str = "user"
    teamId: str = TECHNOLOGY_TEAM_ID
    permissions: list[dict[str, str]] = Field(default_factory=list)


class TeamRequest(BaseModel):
    id: str | None = None
    name: str
    kind: str = "delivery"
    description: str = ""
    namespaceScopes: list[dict[str, str]] = Field(default_factory=list)


class TeamTokenRequest(BaseModel):
    name: str = "Automation token"
    principalId: str | None = None
    roles: list[str] = Field(default_factory=lambda: ["Application Manager"])
    expiresAt: str | None = None


class SecretRequest(BaseModel):
    values: dict[str, str]

class ProfileUpdateRequest(BaseModel):
    values: list[dict[str, Any]]
    redeploy: bool = False

class DeploymentConfigurationRequest(BaseModel):
    environment: str | None = None
    instances: int | None = Field(default=None, ge=1, le=100)
    secrets: dict[str, str] = Field(default_factory=dict)
    redeploy: bool = True
    healthCheckEnabled: bool | None = None


@app.on_event("startup")
def initialize() -> None:
    for directory in (DATA_DIR, PACKAGES_DIR, STAGING_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    ensure_control_plane_defaults()
    reconcile_instances()


@app.get("/api/health")
def health():
    deployments = read_json(DEPLOYMENTS_FILE, [])
    planes = data_plane_inventory()
    return {"status": "ok", "component": "integration-fabric-control-plane", "version": ADMIN_VERSION, "uptimeSeconds": int(time.time() - STARTED_AT), "runtimeAdapterConfigured": bool(RUNTIME_COMMAND), "dataPlanes": len(planes), "onlineDataPlanes": len([item for item in planes if item.get("status") == "ONLINE"]), "capabilities": len(read_json(CAPABILITIES_FILE, [])), "packages": len(package_inventory()), "deployments": len([item for item in deployments if item.get("state") != "UNDEPLOYED"]), "failedDeployments": len([item for item in deployments if item.get("state") == "FAILED"])}


@app.get("/api/session")
def session(request: Request):
    caller = identity(request)
    return {**caller, "team":team_record(caller["teamId"])}


@app.get("/api/control-plane/overview")
def control_plane_overview(request: Request):
    require_technology(request)
    planes, capabilities = data_plane_inventory(), read_json(CAPABILITIES_FILE, [])
    deployments = [item for item in deployment_inventory() if item.get("state") != "UNDEPLOYED"]
    state_counts: dict[str, int] = {}
    for item in deployments: state_counts[item.get("state", "UNKNOWN")] = state_counts.get(item.get("state", "UNKNOWN"), 0) + 1
    return {"controlPlane":{"name":"Integration Fabric", "mode":"self-hosted", "version":ADMIN_VERSION, "region":"local", "status":"RUNNING"}, "teams":{"total":len([item for item in read_json(TEAMS_FILE, []) if item.get('status') == 'ACTIVE']), "delivery":len([item for item in read_json(TEAMS_FILE, []) if item.get('kind') == 'delivery' and item.get('status') == 'ACTIVE'])}, "dataPlanes":{"total":len(planes), "running":len([item for item in planes if item.get("status") == "ONLINE"]), "warning":len([item for item in planes if item.get("status") == "REGISTERED"]), "critical":len([item for item in planes if item.get("status") == "OFFLINE"])}, "capabilities":{"total":len(capabilities), "running":len([item for item in capabilities if item.get("health") == "RUNNING"])}, "applications":{"packages":len(package_inventory()), "deployments":len(deployments), "runningInstances":sum(len(item.get("instances", [])) for item in deployments), "states":state_counts}, "recentActivity":audit_inventory(12)}


@app.get("/api/packages")
def list_packages(request: Request, teamId: str | None = None):
    if teamId: requested_asset_team(request, teamId)
    return visible_assets(request, package_inventory(), teamId)


@app.get("/api/packages/{artifact}/{version}")
def get_package(artifact: str, version: str, request: Request, teamId: str | None = None):
    package_id = f"{safe(artifact)}:{safe(version)}"
    candidates = visible_assets(request, package_inventory(), teamId)
    item = next((value for value in candidates if value.get("packageId") == package_id), None)
    if not item:
        raise HTTPException(404, "Package not found")
    return {**item, "tasks": package_task_inventory(item)}


def agent_deployment_record(plane_id: str, deployment_id: str | None = None):
    deployments = [item for item in deployment_inventory() if (item.get("dataPlaneId") or item.get("machine")) == plane_id and item.get("state") != "UNDEPLOYED"]
    if deployment_id:
        item = next((value for value in deployments if value.get("id") == deployment_id), None)
        if not item: raise HTTPException(404, "Deployment not found")
        item = dict(item); item["secrets"] = deployment_secret_values(item["id"]); return item
    return [{**item, "secrets": deployment_secret_values(item["id"])} for item in deployments]


@app.get("/api/data-planes/{plane_id}/agent/deployments")
def agent_deployments(plane_id: str, request: Request):
    require_technology(request)
    return agent_deployment_record(plane_id)


@app.get("/api/data-planes/{plane_id}/agent/deployments/{deployment_id}/package")
def agent_package(plane_id: str, deployment_id: str, request: Request):
    require_technology(request)
    item = agent_deployment_record(plane_id, deployment_id)
    root = deployment_package_path(item)
    if not root.exists(): raise HTTPException(404, "Deployment package is not available")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file(): archive.write(path, path.relative_to(root).as_posix())
    return Response(buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={safe(item.get('id', deployment_id))}.zip"})


@app.post("/api/data-planes/{plane_id}/agent/deployments/{deployment_id}/report")
def agent_deployment_report(plane_id: str, deployment_id: str, request: Request, payload: dict[str, Any]):
    require_technology(request)
    deployments = read_json(DEPLOYMENTS_FILE, []); item = next((value for value in deployments if value.get("id") == deployment_id and (value.get("dataPlaneId") or value.get("machine")) == plane_id), None)
    if not item: raise HTTPException(404, "Deployment not found")
    for key in ("state", "instances", "message", "lastError"):
        if key in payload: item[key] = payload[key]
    if isinstance(payload.get("health"), dict): item["healthReport"] = payload["health"]
    if isinstance(payload.get("logs"), list): item["remoteLogs"] = payload["logs"][-20:]
    item["updatedAt"] = now(); write_json(DEPLOYMENTS_FILE, deployments)
    return item


@app.delete("/api/packages/{artifact}/{version}")
def delete_package(artifact: str, version: str, request: Request, teamId: str | None = None):
    require_application_manager(request)
    artifact, version = safe(artifact), safe(version)
    package_id = f"{artifact}:{version}"
    candidates = visible_assets(request, package_inventory(), teamId); package = next((item for item in candidates if item.get("packageId") == package_id), None)
    if not package: raise HTTPException(404, "Package not found")
    asset_team = package.get("teamId", TECHNOLOGY_TEAM_ID)
    active = [item for item in read_json(DEPLOYMENTS_FILE, []) if item.get("packageId") == package_id and item.get("teamId", TECHNOLOGY_TEAM_ID) == asset_team and item.get("state") != "UNDEPLOYED"]
    if active:
        raise HTTPException(409, "Undeploy every deployment that uses this package first")
    destination = PACKAGES_DIR / package.get("storagePath", str(Path(artifact) / version))
    if destination.exists():
        shutil.rmtree(destination)
    write_json(PACKAGES_FILE, [item for item in package_inventory() if not (item.get("packageId") == package_id and item.get("teamId", TECHNOLOGY_TEAM_ID) == asset_team)])
    caller = identity(request); audit("package.delete", package_id, actor=caller["name"], team_id=asset_team)
    record_revision("package", package_id, "package.delete", {"deleted":True}, actor=caller["name"], team_id=asset_team)
    return {"deleted": True, "packageId": package_id}


@app.post("/api/packages")
async def upload_package(request: Request, file: UploadFile = File(...), teamId: str | None = None):
    require_application_manager(request)
    asset_team = requested_asset_team(request, teamId)
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
        destination = PACKAGES_DIR / asset_team / artifact / version
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
        record = {**manifest, "packageId": f"{artifact}:{version}", "teamId":asset_team, "storagePath":str(Path(asset_team) / artifact / version), "receivedAt": now(), "status": "VALIDATED", "sha256": hashlib.sha256(body).hexdigest(), "archiveBytes": len(body), "expandedBytes": sum(len(value) for _, value in entries), "fileCount": len(entries), "sourceFile": file.filename or "deployment.ifpkg"}
        write_json(PACKAGES_FILE, [item for item in package_inventory() if not (item.get("packageId") == record["packageId"] and item.get("teamId", TECHNOLOGY_TEAM_ID) == asset_team)] + [record])
        caller = identity(request); audit("package.upload", record["packageId"], detail=f"Validated {len(entries)} files; sha256={record['sha256']}", actor=caller["name"], team_id=asset_team)
        record_revision("package", record["packageId"], "package.upload", {"sha256":record["sha256"], "environments":record.get("environments", []), "starterTaskIds":record.get("starterTaskIds", []), "fileCount":record.get("fileCount")}, actor=caller["name"], team_id=asset_team, detail=file.filename or "deployment.ifpkg")
        return record
    except HTTPException:
        raise
    except Exception as exc:
        caller = identity(request); audit("package.upload", outcome="failure", detail=str(exc), actor=caller["name"], team_id=asset_team)
        raise HTTPException(400, f"Invalid Integration Fabric deployment package: {exc}") from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def machine_inventory():
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


@app.get("/api/machines")
def list_machines(request: Request):
    require_technology(request)
    return machine_inventory()


@app.post("/api/machines")
def register_machine(payload: MachineRequest, request: Request):
    require_technology(request)
    machine_id = safe(payload.id or payload.name.lower())
    machines = read_json(MACHINES_FILE, [])
    if any(item.get("id") == machine_id for item in machines):
        raise HTTPException(409, "Machine already exists")
    if payload.driver not in {"agent", "command"}:
        raise HTTPException(400, "driver must be agent or command")
    item = payload.model_dump()
    item.update(id=machine_id, type="agent", region="local", namespaces=["default"], tags=[], status="REGISTERED", tunnelStatus="DISCONNECTED", runtimeConfigured=False, lastHeartbeat=now(), createdAt=now())
    machines.append(item)
    write_json(MACHINES_FILE, machines)
    audit("machine.register", machine_id, detail=payload.host)
    return item


def record_machine_heartbeat(machine_id: str):
    machines = read_json(MACHINES_FILE, [])
    item = next((value for value in machines if value.get("id") == machine_id), None)
    if not item:
        raise HTTPException(404, "Machine not found")
    item.update(status="ONLINE", tunnelStatus="CONNECTED", runtimeConfigured=True, lastHeartbeat=now())
    write_json(MACHINES_FILE, machines)
    return item


@app.post("/api/machines/{machine_id}/heartbeat")
def machine_heartbeat(machine_id: str, request: Request):
    require_technology(request)
    return record_machine_heartbeat(machine_id)


@app.get("/api/data-planes")
def list_data_planes(request: Request):
    require_technology(request)
    return data_plane_inventory()


@app.post("/api/data-planes")
def register_data_plane(payload: DataPlaneRequest, request: Request):
    require_technology(request)
    if payload.type not in {"kubernetes", "on-premises", "agent"}:
        raise HTTPException(400, "Data plane type must be kubernetes, on-premises, or agent")
    plane_id = safe(payload.id or payload.name.lower())
    machines = read_json(MACHINES_FILE, [])
    if any(item.get("id") == plane_id for item in machines): raise HTTPException(409, "Data plane already exists")
    item = payload.model_dump()
    item.update(id=plane_id, status="REGISTERED", tunnelStatus="DISCONNECTED", runtimeConfigured=False, registrationToken=uuid4().hex, lastHeartbeat=None, createdAt=now(), updatedAt=now())
    machines.append(item); write_json(MACHINES_FILE, machines)
    audit("data-plane.register", plane_id, detail=f"{payload.type} / {payload.region}")
    return item


@app.get("/api/data-planes/{plane_id}")
def get_data_plane(plane_id: str, request: Request):
    require_technology(request)
    item = next((value for value in data_plane_inventory() if value.get("id") == plane_id), None)
    if not item: raise HTTPException(404, "Data plane not found")
    return {**item, "capabilities":[value for value in read_json(CAPABILITIES_FILE, []) if value.get("dataPlaneId") == plane_id], "resources":[value for value in read_json(RESOURCES_FILE, []) if value.get("dataPlaneId") in (plane_id, "*")]}


@app.put("/api/data-planes/{plane_id}")
def update_data_plane(plane_id: str, payload: DataPlaneRequest, request: Request):
    require_technology(request)
    machines = read_json(MACHINES_FILE, [])
    item = next((value for value in machines if value.get("id") == plane_id), None)
    if not item: raise HTTPException(404, "Data plane not found")
    if payload.id and safe(payload.id) != plane_id: raise HTTPException(400, "The data-plane id cannot be changed")
    if payload.type not in {"kubernetes", "on-premises", "agent"}: raise HTTPException(400, "Data plane type must be kubernetes, on-premises, or agent")
    removed = set(item.get("namespaces", [])) - set(payload.namespaces)
    active = [value for value in read_json(DEPLOYMENTS_FILE, []) if (value.get("dataPlaneId") or value.get("machine")) == plane_id and value.get("state") != "UNDEPLOYED" and value.get("namespace") in removed]
    if active: raise HTTPException(409, "Cannot remove namespaces used by active deployments")
    item.update(name=payload.name, type=payload.type, host=payload.host, region=payload.region, namespaces=payload.namespaces, tags=payload.tags, capacity=payload.capacity, driver=payload.driver, updatedAt=now())
    write_json(MACHINES_FILE, machines); audit("data-plane.update", plane_id)
    return item


@app.post("/api/data-planes/{plane_id}/heartbeat")
def data_plane_heartbeat(plane_id: str, request: Request, payload: dict[str, Any] | None = None):
    require_technology(request)
    item = record_machine_heartbeat(plane_id)
    payload = payload or {}
    # Agents may report host capacity and execution counters in addition to
    # their liveness signal. Keep the complete telemetry document so the
    # operator console can show what the runtime is actually consuming.
    # A heartbeat reports health and capacity only.  The data-plane namespace
    # list is deployment topology managed through the Control Plane/UI.  Do
    # not let an older agent INI overwrite it on every heartbeat.
    for key in ("runtimeVersion", "agentVersion", "cpuPercent", "memoryPercent", "memoryUsedBytes", "memoryAvailableBytes", "memoryTotalBytes", "diskPercent", "diskFreeBytes", "loadAverage", "processCount", "availableCapacity", "telemetry"):
        if key in payload: item[key] = payload[key]
    machines = read_json(MACHINES_FILE, [])
    stored = next(value for value in machines if value.get("id") == plane_id); stored.update(item); stored["runtimeConfigured"] = True; write_json(MACHINES_FILE, machines)
    # A capability is provisioned before its agent may be online. Reconcile
    # existing capabilities whenever the data-plane heartbeat arrives so they
    # do not remain permanently PENDING after the agent has connected.
    capabilities = read_json(CAPABILITIES_FILE, [])
    capability_changed = False
    for capability in capabilities:
        if capability.get("dataPlaneId") != plane_id: continue
        next_health = "RUNNING" if stored.get("status") == "ONLINE" else "PENDING"
        if capability.get("health") != next_health:
            capability["health"] = next_health; capability["updatedAt"] = now(); capability_changed = True
    if capability_changed: write_json(CAPABILITIES_FILE, capabilities)
    reports = payload.get("deploymentHealth") or {}
    if isinstance(reports, list): reports = {str(value.get("deploymentId")):value for value in reports if isinstance(value, dict) and value.get("deploymentId")}
    if isinstance(reports, dict) and reports:
        deployments, changed = read_json(DEPLOYMENTS_FILE, []), False
        for deployment in deployments:
            report = reports.get(deployment.get("id"))
            if not isinstance(report, dict) or (deployment.get("dataPlaneId") or deployment.get("machine")) != plane_id: continue
            health_status = str(report.get("status") or "UNKNOWN").upper()
            if health_status not in {"HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"}: continue
            deployment["healthReport"] = {"status":health_status, "message":str(report.get("message") or "Data-plane application health report"), "checkedAt":now()}
            if isinstance(report.get("starterStates"), dict): deployment["reportedStarterStates"] = report["starterStates"]
            changed = True
        if changed: write_json(DEPLOYMENTS_FILE, deployments)
    return item


@app.delete("/api/data-planes/{plane_id}")
def unregister_data_plane(plane_id: str, request: Request, force: bool = False):
    require_technology(request)
    if plane_id == "localhost": raise HTTPException(409, "The local data plane cannot be unregistered")
    active = [item for item in read_json(DEPLOYMENTS_FILE, []) if (item.get("dataPlaneId") or item.get("machine")) == plane_id and item.get("state") != "UNDEPLOYED"]
    if active and not force: raise HTTPException(409, "Undeploy applications from this data plane first")
    write_json(MACHINES_FILE, [item for item in read_json(MACHINES_FILE, []) if item.get("id") != plane_id])
    write_json(CAPABILITIES_FILE, [item for item in read_json(CAPABILITIES_FILE, []) if item.get("dataPlaneId") != plane_id])
    audit("data-plane.unregister", plane_id, detail=f"force={force}")
    return {"deleted":True, "dataPlaneId":plane_id}


@app.get("/api/capabilities")
def list_capabilities(request: Request, dataPlaneId: str | None = None):
    require_technology(request)
    values = read_json(CAPABILITIES_FILE, [])
    return [item for item in values if not dataPlaneId or item.get("dataPlaneId") == dataPlaneId]


@app.post("/api/capabilities")
def provision_capability(payload: CapabilityRequest, request: Request):
    require_technology(request)
    plane = next((item for item in data_plane_inventory() if item.get("id") == payload.dataPlaneId), None)
    if not plane: raise HTTPException(404, "Data plane not found")
    if payload.namespace not in plane.get("namespaces", ["default"]): raise HTTPException(400, "Namespace is not registered on the selected data plane")
    capability_id = safe(f"{payload.type}-{payload.dataPlaneId}-{payload.namespace}")
    values = read_json(CAPABILITIES_FILE, [])
    if any(item.get("id") == capability_id for item in values): raise HTTPException(409, "Capability is already provisioned")
    item = payload.model_dump(); item.update(id=capability_id, state="PROVISIONED", health="RUNNING" if plane.get("status") == "ONLINE" else "PENDING", createdAt=now(), updatedAt=now())
    values.append(item); write_json(CAPABILITIES_FILE, values); audit("capability.provision", capability_id, detail=payload.dataPlaneId)
    return item


@app.put("/api/capabilities/{capability_id}")
def update_capability(capability_id: str, payload: CapabilityRequest, request: Request):
    require_technology(request)
    values = read_json(CAPABILITIES_FILE, [])
    item = next((value for value in values if value.get("id") == capability_id), None)
    if not item: raise HTTPException(404, "Capability not found")
    if safe(f"{payload.type}-{payload.dataPlaneId}-{payload.namespace}") != capability_id: raise HTTPException(400, "Capability type, data plane, and namespace are immutable; delete and provision a new capability")
    plane = next((value for value in data_plane_inventory() if value.get("id") == payload.dataPlaneId), None)
    if not plane: raise HTTPException(404, "Data plane not found")
    if payload.namespace not in plane.get("namespaces", ["default"]): raise HTTPException(400, "Namespace is not registered on the selected data plane")
    item.update(name=payload.name, version=payload.version, tags=payload.tags, updatedAt=now())
    write_json(CAPABILITIES_FILE, values); audit("capability.update", capability_id)
    return item


@app.delete("/api/capabilities/{capability_id}")
def deprovision_capability(capability_id: str, request: Request):
    require_technology(request)
    values = read_json(CAPABILITIES_FILE, []); item = next((value for value in values if value.get("id") == capability_id), None)
    if not item: raise HTTPException(404, "Capability not found")
    active = [value for value in read_json(DEPLOYMENTS_FILE, []) if value.get("capabilityId") == capability_id and value.get("state") != "UNDEPLOYED"]
    if active: raise HTTPException(409, "Undeploy applications using this capability first")
    write_json(CAPABILITIES_FILE, [value for value in values if value.get("id") != capability_id]); audit("capability.deprovision", capability_id)
    return {"deleted":True, "capabilityId":capability_id}


def resource_inventory(dataPlaneId: str | None = None):
    values = read_json(RESOURCES_FILE, [])
    return [item for item in values if not dataPlaneId or item.get("dataPlaneId") in (dataPlaneId, "*")]


@app.get("/api/resources")
def list_resources(request: Request, dataPlaneId: str | None = None):
    require_technology(request)
    return resource_inventory(dataPlaneId)


@app.post("/api/resources")
def create_resource(payload: ResourceRequest, request: Request):
    require_technology(request)
    if payload.type not in {"observability", "ingress", "storage", "secret-provider", "service-account"}: raise HTTPException(400, "Unsupported control-plane resource type")
    if payload.dataPlaneId != "*" and not any(item.get("id") == payload.dataPlaneId for item in data_plane_inventory()): raise HTTPException(404, "Data plane not found")
    item = payload.model_dump(); item.update(id=str(uuid4()), teamId=TECHNOLOGY_TEAM_ID, state="CONFIGURED", createdAt=now(), updatedAt=now())
    values = read_json(RESOURCES_FILE, []); values.append(item); write_json(RESOURCES_FILE, values); audit("resource.create", item["id"], detail=f"{payload.type} / {payload.dataPlaneId}")
    return item


@app.delete("/api/resources/{resource_id}")
def delete_resource(resource_id: str, request: Request):
    require_technology(request)
    values = read_json(RESOURCES_FILE, [])
    if not any(item.get("id") == resource_id for item in values): raise HTTPException(404, "Resource not found")
    write_json(RESOURCES_FILE, [item for item in values if item.get("id") != resource_id]); audit("resource.delete", resource_id)
    return {"deleted":True, "resourceId":resource_id}


def validate_team_scopes(team_id: str, scopes: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized = []
    for scope in scopes:
        plane_id, namespace = safe(scope.get("dataPlaneId", "")), safe(scope.get("namespace", ""))
        plane = next((item for item in data_plane_inventory() if item.get("id") == plane_id), None)
        if not plane: raise HTTPException(400, f"Unknown data plane in team scope: {plane_id}")
        if namespace not in plane.get("namespaces", []): raise HTTPException(400, f"Namespace {namespace} is not registered on {plane_id}")
        normalized.append({"dataPlaneId":plane_id, "namespace":namespace})
    if len({(item["dataPlaneId"], item["namespace"]) for item in normalized}) != len(normalized):
        raise HTTPException(400, "A namespace can appear only once in a team's scope")
    for team in read_json(TEAMS_FILE, []):
        if team.get("id") in (team_id, TECHNOLOGY_TEAM_ID) or team.get("status") != "ACTIVE": continue
        occupied = {(item.get("dataPlaneId"), item.get("namespace")) for item in team.get("namespaceScopes", [])}
        overlap = occupied & {(item["dataPlaneId"], item["namespace"]) for item in normalized}
        if overlap:
            plane_id, namespace = next(iter(overlap))
            raise HTTPException(409, f"Namespace {namespace} on {plane_id} is already isolated for team {team.get('name')}")
    return normalized


@app.get("/api/teams")
def list_teams(request: Request):
    require_technology(request)
    packages, deployments = package_inventory(), read_json(DEPLOYMENTS_FILE, [])
    return [{**item, "packageCount":len([value for value in packages if value.get("teamId", TECHNOLOGY_TEAM_ID) == item.get("id")]), "deploymentCount":len([value for value in deployments if value.get("teamId", TECHNOLOGY_TEAM_ID) == item.get("id") and value.get("state") != "UNDEPLOYED"])} for item in read_json(TEAMS_FILE, [])]


@app.post("/api/teams")
def create_team(payload: TeamRequest, request: Request):
    require_technology(request)
    if payload.kind != "delivery": raise HTTPException(400, "Additional teams must be delivery teams")
    team_id = safe(payload.id or payload.name.lower())
    teams = read_json(TEAMS_FILE, [])
    if any(item.get("id") == team_id for item in teams): raise HTTPException(409, "Team already exists")
    scopes = validate_team_scopes(team_id, payload.namespaceScopes)
    if not scopes: raise HTTPException(400, "A delivery team requires at least one isolated data-plane namespace")
    item = payload.model_dump(); item.update(id=team_id, kind="delivery", controlPlaneAccess=False, namespaceScopes=scopes, status="ACTIVE", createdAt=now(), updatedAt=now())
    teams.append(item); write_json(TEAMS_FILE, teams); audit("team.create", team_id, detail=payload.name)
    return item


@app.put("/api/teams/{team_id}")
def update_team(team_id: str, payload: TeamRequest, request: Request):
    require_technology(request)
    if team_id == TECHNOLOGY_TEAM_ID: raise HTTPException(409, "The Technology Team is the permanent Control Plane owner")
    teams = read_json(TEAMS_FILE, []); item = next((value for value in teams if value.get("id") == team_id), None)
    if not item: raise HTTPException(404, "Team not found")
    scopes = validate_team_scopes(team_id, payload.namespaceScopes)
    if not scopes: raise HTTPException(400, "A delivery team requires at least one isolated data-plane namespace")
    active = [value for value in read_json(DEPLOYMENTS_FILE, []) if value.get("teamId") == team_id and value.get("state") != "UNDEPLOYED" and not any(scope["dataPlaneId"] == (value.get("dataPlaneId") or value.get("machine")) and scope["namespace"] == value.get("namespace") for scope in scopes)]
    if active: raise HTTPException(409, "The new scope would orphan active team deployments")
    item.update(name=payload.name, description=payload.description, namespaceScopes=scopes, updatedAt=now()); write_json(TEAMS_FILE, teams); audit("team.update", team_id)
    return item


@app.delete("/api/teams/{team_id}")
def delete_team(team_id: str, request: Request):
    require_technology(request)
    if team_id == TECHNOLOGY_TEAM_ID: raise HTTPException(409, "The Technology Team cannot be removed")
    assets = [item for item in package_inventory() if item.get("teamId", TECHNOLOGY_TEAM_ID) == team_id]
    deployments = [item for item in read_json(DEPLOYMENTS_FILE, []) if item.get("teamId", TECHNOLOGY_TEAM_ID) == team_id and item.get("state") != "UNDEPLOYED"]
    if assets or deployments: raise HTTPException(409, "Remove the team's packages and deployments before deleting the team")
    teams = read_json(TEAMS_FILE, []); item = next((value for value in teams if value.get("id") == team_id), None)
    if not item: raise HTTPException(404, "Team not found")
    item.update(status="DELETED", updatedAt=now()); write_json(TEAMS_FILE, teams)
    tokens = read_json(TOKENS_FILE, []); [token.update(status="REVOKED", revokedAt=now()) for token in tokens if token.get("teamId") == team_id]; write_json(TOKENS_FILE, tokens)
    audit("team.delete", team_id); return {"deleted":True, "teamId":team_id}


@app.post("/api/teams/{team_id}/tokens")
def issue_team_token(team_id: str, payload: TeamTokenRequest, request: Request):
    require_technology(request); team = team_record(team_id)
    if team_id == TECHNOLOGY_TEAM_ID: raise HTTPException(400, "Use FABRIC_ADMIN_API_KEY for Technology Team access")
    allowed = {"Application Manager", "Application Viewer"}
    if not payload.roles or any(role not in allowed for role in payload.roles): raise HTTPException(400, "Delivery tokens support Application Manager or Application Viewer roles")
    if payload.expiresAt:
        try:
            if datetime.fromisoformat(payload.expiresAt) <= datetime.now(timezone.utc): raise ValueError()
        except ValueError: raise HTTPException(400, "expiresAt must be a future ISO-8601 timestamp")
    raw = "ifcp_" + secrets.token_urlsafe(32); token_id = str(uuid4())
    item = {"id":token_id, "name":payload.name, "teamId":team_id, "principalId":payload.principalId or f"{team_id}-automation", "principalName":payload.name, "roles":payload.roles, "tokenHash":token_hash(raw), "status":"ACTIVE", "createdAt":now(), "expiresAt":payload.expiresAt}
    values = read_json(TOKENS_FILE, []); values.append(item); write_json(TOKENS_FILE, values); audit("team.token.issue", token_id, detail=team_id)
    return {"id":token_id, "teamId":team_id, "token":raw, "shownOnce":True, "roles":payload.roles, "expiresAt":payload.expiresAt}


@app.delete("/api/teams/{team_id}/tokens/{token_id}")
def revoke_team_token(team_id: str, token_id: str, request: Request):
    require_technology(request); values = read_json(TOKENS_FILE, [])
    item = next((value for value in values if value.get("id") == token_id and value.get("teamId") == team_id), None)
    if not item: raise HTTPException(404, "Team token not found")
    item.update(status="REVOKED", revokedAt=now()); write_json(TOKENS_FILE, values); audit("team.token.revoke", token_id, detail=team_id)
    return {"revoked":True, "tokenId":token_id}


@app.get("/api/access/principals")
def list_principals(request: Request):
    require_technology(request)
    return read_json(PRINCIPALS_FILE, [])


@app.post("/api/access/principals")
def create_principal(payload: PrincipalRequest, request: Request):
    require_technology(request)
    if payload.type not in {"user", "team", "idp-group"}: raise HTTPException(400, "Principal type must be user, team, or idp-group")
    team = team_record(payload.teamId)
    allowed = {"Owner", "Team Admin", "Capability Manager", "Application Manager", "Application Viewer"}
    invalid = [item.get("role") for item in payload.permissions if item.get("role") not in allowed]
    if invalid: raise HTTPException(400, f"Unsupported permissions: {', '.join(map(str, invalid))}")
    if team.get("kind") == "delivery" and any(item.get("role") in {"Owner", "Team Admin"} or item.get("scope") == "control-plane" for item in payload.permissions): raise HTTPException(403, "Delivery-team principals cannot receive Control Plane roles")
    item = payload.model_dump(); item.update(id=safe(payload.id or str(uuid4())), status="ACTIVE", createdAt=now())
    values = read_json(PRINCIPALS_FILE, [])
    if any(value.get("id") == item["id"] for value in values): raise HTTPException(409, "Principal already exists")
    values.append(item); write_json(PRINCIPALS_FILE, values); audit("access.principal.create", item["id"], detail=payload.name)
    return item


@app.put("/api/access/principals/{principal_id}")
def update_principal(principal_id: str, payload: PrincipalRequest, request: Request):
    require_technology(request)
    if payload.type not in {"user", "team", "idp-group"}: raise HTTPException(400, "Principal type must be user, team, or idp-group")
    team = team_record(payload.teamId)
    allowed = {"Owner", "Team Admin", "Capability Manager", "Application Manager", "Application Viewer"}
    invalid = [item.get("role") for item in payload.permissions if item.get("role") not in allowed]
    if invalid: raise HTTPException(400, f"Unsupported permissions: {', '.join(map(str, invalid))}")
    if team.get("kind") == "delivery" and any(item.get("role") in {"Owner", "Team Admin"} or item.get("scope") == "control-plane" for item in payload.permissions): raise HTTPException(403, "Delivery-team principals cannot receive Control Plane roles")
    values = read_json(PRINCIPALS_FILE, []); item = next((value for value in values if value.get("id") == principal_id), None)
    if not item: raise HTTPException(404, "Principal not found")
    item.update(name=payload.name, type=payload.type, teamId=payload.teamId, permissions=payload.permissions, updatedAt=now())
    write_json(PRINCIPALS_FILE, values); audit("access.principal.update", principal_id, detail=payload.name)
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


def deployment_inventory():
    reconcile_instances()
    values = read_json(DEPLOYMENTS_FILE, []); changed = False
    for item in values:
        if not item.get("teamId"): item["teamId"] = TECHNOLOGY_TEAM_ID; changed = True
    if changed: write_json(DEPLOYMENTS_FILE, values)
    return values

def deployment_health(item: dict) -> dict:
    if not item.get("healthCheckEnabled", True): return {"status":"DISABLED", "checkedAt":now(), "message":"Health checks are disabled"}
    if item.get("state") == "FAILED": return {"status":"UNHEALTHY", "checkedAt":now(), "message":item.get("lastError") or "Deployment failed"}
    if item.get("state") != "RUNNING": return {"status":"PENDING", "checkedAt":now(), "message":f"Deployment is {item.get('state', 'UNKNOWN')}"}
    if (item.get("dataPlaneId") or item.get("machine")) == "localhost":
        instances = item.get("instances") or []
        healthy = bool(instances) and all(process_alive(int(instance.get("pid") or 0)) for instance in instances)
        return {"status":"HEALTHY" if healthy else "UNHEALTHY", "checkedAt":now(), "message":f"{len(instances)} local runtime instance(s) checked"}
    report = item.get("healthReport")
    if isinstance(report, dict): return report
    return {"status":"UNKNOWN", "checkedAt":now(), "message":"Awaiting an application health report from the data-plane agent"}


@app.get("/api/deployments")
def list_deployments(request: Request, teamId: str | None = None):
    if teamId: requested_asset_team(request, teamId)
    return [{**item, "health":deployment_health(item)} for item in visible_assets(request, deployment_inventory(), teamId)]


@app.get("/api/deployments/{deployment_id}")
def get_deployment(deployment_id: str, request: Request):
    reconcile_instances()
    item = next((value for value in read_json(DEPLOYMENTS_FILE, []) if value.get("id") == deployment_id), None)
    if not item:
        raise HTTPException(404, "Deployment not found")
    require_asset(request, item)
    configured = set(read_json(SECRETS_FILE, {}).get(deployment_id, {}))
    return {**item, "health":deployment_health(item), "secrets": [{"name": name, "configured": name in configured} for name in item.get("requiredSecrets", [])]}


@app.delete("/api/deployments/{deployment_id}")
def delete_application(deployment_id: str, request: Request):
    deployments = read_json(DEPLOYMENTS_FILE, [])
    item = next((value for value in deployments if value.get("id") == deployment_id), None)
    if not item: raise HTTPException(404, "Deployment not found")
    require_application_write(request, item)
    if item.get("state") != "UNDEPLOYED": raise HTTPException(409, "Undeploy the application before deleting it")
    write_json(DEPLOYMENTS_FILE, [value for value in deployments if value.get("id") != deployment_id])
    secrets_store = read_json(SECRETS_FILE, {}); secrets_store.pop(deployment_id, None); write_json(SECRETS_FILE, secrets_store)
    caller = identity(request); audit("application.delete", deployment_id, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID))
    record_revision("deployment", deployment_id, "application.delete", {"deleted":True}, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID))
    return {"deleted":True, "deploymentId":deployment_id}


@app.post("/api/deployments")
def create_deployment(payload: DeploymentRequest, request: Request):
    require_application_manager(request)
    asset_team = requested_asset_team(request, payload.teamId)
    package = next((item for item in package_inventory() if item.get("packageId") == payload.packageId and item.get("teamId", TECHNOLOGY_TEAM_ID) == asset_team), None)
    if not package:
        raise HTTPException(404, "Package not found")
    environments = package_environments(package)
    if payload.environment not in environments:
        raise HTTPException(400, f"Environment must be one of: {', '.join(environments)}")
    data_plane_id = payload.dataPlaneId or payload.machine
    plane = next((item for item in data_plane_inventory() if item.get("id") == data_plane_id), None)
    if not plane: raise HTTPException(404, "Data plane not found")
    if package.get("target") == "cloud" and plane.get("type") != "kubernetes": raise HTTPException(400, "Cloud packages require a Kubernetes data plane")
    if payload.namespace not in plane.get("namespaces", ["default"]): raise HTTPException(400, "Namespace is not registered on the selected data plane")
    if not team_can_use_namespace(asset_team, data_plane_id, payload.namespace): raise HTTPException(403, "The selected namespace is not assigned to this delivery team")
    capabilities = [item for item in read_json(CAPABILITIES_FILE, []) if item.get("dataPlaneId") == data_plane_id and item.get("type") == "integration-runtime"]
    capability = next((item for item in capabilities if item.get("id") == payload.capabilityId and item.get("namespace") == payload.namespace), None) if payload.capabilityId else next((item for item in capabilities if item.get("namespace") == payload.namespace), None)
    if not capability: raise HTTPException(409, "Provision an Integration Runtime capability in this data plane and namespace first")
    if payload.instances > int(plane.get("capacity", 1)): raise HTTPException(409, "Requested instances exceed data-plane capacity")
    required = required_secrets(package, payload.environment)
    missing = [name for name in required if not payload.secrets.get(name)]
    if missing:
        raise HTTPException(422, f"Required secrets are missing: {', '.join(missing)}")
    deployment_id = str(uuid4())
    starter_states = {task_id:"STARTED" for task_id in package.get("starterTaskIds") or []}
    item = {"id": deployment_id, "packageId": payload.packageId, "packageStoragePath":package.get("storagePath"), "teamId":asset_team, "application": package.get("applicationName"), "environment": payload.environment, "machine": data_plane_id, "dataPlaneId": data_plane_id, "capabilityId": capability["id"], "namespace": payload.namespace, "desiredInstances": payload.instances, "instances": [], "requiredSecrets": required, "starterStates":starter_states, "healthCheckEnabled":True, "health":"PENDING", "state": "DEPLOYED", "createdAt": now(), "updatedAt": now(), "message": "Validated and ready to start." if data_plane_id == "localhost" else "Deployment created; awaiting the data-plane runtime agent.", "lastError": None}
    deployments = read_json(DEPLOYMENTS_FILE, [])
    deployments.append(item)
    write_json(DEPLOYMENTS_FILE, deployments)
    save_deployment_secrets(deployment_id, payload.secrets)
    caller = identity(request); audit("application.deploy", deployment_id, detail=f"{payload.packageId} / {payload.environment} / {data_plane_id} / {payload.namespace}", actor=caller["name"], team_id=asset_team)
    record_revision("deployment", deployment_id, "application.deploy", {"packageId":payload.packageId, "environment":payload.environment, "dataPlaneId":data_plane_id, "namespace":payload.namespace, "instances":payload.instances, "starterStates":starter_states}, actor=caller["name"], team_id=asset_team)
    return item


@app.get("/api/applications")
def list_applications(request: Request, dataPlaneId: str | None = None, teamId: str | None = None):
    if teamId: requested_asset_team(request, teamId)
    deployments = [item for item in visible_assets(request, deployment_inventory(), teamId) if item.get("state") != "UNDEPLOYED" and (not dataPlaneId or (item.get("dataPlaneId") or item.get("machine")) == dataPlaneId)]
    packages = visible_assets(request, package_inventory(), teamId)
    return [{**package, "deployments":[item for item in deployments if item.get("packageId") == package.get("packageId") and item.get("teamId", TECHNOLOGY_TEAM_ID) == package.get("teamId", TECHNOLOGY_TEAM_ID)], "deploymentCount":len([item for item in deployments if item.get("packageId") == package.get("packageId") and item.get("teamId", TECHNOLOGY_TEAM_ID) == package.get("teamId", TECHNOLOGY_TEAM_ID)])} for package in packages]


@app.put("/api/deployments/{deployment_id}/secrets")
def update_secrets(deployment_id: str, payload: SecretRequest, request: Request):
    require_application_manager(request)
    item = get_deployment(deployment_id, request)
    unknown = set(payload.values) - set(item.get("requiredSecrets", []))
    if unknown:
        raise HTTPException(400, f"Unknown secret keys: {', '.join(sorted(unknown))}")
    current = deployment_secret_values(deployment_id)
    current.update(payload.values)
    save_deployment_secrets(deployment_id, current)
    caller = identity(request); audit("deployment.secrets.update", deployment_id, detail=f"Updated {len(payload.values)} secret values", actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID))
    record_revision("deployment", deployment_id, "deployment.secrets.update", {"configuredSecretKeys":sorted(current)}, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID), detail=f"Updated {len(payload.values)} secret values")
    return {"updated": sorted(payload.values), "valuesExposed": False}


def deployment_package_path(item: dict) -> Path:
    if item.get("packageStoragePath"): return PACKAGES_DIR / item["packageStoragePath"]
    package = next((value for value in package_inventory() if value.get("packageId") == item.get("packageId") and value.get("teamId", TECHNOLOGY_TEAM_ID) == item.get("teamId", TECHNOLOGY_TEAM_ID)), None)
    if package and package.get("storagePath"): return PACKAGES_DIR / package["storagePath"]
    artifact, version = item["packageId"].split(":", 1); return PACKAGES_DIR / safe(artifact) / safe(version)


def runtime_arguments(item: dict, instance_id: str) -> list[str] | str:
    package_path = deployment_package_path(item)
    command = RUNTIME_COMMAND
    for marker, value in {"{application}": str(package_path / "application"), "{package}": str(package_path), "{environment}": item["environment"], "{deployment_id}": item["id"], "{instance_id}": instance_id}.items():
        command = command.replace(marker, value)
    # Tokenize the configured template before CreateProcess sees it. Passing
    # a raw Windows command string allowed quoted placeholder values to merge
    # (for example, ``...\application--environment\project.json``). Strip
    # only the protective outer quotes; embedded quotes remain part of values.
    if os.name == "nt":
        arguments = shlex.split(command, posix=False)
        return [value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'") else value for value in arguments]
    return shlex.split(command)


def start_instances(item: dict) -> None:
    if not RUNTIME_COMMAND:
        raise HTTPException(409, "No runtime adapter is configured. Set FABRIC_ADMIN_RUNTIME_COMMAND; see the Administrator Guide.")
    machine = next((value for value in machine_inventory() if value.get("id") == item.get("machine")), None)
    if not machine or machine.get("driver") != "command" or item.get("machine") != "localhost":
        raise HTTPException(409, "This build can execute only the localhost command adapter")
    item["instances"] = []
    for ordinal in range(int(item["desiredInstances"])):
        instance_id = f"{item['id'][:8]}-{ordinal + 1}"
        log_path = LOGS_DIR / f"{instance_id}.log"
        environment = os.environ.copy()
        enabled_starters = [task_id for task_id, state in (item.get("starterStates") or {}).items() if state != "STOPPED"]
        environment.update({"FABRIC_DEPLOYMENT_ID": item["id"], "FABRIC_INSTANCE_ID": instance_id, "FABRIC_ENVIRONMENT": item["environment"], "FABRIC_APPLICATION_DIR": str(deployment_package_path(item) / "application"), "FABRIC_ENABLED_STARTERS": json.dumps(enabled_starters), **deployment_secret_values(item["id"])})
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
        if (item.get("dataPlaneId") or item.get("machine")) != "localhost":
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


@app.post("/api/deployments/{deployment_id}/revert")
def revert_deployment_action(deployment_id: str, payload: dict[str, Any], request: Request):
    require_application_manager(request)
    deployments = read_json(DEPLOYMENTS_FILE, [])
    item = next((value for value in deployments if value.get("id") == deployment_id), None)
    if not item: raise HTTPException(404, "Deployment not found")
    require_application_write(request, item)
    revisions = [value for value in read_json(REVISIONS_FILE, []) if value.get("assetType") == "deployment" and value.get("assetId") == deployment_id]
    selected = payload.get("revision") or payload.get("revisionId")
    revision = next((value for value in revisions if str(value.get("revision")) == str(selected) or value.get("id") == selected), None)
    if not revision: raise HTTPException(404, "Deployment revision not found")
    snapshot = revision.get("snapshot") or {}
    if snapshot.get("environment"): item["environment"] = snapshot["environment"]
    if snapshot.get("instances") is not None: item["desiredInstances"] = int(snapshot["instances"])
    if snapshot.get("healthCheckEnabled") is not None: item["healthCheckEnabled"] = bool(snapshot["healthCheckEnabled"])
    if isinstance(snapshot.get("starterStates"), dict): item["starterStates"] = snapshot["starterStates"]
    if item.get("state") == "RUNNING" and (item.get("dataPlaneId") or item.get("machine")) == "localhost": terminate_instances(item); start_instances(item)
    item.update(updatedAt=now(), lastError=None, message=f"Reverted to deployment revision {revision.get('revision')}")
    write_json(DEPLOYMENTS_FILE, deployments)
    caller = identity(request)
    record_revision("deployment", deployment_id, "deployment.revert", {"revertedRevision": revision.get("revision"), "environment": item.get("environment"), "instances": item.get("desiredInstances"), "healthCheckEnabled": item.get("healthCheckEnabled", True), "starterStates": item.get("starterStates", {})}, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID), detail=item["message"])
    audit("deployment.revert", deployment_id, detail=item["message"], actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID))
    return {**item, "health": deployment_health(item)}


@app.post("/api/deployments/{deployment_id}/{action}")
def lifecycle(deployment_id: str, action: str, request: Request):
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(400, "Unsupported lifecycle action")
    deployments = read_json(DEPLOYMENTS_FILE, [])
    item = next((value for value in deployments if value.get("id") == deployment_id), None)
    if not item:
        raise HTTPException(404, "Deployment not found")
    require_application_write(request, item); caller = identity(request)
    if item.get("state") not in ALLOWED_ACTIONS[action]:
        raise HTTPException(409, f"Cannot {action} a deployment in {item.get('state')} state")
    try:
        if action in {"stop", "kill", "restart"} and item.get("state") == "RUNNING":
            terminate_instances(item, action == "kill")
        if action in {"start", "restart"}:
            if item.get("machine") == "localhost":
                start_instances(item)
                item.update(state="RUNNING", message=f"{len(item['instances'])} runtime instance(s) started", lastError=None)
            else:
                item.update(state="RUNNING", message="Start requested; awaiting the remote data-plane agent", lastError=None)
        elif action in {"stop", "kill"}:
            item.update(state="STOPPED", message="Stop requested; awaiting the remote data-plane agent")
        else:
            item.update(state="UNDEPLOYED", instances=[], message="Deployment removed from the runtime inventory")
            secrets = read_json(SECRETS_FILE, {}); secrets.pop(deployment_id, None); write_json(SECRETS_FILE, secrets)
        item["updatedAt"] = now()
        write_json(DEPLOYMENTS_FILE, deployments)
        audit(f"deployment.{action}", deployment_id, detail=item["message"], actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID))
        record_revision("deployment", deployment_id, f"deployment.{action}", {"state":item.get("state"), "environment":item.get("environment"), "instances":item.get("desiredInstances"), "starterStates":item.get("starterStates", {})}, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID), detail=item["message"])
        return item
    except HTTPException as exc:
        item.update(state="FAILED" if action in {"start", "restart"} else item.get("state"), updatedAt=now(), lastError=str(exc.detail), message=f"{action.title()} failed")
        write_json(DEPLOYMENTS_FILE, deployments)
        audit(f"deployment.{action}", deployment_id, "failure", str(exc.detail), actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID))
        raise
    except Exception as exc:
        item.update(state="FAILED", updatedAt=now(), lastError=str(exc), message=f"{action.title()} failed")
        write_json(DEPLOYMENTS_FILE, deployments)
        audit(f"deployment.{action}", deployment_id, "failure", str(exc), actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID))
        raise HTTPException(500, f"Runtime adapter failed: {exc}") from exc

def package_for_request(artifact: str, version: str, request: Request, team_id: str | None = None) -> dict:
    package_id = f"{safe(artifact)}:{safe(version)}"
    item = next((value for value in visible_assets(request, package_inventory(), team_id) if value.get("packageId") == package_id), None)
    if not item: raise HTTPException(404, "Package not found")
    return item

def public_profile_values(values: list[dict]) -> list[dict]:
    output, keys = [], set()
    supported = {"string", "integer", "long", "number", "boolean", "dateTime", "password", "json"}
    for entry in values:
        if not isinstance(entry, dict) or not str(entry.get("key") or "").strip(): raise HTTPException(400, "Every profile property requires a key")
        key, data_type = str(entry["key"]).strip(), str(entry.get("data_type") or "string")
        if key in keys: raise HTTPException(400, f"Duplicate profile property: {key}")
        if data_type not in supported: raise HTTPException(400, f"Unsupported profile data type for {key}: {data_type}")
        value = entry.get("value", "")
        if data_type == "password" and str(value): raise HTTPException(400, f"Secret property {key} must be configured on the deployment, not uploaded in a profile")
        keys.add(key); output.append({"key":key, "value":"" if data_type == "password" else value, "data_type":data_type})
    return output

def update_stored_profile(package: dict, environment: str, values: list[dict]) -> None:
    root = stored_package_path(package)
    profile = root / "environments" / f"{safe(environment)}.json"
    if not profile.exists(): raise HTTPException(404, "Environment profile was not found in the package")
    write_json(profile, values)
    project_file = root / "application" / "project.json"
    if project_file.exists():
        project = read_json(project_file, {})
        project.setdefault("properties", {})[environment] = values
        write_json(project_file, project)
    manifest_file = root / "manifest.json"; manifest = read_json(manifest_file, {})
    manifest.setdefault("secretKeysByEnvironment", {})[environment] = sorted(value["key"] for value in values if value.get("data_type") == "password")
    write_json(manifest_file, manifest)
    public = [value for value in values if value.get("data_type") != "password"]
    if package.get("target") == "cloud":
        candidates = [root / "deployment" / "cloud" / "profiles" / environment / "configmap.yaml", root / "deployment" / "cloud" / "configmap.yaml"]
        descriptor = next((path for path in candidates if path.exists()), None)
        if descriptor:
            text = descriptor.read_text(encoding="utf-8")
            prefix = text.split("\ndata:\n", 1)[0]
            data = "\n".join(f'  {value["key"]}: {json.dumps(str(value.get("value", "")))}' for value in public) or "  {}"
            descriptor.write_text(prefix + "\ndata:\n" + data + "\n", encoding="utf-8")
    else:
        candidates = [root / "deployment" / "on-prem" / "profiles" / environment / "environment.properties", root / "deployment" / "on-prem" / "environment.properties"]
        descriptor = next((path for path in candidates if path.exists()), None)
        if descriptor: descriptor.write_text("\n".join(f'{value["key"]}={value.get("value", "")}' for value in public) + "\n", encoding="utf-8")

@app.get("/api/packages/{artifact}/{version}/tasks")
def get_package_tasks(artifact: str, version: str, request: Request, teamId: str | None = None):
    return package_task_inventory(package_for_request(artifact, version, request, teamId))

@app.get("/api/packages/{artifact}/{version}/environments/{environment}")
def export_environment_profile(artifact: str, version: str, environment: str, request: Request, teamId: str | None = None):
    package = package_for_request(artifact, version, request, teamId)
    if environment not in package_environments(package): raise HTTPException(404, "Environment profile not found")
    profile = stored_package_path(package) / "environments" / f"{safe(environment)}.json"
    if not profile.exists(): raise HTTPException(404, "Environment profile artifact not found")
    return Response(profile.read_bytes(), media_type="application/json", headers={"Content-Disposition":f'attachment; filename="{safe(package.get("artifact", artifact))}-{safe(environment)}.json"'})

@app.put("/api/packages/{artifact}/{version}/environments/{environment}")
def update_environment_profile(artifact: str, version: str, environment: str, payload: ProfileUpdateRequest, request: Request, teamId: str | None = None):
    require_application_manager(request)
    package = package_for_request(artifact, version, request, teamId)
    if environment not in package_environments(package): raise HTTPException(404, "Environment profile not found")
    values = public_profile_values(payload.values)
    new_required = sorted(value["key"] for value in values if value.get("data_type") == "password")
    affected = [item for item in read_json(DEPLOYMENTS_FILE, []) if item.get("packageId") == package["packageId"] and item.get("teamId", TECHNOLOGY_TEAM_ID) == package.get("teamId", TECHNOLOGY_TEAM_ID) and item.get("environment") == environment]
    if payload.redeploy:
        for deployment in affected:
            missing = [key for key in new_required if not deployment_secret_values(deployment["id"]).get(key)]
            if missing: raise HTTPException(422, f"Deployment {deployment['id']} requires new secret values before redeploy: {', '.join(missing)}")
    update_stored_profile(package, environment, values)
    caller, asset_team = identity(request), package.get("teamId", TECHNOLOGY_TEAM_ID)
    revision = record_revision("package", package["packageId"], "environment.update", {"environment":environment, "values":values}, actor=caller["name"], team_id=asset_team, detail=f"{len(values)} properties")
    packages = package_inventory()
    stored = next((item for item in packages if item.get("packageId") == package["packageId"] and item.get("teamId", TECHNOLOGY_TEAM_ID) == asset_team), None)
    if stored:
        stored.setdefault("secretKeysByEnvironment", {})[environment] = sorted(value["key"] for value in values if value.get("data_type") == "password")
        stored.update(status="CONFIGURED", configurationRevision=revision["revision"], updatedAt=now()); write_json(PACKAGES_FILE, packages)
    audit("environment.update", package["packageId"], detail=f"{environment} / revision {revision['revision']}", actor=caller["name"], team_id=asset_team)
    redeployed = []
    if payload.redeploy:
        deployments = read_json(DEPLOYMENTS_FILE, [])
        for item in deployments:
            if item.get("packageId") != package["packageId"] or item.get("teamId", TECHNOLOGY_TEAM_ID) != asset_team or item.get("environment") != environment: continue
            item["requiredSecrets"] = new_required
            if item.get("state") != "RUNNING": continue
            if (item.get("dataPlaneId") or item.get("machine")) == "localhost": terminate_instances(item); start_instances(item)
            item.update(updatedAt=now(), message=f"Environment revision {revision['revision']} redeployed")
            redeployed.append(item["id"])
        write_json(DEPLOYMENTS_FILE, deployments)
    return {"packageId":package["packageId"], "environment":environment, "revision":revision["revision"], "redeployed":redeployed, "values":values}

@app.put("/api/deployments/{deployment_id}/configuration")
def update_deployment_configuration(deployment_id: str, payload: DeploymentConfigurationRequest, request: Request):
    require_application_manager(request)
    deployments = read_json(DEPLOYMENTS_FILE, []); item = next((value for value in deployments if value.get("id") == deployment_id), None)
    if not item: raise HTTPException(404, "Deployment not found")
    require_application_write(request, item)
    package = next((value for value in package_inventory() if value.get("packageId") == item.get("packageId") and value.get("teamId", TECHNOLOGY_TEAM_ID) == item.get("teamId", TECHNOLOGY_TEAM_ID)), None)
    if not package: raise HTTPException(404, "Deployment package not found")
    environment = payload.environment or item["environment"]
    if environment not in package_environments(package): raise HTTPException(400, "Environment is not available in this package")
    required = required_secrets(package, environment)
    unknown = set(payload.secrets) - set(required)
    if unknown: raise HTTPException(400, f"Unknown secret keys: {', '.join(sorted(unknown))}")
    secret_values = deployment_secret_values(deployment_id); secret_values.update(payload.secrets)
    missing = [key for key in required if not secret_values.get(key)]
    if missing: raise HTTPException(422, f"Required secrets are missing: {', '.join(missing)}")
    was_running = item.get("state") == "RUNNING"
    if was_running and payload.redeploy and (item.get("dataPlaneId") or item.get("machine")) == "localhost": terminate_instances(item)
    item.update(environment=environment, requiredSecrets=required, updatedAt=now())
    if payload.instances is not None: item["desiredInstances"] = payload.instances
    if payload.healthCheckEnabled is not None: item["healthCheckEnabled"] = payload.healthCheckEnabled
    save_deployment_secrets(deployment_id, secret_values)
    if was_running and payload.redeploy and (item.get("dataPlaneId") or item.get("machine")) == "localhost": start_instances(item)
    item["message"] = "Configuration saved and redeployed" if payload.redeploy else "Configuration saved; redeploy pending"
    write_json(DEPLOYMENTS_FILE, deployments)
    caller = identity(request); snapshot = {"environment":environment, "instances":item["desiredInstances"], "healthCheckEnabled":item.get("healthCheckEnabled", True), "configuredSecretKeys":sorted(secret_values)}
    revision = record_revision("deployment", deployment_id, "deployment.configuration", snapshot, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID), detail=item["message"])
    audit("deployment.configuration", deployment_id, detail=f"revision {revision['revision']}", actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID))
    return {**item, "health":deployment_health(item), "revision":revision["revision"]}

@app.post("/api/deployments/{deployment_id}/starters/{task_id}/{action}")
def starter_lifecycle(deployment_id: str, task_id: str, action: str, request: Request):
    if action not in {"start", "stop"}: raise HTTPException(400, "Starter action must be start or stop")
    require_application_manager(request)
    deployments = read_json(DEPLOYMENTS_FILE, []); item = next((value for value in deployments if value.get("id") == deployment_id), None)
    if not item: raise HTTPException(404, "Deployment not found")
    require_application_write(request, item)
    package = next((value for value in package_inventory() if value.get("packageId") == item.get("packageId") and value.get("teamId", TECHNOLOGY_TEAM_ID) == item.get("teamId", TECHNOLOGY_TEAM_ID)), None)
    if not package or task_id not in (package.get("starterTaskIds") or []): raise HTTPException(404, "Starter Task not found in this deployment package")
    item.setdefault("starterStates", {})[task_id] = "STARTED" if action == "start" else "STOPPED"
    if item.get("state") == "RUNNING" and (item.get("dataPlaneId") or item.get("machine")) == "localhost": terminate_instances(item); start_instances(item)
    item.update(updatedAt=now(), message=f"Starter {task_id} {action}ed")
    write_json(DEPLOYMENTS_FILE, deployments)
    caller = identity(request); record_revision("deployment", deployment_id, f"starter.{action}", {"starterStates":item["starterStates"]}, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID), detail=task_id)
    audit(f"starter.{action}", deployment_id, detail=task_id, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID))
    return {"deploymentId":deployment_id, "starterTaskId":task_id, "state":item["starterStates"][task_id], "starterStates":item["starterStates"]}

@app.get("/api/deployments/{deployment_id}/health")
def get_deployment_health(deployment_id: str, request: Request):
    item = next((value for value in deployment_inventory() if value.get("id") == deployment_id), None)
    if not item: raise HTTPException(404, "Deployment not found")
    require_asset(request, item); return deployment_health(item)

@app.get("/api/revisions/{asset_type}/{asset_id}")
def revision_history(asset_type: str, asset_id: str, request: Request):
    if asset_type not in {"package", "deployment"}: raise HTTPException(400, "Unsupported revision asset type")
    values = [value for value in read_json(REVISIONS_FILE, []) if value.get("assetType") == asset_type and value.get("assetId") == asset_id]
    visible = visible_assets(request, values)
    return list(reversed(visible))


@app.get("/api/deployments/{deployment_id}/logs")
def deployment_logs(deployment_id: str, request: Request, lines: int = 300):
    item = get_deployment(deployment_id, request)
    output = []
    for entry in item.get("remoteLogs", []):
        if isinstance(entry, dict): output.append({"instanceId": entry.get("instanceId", "remote"), "lines": entry.get("lines", [])[-min(max(lines, 1), 2000):]})
    for instance in item.get("instances", []):
        log_path = Path(instance.get("log", ""))
        if log_path.exists() and LOGS_DIR in log_path.resolve().parents:
            output.append({"instanceId": instance["id"], "lines": log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-min(max(lines, 1), 2000):]})
    return output


def audit_inventory(limit: int = 250):
    return list(reversed(read_json(AUDIT_FILE, [])[-min(max(limit, 1), 1000):]))


@app.get("/api/audit")
def list_audit(request: Request, limit: int = 250):
    require_technology(request)
    return audit_inventory(limit)


@app.get("/api/monitoring")
def monitoring(request: Request):
    require_technology(request)
    deployments, machines = deployment_inventory(), data_plane_inventory()
    states: dict[str, int] = {}
    for item in deployments:
        states[item.get("state", "UNKNOWN")] = states.get(item.get("state", "UNKNOWN"), 0) + 1
    return {"time": now(), "deploymentStates": states, "runningInstances": sum(1 for item in deployments for instance in item.get("instances", []) if instance.get("state") == "RUNNING"), "machines": {"total": len(machines), "online": len([item for item in machines if item.get("status") == "ONLINE"])}, "dataPlanes": {"total": len(machines), "running": len([item for item in machines if item.get("status") == "ONLINE"]), "warning":len([item for item in machines if item.get("status") == "REGISTERED"]), "critical":len([item for item in machines if item.get("status") == "OFFLINE"])}, "runtimeAdapterConfigured": bool(RUNTIME_COMMAND), "recentFailures": [item for item in deployments if item.get("state") == "FAILED"][-20:]}


@app.get("/api/observability")
def observability(request: Request, dataPlaneId: str | None = None, teamId: str | None = None):
    if teamId: requested_asset_team(request, teamId)
    caller = identity(request); deployments = [item for item in visible_assets(request, deployment_inventory(), teamId) if not dataPlaneId or (item.get("dataPlaneId") or item.get("machine")) == dataPlaneId]
    visible_plane_ids = {(item.get("dataPlaneId") or item.get("machine")) for item in deployments}
    planes = [item for item in data_plane_inventory() if (caller.get("teamId") == TECHNOLOGY_TEAM_ID or item.get("id") in visible_plane_ids) and (not dataPlaneId or item.get("id") == dataPlaneId)]
    running = [instance for item in deployments for instance in item.get("instances", []) if instance.get("state") == "RUNNING"]
    total = int(REQUEST_METRICS["total"]) if caller.get("teamId") == TECHNOLOGY_TEAM_ID else 0; errors = int(REQUEST_METRICS["errors"]) if caller.get("teamId") == TECHNOLOGY_TEAM_ID else 0
    return {"time":now(), "filter":{"dataPlaneId":dataPlaneId or "*", "teamId":teamId or caller.get("teamId")}, "summary":{"applications":len({item.get('application') for item in deployments}), "deployments":len(deployments), "runningInstances":len(running), "requestCount":total, "errorCount":errors, "errorRate":round(errors / total * 100, 2) if total else 0}, "dataPlanes":[{"id":item.get("id"), "name":item.get("name"), "status":item.get("status"), "tunnelStatus":item.get("tunnelStatus"), "cpuPercent":item.get("cpuPercent"), "memoryPercent":item.get("memoryPercent"), "memoryUsedBytes":item.get("memoryUsedBytes"), "memoryAvailableBytes":item.get("memoryAvailableBytes"), "memoryTotalBytes":item.get("memoryTotalBytes"), "diskPercent":item.get("diskPercent"), "diskFreeBytes":item.get("diskFreeBytes"), "loadAverage":item.get("loadAverage"), "processCount":item.get("processCount"), "telemetry":item.get("telemetry", {}), "lastHeartbeat":item.get("lastHeartbeat")} for item in planes], "applications":[{"id":item.get("id"), "name":item.get("application"), "state":item.get("state"), "dataPlaneId":item.get("dataPlaneId") or item.get("machine"), "namespace":item.get("namespace", "default"), "instances":len(item.get("instances", [])), "lastError":item.get("lastError")} for item in deployments], "requests":{"total":total, "errors":errors, "routes":REQUEST_METRICS["routes"] if caller.get("teamId") == TECHNOLOGY_TEAM_ID else {}, "recentErrors":REQUEST_METRICS["recentErrors"] if caller.get("teamId") == TECHNOLOGY_TEAM_ID else []}, "resources":resource_inventory(dataPlaneId) if caller.get("teamId") == TECHNOLOGY_TEAM_ID else []}


@app.get("/api/operator/runtime-tree")
def runtime_tree(request: Request):
    caller = identity(request); deployments = visible_assets(request, deployment_inventory())
    planes = data_plane_inventory(); capabilities = read_json(CAPABILITIES_FILE, [])
    result = []
    for plane in planes:
        if caller.get("teamId") != TECHNOLOGY_TEAM_ID and not any((item.get("dataPlaneId") or item.get("machine")) == plane.get("id") for item in deployments): continue
        plane_caps = [dict(item) for item in capabilities if item.get("dataPlaneId") == plane.get("id")]
        plane_apps = [item for item in deployments if (item.get("dataPlaneId") or item.get("machine")) == plane.get("id")]
        result.append({"id":plane.get("id"), "name":plane.get("name"), "status":plane.get("status"), "capabilities":[{**cap, "applications":[{**item, "instances":[{**instance, "taskId":(read_json(PROCESS_STATES_FILE, {}).get(instance.get("id"), {}) or {}).get("taskId", "runtime")} for instance in item.get("instances", [])]} for item in plane_apps if item.get("capabilityId") == cap.get("id")]} for cap in plane_caps]})
    return {"time":now(), "dataPlanes":result}


@app.get("/api/operator/process-instances")
def process_instances(request: Request, deploymentId: str | None = None):
    deployments = visible_assets(request, deployment_inventory())
    if deploymentId: deployments = [item for item in deployments if item.get("id") == deploymentId]
    return operator_process_instances(deployments)


@app.get("/api/operator/metrics")
def operator_metrics(request: Request):
    deployments = visible_assets(request, deployment_inventory()); instances = operator_process_instances(deployments)
    completed = [item for item in instances if item.get("status") in {"COMPLETED", "SUCCESS"}]
    failed = [item for item in instances if item.get("status") in {"FAILED", "FAULTED"}]
    planes = data_plane_inventory()
    task_counts: dict[str, dict[str, int]] = {}; activity_counts: dict[str, dict[str, int]] = {}
    for plane in planes:
        execution = (plane.get("telemetry") or {}).get("execution") or {}
        for kind, target in (("tasks", task_counts), ("activities", activity_counts)):
            for item in execution.get(kind, []) if isinstance(execution.get(kind), list) else []:
                name = str(item.get("name") or "unknown")
                bucket = target.setdefault(name, {"total": 0, "completed": 0, "failed": 0})
                for key in bucket: bucket[key] += int(item.get(key) or 0)
    compact = lambda values: [{"name":name, **count} for name, count in sorted(values.items(), key=lambda value: (-value[1]["total"], value[0]))[:12]]
    return {"time":now(), "applications":len({item.get("application") for item in deployments}), "instances":len(instances), "running":len([item for item in instances if item.get("status") == "RUNNING"]), "completed":len(completed), "failed":len(failed), "successRate":round(len(completed) / (len(completed) + len(failed)) * 100, 2) if completed or failed else 0, "requests":REQUEST_METRICS["total"] if identity(request).get("teamId") == TECHNOLOGY_TEAM_ID else 0, "dataPlanes":[{"id":item.get("id"), "name":item.get("name"), "status":item.get("status"), "system":(item.get("telemetry") or {}).get("system", {})} for item in planes], "tasks":compact(task_counts), "activities":compact(activity_counts)}


@app.get("/api/operator/commands")
def operator_commands(request: Request, limit: int = 250):
    return audit_inventory(limit) if identity(request).get("teamId") == TECHNOLOGY_TEAM_ID else [item for item in audit_inventory(limit) if item.get("teamId") == identity(request).get("teamId")]


@app.get("/api/alerts")
def list_alerts(request: Request):
    require_technology(request); values = read_json(ALERTS_FILE, [])
    planes, deployments = data_plane_inventory(), deployment_inventory()
    for alert in values:
        if not alert.get("enabled", True): alert["state"] = "DISABLED"; continue
        kind = alert.get("type"); threshold = float(alert.get("threshold", 0)); value = 0
        if kind == "offline-data-plane": value = len([x for x in planes if x.get("status") != "ONLINE"])
        elif kind == "failed-deployment": value = len([x for x in deployments if x.get("state") == "FAILED"])
        elif kind == "unhealthy-application": value = len([x for x in deployments if x.get("state") == "RUNNING" and deployment_health(x).get("status") not in {"HEALTHY", "UNKNOWN"}])
        alert.update(value=value, state="FIRING" if value >= threshold else "OK", evaluatedAt=now())
    write_json(ALERTS_FILE, values); return values


@app.post("/api/alerts")
def create_alert(payload: dict[str, Any], request: Request):
    require_technology(request)
    if payload.get("type") not in {"offline-data-plane", "failed-deployment", "unhealthy-application", "resource-threshold"}: raise HTTPException(400, "Unsupported alert type")
    values = read_json(ALERTS_FILE, []); item = {"id":str(uuid4()), "name":str(payload.get("name") or payload["type"]), "type":payload["type"], "threshold":float(payload.get("threshold", 1)), "enabled":bool(payload.get("enabled", True)), "createdAt":now()}; values.append(item); write_json(ALERTS_FILE, values); audit("alert.create", item["id"], detail=item["name"]); return item


@app.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: str, request: Request):
    require_technology(request); values = read_json(ALERTS_FILE, []); updated = [item for item in values if item.get("id") != alert_id]
    if len(updated) == len(values): raise HTTPException(404, "Alert not found")
    write_json(ALERTS_FILE, updated); audit("alert.delete", alert_id); return {"deleted":True, "id":alert_id}


@app.post("/api/deployments/{deployment_id}/instances/{instance_id}/{action}")
def instance_action(deployment_id: str, instance_id: str, action: str, request: Request):
    if action not in {"start", "stop", "restart", "suspend", "resume"}: raise HTTPException(400, "Unsupported instance action")
    require_application_manager(request); deployments = read_json(DEPLOYMENTS_FILE, []); item = next((value for value in deployments if value.get("id") == deployment_id), None)
    if not item: raise HTTPException(404, "Deployment not found")
    require_application_write(request, item); instance = next((value for value in item.get("instances", []) if value.get("id") == instance_id), None)
    if not instance: raise HTTPException(404, "Runtime instance not found")
    states = read_json(PROCESS_STATES_FILE, {}); current = states.get(instance_id, {}) if isinstance(states, dict) else {}
    if action in {"suspend", "resume"}:
        current["status"] = "SUSPENDED" if action == "suspend" else "RUNNING"; states[instance_id] = current; write_json(PROCESS_STATES_FILE, states)
    elif (item.get("dataPlaneId") or item.get("machine")) != "localhost": raise HTTPException(409, "Instance-level control requires a connected remote agent implementation")
    else:
        process = PROCESS_HANDLES.get(instance_id)
        if action == "stop" and process and process.poll() is None: process.terminate(); instance["state"] = "STOPPED"
        elif action == "start": item["state"] = "RUNNING"; start_instances(item)
        elif action == "restart": terminate_instances(item); start_instances(item); item["state"] = "RUNNING"
        write_json(DEPLOYMENTS_FILE, deployments)
    audit(f"instance.{action}", instance_id); return {"deploymentId":deployment_id, "instanceId":instance_id, "action":action, "state":instance.get("state", current.get("status"))}


@app.post("/api/deployments/bulk")
def bulk_deployment_action(payload: dict[str, Any], request: Request):
    action = payload.get("action"); ids = payload.get("deploymentIds") or []
    if action not in {"start", "stop", "restart", "undeploy"} or not isinstance(ids, list) or not ids: raise HTTPException(400, "Provide deploymentIds and a supported action")
    results = []
    for deployment_id in ids:
        try: results.append(lifecycle(str(deployment_id), action, request))
        except HTTPException as error: results.append({"id":deployment_id, "error":error.detail})
    return {"action":action, "results":results}


@app.get("/api/deployments/{deployment_id}/compare")
def compare_deployment(deployment_id: str, request: Request, revision: int | None = None):
    item = get_deployment(deployment_id, request); revisions = [x for x in read_json(REVISIONS_FILE, []) if x.get("assetType") == "deployment" and x.get("assetId") == deployment_id]
    target = next((x for x in revisions if revision is not None and int(x.get("revision", 0)) == revision), None) if revision is not None else (revisions[-1] if revisions else None)
    current = {"environment":item.get("environment"), "instances":item.get("desiredInstances"), "healthCheckEnabled":item.get("healthCheckEnabled", True), "starterStates":item.get("starterStates", {})}; previous = target.get("snapshot", {}) if target else {}
    return {"deploymentId":deployment_id, "current":current, "revision":target, "changes":{key:{"from":previous.get(key), "to":value} for key,value in current.items() if previous.get(key) != value}}


@app.get("/api/deployments/{deployment_id}/backup")
def backup_deployment(deployment_id: str, request: Request):
    item = get_deployment(deployment_id, request); root = deployment_package_path(item)
    if not root.exists(): raise HTTPException(404, "Deployment package is not available")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file(): archive.write(path, path.relative_to(root).as_posix())
        archive.writestr("deployment-state.json", json.dumps({"deploymentId":item.get("id"), "packageId":item.get("packageId"), "environment":item.get("environment"), "dataPlaneId":item.get("dataPlaneId"), "namespace":item.get("namespace"), "desiredInstances":item.get("desiredInstances"), "healthCheckEnabled":item.get("healthCheckEnabled", True)}, indent=2))
    return Response(buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition":f"attachment; filename={safe(item.get('application', deployment_id))}-backup.zip"})


@app.post("/api/deployments/{deployment_id}/restore")
async def restore_deployment(deployment_id: str, request: Request, file: UploadFile = File(...)):
    require_application_manager(request); deployments = read_json(DEPLOYMENTS_FILE, []); item = next((value for value in deployments if value.get("id") == deployment_id), None)
    if not item: raise HTTPException(404, "Deployment not found")
    require_application_write(request, item)
    if item.get("state") not in {"UNDEPLOYED", "STOPPED", "FAILED", "DEPLOYED"}: raise HTTPException(409, "Stop or undeploy the application before restoring it")
    body = await file.read()
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive: state = json.loads(archive.read("deployment-state.json"))
    except (KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error: raise HTTPException(400, "The backup archive is invalid or missing deployment-state.json") from error
    if state.get("packageId") and state.get("packageId") != item.get("packageId"): raise HTTPException(400, "Backup belongs to a different application package")
    for key in ("environment", "dataPlaneId", "namespace", "desiredInstances", "healthCheckEnabled"):
        if key in state: item[key] = state[key]
    item["machine"] = item.get("dataPlaneId") or item.get("machine"); item.update(state="DEPLOYED", instances=[], updatedAt=now(), lastError=None, message="Deployment configuration restored from backup")
    write_json(DEPLOYMENTS_FILE, deployments); caller = identity(request); audit("deployment.restore", deployment_id, detail=file.filename or "backup", actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID)); record_revision("deployment", deployment_id, "deployment.restore", {"environment":item.get("environment"), "dataPlaneId":item.get("dataPlaneId"), "namespace":item.get("namespace"), "instances":item.get("desiredInstances")}, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID), detail="Restored deployment backup"); return item


@app.post("/api/deployments/{deployment_id}/move")
def move_deployment(deployment_id: str, payload: dict[str, Any], request: Request):
    require_application_manager(request); deployments = read_json(DEPLOYMENTS_FILE, []); item = next((value for value in deployments if value.get("id") == deployment_id), None)
    if not item: raise HTTPException(404, "Deployment not found")
    require_application_write(request, item)
    plane_id, namespace = str(payload.get("dataPlaneId") or ""), str(payload.get("namespace") or item.get("namespace", "default"))
    plane = next((value for value in data_plane_inventory() if value.get("id") == plane_id), None)
    if not plane: raise HTTPException(404, "Data plane not found")
    if namespace not in plane.get("namespaces", []): raise HTTPException(400, "Namespace is not registered on the selected data plane")
    capability = next((value for value in read_json(CAPABILITIES_FILE, []) if value.get("id") == payload.get("capabilityId") and value.get("dataPlaneId") == plane_id and value.get("namespace") == namespace and value.get("type") == "integration-runtime"), None)
    if not capability: raise HTTPException(409, "Provision an Integration Runtime capability in the target data plane and namespace first")
    if item.get("state") == "RUNNING": raise HTTPException(409, "Stop or undeploy the application before moving it")
    item.update(dataPlaneId=plane_id, machine=plane_id, namespace=namespace, capabilityId=capability["id"], updatedAt=now(), message="Deployment target updated; start to activate the new target")
    write_json(DEPLOYMENTS_FILE, deployments); caller = identity(request); audit("deployment.move", deployment_id, detail=f"{plane_id} / {namespace}", actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID)); record_revision("deployment", deployment_id, "deployment.move", {"dataPlaneId":plane_id, "namespace":namespace, "capabilityId":capability["id"]}, actor=caller["name"], team_id=item.get("teamId", TECHNOLOGY_TEAM_ID), detail=item["message"]); return item


static_candidates = [Path(os.environ["FABRIC_ADMIN_WEB"]) if os.environ.get("FABRIC_ADMIN_WEB") else None, Path(getattr(sys, "_MEIPASS", "")) / "web" if getattr(sys, "_MEIPASS", None) else None, Path(__file__).parents[1] / "web"]
WEB_DIR = next((candidate for candidate in static_candidates if candidate and candidate.exists()), None)
if WEB_DIR:
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="administrator")
