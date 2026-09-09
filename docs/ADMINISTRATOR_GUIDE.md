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

Build with `scripts/build-administrator.ps1 -Version 2.4.0`, extract the generated versioned ZIP, and run `IntegrationFabricAdministrator.exe`. The output is a one-directory native Windows distribution, so copy the complete extracted directory—not only the `.exe`. Use `bin\fabricadmin.cmd start|stop|status|run` for service-style local control.

### Linux distribution

Build on Linux with `scripts/build-administrator.sh 2.4.0`, extract the generated tarball under `/opt/integration-fabric/administrator`, set `FABRIC_ADMIN_HOME`, and use `bin/fabricadmin start|stop|status|run`. PyInstaller output is operating-system specific: build the Linux bundle on Linux and deploy the entire extracted directory.

### Container

```bash
docker build -f Dockerfile.administrator --build-arg FABRIC_VERSION=2.4.0 -t integration-fabric-administrator:2.4.0 .
docker run -d --name fabric-admin -p 9080:9080 \
  -e FABRIC_ADMIN_API_KEY='replace-me' \
  -e FABRIC_ADMIN_SECRET_KEY='retrieve-from-secret-manager' \
  -v fabric-admin-data:/var/lib/integration-fabric/administrator \
  integration-fabric-administrator:2.4.0
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

1. In Studio Packaging, select the starter tasks, environments, target, archive format (`.ifpkg`, `.zip`, `.tar.gz`, or `.ear`), and deployment files. Only selected starter tasks and their recursively called Sub Tasks are packaged.
2. Select **Export archive** for an offline bundle, or enter the Control Plane URL, credential, team, data plane, namespace, capability, deployment environment, and required secrets and select **Deploy to Control Plane**. Studio builds the archive once, uploads those exact bytes, creates the deployment, and reports the Control Plane deployment ID/state. Credentials and secret values are transient and are not saved in the project or package.
3. Alternatively, upload an exported archive in **Applications**. Administrator rejects traversal paths, links/devices, duplicate paths, oversized expansion, unsupported formats, missing project/task artifacts, and invalid manifests.
4. Review checksum, target, profiles, selected task metadata, and secret requirements.
5. For local on-premises deployment, **Start** uses `FABRIC_ADMIN_RUNTIME_COMMAND`. Generated packages contain Linux `install.sh`/`deploy.sh` and Windows `install.ps1`/`deploy.ps1`/`start.ps1` assets. If the command adapter is not configured, startup fails visibly rather than reporting a false running state.
6. For cloud deployment, the Control Plane records the desired application, environment, replicas, namespace, and capability. The registered Kubernetes data-plane agent applies the generated Dockerfile, ConfigMap, Secret, Deployment, Service, HPA, and Kustomize assets; Studio does not incorrectly invoke the local command adapter for cloud targets.
7. Use **Details** for instance PIDs and logs. **Stop** performs normal termination; **Kill** is forced; **Restart** stops and recreates desired instances; **Undeploy** removes deployment secrets and the active inventory record.

For a private CA, keep TLS verification enabled and supply the CA PEM path in Studio. Disabling verification is provided only for isolated development systems.

Legal lifecycle transitions are enforced. Package deletion is blocked while any non-undeployed deployment references it.

Application health is evaluated per deployment. For the local command adapter, Control Plane verifies each managed runtime PID. Remote and Kubernetes agents report `HEALTHY`, `DEGRADED`, `UNHEALTHY`, or `UNKNOWN` in the `deploymentHealth` object of their data-plane heartbeat; Control Plane does not infer application health merely because the data plane is online. Health checks can be disabled per deployment.

Starter Task start/stop changes the deployment's desired starter set. A running local deployment is restarted with `FABRIC_ENABLED_STARTERS` containing only enabled task IDs. Remote and Kubernetes runtime agents reconcile the same desired state and may report their observed task state with the health heartbeat. Whole-application lifecycle state and individual Starter Task state remain separate.

## Control-plane model and screens

- **Overview**: fleet, capability, deployment, request, and recent activity summaries.
- **Data planes**: local, remote on-premises, and Kubernetes registrations; namespace, capacity, tag, tunnel, heartbeat, and health inventory.
- **Capabilities**: namespace-scoped capability provisioning and status. Application deployment requires an Integration Runtime capability.
- **Applications**: searchable package/deployment repository; archive task and Starter Task inventory; health, instance details and logs; deploy, start, stop, configure, redeploy, undeploy, and safe package deletion; deployment and configuration revision history; individual Starter Task desired-state controls.
- **Environments & secrets**: exportable packaged profiles, JSON profile editing/upload, optional immediate redeployment, and required secret names. Password values are rejected from profile uploads because secret values remain encrypted and deployment-scoped.
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
- `GET /api/packages/{artifact}/{version}/tasks`
- `GET|PUT /api/packages/{artifact}/{version}/environments/{environment}`
- `GET|POST /api/deployments`; `GET /api/deployments/{id}`
- `PUT /api/deployments/{id}/configuration`; `GET /api/deployments/{id}/health`
- `POST /api/deployments/{id}/starters/{taskId}/{start|stop}`
- `PUT /api/deployments/{id}/secrets`
- `POST /api/deployments/{id}/{start|stop|restart|kill|undeploy}`
- `GET /api/deployments/{id}/logs`
- `GET /api/revisions/{package|deployment}/{id}`

## Security, recovery, and troubleshooting

- Put Control Plane behind TLS/reverse proxy and set an API key. Restrict the data directory to the service identity.
- Permission enforcement is performed on every backend API call. UI filtering is informational and is not the security boundary.
- Back up the entire data directory together with the external `FABRIC_ADMIN_SECRET_KEY`. Losing or changing the key makes stored secrets unreadable.
- Rotate a secret with the secret API while stopped, then restart. The API returns secret names/configuration state only.
- A `FAILED` deployment preserves its error and logs. Correct the adapter or configuration and select **Restart**.
- `No runtime adapter is configured` means package validation and deployment creation are working, but `FABRIC_ADMIN_RUNTIME_COMMAND` has not been supplied.
- Control Plane PID reconciliation detects local processes that exited unexpectedly. Data-plane registration and heartbeat APIs provide the management-plane inventory. Remote command execution still requires a trusted data-plane agent/tunnel; this repository does not silently execute remote commands or claim a remote application is running without that adapter.
