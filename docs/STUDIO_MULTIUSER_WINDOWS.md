# MINA Studio on a shared Windows host

Use one machine-wide installation with a separate Windows account and private user profile for each developer. Each Studio starts a local runtime with an independent workspace, Run state, Debug sessions, and logs. Installed binaries are shared. The runtime reserves its own Windows-assigned loopback port and accepts Studio API calls only with the credential for that launch.

## Host rollout

1. The host administrator installs `MINAStudio-<version>-Setup.exe` once from a maintenance session. Close Studio in every active Windows session before setup, upgrades, or uninstall. Ask users to save their work and close Studio normally. A concurrent setup request exits while the first owns the installer lock.
2. Give users standard Windows accounts, private profiles and sufficient storage for `%APPDATA%\MINA Studio\workspace-data` and the profile's logs and caches. If using profile containers, verify that storage performance and access controls hold during a logon burst. Keep installation files read-only for standard users.
3. Have each user launch **MINA Studio** from the Start menu in their own desktop session. Open their own source-control working copy or save imported projects under their private workspace. Exchange work through source control or project exports. Grant shared resources only to users who need them.
4. Give hosted Run and Debug HTTP services distinct host/port assignments per developer when they are used concurrently. Set a project environment property for the HTTP server connection's port and give each developer a different local value from an administrator-approved range. Use loopback bindings for local tests and configure authentication for hosted listeners when their data must be private. The Studio API credential is separate from the hosted application's authentication.
5. For broker and database development, provision separate test consumer groups, queues/subscriptions, database schemas and credentials where developers need isolation. Peak resource demand depends on the project, payload sizes, connector clients and concurrent listeners.

## Capacity and acceptance test

Run the sidecar soak on a nonproduction representative host. The harness starts 52 isolated runtime processes, verifies unique ports and checks that anonymous calls and the next user's credential are rejected. It runs concurrent project saves and reads, Run calls, interactive Debug steps, and trace reads. Every user uses the same project identifier to expose accidental cross-profile reuse. On Windows the report also samples private memory and working sets for the test sidecars.

From the repository root, using the installer build environment with Python 3.11 and `httpx`:

```powershell
& .\backend\build\.venv311\Scripts\python.exe .\scripts\studio-multiuser-soak.py --users 52 --seconds 600 --live-http --runtime ".\frontend\release\win-unpacked\resources\runtime\MINARuntime\MINARuntime.exe" --output ".\tmp\studio-multiuser\report.json"
```

The `--live-http` option adds an actual HTTP Run listener and Debug listener per runtime and checks that each returns only its own fixture response. The script stops on functional or isolation failures. The default latency gate is 2,000 ms P95 for each measured API operation. Its temporary data stays under its output directory and is removed after the run. Logs for real Studio launches are in each profile's `logs\runtime-startup.log`.

The soak separates designer asset loading, project creation, and listener startup. All 52 users participate in each phase by default. On Windows, the test requests that the system stay awake during the run and releases that request when the test exits. The report includes load-driver event-loop delay and saves partial timings on transport or functional failure. It never retries a failed Run or Debug command. The optional `--provision-batch` setting stages project creation and listener startup while keeping all users active during the timed workload.

HTTP/1 listeners publish readiness after the socket is accepting connections. Anonymous HTTP routes skip authentication worker warmup and dispatch. Authenticated routes keep their configured worker policy. Studio Run, Debug, and HTTP preview move project reads and log writes off the network event loop.

Complete Windows host acceptance by launching Studio in at least 52 actual desktop sessions on the target host, opening representative projects, and repeating saves, Run, Debug, and live listener operations. Check user-visible response time, CPU, memory, profile-disk throughput, and external connector limits. The sidecar report covers the server workload and generated designer assets. Full desktop capacity also depends on Electron renderers, RDS, and the host's OS and policies.
