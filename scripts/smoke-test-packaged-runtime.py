"""Verify that the exact PyInstaller output can boot and answer /api/health."""
from __future__ import annotations

import json
import os
from collections import deque
from queue import Empty, Queue
import re
from secrets import token_hex
import subprocess
import sys
import tempfile
from threading import Thread
import time
import urllib.error
import urllib.request
from pathlib import Path


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
    with tempfile.TemporaryDirectory(prefix="mina-smoke-") as data_dir:
        environment = os.environ.copy()
        token = token_hex(32)
        environment.update(MINA_PORT="0", MINA_DESKTOP_TOKEN=token, MINA_DATA_DIR=data_dir, MINA_LOG_LEVEL="warning", PYTHONUTF8="1")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen([str(executable)], cwd=executable.parent, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags)
        recent = deque(maxlen=60)
        announcements = Queue()

        def read_stdout():
            for line in process.stdout:
                recent.append(line)
                match = re.fullmatch(r'MINA_DESKTOP_PORT=(\d+)\s*', line)
                if match:
                    announcements.put(int(match.group(1)))
            announcements.put(None)

        reader = Thread(target=read_stdout, daemon=True)
        reader.start()
        try:
            deadline = time.monotonic() + 60
            try:
                port = announcements.get(timeout=60)
            except Empty:
                port = None
            if port is None:
                print('Packaged runtime did not announce a port.\n' + ''.join(recent), file=sys.stderr)
                return 1
            health = urllib.request.Request(f'http://127.0.0.1:{port}/api/health', headers={'X-MINA-Desktop-Token': token})
            last_error = ""
            while time.monotonic() < deadline:
                exit_code = process.poll()
                if exit_code is not None:
                    output = ''.join(recent)
                    print(f"Packaged runtime exited with code {exit_code}:\n{output}", file=sys.stderr)
                    return 1
                try:
                    with urllib.request.urlopen(health, timeout=1) as response:
                        payload = json.loads(response.read())
                    if response.status == 200 and payload.get("status") == "ok":
                        try:
                            with urllib.request.urlopen(health.full_url, timeout=2):
                                raise RuntimeError('Packaged runtime admitted an anonymous API request')
                        except urllib.error.HTTPError as denied:
                            if denied.code != 403:
                                raise
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
            print(f"Packaged runtime did not become healthy: {last_error}\n{''.join(recent)}", file=sys.stderr)
            return 1
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            reader.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
