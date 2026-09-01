# Integration Fabric Control Plane guide

## Purpose and operating model

Integration Fabric Control Plane is the self-hosted management plane for Integration Fabric data planes, capabilities, applications, resources, access assignments, observability, and immutable deployment packages. A data plane represents an on-premises runtime host or Kubernetes runtime boundary. Capabilities are provisioned into a data-plane namespace, while applications are deployed to a selected data plane, namespace, and compatible Integration Runtime capability.

The implementation follows the main TIBCO Platform Control Plane concepts without copying its hosted service: separation of control and data planes, namespace-scoped capabilities and applications, platform resources, role assignments, health/heartbeat inventory, application lifecycle, audit, and observability dashboards.

## Organization and delivery-team isolation

The built-in **Technology Team** is the permanent Control Plane owner. It registers data planes, provisions capabilities, configures platform resources, creates delivery teams, assigns principals, issues or revokes delivery credentials, and can govern all assets. Set `FABRIC_ADMIN_API_KEY` for its production credential.

Each data delivery team must be assigned one or more exclusive `{data plane, namespace}` scopes. The same namespace cannot be assigned to two active delivery teams. Packages, extracted package storage, deployments, environment requirements, encrypted secrets, runtime logs, lifecycle operations, and application observability carry an immutable `teamId`. Backend authorization returns `404` when another delivery team probes an asset identifier, preventing both access and asset discovery.

Technology Team can upload a package on behalf of a delivery team by selecting its name beside **Upload package**. Delivery automation uses a one-time credential issued from **Delivery teams** and sends it in `X-Control-Plane-Key`. Only a SHA-256 hash of that credential is stored. An Application Manager token can upload, deploy, manage secrets, run lifecycle operations, and inspect its own team assets. An Application Viewer token is read-only. Delivery credentials cannot access Control Plane overview, data-plane registration, capabilities, resources, team/access administration, global monitoring, or audit APIs.

For production, configure corporate identity-provider groups at the reverse proxy or identity gateway and exchange their authenticated team identity for scoped Control Plane credentials. Never expose the Technology Team key to delivery pipelines.

Control Plane does not rebuild a Studio project. A package already contains the selected starter tasks and every reachable called task, shared connection, XSD/JSON schema, resource, property profile, and deployment descriptor selected during packaging. Cloud packages keep their generated Docker/Kubernetes descriptors and can be assigned only to a Kubernetes data plane. On-premises packages can run locally through the configured command adapter.

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

## Control-plane model and screens

- **Overview**: fleet, capability, deployment, request, and recent activity summaries.
- **Data planes**: local, remote on-premises, and Kubernetes registrations; namespace, capacity, tag, tunnel, heartbeat, and health inventory.
- **Capabilities**: namespace-scoped capability provisioning and status. Application deployment requires an Integration Runtime capability.
- **Applications**: validated package repository, deployments, legal lifecycle actions, failure messages, instance details, and logs.
- **Environments & secrets**: packaged profiles and required secret names. Secret values are encrypted and never displayed.
- **Observability**: control-plane request/error totals plus data-plane and application CPU, memory, instance, and state telemetry.
- **Resources**: reusable global or data-plane-scoped resource definitions. Secret-valued properties are masked in list responses and audit entries.
- **Access control**: platform and team principals with Owner, Team Admin, Capability Manager, Application Manager, and Application Viewer roles, optionally scoped to a data plane and namespaces.
- **Delivery teams**: exclusive namespace allocation, asset counts, and one-time scoped automation credentials. Control Plane access remains disabled for delivery teams.
- **Audit trail**: provisioning, registration, deployment, resource, access, secret, and lifecycle operations with time, outcome, target, and detail.

## REST API summary

- `GET /api/health`, `/api/control-plane/overview`, `/api/monitoring`, `/api/observability`, `/api/audit`
- `GET|POST /api/data-planes`; `GET|DELETE /api/data-planes/{id}`; `POST /api/data-planes/{id}/heartbeat`
- `GET|POST /api/capabilities`; `DELETE /api/capabilities/{id}`
- `GET|POST /api/resources`; `DELETE /api/resources/{id}`
- `GET|POST /api/access/principals`
- `GET|POST /api/teams`; `PUT|DELETE /api/teams/{id}`
- `POST /api/teams/{id}/tokens`; `DELETE /api/teams/{id}/tokens/{tokenId}`
- `GET /api/session`
- `GET /api/applications`
- `GET|POST /api/packages`; `GET|DELETE /api/packages/{artifact}/{version}`
- `GET|POST /api/deployments`; `GET /api/deployments/{id}`
- `PUT /api/deployments/{id}/secrets`
- `POST /api/deployments/{id}/{start|stop|restart|kill|undeploy}`
- `GET /api/deployments/{id}/logs`

## Security, recovery, and troubleshooting

- Put Control Plane behind TLS/reverse proxy and set an API key. Restrict the data directory to the service identity.
- Permission enforcement is performed on every backend API call. UI filtering is informational and is not the security boundary.
- Back up the entire data directory together with the external `FABRIC_ADMIN_SECRET_KEY`. Losing or changing the key makes stored secrets unreadable.
- Rotate a secret with the secret API while stopped, then restart. The API returns secret names/configuration state only.
- A `FAILED` deployment preserves its error and logs. Correct the adapter or configuration and select **Restart**.
- `No runtime adapter is configured` means package validation and deployment creation are working, but `FABRIC_ADMIN_RUNTIME_COMMAND` has not been supplied.
- Control Plane PID reconciliation detects local processes that exited unexpectedly. Data-plane registration and heartbeat APIs provide the management-plane inventory. Remote command execution still requires a trusted data-plane agent/tunnel; this repository does not silently execute remote commands or claim a remote application is running without that adapter.
