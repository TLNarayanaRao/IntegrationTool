# MINA security review — 2026-09-22

## Outcome and scope

**Production blockers found, particularly for shared/multi-team deployments.**
Reviewed source at commit `676c0bf` with the existing working-tree changes present.
This is a security-focused review across Studio/runtime, debugger, Control Plane,
local/Kubernetes agent, Electron IPC, package handling, connector execution, secret
storage, and selected dependencies. It is not an exhaustive certification that all
code or dependencies are safe. No application security fixes were applied in this
review. Only this report was added.

Checks used static source inspection, mocked in-process authorization checks,
synthetic credentials, installed-package metadata, upstream advisories, and
`npm audit --json --ignore-scripts`. No real credentials were printed, no live
deployments were modified, and no destructive or resource-exhaustion tests ran.

Severity below assumes the affected service is reachable or the stated attacker
role exists. Firewall, reverse proxy, OS permissions, and deployment topology can
reduce exposure, but do not fix the underlying application boundary.

## Findings

### F1 — Critical: unauthenticated Control Plane owner access by default

**Evidence:** `administrator/app/main.py:66,141-157` uses an empty API key by
default and returns the Technology Team Owner identity when no credential is
provided. `administrator/run_admin.py:6` binds to `0.0.0.0:9080` by default.

**Impact:** Anyone able to reach an unconfigured instance can obtain governance
and deployment privileges, including access to agent deployment responses that
contain decrypted deployment secrets. The risk is not restricted to localhost.

**Validation:** With `API_KEY` mocked to empty, an anonymous synthetic request
resolved to `roles=['Owner']`. No live server configuration was changed.

**Fix:** Fail closed when credentials are missing. Restrict initial bootstrap to
loopback plus a one-time credential; require authenticated setup before exposing
network access. Keep management APIs behind TLS and an authenticated boundary.

### F2 — Critical: deployed application code inherits management credentials and host privileges

**Evidence:** `administrator/app/main.py:1238-1243` copies the full administrator
environment into application subprocesses. `administrator/agent/main.py:173-184`
does the same for agent deployments. Agent configuration reads `FABRIC_AGENT_KEY`
from that environment (`administrator/agent/main.py:39`). Raw Python deployments
are started under the same OS identity, not a separate tenant security boundary.

**Impact:** A malicious or compromised deployed application can read management
credentials such as the admin API key, secret-encryption key, or agent key when
configured via environment. Agent endpoints currently require a Technology Team
credential, not a narrowly scoped per-plane identity. Consequently an inherited
credential can expose other teams' deployments and secrets. The same OS identity
also permits access to other application files accessible to the service account;
clearing environment variables alone is insufficient isolation.

**Validation:** Source-confirmed inheritance and privileged agent authorization.
No real credential extraction or malicious deployment was attempted.

**Fix:** Explicit child-process environment allowlist, per-plane scoped credentials,
and isolated low-privilege application identities/containers with separate
filesystem access. Never expose management or encryption keys to application code.
Treat packages, scripts, and vendor drivers as executable code requiring approval.

### F3 — High: deployment move bypasses team namespace authorization

**Evidence:** `administrator/app/main.py:1735-1748` checks deployment ownership,
the target plane's registered namespaces, and the capability, but omits
`team_can_use_namespace`. Initial deployment creation checks this permission at
`administrator/app/main.py:1160`.

**Impact:** An Application Manager can move its stopped deployment to a registered
namespace not assigned to its team, bypassing the intended deployment-placement
boundary. Availability of valid plane/capability IDs is required.

**Validation:** A mocked Team A request successfully moved its own deployment to
`team-b`; a mocked `team_can_use_namespace` returning false was never called.
All persistence/audit functions were mocked; no real deployment moved.

**Fix:** Apply the same team/namespace/capability authorization to move, redeploy,
restore/revert, and start. Recheck immediately before execution as permissions
may change after deployment creation. Add negative cross-team route tests.

### F4 — High: Studio management/runtime APIs have no authentication boundary

**Evidence:** `backend/app/main.py:575-617` exposes project listing, creation,
editing, and execution without authentication dependencies. The middleware near
line 80 controls caching, not access. Workflows can execute Python and commands
(`backend/app/runtime.py:2030,2089`).

**Impact:** A caller who can access the runtime HTTP endpoint can read projects
and configure/execute operations with the runtime account's permissions. The
packaged sidecar binds to loopback (`backend/run_sidecar.py`), which limits remote
exposure but does not authenticate other local users/processes. Exposing this
same API for browser access without an authenticated proxy broadens the risk.
Cross-origin browser exploitation was not established in this review.

**Validation:** Unauthenticated in-process requests to project listing and a
synthetic memory-only connection test both returned HTTP 200. No shell commands
or real connector operations were invoked through these endpoints.

**Fix:** Per-launch authenticated desktop session credentials, Origin/Host checks,
and explicit authenticated user access/RBAC for browser deployments. Keep
untrusted workflow code out of the privileged Studio/management process.

### F5 — Medium: project exports and workspace files contain plaintext secrets

**Evidence:** `backend/app/store.py:46-58` serializes resource configurations and
property values without encryption. `backend/app/main.py:689-700` writes full
project/resource/property models into the project export without redaction.

**Impact:** Shared `.mpackage` exports and workspace backups can disclose database,
EMS, cloud, and other connector credentials. This concerns project exports; it
does not imply every deployment archive's secret handling is identical.

**Validation:** A synthetic password in a mocked project resource was present in
the exported `project.json`. No real project secret was read or displayed.

**Fix:** Redact secret values by default on project export, preserve secret
references, and make any sensitive export an explicit protected operation.
Use OS-backed or managed secret storage and restrict workspace ACLs.

### F6 — High: Studio project import has unbounded memory/decompression exposure

**Evidence:** `backend/app/main.py:1475-1494` calls `await file.read()` with no
application limit and decompresses manifest/project ZIP entries without checking
uncompressed size or compression ratios. By contrast, Control Plane and agent
archive handlers implement explicit member and expanded-size limits.

**Impact:** A reachable import endpoint can be used to consume large amounts of
memory/CPU using oversized or highly compressed uploads, disrupting Studio and
its runtime. A reverse-proxy compressed-body limit alone is insufficient.

**Validation:** Source-confirmed. No ZIP bomb or large-memory attack was executed.

**Fix:** Limit upload bytes, entry count, expanded size and per-entry size before
materialization; use bounded streaming reads, concurrency limits, and quotas.

### F7 — Medium: installed Python web dependencies have known advisories

**Evidence:** The inspected backend environment has FastAPI `0.115.12`, Starlette
`0.46.2`, and python-multipart `0.0.20`. Both backend and administrator requirements
pin FastAPI `0.115.12` and python-multipart `0.0.20`.

- Starlette's multipart rollover can block the event loop: CVE-2025-54121,
  fixed in `0.47.2`. The installed `0.46.2` is affected.
  [Maintainer advisory](https://github.com/Kludex/starlette/security/advisories/GHSA-2c2j-9gv5-cj73).
- python-multipart has Content-Disposition parameter interpretation issues
  covered by CVE-2026-53537, fixed in `0.0.30`.
  [Maintainer advisory](https://github.com/Kludex/python-multipart/security/advisories/GHSA-vffw-93wf-4j4q).
- The separate python-multipart arbitrary-file-write advisory CVE-2026-24486
  requires non-default `UPLOAD_DIR`/`UPLOAD_KEEP_FILENAME` settings. Those settings
  were not found in the reviewed application, so this is **not** being claimed as
  a demonstrated arbitrary-file-write exploit here.
  [Advisory](https://github.com/advisories/GHSA-wp53-j4wj-2cfg).

**Fix:** Upgrade to a mutually compatible, patched FastAPI/Starlette/multipart
set and regression-test uploads, forms, and packaged builds. Scan resolved Python
dependencies and shipped artifacts in CI rather than only requirements text.

## Additional hardening observations

- Electron uses context isolation, disabled Node integration, and sandboxing,
  which are positive. However, file-write IPC accepts caller-provided paths
  (`frontend/electron/main.cjs:158-170`) without sender-frame authorization, and
  navigation/window-opening restrictions were not found. A compromised renderer
  could abuse the bridge. A renderer compromise was not demonstrated here.
- Control Plane UI stores its credential in localStorage. Reduce exposure with
  scoped/session credentials and a suitable CSP; do not assume HTML escaping alone
  provides a complete browser security boundary.
- TLS enforcement, firewall rules, Windows ACLs, Unix permissions, Kubernetes
  RBAC/network policies, and supply-chain/signing controls need deployment-level
  verification. They cannot be certified from this source checkout.
- Existing archive path/member checks, Control Plane encrypted secret storage,
  hashed team tokens, ownership checks on many routes, and default SSH host-key
  rejection are useful controls. Their presence does not mitigate the specific
  bypasses above.

## Dependency-check results and limitations

`npm audit --json --ignore-scripts` completed successfully and reported **zero
known advisories** across 478 dependency entries. This is not a claim that the
frontend or Electron bridge is vulnerability-free.

`pip-audit` is not installed in the backend environment. No package installation
or application dependency mutation was performed. Python checks were limited to
installed metadata and selected verified upstream advisories, not a full resolved
dependency audit. Vendor SAP/EMS/JDBC JARs, native libraries, bundled Java/Python,
and the actual Windows installer were not fully audited.

## Recommended order

1. Before shared deployment: close anonymous Control Plane access and isolate
   application processes from management credentials and filesystem privileges.
2. Fix namespace authorization on move and audit every lifecycle route.
3. Authenticate Studio APIs and restrict network exposure.
4. Patch the web dependency stack and bound import/upload processing.
5. Redact/export secrets safely, harden Electron IPC/navigation, and add security
   regression tests plus complete Python/JAR/native artifact scans.

No live-server compromise was demonstrated or required. The findings are enough
to block a claim that the current product is safe for untrusted multi-team hosting.
