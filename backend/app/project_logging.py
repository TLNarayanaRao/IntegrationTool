"""Persistent, per-project runtime logging with bounded automatic rollover."""
from __future__ import annotations

import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock

from .store import DATA_DIR, safe_component

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 4
_handlers: dict[tuple[str, str], RotatingFileHandler] = {}
_lock = RLock()


def log_settings() -> tuple[int, int]:
    max_bytes = max(1024, int(os.getenv("FABRIC_PROJECT_LOG_MAX_BYTES", DEFAULT_MAX_BYTES)))
    backups = max(1, int(os.getenv("FABRIC_PROJECT_LOG_BACKUP_COUNT", DEFAULT_BACKUP_COUNT)))
    return max_bytes, backups


def _log_component(project_id: str, project_name: str = "") -> str:
    """Use the current application name for user-facing files.

    The project ID is intentionally immutable because transitions, deployments,
    and saved Studio references depend on it.  It must not, however, leak into
    the folder and filename an operator sees after renaming an application.
    """
    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(project_name or project_id)).strip(".-")
    return safe_component(candidate or project_id)


def project_log_path(project_id: str, project_name: str = "", configured_directory: str = "") -> Path:
    configured = os.path.expandvars(str(configured_directory or "").strip())
    root = Path(configured or os.getenv("FABRIC_RUNTIME_LOG_DIR", DATA_DIR / "logs")).expanduser()
    if not root.is_absolute():
        root = DATA_DIR / root
    root = root.resolve()
    safe = _log_component(project_id, project_name)
    target = (root / safe / f"{safe}.log").resolve()
    if target.parent.parent != root:
        raise ValueError("Invalid project log path")
    return target


def _handler(project_id: str, project_name: str = "", configured_directory: str = "") -> RotatingFileHandler:
    with _lock:
        path = project_log_path(project_id, project_name, configured_directory)
        cache_key = (project_id, str(path))
        existing = _handlers.get(cache_key)
        if existing:
            return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        max_bytes, backups = log_settings()
        handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8", delay=True)
        handler.setFormatter(logging.Formatter("%(message)s"))
        _handlers[cache_key] = handler
        return handler


def append_project_logs(project_id: str, project_name: str, entries: list[dict], configured_directory: str = "") -> None:
    if not entries:
        return
    handler = _handler(project_id, project_name, configured_directory)
    with _lock:
        for supplied in entries:
            entry = {"projectId": project_id, "project": project_name, **supplied}
            record = logging.LogRecord(
                name=f"integration-fabric.{project_id}", level=getattr(logging, str(entry.get("level", "INFO")).upper(), logging.INFO),
                pathname="", lineno=0, msg=json.dumps(entry, ensure_ascii=False, default=str, separators=(",", ":")), args=(), exc_info=None,
            )
            handler.emit(record)


def close_project_log_handlers(project_id: str | None = None) -> None:
    """Release log files, especially before deleting a project on Windows."""
    with _lock:
        for key in list(_handlers):
            if project_id is None or key[0] == project_id:
                _handlers.pop(key).close()


def read_project_logs(project_id: str, project_name: str = "", limit: int = 1000, configured_directory: str = "") -> list[dict]:
    """Read the newest records across the active log and its rolled archives."""
    path = project_log_path(project_id, project_name, configured_directory)
    _, backups = log_settings()
    paths = [path.with_name(f"{path.name}.{index}") for index in range(backups, 0, -1)] + [path]
    entries: list[dict] = []
    for candidate in paths:
        if not candidate.exists():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    entries.append({"level": "INFO", "kind": "system", "message": line})
        except OSError:
            continue
    return entries[-max(1, min(limit, 10000)):]


def project_log_info(project_id: str, project_name: str = "", configured_directory: str = "") -> dict:
    path = project_log_path(project_id, project_name, configured_directory)
    max_bytes, backups = log_settings()
    return {"path": str(path), "sizeBytes": path.stat().st_size if path.exists() else 0, "maxBytes": max_bytes, "backupCount": backups}
