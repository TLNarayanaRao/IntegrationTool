"""Verify that the exact PyInstaller output can boot and answer /api/health."""
from __future__ import annotations

import json
import os
import re
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


def verify_designer(base_url: str) -> int:
    """Fetch the packaged designer, not just a healthy backend with missing assets."""
    with urllib.request.urlopen(base_url+'/',timeout=5) as response:
        html=response.read().decode('utf-8')
    assets=set(re.findall(r'(?:src|href)="(/assets/[^"<>]+)"',html))
    if not assets:raise RuntimeError('Packaged designer has no generated asset references')
    for asset in assets:
        with urllib.request.urlopen(base_url+asset,timeout=10) as response:
            content_type=response.headers.get_content_type()
            if not response.read():raise RuntimeError('Empty designer asset: '+asset)
        if asset.endswith('.js') and content_type not in ('text/javascript','application/javascript'):
            raise RuntimeError('Designer JavaScript is missing or served with the wrong content type: '+asset)
        if asset.endswith('.css') and content_type!='text/css':
            raise RuntimeError('Designer CSS is missing or served with the wrong content type: '+asset)
    return len(assets)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: smoke-test-packaged-runtime.py <runtime-executable>", file=sys.stderr)
        return 2
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        print(f"Runtime executable does not exist: {executable}", file=sys.stderr)
        return 2
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="mina-smoke-") as data_dir:
        environment = os.environ.copy()
        environment.update(MINA_PORT=str(port), MINA_DATA_DIR=data_dir, MINA_LOG_LEVEL="info", PYTHONUTF8="1")
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
                        asset_count=verify_designer(f'http://127.0.0.1:{port}')
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/legal/THIRD_PARTY_NOTICES.txt", timeout=5) as legal:
                            if b'THIRD-PARTY NOTICES' not in legal.read():raise RuntimeError('Renderer license notices are not served')
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/legal/SBOM.cdx.json", timeout=5) as legal:
                            if json.loads(legal.read()).get('bomFormat')!='CycloneDX':raise RuntimeError('Renderer SBOM is not served')
                        print(f"Packaged runtime health, designer ({asset_count} assets) and legal routes passed on port {port}")
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
