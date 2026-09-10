from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PUBSUB_SCOPE = "https://www.googleapis.com/auth/pubsub"
SERVICE_ACCOUNT_FIELDS = ("type", "project_id", "client_email", "private_key", "token_uri")


def _credentials_from_info(info: dict[str, Any]):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(info, scopes=[PUBSUB_SCOPE])


def _credentials_with_ca(credentials, ca_file: str):
    """Make service-account token refreshes trust the configured corporate CA."""
    from google.auth.transport.requests import Request
    import requests

    class CACredentials(type(credentials)):
        def __init__(self, source, certificate_file):
            self.__dict__.update(source.__dict__)
            self._integration_fabric_ca_file = certificate_file

        def refresh(self, request):
            session = requests.Session()
            session.verify = self._integration_fabric_ca_file
            return super().refresh(Request(session=session))

    return CACredentials(credentials, ca_file)


def _service_account_info(config: dict[str, Any]) -> dict[str, Any] | None:
    raw = config.get("serviceAccountJson") or config.get("credentialsJson")
    if raw:
        if isinstance(raw, dict):
            info = dict(raw)
        else:
            text = str(raw).strip()
            # A property binding may resolve the credential field to a file
            # path.  Accept that form as well as the existing inline JSON
            # form, while keeping the full service-account document intact.
            if not text.startswith("{"):
                candidate = Path(text).expanduser()
                if candidate.is_file():
                    try:
                        info = json.loads(candidate.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        raise ValueError(f"Unable to read service account JSON file: {exc}") from exc
                else:
                    raise ValueError(f"Service account JSON file was not found: {candidate}")
            else:
                try:
                    info = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Service account JSON is invalid: {exc.msg} at line {exc.lineno}, column {exc.colno}"
                    ) from exc
        if not isinstance(info, dict):
            raise ValueError("Service account JSON must contain one JSON object")
        return info

    # Backward compatibility for projects created before inline JSON credentials.
    credentials_file = str(config.get("credentialsFile") or config.get("serviceAccountJsonFile") or "").strip()
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

    # Corporate TLS inspection commonly replaces Google's certificate with a
    # certificate signed by an internal CA.  Pass that CA to gRPC explicitly;
    # do not disable certificate verification.
    ca_file = str(config.get("caCertificateFile") or config.get("certificateAuthorityFile") or "").strip()
    if ca_file:
        ca_path = Path(ca_file).expanduser()
        if not ca_path.is_file():
            raise ValueError(f"Pub/Sub CA certificate file was not found: {ca_path}")
        try:
            import grpc
            # Keep this private marker out of the public client constructor;
            # the generated Publisher/Subscriber clients accept the TLS
            # credentials through their transport, not as a direct keyword.
            kwargs["_ssl_channel_credentials"] = grpc.ssl_channel_credentials(root_certificates=ca_path.read_bytes())
            kwargs["_ca_certificate_file"] = str(ca_path.resolve())
        except OSError as exc:
            raise ValueError(f"Unable to read Pub/Sub CA certificate file: {exc}") from exc

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
        credentials = _credentials_from_info(info)
        if ca_file:
            credentials = _credentials_with_ca(credentials, ca_file)
        kwargs["credentials"] = credentials
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


def create_client(client_class, config: dict[str, Any]):
    """Create a Pub/Sub client, including an optional corporate CA transport."""
    kwargs, _ = client_configuration(config)
    ssl_credentials = kwargs.pop("_ssl_channel_credentials", None)
    kwargs.pop("_ca_certificate_file", None)
    if ssl_credentials is None:
        return client_class(**kwargs)
    from google.pubsub_v1.services.publisher.transports import PublisherGrpcTransport
    from google.pubsub_v1.services.subscriber.transports import SubscriberGrpcTransport

    endpoint = str((kwargs.get("client_options") or {}).get("api_endpoint") or "pubsub.googleapis.com")
    endpoint = endpoint.removeprefix("https://").removeprefix("http://")
    transport_class = PublisherGrpcTransport if "Publisher" in client_class.__name__ else SubscriberGrpcTransport
    transport_kwargs = {
        "host": endpoint,
        "credentials": kwargs.get("credentials"),
        "ssl_channel_credentials": ssl_credentials,
    }
    return client_class(transport=transport_class(**transport_kwargs))


def credential_summary(config: dict[str, Any]) -> dict[str, str]:
    """Return safe parsed identity details without exposing the private key."""
    info = _service_account_info(config)
    return {
        "projectId": str((info or {}).get("project_id") or config.get("projectId") or ""),
        "clientEmail": str((info or {}).get("client_email") or ""),
    }
