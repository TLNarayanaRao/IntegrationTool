from __future__ import annotations

import json
import base64
import os
import subprocess
import sys
import tempfile
import asyncio
import queue
import threading
from pathlib import Path
from typing import Any


class JavaBridgeError(RuntimeError):
    pass


class SapJcoListener:
    def __init__(self, process: subprocess.Popen, descriptor: Path, max_pending_events: int = 32):
        self.process = process
        self.descriptor = descriptor
        # Drain the Java bridge continuously.  A large IDoc can be hundreds
        # of KB of JSON; reading stdout only after the previous IDoc finishes
        # processing can fill the Windows pipe and block JCo/SAP callbacks.
        # A bounded queue is deliberate.  Under a burst of large IDocs/RFCs
        # the Java process and SAP gateway apply backpressure instead of
        # allowing Python heap usage to grow without a limit.
        self._events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max(2, min(4096, int(max_pending_events))))
        self._command_lock = threading.Lock()
        self._closed = threading.Event()
        self._stderr_tail: queue.Queue[str] = queue.Queue(maxsize=100)
        self._reader = threading.Thread(target=self._read_events, name="sap-jco-stdout", daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, name="sap-jco-stderr", daemon=True)
        self._reader.start()
        self._stderr_reader.start()

    def _read_stderr(self) -> None:
        try:
            while True:
                line = self.process.stderr.readline() if self.process.stderr else ""
                if not line:
                    return
                line = line.rstrip()
                if not line:
                    continue
                if self._stderr_tail.full():
                    try: self._stderr_tail.get_nowait()
                    except queue.Empty: pass
                self._stderr_tail.put_nowait(line)
        except Exception:
            return

    def _stderr_detail(self) -> str:
        with self._stderr_tail.mutex:
            return "\n".join(list(self._stderr_tail.queue)[-20:]).strip()

    def _read_events(self) -> None:
        try:
            while True:
                line = self.process.stdout.readline() if self.process.stdout else ""
                if not line:
                    detail = self._stderr_detail()
                    self._put_event({"event": "bridge_error", "message": detail or f"SAP JCo listener stopped with exit code {self.process.poll()}"})
                    return
                try:
                    output = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._put_event({"event": "bridge_error", "message": f"SAP JCo listener returned invalid output: {line.strip()}", "cause": str(exc)})
                    return
                if not self._put_event(output): return
        except Exception as exc:
            self._put_event({"event": "bridge_error", "message": f"SAP JCo listener reader failed: {exc}"})

    def _put_event(self, event: dict[str, Any]) -> bool:
        while not self._closed.is_set():
            try:
                self._events.put(event, timeout=.2)
                return True
            except queue.Full:
                continue
        return False

    async def next_event(self, timeout: float | None = None) -> dict[str, Any]:
        # Do not park queue.get() in asyncio.to_thread: cancelling a listener
        # would leave that worker thread blocked forever.  Polling a bounded
        # in-memory queue keeps cancellation immediate and thread counts flat.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout if timeout else None
        while True:
            try:
                event = self._events.get_nowait()
                break
            except queue.Empty:
                if self.process.poll() is not None:
                    raise JavaBridgeError(self._stderr_detail() or f"SAP JCo listener stopped with exit code {self.process.returncode}")
                if deadline is not None and loop.time() >= deadline:
                    raise JavaBridgeError("SAP JCo listener timed out while waiting for registration")
                await asyncio.sleep(.05)
        output = event
        if output.get("event") == "bridge_error":
            raise JavaBridgeError(str(output.get("message") or "SAP JCo listener failed"))
        if not output.get("ok", True) and output.get("event") != "idoc":
            raise JavaBridgeError(str(output.get("message") or "SAP JCo listener failed"))
        return output

    def acknowledge(self, delivery_id: str, success: bool, response: dict[str, Any] | None = None) -> None:
        """Release one SAP callback, optionally populating RFC reply fields."""
        if not delivery_id or not self.process.stdin or self.process.poll() is not None:
            raise JavaBridgeError("SAP JCo listener is not available to acknowledge the IDoc")
        command = ("commit" if success else "rollback") + "\t" + str(delivery_id) + "\n"
        try:
            with self._command_lock:
                if success and isinstance(response, dict):
                    exports = response.get("exports") if isinstance(response.get("exports"), dict) else {key: value for key, value in response.items() if key not in ("tables", "imports", "RfcRequest")}
                    tables = response.get("tables") if isinstance(response.get("tables"), dict) else {}
                    flattened_exports: list[tuple[str, Any]] = []
                    def flatten_export(prefix: str, value: Any) -> None:
                        if isinstance(value, dict):
                            for child_key, child_value in value.items():
                                flatten_export(f"{prefix}.{child_key}", child_value)
                        else:
                            flattened_exports.append((prefix, value))
                    for key, value in exports.items():
                        flatten_export(str(key), value)
                    for key, value in flattened_exports:
                        encoded = base64.b64encode(str(value if value is not None else "").encode("utf-8")).decode("ascii")
                        self.process.stdin.write(f"set\t{delivery_id}\texport.{key}\t{encoded}\n")
                    for table_name, rows in tables.items():
                        rows = rows if isinstance(rows, list) else [rows]
                        for index, row in enumerate(rows):
                            if not isinstance(row, dict): continue
                            for key, value in row.items():
                                encoded = base64.b64encode(str(value if value is not None else "").encode("utf-8")).decode("ascii")
                                self.process.stdin.write(f"set\t{delivery_id}\ttable.{table_name}.{index}.{key}\t{encoded}\n")
                self.process.stdin.write(command)
                self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise JavaBridgeError(f"SAP JCo listener acknowledgement failed: {exc}") from exc

    def close(self) -> None:
        self._closed.set()
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                if stream: stream.close()
            except OSError: pass
        if self._reader.is_alive(): self._reader.join(timeout=1)
        if self._stderr_reader.is_alive(): self._stderr_reader.join(timeout=1)
        self.descriptor.unlink(missing_ok=True)


class SapJcoWorker:
    """One persistent SAP client JVM with a live JCo destination pool."""
    def __init__(self, process: subprocess.Popen, descriptor: Path, loaded_jars: list[str], startup_timeout: float = 30, connector_name: str = "SAP JCo"):
        self.process, self.descriptor, self.loaded_jars = process, descriptor, loaded_jars
        self.connector_name = connector_name
        self._lock, self._closed = threading.Lock(), threading.Event()
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
        self._stderr: queue.Queue[str] = queue.Queue(maxsize=100)
        self._stdout_thread = threading.Thread(target=self._read_stdout, name="sap-jco-client-stdout", daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, name="sap-jco-client-stderr", daemon=True)
        self._stdout_thread.start(); self._stderr_thread.start()
        try: ready = self._responses.get(timeout=startup_timeout)
        except queue.Empty as exc:
            detail = '; '.join(list(self._stderr.queue)[-5:])
            self.close()
            raise JavaBridgeError(f"{self.connector_name} worker startup timed out{': ' + detail if detail else ''}") from exc
        if ready.get("event") != "ready" or not ready.get("ok", False):
            self.close(); raise JavaBridgeError(str(ready.get("message") or f"{self.connector_name} worker did not become ready"))

    def _read_stdout(self) -> None:
        try:
            while not self._closed.is_set():
                line = self.process.stdout.readline() if self.process.stdout else ""
                if not line: return
                try: value = json.loads(line)
                except json.JSONDecodeError: value = {"ok":False, "message":f"Invalid SAP worker output: {line.strip()}"}
                self._responses.put(value)
        except Exception as exc:
            if not self._closed.is_set():
                try: self._responses.put_nowait({"ok":False, "message":f"SAP worker reader failed: {exc}"})
                except queue.Full: pass

    def _read_stderr(self) -> None:
        try:
            while not self._closed.is_set():
                line = self.process.stderr.readline() if self.process.stderr else ""
                if not line: return
                if self._stderr.full():
                    try: self._stderr.get_nowait()
                    except queue.Empty: pass
                self._stderr.put_nowait(line.rstrip())
        except Exception: return

    def request(self, action: str, values: dict[str, Any] | None = None, timeout: float = 35) -> dict[str, Any]:
        if self.process.poll() is not None or not self.process.stdin: raise JavaBridgeError(f"{self.connector_name} worker is not running")
        request_id = str(__import__('uuid').uuid4())
        encoded = ""
        if values is not None:
            body = "".join(f"{_escape_property(key)}={_escape_property(value)}\n" for key, value in values.items() if value is not None)
            encoded = base64.b64encode(body.encode("utf-8")).decode("ascii")
        with self._lock:
            try:
                self.process.stdin.write(f"{action}\t{request_id}" + (f"\t{encoded}" if values is not None else "") + "\n"); self.process.stdin.flush()
                while True:
                    response = self._responses.get(timeout=timeout)
                    if response.get("requestId") == request_id: break
            except (OSError, queue.Empty) as exc:
                raise JavaBridgeError(f"{self.connector_name} worker request failed or timed out: {exc}") from exc
        if not response.get("ok", False): raise JavaBridgeError(str(response.get("message") or f"{self.connector_name} worker call failed"))
        response["loadedJars"] = self.loaded_jars
        return response

    def close(self) -> None:
        if self._closed.is_set(): return
        self._closed.set()
        try:
            if self.process.poll() is None and self.process.stdin:
                self.process.stdin.write("stop\tshutdown\n"); self.process.stdin.flush(); self.process.wait(timeout=5)
        except Exception:
            if self.process.poll() is None: self.process.terminate()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                if stream: stream.close()
            except OSError: pass
        self._stdout_thread.join(timeout=1); self._stderr_thread.join(timeout=1)
        self.descriptor.unlink(missing_ok=True)


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


def _java_command(config: dict[str, Any], classpath: str, descriptor: str) -> list[str]:
    """Build a bounded JVM command for native connector bridge processes."""
    initial = max(16, min(4096, int(config.get("jvmInitialHeapMb") or 64)))
    maximum = max(initial, min(8192, int(config.get("jvmMaximumHeapMb") or 512)))
    return [
        str(_java_executable()), f"-Xms{initial}m", f"-Xmx{maximum}m",
        "-XX:+ExitOnOutOfMemoryError", "-cp", classpath,
        "com.integrationfabric.bridge.FabricJavaBridge", descriptor,
    ]


def default_driver_home() -> Path:
    override = os.environ.get("FABRIC_DRIVER_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("PROGRAMDATA"):
        return Path(os.environ["PROGRAMDATA"]) / "Integration Fabric Studio" / "drivers"
    return Path("/opt/integrationfabric/drivers") if os.name != "nt" else Path.home() / ".integration-fabric" / "drivers"


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
    process_env = os.environ.copy()
    if family == "sap":
        # JCo loads sapjco3.dll/lib sapjco3.so natively; keep the licensed
        # driver outside the application and make its directory discoverable.
        native_directories = [str(path) for path in driver_directories(config, family) if path.exists()]
        if native_directories:
            process_env["PATH"] = os.pathsep.join(native_directories + [process_env.get("PATH", "")])
    properties = {"command": command, **(values or {})}
    descriptor = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".properties", delete=False)
    try:
        with descriptor:
            for key, value in properties.items():
                if value is not None:
                    descriptor.write(f"{_escape_property(key)}={_escape_property(value)}\n")
        completed = subprocess.run(
            _java_command(config, classpath, descriptor.name),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout or float(config.get("timeoutSeconds") or 30) + 5,
            env=process_env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise JavaBridgeError("Java runtime is unavailable. Rebuild the desktop installer so its bundled Java runtime is included.") from exc
    except subprocess.TimeoutExpired as exc:
        raise JavaBridgeError(f"Java connector timed out after {exc.timeout:g} seconds") from exc
    finally:
        Path(descriptor.name).unlink(missing_ok=True)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        detail = stderr.strip() or f"Java bridge exited with code {completed.returncode}"
        raise JavaBridgeError(detail)
    try:
        output = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise JavaBridgeError(f"Java bridge returned invalid output: {lines[-1]}") from exc
    if completed.returncode or not output.get("ok", False):
        raise JavaBridgeError(str(output.get("message") or stderr.strip() or "Java connector failed"))
    output["loadedJars"] = [jar.name for jar in jars]
    return output


def start_sap_listener(config: dict[str, Any], values: dict[str, Any]) -> SapJcoListener:
    classpath, _ = _classpath(config, "sap")
    process_env = os.environ.copy()
    native_directories = [str(path) for path in driver_directories(config, "sap") if path.exists()]
    if native_directories:
        process_env["PATH"] = os.pathsep.join(native_directories + [process_env.get("PATH", "")])
    descriptor = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".properties", delete=False)
    with descriptor:
        for key, value in {"command": "sap.listen", **values}.items():
            if value is not None: descriptor.write(f"{_escape_property(key)}={_escape_property(value)}\n")
    try:
        process = subprocess.Popen(
            _java_command(config, classpath, descriptor.name),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=process_env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), bufsize=1,
        )
    except FileNotFoundError as exc:
        Path(descriptor.name).unlink(missing_ok=True)
        raise JavaBridgeError("Java runtime is unavailable for the SAP JCo listener") from exc
    maximum = int(values.get("jco.server.max_pending_events") or max(4, int(values.get("jco.server.connection_count") or 8) * 2))
    return SapJcoListener(process, Path(descriptor.name), maximum)


def start_sap_worker(config: dict[str, Any], values: dict[str, Any]) -> SapJcoWorker:
    classpath, jars = _classpath(config, "sap")
    process_env = os.environ.copy()
    native_directories = [str(path) for path in driver_directories(config, "sap") if path.exists()]
    if native_directories: process_env["PATH"] = os.pathsep.join(native_directories + [process_env.get("PATH", "")])
    descriptor = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".properties", delete=False)
    with descriptor:
        for key, value in {"command":"sap.worker", **values}.items():
            if value is not None: descriptor.write(f"{_escape_property(key)}={_escape_property(value)}\n")
    try:
        process = subprocess.Popen(_java_command(config, classpath, descriptor.name), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=process_env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), bufsize=1)
        return SapJcoWorker(process, Path(descriptor.name), [jar.name for jar in jars], float(config.get("timeoutSeconds") or 30) + 5)
    except Exception:
        Path(descriptor.name).unlink(missing_ok=True)
        raise


def start_jdbc_worker(config: dict[str, Any], values: dict[str, Any], family: str) -> SapJcoWorker:
    """Start a persistent, single-session JDBC transaction bridge."""
    classpath, jars = _classpath(config, family)
    descriptor = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".properties", delete=False)
    with descriptor:
        for key, value in {"command": "jdbc.worker", **values}.items():
            if value is not None: descriptor.write(f"{_escape_property(key)}={_escape_property(value)}\n")
    try:
        process = subprocess.Popen(
            _java_command(config, classpath, descriptor.name), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=os.environ.copy(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), bufsize=1,
        )
        worker = SapJcoWorker(process, Path(descriptor.name), [jar.name for jar in jars], float(config.get("timeoutSeconds") or 30) + 5, "JDBC")
        worker.request("begin", timeout=float(config.get("timeoutSeconds") or 30) + 5)
        return worker
    except Exception:
        Path(descriptor.name).unlink(missing_ok=True)
        raise


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
        "sessionCount": options.get("maxSessions", options.get("sessionCount", 1)), "flowLimit": options.get("flowLimit", 0),
        "clientAcknowledge": str(bool(options.get("clientAcknowledge"))).lower(), "persistent": str(str(options.get("deliveryMode", "Persistent")).lower() == "persistent").lower(),
        "priority": options.get("priority", 4), "expiration": options.get("expiration", 0), "correlationId": options.get("correlationId"), "messageType": options.get("type"),
    }
    for key, value in (options.get("properties") or {}).items():
        values[f"messageProperty.{key}"] = value
    return invoke(f"jms.{operation}", config, values, family="jms", timeout=max(10, float(values["timeoutMs"] or 0) / 1000 + 10))
