# Integration Fabric Enterprise Administrator guide

## Purpose and operating model

Enterprise Administrator is the on-premises control plane for immutable Integration Fabric deployment packages. It validates and inventories packages, binds one packaged environment profile to a deployment, encrypts deployment secrets, assigns a runtime machine and desired instance count, starts and stops local runtime processes through a configured adapter, captures process logs, monitors instance PIDs, and records an audit trail.

Administrator does not rebuild a Studio project. A package already contains the selected starter tasks and every reachable called task, shared connection, XSD/JSON schema, resource, property profile, and deployment descriptor selected during packaging. Cloud packages can be inventoried, but their generated Docker/Kubernetes descriptors are the deployment mechanism; Administrator creates executable deployments only for `on-prem` packages.

## Install and start

### Development

```powershell
cd D:\Integration-tool\IntegrationFabric\administrator
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:FABRIC_ADMIN_DATA_DIR = "D:\IntegrationFabricAdmin\data"
.\.venv\Scripts\python.exe run_admin.py
```

Open `http://localhost:9080`. OpenAPI is available at `http://localhost:9080/docs`.

### Windows distribution

Build with `scripts/build-administrator.ps1`, extract the generated ZIP, and run `IntegrationFabricAdministrator.exe`. Use `bin\fabricadmin.cmd start|stop|status|run` for service-style local control.

### Linux distribution

Build on Linux with `scripts/build-administrator.sh`, extract the generated tarball under `/opt/integration-fabric/administrator`, set `FABRIC_ADMIN_HOME`, and use `bin/fabricadmin start|stop|status|run`.

### Container

```bash
docker build -f Dockerfile.administrator -t integration-fabric-administrator:1.0.0 .
docker run -d --name fabric-admin -p 9080:9080 \
  -e FABRIC_ADMIN_API_KEY='replace-me' \
  -e FABRIC_ADMIN_SECRET_KEY='retrieve-from-secret-manager' \
  -v fabric-admin-data:/var/lib/integration-fabric/administrator \
  integration-fabric-administrator:1.0.0
```

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| `FABRIC_ADMIN_HOST` | `0.0.0.0` | HTTP bind address |
| `FABRIC_ADMIN_PORT` | `9080` | HTTP port |
| `FABRIC_ADMIN_DATA_DIR` | `administrator/data` | Repository, state, encrypted secrets, logs, and audit location |
| `FABRIC_ADMIN_API_KEY` | empty | If set, `/api/*` except health requires `X-Admin-Key` |
| `FABRIC_ADMIN_SECRET_KEY` | generated local key | Stable encryption passphrase; supply from a secret manager in clustered/production installs |
| `FABRIC_ADMIN_RUNTIME_COMMAND` | empty | Administrator-approved runtime command template |
| `FABRIC_ADMIN_MAX_PACKAGE_MB` | `250` | Maximum uploaded archive size |
| `FABRIC_ADMIN_MAX_EXPANDED_MB` | `1024` | Maximum expanded package size |
| `FABRIC_ADMIN_MAX_PACKAGE_FILES` | `10000` | Maximum archive members |

The runtime command supports `{application}`, `{package}`, `{environment}`, `{deployment_id}`, and `{instance_id}` placeholders. Example:

```bash
export FABRIC_ADMIN_RUNTIME_COMMAND='integration-fabric-runtime --application {application} --environment {environment}'
```

The runtime receives `FABRIC_APPLICATION_DIR`, `FABRIC_ENVIRONMENT`, `FABRIC_DEPLOYMENT_ID`, `FABRIC_INSTANCE_ID`, and decrypted deployment secret values in its process environment. The command comes only from trusted Administrator configuration; package contents cannot provide an executable command.

## Package and deployment workflow

1. In Studio Packaging, select the starter tasks, environments, target, and deployment files.
2. Upload the `.ifpkg` in **Applications**. Administrator rejects traversal paths, links/devices, duplicate paths, oversized expansion, unsupported formats, missing project/task artifacts, and invalid manifests.
3. Review checksum, target, profiles, selected task metadata, and secret requirements.
4. Select **Create deployment**, then choose one packaged environment, a registered machine, desired instances, and all required secret values.
5. Select **Start**. If the command adapter is not configured, the request fails visibly rather than reporting a false running state.
6. Use **Details** for instance PIDs and logs. **Stop** performs normal termination; **Kill** is forced; **Restart** stops and recreates desired instances; **Undeploy** removes deployment secrets and the active inventory record.

Legal lifecycle transitions are enforced. Package deletion is blocked while any non-undeployed deployment references it.

## Administrator screens

- **Applications**: validated repository, deployments, legal actions, failure messages, instance details and logs.
- **Machines**: local command adapter and remote agent registrations, capacities, heartbeat and readiness.
- **Environments & secrets**: packaged profiles and required secret names. Values are never displayed.
- **Monitoring**: deployment-state counts, running instances, online machines, adapter readiness and recent failures.
- **Audit**: package, machine, secret and lifecycle operations with time, outcome, target and detail.

## REST API summary

- `GET /api/health`, `/api/monitoring`, `/api/audit`
- `GET|POST /api/packages`; `GET|DELETE /api/packages/{artifact}/{version}`
- `GET|POST /api/machines`; `POST /api/machines/{id}/heartbeat`
- `GET|POST /api/deployments`; `GET /api/deployments/{id}`
- `PUT /api/deployments/{id}/secrets`
- `POST /api/deployments/{id}/{start|stop|restart|kill|undeploy}`
- `GET /api/deployments/{id}/logs`

## Security, recovery, and troubleshooting

- Put Administrator behind TLS/reverse proxy and set an API key. Restrict the data directory to the service identity.
- Back up the entire data directory together with the external `FABRIC_ADMIN_SECRET_KEY`. Losing or changing the key makes stored secrets unreadable.
- Rotate a secret with the secret API while stopped, then restart. The API returns secret names/configuration state only.
- A `FAILED` deployment preserves its error and logs. Correct the adapter or configuration and select **Restart**.
- `No runtime adapter is configured` means package validation and deployment creation are working, but `FABRIC_ADMIN_RUNTIME_COMMAND` has not been supplied.
- Administrator PID reconciliation detects local processes that exited unexpectedly. A remote agent integration must post heartbeats and implement its runtime-side command polling before remote execution is enabled.
