# Integration Fabric environment variables

This is the reference list of environment variables recognized by the current
Integration Fabric source, Studio sidecar, and Control Plane. Variable names
are case-sensitive on Linux and Kubernetes. Values containing passwords,
private keys, API keys, or tokens must be supplied by the operating system,
service manager, or cloud secret store; do not commit them to a project or
container image.

## Runtime and Studio sidecar

| Variable | Default | Scope and purpose |
|---|---|---|
| `FABRIC_PORT` | `8787` | Backend HTTP port used by `run_sidecar.py`. Studio normally assigns this automatically. |
| `FABRIC_LOG_LEVEL` | `info` | Uvicorn process log level, for example `debug`, `info`, `warning`, or `error`. |
| `FABRIC_DATA_DIR` | `backend/data` | Runtime data root for projects, SAP TID files, and default project logs. |
| `FABRIC_RUNTIME_LOG_DIR` | `<data-dir>/logs` | Process-wide fallback log root when `runtime.logDirectory` is blank. |
| `FABRIC_PROJECT_LOG_MAX_BYTES` | `10485760` | Maximum size of each project log file before rotation. |
| `FABRIC_PROJECT_LOG_BACKUP_COUNT` | `4` | Number of rotated project log files retained. |
| `FABRIC_LOG_TIMEZONE` | `America/Phoenix` | IANA display timezone for runtime, debugger, and audit timestamps. Arizona is emitted with `-07:00`. |
| `FABRIC_WORKER_THREADS` | `auto` | Runtime worker-thread setting; otherwise environment property `advanced.workerThreads` or `advanced.threadCount` is used. |
| `FABRIC_APPLICATION_DIR` | unset | Application directory supplied to a deployed runtime by the Control Plane. |
| `FABRIC_ENVIRONMENT` | `local` or deployment value | Active runtime environment. |
| `FABRIC_DEPLOYMENT_ID` | unset | Deployment identifier supplied by the Control Plane. |
| `FABRIC_INSTANCE_ID` | unset | Runtime instance identifier supplied by the Control Plane. |
| `FABRIC_BUILD_VERSION` | `source` | Build/version value included in startup diagnostics. |
| `FABRIC_STATIC_DIR` | bundled static directory | Override location of backend-served frontend assets. |
| `FABRIC_DRIVER_HOME` | platform search locations | SAP JCo/native driver directory override. Must contain matching `sapjco3.jar` and native library. |
| `FABRIC_JAVA` | automatic Java lookup | Java executable override for the SAP/JMS Java bridge. |
| `FABRIC_JAVA_BRIDGE_HOME` | repository/bundled bridge location | Java bridge installation directory override. |
| `INTEGRATION_FABRIC_AI_MODEL` | `gpt-5` | AI Builder model name when `OPENAI_API_KEY` is configured. |
| `OPENAI_API_KEY` | unset | Enables the OpenAI AI Builder provider. Store as a secret. |

The Electron Studio sets `FABRIC_PORT`, `FABRIC_DATA_DIR`,
`FABRIC_LOG_LEVEL`, and `FABRIC_BUILD_VERSION` for its child runtime. It also
supports these Studio-only process variables:

| Variable | Purpose |
|---|---|
| `FABRIC_PYTHON` | Python executable override for development sidecar startup. |
| `FABRIC_DEV_URL` | Frontend development URL loaded by Electron instead of the local production URL. |

## Control Plane

| Variable | Default | Scope and purpose |
|---|---|---|
| `FABRIC_ADMIN_HOST` | `0.0.0.0` | Control Plane HTTP bind address. |
| `FABRIC_ADMIN_PORT` | `9080` | Control Plane HTTP port. |
| `FABRIC_ADMIN_DATA_DIR` | `administrator/data` | Control Plane state root: packages, deployments, machines, secrets, audit, and logs. Mount this directory persistently. |
| `FABRIC_ADMIN_API_KEY` | unset | Technology Team API key. When set, protected APIs require `X-Admin-Key` or `X-Control-Plane-Key`. Store in a secret manager. |
| `FABRIC_ADMIN_SECRET_KEY` | generated local key | Stable encryption key for stored deployment secrets. Required from a durable secret store for production and clustered deployments. |
| `FABRIC_ADMIN_RUNTIME_COMMAND` | unset | Trusted command template used to start an on-premises runtime. Supports `{application}`, `{package}`, `{environment}`, `{deployment_id}`, and `{instance_id}`. |
| `FABRIC_ADMIN_MAX_PACKAGE_MB` | `250` | Maximum uploaded package size in megabytes. |
| `FABRIC_ADMIN_MAX_EXPANDED_MB` | `1024` | Maximum expanded package size in megabytes. |
| `FABRIC_ADMIN_MAX_PACKAGE_FILES` | `10000` | Maximum archive member count. |
| `FABRIC_ADMIN_VERSION` | packaged value or `development` | Control Plane version override. |
| `FABRIC_ADMIN_WEB` | bundled `web` directory | Override location of Control Plane frontend files. |

The Linux service wrapper also recognizes:

| Variable | Default | Purpose |
|---|---|---|
| `FABRIC_ADMIN_HOME` | `/opt/integration-fabric/administrator` | Installed Control Plane directory. |
| `FABRIC_ADMIN_PID_DIR` | `/var/run/integration-fabric` | PID file directory used by `bin/fabricadmin`. |
| `FABRIC_ADMIN_LOG_DIR` | `/var/log/integration-fabric` | Service-wrapper stdout/stderr log directory. |

## Build and packaging variables

| Variable | Purpose |
|---|---|
| `FABRIC_VERSION` | Default version passed to Studio or Control Plane build scripts when no explicit version argument is supplied. |
| `WIN_CSC_LINK` / `WIN_CSC_KEY_PASSWORD` | Windows Electron signing certificate and password. Keep both outside source control. |
| `CSC_LINK` / `CSC_KEY_PASSWORD` | Electron Builder fallback names for Windows signing. |

`FABRIC_VERSION` and signing variables are build-time settings; they are not
needed on an installed runtime machine.

## Automatically injected deployment variables

When the Control Plane starts an on-premises deployment, it injects
`FABRIC_APPLICATION_DIR`, `FABRIC_ENVIRONMENT`, `FABRIC_DEPLOYMENT_ID`, and
`FABRIC_INSTANCE_ID`. It also injects the deployment's decrypted secret values
using their configured names. These values should not be manually duplicated
in a package or checked into source control.

## Windows

For the current PowerShell session:

```powershell
$env:FABRIC_DATA_DIR = 'C:\ProgramData\Integration Fabric\runtime-data'
$env:FABRIC_RUNTIME_LOG_DIR = 'D:\IntegrationLogs'
$env:FABRIC_LOG_TIMEZONE = 'America/Phoenix'
$env:FABRIC_DRIVER_HOME = 'C:\SAP\jco'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

For a persistent machine-level setting, run PowerShell as Administrator and
use `[Environment]::SetEnvironmentVariable('NAME', 'VALUE', 'Machine')`.
Restart the service or application after changing environment variables.

## Linux and systemd

Create a root-readable environment file such as
`/etc/integration-fabric/runtime.env`:

```text
FABRIC_DATA_DIR=/var/lib/integration-fabric/runtime
FABRIC_RUNTIME_LOG_DIR=/var/log/integration-fabric/runtime
FABRIC_LOG_TIMEZONE=America/Phoenix
FABRIC_DRIVER_HOME=/opt/sap/jco
FABRIC_ENVIRONMENT=dev
```

Reference it from the service unit:

```ini
[Service]
EnvironmentFile=/etc/integration-fabric/runtime.env
```

Protect files containing secrets with `chmod 600` and set the service account
as owner. Run `systemctl daemon-reload` and restart the service after changes.

## Docker and Kubernetes

Use ordinary configuration values for paths and ports, and use Docker/Kubernetes
Secrets for credentials:

```yaml
env:
  - name: FABRIC_ENVIRONMENT
    value: dev
  - name: FABRIC_LOG_TIMEZONE
    value: America/Phoenix
  - name: FABRIC_DATA_DIR
    value: /var/lib/integration-fabric/runtime
  - name: FABRIC_ADMIN_API_KEY
    valueFrom:
      secretKeyRef:
        name: fabric-admin-secrets
        key: api-key
  - name: FABRIC_ADMIN_SECRET_KEY
    valueFrom:
      secretKeyRef:
        name: fabric-admin-secrets
        key: encryption-key
```

Persist `FABRIC_DATA_DIR` and `FABRIC_ADMIN_DATA_DIR` on volumes. For SAP JCo,
provide the licensed matching JCo JAR/native library through a protected
volume or image layer and set `FABRIC_DRIVER_HOME` to that directory. Do not
print secret environment values in startup diagnostics.

## Operational notes

- Environment variables are read during process startup; restart the affected
  process after changing them.
- Relative paths are resolved from the process/application data location and
  should be replaced with absolute paths in production.
- `FABRIC_LOG_TIMEZONE` changes display timestamps only. Scheduler and token
  expiry calculations continue to use UTC internally.
- Existing log files are not rewritten when the timezone changes.
- To inspect effective non-secret settings on Windows use `Get-ChildItem Env:`;
  on Linux use `env` or `systemctl show <service> --property=Environment`.
