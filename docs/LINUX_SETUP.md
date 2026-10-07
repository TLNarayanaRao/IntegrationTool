# MINA Control Plane and Data Plane: one-stop guide

This is the authoritative setup and operations entry point. Use one program,
`scripts/linux/mina-setup.py`, with separate INI files for the Control Plane and
each Data Plane. The older shell entry points are compatibility aliases. Do not
combine instructions from older layouts. No systemd or systemctl is required.

## 1. Provision the Linux hosts

Ask the Unix team to provide an installation directory owned by the account that
will run MINA, for example `/opt/mina`. Run the installation and processes as that
account. Each host needs Linux, Python 3.12+ with venv/pip, Bash and network access
to the approved Python package mirror, or a complete Linux wheelhouse. `curl` is
useful for manual health checks. The Control Plane source build additionally uses
PyInstaller, installed by the build script. Build and deployment must use the same
Linux architecture and a compatible Linux distribution/glibc.

Data Planes need the Control Plane URL and owner credential for registration and
the current remote-agent API. Use an internal HTTPS reverse proxy for remote
access; the Control Plane listener itself is HTTP. Allow access to the configured
Control Plane port/proxy and to the application connector endpoints. The setup
script does not install OS packages, configure firewalls or create a TLS proxy.

For Java/JDBC/SAP/JMS connectors, provide JDK 17+ and licensed vendor JARs plus
Linux native libraries where required. Windows `.dll` files and Windows virtual
environments are not Linux runtimes. Set `[runtime] build_java_bridge=true` to
compile the Java bridge automatically. Native ODBC, AMQP 1.0 and optional DB2
prerequisites must be supplied on hosts whose applications use them.

## 2. Prepare the software on Windows

From the repository root in PowerShell:

```powershell
cd D:\Integration-tool\IntegrationFabric
py -3 scripts/linux/mina-setup.py bundle --output MinaLinuxSetup.zip
scp .\MinaLinuxSetup.zip minauser@control-plane-host:/tmp/
```

The bundle contains `administrator/`, `backend/`, `scripts/`, Java bridge source,
`drivers/` when present, the two INI templates and this guide under `software/`.
It excludes local databases, logs, virtual environments, caches, Windows build
outputs and release archives. Review vendor driver files before transfer. The
bundle sets shell scripts to LF and removes UTF-8 BOMs; the Linux entry also
normalizes copied shell scripts automatically. No `dos2unix`, script editing or
`chmod +x` step is required to invoke the setup entry or its subscripts.

The Linux Administrator executable is built on Linux. A Windows executable cannot
be used. To use a prebuilt Linux release instead, copy the entire
`MinaAdministrator-<version>-Linux-x64.tar.gz` separately and set its absolute
path in `[setup] administrator_archive`; set `build_administrator=false`.

## 3. Extract and configure the Control Plane

On the Control Plane host, as the MINA account:

```bash
mkdir -p /opt/mina
python3.12 -m zipfile -e /tmp/MinaLinuxSetup.zip /opt/mina
cd /opt/mina/software
umask 077
mkdir -p /opt/mina/config
cp scripts/linux/mina-control-plane.ini /opt/mina/config/control-plane.ini
```

Edit only `/opt/mina/config/control-plane.ini`:

- `install_root=/opt/mina`, `source_root=/opt/mina/software` and the available
  Python command/path under `[setup]`.
- `version` for the Linux Administrator build/release.
- `[control-plane] host` is a bind address; `0.0.0.0` binds all interfaces. Set
  `port`, a strong `api_key`, and a separate stable `secret_key` for encryption.
  `CHANGE_ME` values are rejected. Preserve the encryption key across upgrades.
- Set `pip_index_url` to the approved package mirror, or `wheelhouse` to an
  absolute directory with all required Linux wheels and build dependencies.
  With a wheelhouse, pip uses `--no-index`. Blank values use the configured pip
  defaults. The INI contains plain values without shell quoting or interpolation:
  `#`, `%`, `$` and `;` inside a value are preserved. Put comments on separate lines.
- `start=true` starts and health-checks the server after installation;
  `start=false` installs it without starting it.
- Keep `install_local_runtime=false` when applications run on separate Data Planes.
  Enable it only when the Control Plane host must also run local applications.

```bash
chmod 600 /opt/mina/config/control-plane.ini
python3.12 scripts/linux/mina-setup.py control-plane --config /opt/mina/config/control-plane.ini --check
python3.12 scripts/linux/mina-setup.py control-plane --config /opt/mina/config/control-plane.ini
```

Execute from `/opt/mina/software` as shown. Absolute script/config paths also work
from another directory. The default action is `setup`: it builds or reads the
Linux archive, installs the complete bundle, retains existing Control Plane data,
copies the private INI, starts the listener and waits for `/api/health`.
Data Plane registration is a separate step. Do not append `&` to setup: it already
starts the persistent process in the background and reports failures.
Open the configured reverse-proxy URL, or `http://<control-plane-host>:19080/`
on the permitted internal network, to use the Control Plane browser UI.

Default layout:

```text
/opt/mina/
  software/             copied source and setup scripts
  config/               private operator-maintained INI files
  control-plane/        Linux executable, internal libraries, installed INI
  control-plane-data/   repository, encrypted secrets and audit state
  runtime/              Data Plane Python venv and runtime adapter (when installed)
  agent/<plane-id>/     isolated packages, agent configuration, PID and logs
  drivers/              operator-supplied Linux vendor drivers
  logs/control-plane/   administrator.log
  logs/runtime/         runtime logs
  run/                  Control Plane PID
```

Optional INI keys `home`, `data_dir`, `log_dir`, `pid_dir`, and `runtime_command`
under `[control-plane]`, and `data_dir`, `log_dir`, `driver_home`,
`java_bridge_home`, `java`, `build_java_bridge`, `install_db2` under `[runtime]`
allow explicit paths/options. Use absolute Linux paths. `runtime_command` accepts
the existing application/environment placeholders; leave it absent for the
generated local adapter. With separate Data Planes, the agent launches applications
on its own host, not through the Control Plane's local runtime command.

## 4. Set up each Data Plane separately

Copy the same software ZIP to the Data Plane host and extract it as in step 3.
On that host:

```bash
cd /opt/mina/software
umask 077
mkdir -p /opt/mina/config
cp scripts/linux/mina-data-plane.ini /opt/mina/config/customer-plane.ini
```

Edit the new INI:

- `[setup] install_root`, `source_root`, `python`, mirror/wheelhouse and `start`.
- `[control-plane] control_plane_url` is the externally reachable URL (HTTP or
  HTTPS), `admin_key` matches the Control Plane owner key, and optional `ca_bundle`
  points to a PEM trust bundle for an internal HTTPS CA. TLS verification remains
  enabled. Include required CA certificates; never use a verification bypass.
- `[data-plane] id`, `name`, `host`, `namespace`, `region`, `available_capacity`,
  `heartbeat_seconds`, `agent_version` and `capability_name`. IDs and namespaces
  use letters, digits, underscores and hyphens. `host` identifies the runtime
  host in inventory; the setup must be executed on that host.
- Leave `state_dir` empty to derive `/opt/mina/agent/<id>`. Different planes must
  not share state directories. Applications, PIDs and logs are isolated by plane.
- Configure the vendor driver directory and Java bridge options under `[runtime]`.
  Copy the Linux vendor libraries into the configured driver directory before
  starting connector applications. `install_db2=false` omits optional `ibm-db`;
  set true only when the required DB2 build/runtime prerequisites are available.
- Team/user creation is optional: leave their `id` fields empty to manage them
  through the UI. When using `[delivery-team]`, set its `id` and `name`; an empty
  `scopes_json` adds this plane/namespace to existing scopes. An explicit JSON
  array replaces the team's full scope list. When using `[user]`, set a unique
  user ID, `team_id`, role and scope. Empty `resource_id` uses this namespace.

```bash
chmod 600 /opt/mina/config/customer-plane.ini
python3.12 scripts/linux/mina-setup.py data-plane --config /opt/mina/config/customer-plane.ini --check
python3.12 scripts/linux/mina-setup.py data-plane --config /opt/mina/config/customer-plane.ini
```

This installs the host runtime, registers/updates the Data Plane, provisions its
Integration Runtime capability, optionally creates the team/user, and starts its
reconciliation/heartbeat agent. It does not install another Control Plane.
The agent downloads assigned application archives, starts/stops runtime workers,
reports health and handles graceful shutdown. Inspect its agent log and the
Control Plane Data Planes view to confirm ONLINE status; successful registration
alone is not proof that application deployments are healthy.

For another plane, copy the INI to a different filename and change its ID, name,
host and namespace. If `state_dir` is explicit, give it a unique path. Run the same
command on that plane's host. Separate planes can share one installed runtime on
the same Linux host; stop affected agents before upgrading that shared runtime.

## 5. Lifecycle commands and upgrades

From `/opt/mina/software`, use the same entry and same INI with `--action`:

```bash
python3.12 scripts/linux/mina-setup.py control-plane --config /opt/mina/config/control-plane.ini --action status
python3.12 scripts/linux/mina-setup.py control-plane --config /opt/mina/config/control-plane.ini --action stop
python3.12 scripts/linux/mina-setup.py control-plane --config /opt/mina/config/control-plane.ini --action start
python3.12 scripts/linux/mina-setup.py data-plane --config /opt/mina/config/customer-plane.ini --action status
python3.12 scripts/linux/mina-setup.py data-plane --config /opt/mina/config/customer-plane.ini --action stop
python3.12 scripts/linux/mina-setup.py data-plane --config /opt/mina/config/customer-plane.ini --action start
```

`restart` is available for both roles. To change installed software or INI values,
stop the relevant process, back up state and the private INI/encryption key,
replace the software tree, update the version/configuration and run `setup` again.
Setup refuses to overwrite a running installation. Stops are graceful; Data Plane
shutdown also stops managed runtime workers. The setup does not delete deployment
state or generate a replacement encryption key. Keep the installation root and
private configuration paths unchanged unless deliberately migrating the service.

`--check` validates the INI and source location without installing or starting
anything; it does not prove that the network, OS libraries or package mirror are
ready. API update errors other than 404 stop setup instead of creating duplicate
resources. A failure leaves logs and completed setup steps available for diagnosis;
correct the INI/prerequisite and rerun after stopping any affected process.

## 6. Troubleshooting and backup

- Control Plane: `/opt/mina/logs/control-plane/administrator.log` and
  `--action status`; check configured listener/proxy and `/api/health`.
- Data Plane: `/opt/mina/agent/<id>/agent.log`, its application logs and
  `--action status`. Agent PID checks identify the expected script/configuration
  rather than signalling an unrelated reused PID.
- 401/403: verify the owner credential and intended permissions; it is never
  printed by the setup program. 400/409: inspect conflicting namespaces/scopes or
  immutable capability identifiers before rerunning.
- Mirror/offline failures: supply Linux wheels matching Python and architecture,
  including PyInstaller dependencies for source builds. Windows wheels cannot
  replace them. The mirror must provide the versions in the shipped requirements.
- Vendor failures: verify Linux native library compatibility, JDK/bridge and
  driver locations. OS prerequisites and licensed drivers are not downloaded.
- Protect INIs with mode 600. Back up `control-plane-data/`, the stable encryption
  key, private INIs, Data Plane state and any required vendor libraries together.
  Restore the same key with the data; changing it makes existing secrets unreadable.

## 7. Compatibility entries

Use the Python entry for Windows-to-Linux transfers. `setup-mina-linux.sh` and
`00-setup-and-register.sh` now delegate to **Control Plane setup only**. They read
`MINA_CONFIG_FILE`; edit version and paths in the INI rather than supplying a
positional version. `build-administrator.sh` delegates to the Linux build script.
Numbered registration helpers and `deploy-application.sh` remain available for
advanced operations. They are subscripts, not additional installation guides.

## 8. Control Plane model and operator reference

## Purpose and operating model

MINA Control Plane is the self-hosted management plane for MINA data planes, capabilities, applications, resources, access assignments, observability, and immutable deployment packages. A data plane represents an on-premises runtime host or Kubernetes runtime boundary. Capabilities are provisioned into a data-plane namespace, while applications are deployed to a selected data plane, namespace, and compatible Integration Runtime capability.

MINA separates control and data planes and provides namespace-scoped capabilities and applications, platform resources, role assignments, health/heartbeat inventory, application lifecycle, audit, and observability dashboards.

## Organization and delivery-team isolation

The built-in **Technology Team** is the permanent Control Plane owner. It registers data planes, provisions capabilities, configures platform resources, creates delivery teams, assigns principals, issues or revokes delivery credentials, and can govern all assets. Set `MINA_ADMIN_API_KEY` for its production credential.

Each data delivery team must be assigned one or more exclusive `{data plane, namespace}` scopes. The same namespace cannot be assigned to two active delivery teams. Packages, extracted package storage, deployments, environment requirements, encrypted secrets, runtime logs, lifecycle operations, and application observability carry an immutable `teamId`. Backend authorization returns `404` when another delivery team probes an asset identifier, preventing both access and asset discovery.

Technology Team can upload a package on behalf of a delivery team by selecting its name beside **Upload package**. Delivery automation uses a one-time credential issued from **Delivery teams** and sends it in `X-Control-Plane-Key`. Only a SHA-256 hash of that credential is stored. An Application Manager token can upload, deploy, manage secrets, run lifecycle operations, and inspect its own team assets. An Application Viewer token is read-only. Delivery credentials cannot access Control Plane overview, data-plane registration, capabilities, resources, team/access administration, global monitoring, or audit APIs.

For production, configure corporate identity-provider groups at the reverse proxy or identity gateway and exchange their authenticated team identity for scoped Control Plane credentials. Never expose the Technology Team key to delivery pipelines.

Control Plane does not rebuild a Studio project. A package already contains the selected starter tasks and every reachable called task, shared connection, XSD/JSON schema, resource, property profile, and deployment descriptor selected during packaging. Cloud packages keep their generated Docker/Kubernetes descriptors and can be assigned only to a Kubernetes data plane. On-premises packages can run locally through the configured command adapter.

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| `MINA_ADMIN_HOST` | `0.0.0.0` | HTTP bind address |
| `MINA_ADMIN_PORT` | `9080` | HTTP port |
| `MINA_ADMIN_DATA_DIR` | `administrator/data` | Repository, state, encrypted secrets, logs, and audit location |
| `MINA_ADMIN_API_KEY` | empty | Owner credential sent in `X-Admin-Key` or `X-Control-Plane-Key`. Credential-free owner access is restricted to direct loopback clients and same-origin browser requests. Remote and reverse-proxy clients must supply an owner key or scoped team token. |
| `MINA_ADMIN_SECRET_KEY` | generated local key | Stable encryption passphrase; supply from a secret manager in clustered/production installs |
| `MINA_ADMIN_RUNTIME_COMMAND` | empty | Administrator-approved runtime command template |
| `MINA_ADMIN_MAX_PACKAGE_MB` | `250` | Maximum uploaded archive size |
| `MINA_ADMIN_MAX_EXPANDED_MB` | `1024` | Maximum expanded package size |
| `MINA_ADMIN_MAX_PACKAGE_FILES` | `10000` | Maximum archive members |

The runtime command supports `{application}`, `{package}`, `{environment}`, `{deployment_id}`, and `{instance_id}` placeholders. The desktop installer includes a separate `MINAWorker` executable for this purpose. Example:

```bash
export MINA_ADMIN_RUNTIME_COMMAND='mina-runtime --application {application} --environment {environment}'
```

On Windows desktop installations, configure the worker executable rather than the Studio sidecar:

```powershell
$worker = 'C:\Program Files\MINA Studio\resources\runtime\MINAWorker\MINAWorker.exe'
$command = "`\"$worker`\" --application `\"{application}`\" --environment `\"{environment}`\""
[Environment]::SetEnvironmentVariable('MINA_ADMIN_RUNTIME_COMMAND', $command, 'Machine')
```

The runtime receives `MINA_APPLICATION_DIR`, `MINA_ENVIRONMENT`, `MINA_DEPLOYMENT_ID`, `MINA_INSTANCE_ID`, and decrypted deployment secret values in its process environment. The command comes only from trusted Administrator configuration; package contents cannot provide an executable command.

## Package and deployment workflow

1. In Studio Packaging, select the starter tasks, environments, target, archive format (`.mpkg`, `.zip`, `.tar.gz`, or `.ear`), and deployment files. Only selected starter tasks and their recursively called Sub Tasks are packaged. Legacy `.ifpkg` uploads remain supported during the compatibility period.
2. Select **Export archive** for an offline bundle, or enter the Control Plane URL, credential, team, data plane, namespace, capability, deployment environment, and required secrets and select **Deploy to Control Plane**. Studio builds the archive once, uploads those exact bytes, creates the deployment, and reports the Control Plane deployment ID/state. Credentials and secret values are transient and are not saved in the project or package.
3. Alternatively, upload an exported archive in **Applications**. Administrator rejects traversal paths, links/devices, duplicate paths, oversized expansion, unsupported formats, missing project/task artifacts, and invalid manifests.
4. Review checksum, target, profiles, selected task metadata, and secret requirements.
5. For local on-premises deployment, **Start** uses `MINA_ADMIN_RUNTIME_COMMAND`. Generated packages contain Linux `install.sh`/`deploy.sh` and Windows `install.ps1`/`deploy.ps1`/`start.ps1` assets. If the command adapter is not configured, startup fails visibly rather than reporting a false running state.
6. For cloud deployment, the Control Plane records the desired application, environment, replicas, namespace, and capability. The registered Kubernetes data-plane agent applies the generated Dockerfile, ConfigMap, Secret, Deployment, Service, HPA, and Kustomize assets; Studio does not incorrectly invoke the local command adapter for cloud targets.
7. Use **Details** for instance PIDs and logs. **Stop** performs normal termination; **Kill** is forced; **Restart** stops and recreates desired instances; **Undeploy** removes deployment secrets and the active inventory record.

For a private CA, keep TLS verification enabled and supply the CA PEM path in Studio. Disabling verification is provided only for isolated development systems.

Legal lifecycle transitions are enforced. Package deletion is blocked while any non-undeployed deployment references it.

Application health is evaluated per deployment. For the local command adapter, Control Plane verifies each managed runtime PID. Remote and Kubernetes agents report `HEALTHY`, `DEGRADED`, `UNHEALTHY`, or `UNKNOWN` in the `deploymentHealth` object of their data-plane heartbeat; Control Plane does not infer application health merely because the data plane is online. Health checks can be disabled per deployment.

Starter Task start/stop changes the deployment's desired starter set. A running local deployment is restarted with `MINA_ENABLED_STARTERS` containing only enabled task IDs. Remote and Kubernetes runtime agents reconcile the same desired state and may report their observed task state with the health heartbeat. Whole-application lifecycle state and individual Starter Task state remain separate.

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
- Back up the entire data directory together with the external `MINA_ADMIN_SECRET_KEY`. Losing or changing the key makes stored secrets unreadable.
- Rotate a secret with the secret API while stopped, then restart. The API returns secret names/configuration state only.
- A `FAILED` deployment preserves its error and logs. Correct the adapter or configuration and select **Restart**.
- `No runtime adapter is configured` means package validation and deployment creation are working, but `MINA_ADMIN_RUNTIME_COMMAND` has not been supplied.
- Control Plane PID reconciliation detects local processes that exited unexpectedly. Data-plane registration and heartbeat APIs provide the management-plane inventory. Remote command execution still requires a trusted data-plane agent/tunnel; this repository does not silently execute remote commands or claim a remote application is running without that adapter.

## Application operations


Open **Applications** to manage deployments or uploaded packages. Existing configuration, starter controls, logs, revision history, and health information remain available through **Manage** on an application card.

## Views and finding applications

- **Cards** shows application identity, environment, owning team, instance state, and reported health.
- **Compact** provides denser application cards.
- **Status board** groups deployments by lifecycle state. It is not a drag-to-deploy board: state changes require explicit lifecycle actions.
- Combine search, lifecycle state, data plane, environment, and team filters. **Needs attention** selects failed deployments or unhealthy/degraded health reports.
- Star applications and enable **Favorites** to focus on them. Favorites and view preferences are stored locally in this browser, not shared with other operators.
- **Ctrl+K** (Command+K on macOS) opens application search, unless a dialog is open.

## Bulk lifecycle operations

Select individual deployments or **Select visible**, then choose **Start**, **Stop**, or **Restart**. Only eligible selected deployments are included in the confirmation dialog. Review the names, environments, and teams before confirming. Stop/restart may interrupt processing.

The client re-fetches each deployment before sending its operation, executes requests sequentially, and reports accepted, skipped, or failed results separately. A failure does not prevent later targets from being attempted. Accepted requests are not proof of healthy execution; inspect updated deployment status and health. Closing the result dialog does not cancel requests already sent. Changing filters clears hidden selections. There is deliberately no bulk delete.

UI eligibility follows the Technology Team/Application Manager model. Every request still uses the existing authenticated API and server-side authorization; client-side controls do not grant permissions.

## Themes

Use **Theme** in the top header: **Ocean dark**, **Slate dark**, **Light**, or **System**. System follows the operating system preference. The choice persists locally per browser origin and applies to navigation, forms, dialogs, application views, and telemetry surfaces. Windows desktop and browser clients use the same served UI; their local preferences may differ.

## Updating an installation

Deploy the updated `administrator/web` assets together, including `index.html`, `operations-workspace.js`, and `operations-workspace.css`. Refresh the browser or reload the Windows Control Plane client. No database migration is required. Do not replace your existing administrator data directory, environment settings, or credentials.

## Application inspector and operations


The Control Plane home page summarizes running applications, data-plane
connectivity, unhealthy/stopped deployments, and recent operations. The
**Applications** workspace lets an operator search and filter deployments and
packages, then inspect an application without leaving the list.

The application inspector exposes lifecycle actions, health and instances,
environment/instance/health-check configuration, write-only secret updates,
Starter Task controls, runtime logs, revision history and revert, configuration
comparison, backup, and restore. Existing package upload, archive inspection,
and deployment flows remain available.

The **Telemetry** page shows CPU, memory, and disk readings reported by agents,
with bounded trends (up to 720 samples per data plane, sampled no more than
once every 15 seconds). It also shows task outcomes and recent Control Plane
request errors. Blank readings mean the agent has not reported that metric;
they are not treated as zero.

Operators can create or delete alert rules for offline data planes, failed
deployments, unhealthy applications, and CPU/memory/disk thresholds. Resource
rules report `NO_DATA` when a host has not sent the selected metric. Rules are
evaluated in the Control Plane UI/API; external notification delivery is not
implemented by these rules.

Python data-plane agents install `psutil` to report host CPU, memory, and disk.
If `psutil` is unavailable, the agent still reports disk space and its local
process count. A remote on-premises Python agent forwards a bounded tail of
each instance log. Kubernetes pod-log forwarding is not yet implemented;
local deployments are read from the Control Plane host.

## Optional Windows client


The Linux Control Plane remains the server. The existing browser UI remains
available at the same HTTPS address. This client adds a Windows application;
it does not install Python, start a local Control Plane or change server permissions.

## Build on Windows

From `frontend`, run `npm ci` if dependencies are not installed, then:

```powershell
npm run control-plane:installer
# Or an unpacked build:
npm run control-plane:unpacked
# Override the version without editing application code:
powershell -File ../scripts/build-control-plane-desktop.ps1 -Version 1.2.0
```

Installer: `frontend/release-control-plane/MINAControlPlane-<version>-Setup.exe`.
Unpacked executable: `frontend/release-control-plane/win-unpacked/MINA Control Plane.exe`.
These are separate from the Studio installer and Administrator server archive.
Release signing requires your organization's Windows code-signing configuration;
unsigned development installers may trigger Windows SmartScreen warnings.

## Connect

1. Update the Linux server's `administrator/web/admin.js` from this version (or
   redeploy the updated Control Plane). Sign-in and rename dialogs now support
   both browsers and Electron. Older servers using `window.prompt` are incompatible.
2. Expose the existing Control Plane through HTTPS with a certificate trusted by
   Windows. A reverse proxy can terminate TLS and forward to the existing service.
   Serve at the origin root, e.g. `https://mina.company.com`, not `/control-plane`.
   Enable authentication and preserve existing API routes, uploads and downloads.
3. Install and launch **MINA Control Plane** on Windows, enter that HTTPS address,
   then enter your existing Control Plane credential when requested.
4. Use **Connection → Reload / reconnect** after a connection failure, or
   **Sign out / change server** to end the local session. Closing the app does not
   stop remote applications or cancel operations already accepted by the server.

## Security and limitations

Only the server address is stored in `%APPDATA%/MINAControlPlaneDesktop/server.json`.
Remote browsing uses an isolated, non-persistent session. Its cookies, credentials
and local storage are not persisted across app restarts; changing server creates a
new session. Browser credential storage behavior is unchanged. Local sign-out does
not revoke a server-issued credential; revoke credentials through server administration.

Remote pages have no Node.js or desktop IPC access. Sandboxing, context isolation,
certificate validation and web security are enabled. HTTP and invalid certificates
are rejected; there is no bypass switch. Cross-origin navigation, pop-ups and device
permissions are blocked. External identity-provider redirects and cross-origin CDNs
are not supported by this initial client. Existing same-origin Control Plane
credential authentication, uploads, exports and management APIs remain available.

Network outages interrupt the desktop view, not deployed workloads. Reload when
connectivity returns. This is an online client, not an offline administration replica.

## Development and tests

`npm run control-plane:desktop` launches from source. `npm run control-plane:test`
checks URL policy, isolation settings, independent packaging and dialog compatibility.
The entry point is `frontend/control-plane-desktop/main.cjs`; the connection screen
is `connect.html`, `connect.js` and `connect.css`. Remote content has no preload.
The local screen's narrow IPC bridge is validated against its exact sender/frame.
Follow release qualification with a real HTTPS Linux server: sign-in, team isolation,
package upload/download, start/stop, network interruption, reconnect and local sign-out.
