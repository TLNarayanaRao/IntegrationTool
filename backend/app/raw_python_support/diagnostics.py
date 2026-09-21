"""Deployment preflight for a generated direct-Python application."""
from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any

from .requirements import CHECKS, EXTERNAL_FILES


def _module_available(name: str) -> bool:
    try: return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError): return False


def check_runtime() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for item in CHECKS:
        modules = item.get('modules') or []
        available = [name for name in modules if _module_available(name)]
        ok = bool(available) if item.get('any') else len(available) == len(modules)
        checks.append({'name': item['name'], 'kind': 'python-package', 'ok': ok,
                       'required': modules, 'found': available, 'install': item.get('install', '')})
    if any(item.get('java') for item in CHECKS):
        java = shutil.which('java')
        checks.append({'name': 'Java runtime', 'kind': 'executable', 'ok': bool(java), 'found': java,
                       'required': ['java'], 'install': 'Install or provision a Java runtime and put java on PATH.'})
    for value in EXTERNAL_FILES:
        expanded = os.path.expandvars(os.path.expanduser(value))
        checks.append({'name': value, 'kind': 'external-file', 'ok': Path(expanded).exists(),
                       'found': expanded if Path(expanded).exists() else None,
                       'required': [value], 'install': 'Provision this project artifact on the target runtime.'})
    failures = [item for item in checks if not item['ok']]
    return {'ready': not failures, 'checks': checks, 'failures': failures}

