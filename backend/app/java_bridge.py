from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class JavaBridgeError(RuntimeError):
    pass


def _application_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bridge_home() -> Path:
    override = os.environ.get("FABRIC_JAVA_BRIDGE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "java-bridge"
    return _application_root() / "java-bridge" / "build"


def _java_executable() -> Path | str:
    override = os.environ.get("FABRIC_JAVA")
    if override:
        return override
    bundled = _bridge_home() / "runtime" / "bin" / ("java.exe" if os.name == "nt" else "java")
    return bundled if bundled.exists() else "java"


def default_driver_home() -> Path:
    override = os.environ.get("FABRIC_DRIVER_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("PROGRAMDATA"):
        return Path(os.environ["PROGRAMDATA"]) / "Integration Fabric Studio" / "drivers"
    return Path.home() / ".integration-fabric" / "drivers"


def driver_directories(config: dict[str, Any], family: str) -> list[Path]:
    configured = str(config.get("driverDirectory") or "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(default_driver_home() / family)
    candidates.append(_application_root() / "drivers" / family)
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _classpath(config: dict[str, Any], family: str) -> tuple[str, list[Path]]:
    classes = _bridge_home() / "classes"
    if not classes.exists():
        raise JavaBridgeError(
            f"The Java bridge classes are missing at {classes}. Run npm run desktop:prepare or scripts/build-java-bridge.ps1."
        )
    directories = driver_directories(config, family)
    jars = sorted({jar.resolve() for directory in directories if directory.exists() for jar in directory.rglob("*.jar")})
    if not jars:
        searched = ", ".join(str(item) for item in directories)
        raise JavaBridgeError(f"No vendor JARs were found for {family}. Place the licensed driver JARs in: {searched}")
    return os.pathsep.join([str(classes), *(str(jar) for jar in jars)]), jars


def _escape_property(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")


def invoke(command: str, config: dict[str, Any], values: dict[str, Any] | None = None, *, family: str, timeout: float | None = None) -> dict[str, Any]:
    classpath, jars = _classpath(config, family)
    properties = {"command": command, **(values or {})}
    descriptor = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".properties", delete=False)
    try:
        with descriptor:
            for key, value in properties.items():
                if value is not None:
                    descriptor.write(f"{_escape_property(key)}={_escape_property(value)}\n")
        completed = subprocess.run(
            [str(_java_executable()), "-cp", classpath, "com.integrationfabric.bridge.FabricJavaBridge", descriptor.name],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout or float(config.get("timeoutSeconds") or 30) + 5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise JavaBridgeError("Java runtime is unavailable. Rebuild the desktop installer so its bundled Java runtime is included.") from exc
    except subprocess.TimeoutExpired as exc:
        raise JavaBridgeError(f"Java connector timed out after {exc.timeout:g} seconds") from exc
    finally:
        Path(descriptor.name).unlink(missing_ok=True)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        detail = completed.stderr.strip() or f"Java bridge exited with code {completed.returncode}"
        raise JavaBridgeError(detail)
    try:
        output = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise JavaBridgeError(f"Java bridge returned invalid output: {lines[-1]}") from exc
    if completed.returncode or not output.get("ok", False):
        raise JavaBridgeError(str(output.get("message") or completed.stderr.strip() or "Java connector failed"))
    output["loadedJars"] = [jar.name for jar in jars]
    return output


def jms_values(config: dict[str, Any]) -> dict[str, Any]:
    jndi = str(config.get("connectionFactoryType") or "Direct").lower() == "jndi"
    return {
        "serverUrl": config.get("serverUrl"), "username": config.get("username"), "password": config.get("password"),
        "clientId": config.get("clientId"), "connectionFactoryClass": config.get("connectionFactoryClass") or "com.tibco.tibjms.TibjmsConnectionFactory",
        "jndiEnabled": str(jndi).lower(), "connectionFactory": config.get("connectionFactory"),
        "jndiContextFactory": config.get("jndiContextFactory"), "jndiProviderUrl": config.get("jndiProviderUrl"),
        "jndiUsername": config.get("jndiUsername"), "jndiPassword": config.get("jndiPassword"),
    }


def test_jms(config: dict[str, Any]) -> dict[str, Any]:
    return invoke("jms.test", config, jms_values(config), family="jms", timeout=float(config.get("connectionTimeoutSeconds") or 30) + 5)


def execute_jms(config: dict[str, Any], operation: str, destination: str, payload: Any = None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    values = {
        **jms_values(config), "destination": destination, "topic": str(bool(options.get("topic"))).lower(),
        "jndiDestination": str(bool(options.get("jndiDestination"))).lower(), "body": payload if isinstance(payload, str) else json.dumps(payload),
        "selector": options.get("messageSelector"), "timeoutMs": options.get("receiveTimeout", 30000),
        "clientAcknowledge": str(bool(options.get("clientAcknowledge"))).lower(), "persistent": str(str(options.get("deliveryMode", "Persistent")).lower() == "persistent").lower(),
        "priority": options.get("priority", 4), "expiration": options.get("expiration", 0), "correlationId": options.get("correlationId"), "messageType": options.get("type"),
    }
    for key, value in (options.get("properties") or {}).items():
        values[f"messageProperty.{key}"] = value
    return invoke(f"jms.{operation}", config, values, family="jms", timeout=max(10, float(values["timeoutMs"] or 0) / 1000 + 10))

