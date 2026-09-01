from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PUBSUB_SCOPE = "https://www.googleapis.com/auth/pubsub"
SERVICE_ACCOUNT_FIELDS = ("type", "project_id", "client_email", "private_key", "token_uri")


def _credentials_from_info(info: dict[str, Any]):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(info, scopes=[PUBSUB_SCOPE])


def _service_account_info(config: dict[str, Any]) -> dict[str, Any] | None:
    raw = config.get("serviceAccountJson") or config.get("credentialsJson")
    if raw:
        if isinstance(raw, dict):
            info = dict(raw)
        else:
            try:
                info = json.loads(str(raw))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Service account JSON is invalid: {exc.msg} at line {exc.lineno}, column {exc.colno}"
                ) from exc
        if not isinstance(info, dict):
            raise ValueError("Service account JSON must contain one JSON object")
        return info

    # Backward compatibility for projects created before inline JSON credentials.
    credentials_file = str(config.get("credentialsFile") or "").strip()
    if credentials_file:
        path = Path(credentials_file).expanduser()
        if not path.is_file():
            raise ValueError(f"Service account JSON file was not found: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read service account JSON file: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("Service account JSON file must contain one JSON object")
        return value
    return None


def client_configuration(config: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Build Pub/Sub client kwargs and resolve the effective Google project ID."""
    auth_type = str(config.get("authenticationType") or "Service Account JSON").strip().lower()
    emulator_host = str(config.get("emulatorHost") or "").strip()
    info = _service_account_info(config)
    kwargs: dict[str, Any] = {}

    if emulator_host or auth_type == "emulator":
        from google.auth.credentials import AnonymousCredentials

        kwargs["credentials"] = AnonymousCredentials()
        kwargs["client_options"] = {"api_endpoint": emulator_host or "localhost:8085"}
    elif info is not None:
        missing = [key for key in SERVICE_ACCOUNT_FIELDS if not str(info.get(key) or "").strip()]
        if info.get("type") != "service_account":
            raise ValueError("Credential JSON type must be 'service_account'")
        if missing:
            raise ValueError(f"Service account JSON is missing: {', '.join(missing)}")
        kwargs["credentials"] = _credentials_from_info(info)
        endpoint = str(config.get("endpoint") or "").strip()
        if endpoint:
            kwargs["client_options"] = {"api_endpoint": endpoint}
    elif auth_type not in {"application default credentials", "adc"}:
        raise ValueError("Service account JSON is required for Google Pub/Sub authentication")
    else:
        endpoint = str(config.get("endpoint") or "").strip()
        if endpoint:
            kwargs["client_options"] = {"api_endpoint": endpoint}

    project_id = str((info or {}).get("project_id") or config.get("projectId") or "").strip()
    if not project_id:
        raise ValueError(
            "GCP project ID is required or must be present as project_id in the service account JSON"
        )
    return kwargs, project_id


def credential_summary(config: dict[str, Any]) -> dict[str, str]:
    """Return safe parsed identity details without exposing the private key."""
    info = _service_account_info(config)
    return {
        "projectId": str((info or {}).get("project_id") or config.get("projectId") or ""),
        "clientEmail": str((info or {}).get("client_email") or ""),
    }
