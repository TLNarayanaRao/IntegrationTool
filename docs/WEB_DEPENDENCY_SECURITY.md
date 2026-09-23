# Web dependency security update

The Studio backend, browser runtime, and Administrator now pin the same reviewed
web stack: FastAPI 0.141.1, Starlette 1.6.0, and python-multipart 0.0.32.
This replaces FastAPI 0.115.12 and python-multipart 0.0.20 and explicitly pins
Starlette instead of relying on an indirect dependency.

Upstream references:

- [Multipart upload rollover denial of service](https://github.com/Kludex/starlette/security/advisories/GHSA-2c2j-9gv5-cj73)
- [URL-encoded form limits](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq)
- [Windows StaticFiles UNC handling](https://github.com/Kludex/starlette/security/advisories/GHSA-wqp7-x3pw-xc5r)
- [Multipart disposition parsing](https://github.com/Kludex/python-multipart/security/advisories/GHSA-vffw-93wf-4j4q)

## Applying the update

For source installations, stop the service, install its requirements with its own
Python environment, then restart it. From the repository root on Windows:

```powershell
& .\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
& .\backend\.venv\Scripts\python.exe scripts/verify-web-dependencies.py
& .\administrator\.venv\Scripts\python.exe -m pip install -r administrator/requirements.txt
& .\administrator\.venv\Scripts\python.exe scripts/verify-web-dependencies.py
```

For a browser-only installation use `backend/requirements-browser.txt` instead.
For packaged installations, rebuild and redistribute the desktop/Administrator
installer. Already installed executables retain their old bundled dependencies.
Existing deployment environments must update their own Python dependencies too.
Do not disable certificate verification to install dependencies.

Windows packaging scripts now verify the installed web versions before bundling;
dependency-install failures stop packaging rather than reusing stale packages.

## Verification and limits

Security regressions cover multipart upload functionality, offloaded disk rollover,
URL-encoded field count/size enforcement, consistent dependency pins, and stale
build rejection. Backend runtime and Administrator tests pass with the new stack.
This is not a full security certification or remediation of other audit findings.
Request/body size limits, authentication, and deployment hardening remain necessary.

Local environment caveats: the Administrator virtual environment points to a
missing Python 3.11 installation, so Administrator tests were run with the updated
backend environment. Repair/recreate that environment before building it. The
backend Python 3.14 environment also reports platform compatibility issues for
httptools, PyYAML, watchfiles, and websockets during `pip check`; these packages
were not changed by this update. A clean supported build environment and installer
smoke test are still required before release.
