"""Verify that the exact PyInstaller output can boot and answer /api/health."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: smoke-test-packaged-runtime.py <runtime-executable>", file=sys.stderr)
        return 2
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        print(f"Runtime executable does not exist: {executable}", file=sys.stderr)
        return 2
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="integration-fabric-smoke-") as data_dir:
        environment = os.environ.copy()
        environment.update(FABRIC_PORT=str(port), FABRIC_DATA_DIR=data_dir, FABRIC_LOG_LEVEL="info", PYTHONUTF8="1")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen([str(executable)], cwd=executable.parent, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags)
        try:
            deadline = time.monotonic() + 60
            last_error = ""
            while time.monotonic() < deadline:
                exit_code = process.poll()
                if exit_code is not None:
                    output = process.stdout.read() if process.stdout else ""
                    print(f"Packaged runtime exited with code {exit_code}:\n{output}", file=sys.stderr)
                    return 1
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                        payload = json.loads(response.read())
                    if response.status == 200 and payload.get("status") == "ok":
                        print(f"Packaged runtime health check passed on port {port}")
                        return 0
                except Exception as exc:
                    last_error = str(exc)
                time.sleep(0.25)
            process.terminate()
            try:
                output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); output, _ = process.communicate(timeout=5)
            print(f"Packaged runtime did not become healthy: {last_error}\n{output}", file=sys.stderr)
            return 1
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
