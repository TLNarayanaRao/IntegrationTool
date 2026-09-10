"""Standalone Integration Fabric deployment worker.

This entry point is intentionally separate from ``run_sidecar.py``.  The
sidecar serves Studio's HTTP API; this worker executes one packaged
application under Control Plane lifecycle management.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def load_project(application: Path):
    from app.models import Project

    project_file = application / "project.json"
    if not project_file.is_file():
        raise FileNotFoundError(f"Packaged application descriptor not found: {project_file}")
    project = Project.model_validate(json.loads(project_file.read_text(encoding="utf-8")))
    return project


async def run_deployment(application: Path, environment: str) -> None:
    from app.main import (
        _continuous_event_loop,
        _continuous_sap_event_loop,
        _environment_values,
        _event_subscription,
        _publish_runtime_state,
        append_project_logs as persist_logs,
        effective_event_activities,
        runtime,
    )
    import app.main as runtime_api

    project = load_project(application)
    if environment not in project.properties:
        raise ValueError(f"Environment {environment!r} is not present in the packaged application")
    project.active_environment = environment

    # Secrets are injected by the Control Plane into the worker environment.
    # Overlay them onto the sanitized package profile without writing them to
    # disk or altering the package.
    for prop in project.properties[environment]:
        if prop.key in os.environ:
            prop.value = os.environ[prop.key]

    # The Control Plane redirects stdout/stderr to the per-instance log. Also
    # persist structured records using the same bounded logger as Studio and
    # mirror them to stdout so deployment logs work for packaged workers.
    def record_logs(project_id, project_name, entries, configured_directory=""):
        persist_logs(project_id, project_name, entries, configured_directory)
        for entry in entries or []:
            print(json.dumps({"projectId": project_id, "project": project_name, **entry}, ensure_ascii=False, default=str), flush=True)

    runtime_api.append_project_logs = record_logs
    resources = {resource.id: resource for resource in project.resources}
    tasks = [task for task in project.tasks if task.kind == "starter"]
    enabled = os.environ.get("FABRIC_ENABLED_STARTERS", "").strip()
    if enabled:
        try:
            enabled_ids = set(json.loads(enabled))
            tasks = [task for task in tasks if task.id in enabled_ids]
        except (TypeError, ValueError, json.JSONDecodeError):
            print(json.dumps({"level": "WARNING", "kind": "configuration", "message": "Ignoring invalid FABRIC_ENABLED_STARTERS"}), flush=True)
    if not tasks:
        raise ValueError("The packaged application has no enabled Starter Tasks")

    startup = {"time": runtime_api.log_timestamp(), "level": "INFO", "kind": "lifecycle", "message": f"Deployment worker started: {project.name}", "environment": environment}
    record_logs(project.id, project.name, [startup], str(_environment_values(project, environment).get("runtime.logDirectory") or ""))

    async def run_one(task):
        events = effective_event_activities(task.activities, task.transitions)
        event = events[0] if events and events[0].type != "start" else None
        if event is not None:
            subscription = _event_subscription(project, task, event, environment)
            print(json.dumps({"projectId": project.id, "project": project.name, "level": "INFO", "kind": "endpoint", "message": f"{event.name} listener ready", "subscription": subscription}, ensure_ascii=False, default=str), flush=True)
            if event.type == "sap":
                await _continuous_sap_event_loop(project, task, event, environment)
            else:
                await _continuous_event_loop(project, task, event, environment)
            return
        result = await runtime.run(task, {}, resources, _environment_values(project, environment), project=project)
        record_logs(project.id, project.name, result.logs, str(_environment_values(project, environment).get("runtime.logDirectory") or ""))
        if result.status != "completed":
            raise RuntimeError(f"Starter Task {task.name} finished with status {result.status}")

    await asyncio.gather(*(run_one(task) for task in tasks))
    # A one-shot application remains managed until Control Plane stops it.
    await asyncio.Event().wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a packaged Integration Fabric application")
    parser.add_argument("--application", required=True, help="Path to the packaged application directory")
    parser.add_argument("--environment", "--env", dest="environment", default=None)
    # Accept the environment as a positional fallback as well. This keeps
    # deployments compatible with Windows command-line wrappers that can
    # separate a quoted option value while CreateProcess parses the command.
    parser.add_argument("environment_positional", nargs="?")
    args = parser.parse_args()
    environment = args.environment or args.environment_positional or os.environ.get("FABRIC_ENVIRONMENT", "local")
    try:
        asyncio.run(run_deployment(Path(args.application).resolve(), environment))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(json.dumps({"level": "ERROR", "kind": "runtime", "message": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
