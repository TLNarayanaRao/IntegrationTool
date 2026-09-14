# Linux Control Plane: Direct Run Guide

> Current standard layout: copy `administrator/`, `backend/`, `drivers/`,
> `java-bridge/`, and `scripts/` into `/opt/tibco/esb/IntegrationFabricSoftware`.
> Run `scripts/linux/setup-integration-fabric-linux.sh` from that directory.
> The commands in this guide that reference the older `integrationfabric/source`
> layout are retained as historical alternatives; do not mix the two layouts.

This guide runs the Integration Fabric Control Plane directly from the shell. It does not use `systemctl` or require a systemd service. The Unix team only needs to provision `/opt/tibco/esb/IntegrationFabricSoftware` and its permissions.

## Directory layout

All Control Plane state, packages, runtime files, drivers, and logs are kept below one root directory:

```text
/opt/tibco/esb/integrationfabric/
├── source/
├── control-plane/
├── control-plane-data/
├── runtime/
├── apps/
├── drivers/
├── logs/
└── run/
```

The shell environment file may remain under `/etc` if the Unix team requires centralized configuration. Application data and logs do not use `/var` or a user home directory.

## Build the Linux package

The Linux package must be built on Linux or by a Linux CI runner. A Windows Control Plane executable cannot run on Linux.

Install prerequisites on Ubuntu or Debian:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip build-essential
```

Build the Administrator package:

```bash
cd /opt/tibco/esb/integrationfabric/source
chmod +x scripts/build-administrator.sh
./scripts/build-administrator.sh 2.4.0
```

The build requires Python 3.10 or newer. If the system `python3` is an older
version, select the supported interpreter explicitly:

```bash
python3.11 --version
FABRIC_PYTHON=python3.11 ./scripts/build-administrator-linux.sh 2.4.0
```

The build script validates the Python version before creating its virtual
environment. Python 3.6 and pip 9 are not supported.

The package repository must provide FastAPI `0.115.12` and PyInstaller `6.15`
or newer. If the default corporate mirror is stale, use the approved internal
mirror or PyPI explicitly:

```bash
export FABRIC_PYPI_INDEX_URL=https://<approved-pypi-mirror>/simple
# Or, only when permitted by your network policy:
# export FABRIC_PYPI_INDEX_URL=https://pypi.org/simple

FABRIC_PYTHON=/usr/bin/python3.12 \
  ./scripts/build-administrator-linux.sh 2.4.0
```

The build script accepts `FABRIC_PYPI_INDEX_URL` and requires
`pyinstaller>=6.15,<7`; it will no longer silently select the obsolete
PyInstaller 4.x series.

When the repository was copied from Windows, use the Linux-specific entry
point instead. It normalizes the existing build script's line endings before
running it:

```bash
cd /opt/temp/IntegrationFabric
chmod +x scripts/build-administrator-linux.sh
./scripts/build-administrator-linux.sh 2.4.0
```

The generated archive is:

```text
/opt/tibco/esb/integrationfabric/source/administrator/release/IntegrationFabricAdministrator-2.4.0-Linux-x64.tar.gz
```

## Clean setup from the copied Linux archive

For a fresh machine, copy the Linux Administrator archive into
`/opt/tibco/esb/IntegrationFabricSoftware/administrator/release/`, and copy
`backend/`, `drivers/`, and `java-bridge/` beside the `administrator/` and
`scripts/` folders. Then run the setup script. It creates the Control Plane
layout, runtime virtual environment, runtime adapter, and INI file:

If there is no `release/` folder, the setup script automatically runs
`scripts/linux/build-administrator-linux.sh` and generates the archive under
`administrator/release/`. This requires Linux Python 3.10+ and the build
dependencies to be available. To build version `1.0.0`, run:

```bash
./scripts/linux/setup-integration-fabric-linux.sh 1.0.0
```

The setup script also accepts an already extracted Linux Administrator folder:
copy `IntegrationFabricAdministrator` and its `_internal/` directory below
`/opt/tibco/esb/IntegrationFabricSoftware/administrator/` and set
`FABRIC_BUILD_ADMIN=false`.

The shared requirements file excludes the Windows-only
`python-qpid-proton-wheel` package on Linux. If an application uses AMQP 1.0,
install a Linux-compatible native Qpid Proton package from the approved Red
Hat package repository or internal Python mirror separately; RabbitMQ AMQP
0.9.1 uses `pika` and does not require it.

The setup script also skips the optional `ibm-db` package by default because
its Linux installation builds the IBM DB2 CLI driver and requires `gcc`. If a
deployed application uses DB2, have the Unix team install the compiler and
run the setup with:

```bash
FABRIC_INSTALL_DB2=true \
FABRIC_PYTHON=/usr/bin/python3.12 \
./scripts/linux/setup-integration-fabric-linux.sh 1.0.0
```

```bash
cd /opt/tibco/esb/IntegrationFabricSoftware
chmod +x scripts/linux/setup-integration-fabric-linux.sh
./scripts/linux/setup-integration-fabric-linux.sh 2.4.0
```

If the archive is the only Linux Administrator archive in the temp directory,
the version argument can be omitted. Set `FABRIC_PYTHON` if Python 3.12 is at
another path.

## Install the Control Plane files

```bash
mkdir -p /opt/tibco/esb/integrationfabric/control-plane
mkdir -p /opt/tibco/esb/integrationfabric/control-plane-data
mkdir -p /opt/tibco/esb/integrationfabric/runtime/data
mkdir -p /opt/tibco/esb/integrationfabric/apps
mkdir -p /opt/tibco/esb/integrationfabric/drivers
mkdir -p /opt/tibco/esb/integrationfabric/logs/control-plane
mkdir -p /opt/tibco/esb/integrationfabric/logs/runtime
mkdir -p /opt/tibco/esb/integrationfabric/run

tar -xzf /opt/tibco/esb/integrationfabric/source/administrator/release/IntegrationFabricAdministrator-2.4.0-Linux-x64.tar.gz \
  -C /opt/tibco/esb/integrationfabric/control-plane \
  --strip-components=1

cp /opt/tibco/esb/integrationfabric/control-plane/IntegrationFabricAdministrator \
   /opt/tibco/esb/integrationfabric/control-plane/integration-fabric-control-plane

chmod +x /opt/tibco/esb/integrationfabric/control-plane/integration-fabric-control-plane
```

The copy step provides the requested executable name:

```text
/opt/tibco/esb/integrationfabric/control-plane/integration-fabric-control-plane
```

## Install the runtime adapter before deploying applications

Building and installing the Administrator only starts the Control Plane APIs. It does **not** provide the runtime that executes deployed applications. Complete this section before using **Start**, **Run**, or **Debug** for an application.

Copy the Linux-compatible application runtime source and drivers below the same root, then create its virtual environment:

```bash
mkdir -p /opt/tibco/esb/integrationfabric/runtime
python3.12 -m venv /opt/tibco/esb/integrationfabric/runtime/.venv
/opt/tibco/esb/integrationfabric/runtime/.venv/bin/pip install   -r /opt/tibco/esb/integrationfabric/source/backend/requirements.txt
```

Create the runtime adapter at exactly this path:

```bash
vi /opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime
```

Use this content:

```bash
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=/opt/tibco/esb/integrationfabric/source/backend
export FABRIC_DRIVER_HOME=/opt/tibco/esb/integrationfabric/source/drivers
exec /opt/tibco/esb/IntegrationFabricSoftware/runtime/.venv/bin/python \
  /opt/tibco/esb/IntegrationFabricSoftware/backend/run_deployment.py "$@"
```

Make it executable and verify it exists:

```bash
chmod 755 /opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime
ls -l /opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime
/opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime --help
```

The adapter path in the INI file must match this path exactly:

```ini
runtime_command=/opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime --application {application} --environment {environment}
```

If this file is missing, application deployment fails with:
`[Errno 2] No such file or directory: '/opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime'`.

## Configure the current shell

Run these commands in the same shell that starts the Control Plane:

```bash
export FABRIC_ADMIN_HOME=/opt/tibco/esb/integrationfabric/control-plane
export FABRIC_ADMIN_HOST=0.0.0.0
export FABRIC_ADMIN_PORT=9080
export FABRIC_ADMIN_DATA_DIR=/opt/tibco/esb/integrationfabric/control-plane-data
export FABRIC_ADMIN_LOG_DIR=/opt/tibco/esb/integrationfabric/logs/control-plane
export FABRIC_ADMIN_PID_DIR=/opt/tibco/esb/integrationfabric/run

export FABRIC_ADMIN_API_KEY=dev-api-key-if
export FABRIC_ADMIN_SECRET_KEY=dev-api-key-if
```

`FABRIC_ADMIN_SECRET_KEY` must remain stable. Changing it can make previously encrypted deployment secrets unreadable.

## Start directly in the background

```bash
cd /opt/tibco/esb/integrationfabric/control-plane

nohup ./integration-fabric-control-plane \
  >> /opt/tibco/esb/integrationfabric/logs/control-plane/administrator.log 2>&1 &

echo $! > /opt/tibco/esb/integrationfabric/run/control-plane.pid
```

This is equivalent to running the executable with `&`, but `nohup` allows it to continue after the terminal session closes.

## Configure and run with an INI file

The Linux package includes `integration-fabric-control-plane.ini` and
`start-control-plane.sh`. The self-contained `build-administrator-linux.sh`
does not depend on `build-administrator.sh`, which may be an older Windows
copy. Edit the INI file before starting:

```bash
cd /opt/tibco/esb/integrationfabric/control-plane
vi integration-fabric-control-plane.ini
chmod 600 integration-fabric-control-plane.ini
chmod +x start-control-plane.sh
```

The INI file controls the host, port, data, log, and PID paths, security keys,
runtime command, driver directory, and runtime log directory. Start, stop,
restart, or check status without systemd:

```bash
./start-control-plane.sh start
./start-control-plane.sh status
./start-control-plane.sh restart
./start-control-plane.sh stop
```

The launcher applies the INI settings every time it runs. After editing the
INI file, use `restart`; no shell profile changes are required. A different
configuration file can be selected with:

```bash
FABRIC_ADMIN_INI=/opt/tibco/esb/integrationfabric/control-plane/custom.ini \
  ./start-control-plane.sh restart
```

To run it only for the current terminal session instead:

```bash
cd /opt/tibco/esb/integrationfabric/control-plane
./integration-fabric-control-plane \
  >> /opt/tibco/esb/integrationfabric/logs/control-plane/administrator.log 2>&1 &
echo $! > /opt/tibco/esb/integrationfabric/run/control-plane.pid
```

## Verify the process and health

```bash
cat /opt/tibco/esb/integrationfabric/run/control-plane.pid
ps -fp "$(cat /opt/tibco/esb/integrationfabric/run/control-plane.pid)"

curl http://localhost:9080/api/health
```

The health response should show:

```json
{
  "status": "ok",
  "component": "integration-fabric-control-plane",
  "runtimeAdapterConfigured": false
}
```

`runtimeAdapterConfigured` is `false` until a runtime command is configured. The Control Plane UI and management APIs can still run.

Open the UI at:

```text
http://<linux-host>:9080
```

The OpenAPI page is available at:

```text
http://<linux-host>:9080/docs
```

## Configure deployed application startup

The Control Plane needs the runtime adapter above to start on-premises applications. The INI file is preferred for direct-run deployments:

```bash
vi /opt/tibco/esb/integrationfabric/control-plane/integration-fabric-control-plane.ini
```

Set:

```ini
runtime_command=/opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime --application {application} --environment {environment}
```

If you are not using the INI file, configure the adapter in the same shell that starts the Control Plane:

```bash
export FABRIC_ADMIN_RUNTIME_COMMAND='/opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime --application {application} --environment {environment}'
```

The runtime command supports these placeholders:

```text
{application}     Extracted application directory
{package}        Extracted package directory
{environment}    Deployment environment
{deployment_id}  Control Plane deployment ID
{instance_id}    Runtime instance ID
```

For Linux application packages, use this install-root convention in Studio:

```text
/opt/tibco/esb/integrationfabric/apps/<application-name>
```

After adding the runtime command, stop and restart the Control Plane from the same shell so it inherits the variable.

## Deploy an application from Linux

Use the included API script to upload a package, create its deployment, and
start it automatically:

```bash
chmod +x /opt/tibco/esb/integrationfabric/source/scripts/linux/deploy-application.sh
export FABRIC_CONTROL_PLANE_URL=http://localhost:19080
export FABRIC_CONTROL_PLANE_KEY=dev-api-key-if
export FABRIC_DATA_PLANE=localhost
export FABRIC_NAMESPACE=default
export FABRIC_SECRETS_FILE=/opt/tibco/esb/temp/linux/deployment-secrets.json

/opt/tibco/esb/integrationfabric/source/scripts/linux/deploy-application.sh \
  /opt/tibco/esb/temp/linux/my-application.ifpkg dev
```

The script prints the generated Deployment ID. To deploy without starting,
set `FABRIC_START_AFTER_DEPLOY=false`. For a delivery-team token, set
`FABRIC_CONTROL_PLANE_KEY` to that token and set `FABRIC_TEAM_ID` when required.

## View logs

Control Plane process logs:

```bash
tail -f /opt/tibco/esb/integrationfabric/logs/control-plane/administrator.log
```

Control Plane application state, uploaded packages, deployment records, and deployment instance logs are stored below:

```text
/opt/tibco/esb/integrationfabric/control-plane-data/
```

Runtime application logs are stored below:

```text
/opt/tibco/esb/integrationfabric/logs/runtime/
```

## Stop manually

```bash
kill "$(cat /opt/tibco/esb/integrationfabric/run/control-plane.pid)"
rm -f /opt/tibco/esb/integrationfabric/run/control-plane.pid
```

Allow a short period for graceful shutdown. Use `kill -9` only if the process does not terminate normally.

## Important notes

- Do not copy the Windows `.exe` to Linux.
- Do not run the Control Plane from the Windows `backend` or Studio installation.
- SAP JCo native libraries and the Java bridge must be Linux-compatible.
- Configure SAP JCo drivers below `/opt/tibco/esb/integrationfabric/drivers`.
- Existing packages containing `/opt/integration-fabric/...` should be regenerated with the new `/opt/tibco/esb/integrationfabric/...` install root.
- If the Linux shell closes and `nohup` was not used, the background process may stop.

## Files and folders to copy from the repository

The current repository is a cross-platform source tree. Do not copy the Windows executable output and expect it to run on Linux. Use one of the following transfer options.

### Transfer from the current Windows machine

The current source root is:

```text
C:\Narayana\Integration-Tool\Software
```

Copy the following folders and files to this Linux staging location:

```text
/opt/temp/IntegrationFabric/
├── administrator/
│   ├── app/
│   ├── bin/fabricadmin
│   ├── web/
│   ├── requirements.txt
│   └── run_admin.py
├── backend/
│   ├── app/
│   ├── requirements.txt
│   ├── requirements-sap.txt
│   └── run_deployment.py
├── drivers/
│   └── <Linux-compatible vendor driver files>
├── java-bridge/
│   └── src/
├── scripts/
│   └── build-administrator.sh
└── docs/
```

The `docs/` folder is optional. The other entries are the recommended source transfer when the Linux host will build and run both the Control Plane and on-premises application workers.

For Control Plane-only operation, the minimum transfer is:

```text
administrator/app/
administrator/bin/fabricadmin
administrator/web/
administrator/requirements.txt
administrator/run_admin.py
scripts/build-administrator.sh
```

After copying to `/opt/tibco/esb/integrationfabric/source`, use it as the build source and install the generated Control Plane under:

```text
/opt/tibco/esb/integrationfabric/control-plane
```

Example Linux staging commands:

```bash
mkdir -p /opt/tibco/esb/integrationfabric/source
```

Do not copy the entire Windows `Software` directory blindly. In particular, exclude `.venv`, `__pycache__`, `node_modules`, Windows `dist` folders, Windows `.exe` files, `.dll` files, and any Windows-generated Java runtime.

### Control Plane only: minimum source files

If the Linux machine will build the Control Plane itself, copy:

```text
IntegrationFabric/
├── administrator/
│   ├── app/
│   ├── web/
│   ├── requirements.txt
│   └── run_admin.py
└── scripts/
    └── build-administrator.sh
```

The `administrator/app` directory contains the Control Plane API and lifecycle implementation. The `administrator/web` directory contains the bundled browser UI. The Linux build script creates the Linux-native Administrator executable.

Copy the complete repository to `/opt/tibco/esb/integrationfabric/source` if you want the build process, tests, documentation, and deployment tools available on the Linux host:

```bash
rsync -a --delete \
  --exclude='.git' \
  --exclude='*/.venv' \
  --exclude='*/__pycache__' \
  --exclude='*/dist' \
  --exclude='*/node_modules' \
  <repository>/ /opt/tibco/esb/integrationfabric/source/
```

The minimum source-only copy does not require `frontend/`, `images/`, `java-sdk/`, `drivers/`, or `backend/` to run the Control Plane UI and management APIs.

### Required for deployed on-premises applications

To allow the Control Plane to start packaged applications through `FABRIC_ADMIN_RUNTIME_COMMAND`, also copy or install:

```text
IntegrationFabric/
├── backend/
│   ├── app/
│   ├── requirements.txt
│   ├── requirements-sap.txt       # if SAP/JCo activities are used
│   └── run_deployment.py
├── drivers/
│   └── <vendor driver files>
└── java-bridge/
    ├── src/
    └── build/                     # build this on Linux; do not copy Windows output
```

Install the backend dependencies into a Linux virtual environment:

```bash
python3 -m venv /opt/tibco/esb/integrationfabric/runtime/.venv
/opt/tibco/esb/integrationfabric/runtime/.venv/bin/pip install -r \
  /opt/tibco/esb/integrationfabric/source/backend/requirements.txt
```

For SAP, build the Java bridge on Linux with a Linux JDK 17 or newer. The existing `java-bridge/build` directory may contain Windows DLLs and `java.exe`; it must not be reused on Linux. Place Linux-compatible SAP JCo files below:

```text
/opt/tibco/esb/integrationfabric/drivers/
```

Then set:

```bash
export FABRIC_DRIVER_HOME=/opt/tibco/esb/integrationfabric/drivers
export PYTHONPATH=/opt/tibco/esb/integrationfabric/source/backend
```

Create `/opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime` with:

```bash
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=/opt/tibco/esb/integrationfabric/source/backend
exec /opt/tibco/esb/IntegrationFabricSoftware/runtime/.venv/bin/python \
  /opt/tibco/esb/IntegrationFabricSoftware/backend/run_deployment.py "$@"
```

Configure the Control Plane before starting it:

```bash
export FABRIC_ADMIN_RUNTIME_COMMAND='/opt/tibco/esb/integrationfabric/runtime/integration-fabric-runtime --application {application} --environment {environment}'
```

### Optional files

Copy these only when needed:

```text
frontend/       Only if rebuilding the Studio/browser frontend
java-sdk/       Only if the project requires Java SDK source or vendor integration
docs/           Documentation only
tests/          Validation only
deploy/         Additional deployment assets, if used by your release process
```

### Do not copy as Linux runtime binaries

Do not use these Windows-generated artifacts on Linux:

```text
administrator/dist/
backend/dist/
backend/.venv/
java-bridge/build/runtime/    # if generated on Windows
java-bridge/build/**/*.dll
java-bridge/build/**/java.exe
frontend/node_modules/
```

A Linux-native Administrator package and Linux-native Java bridge must be built on Linux or in a Linux CI runner.

### Remote data-plane agents and team isolation

The Linux scripts now include a real remote data-plane agent. It is a normal foreground process launched with `nohup`; it does not require `systemctl`.

The central configuration is:

```text
/opt/tibco/esb/IntegrationFabricSoftware/scripts/linux/integration-fabric-control-plane.ini
```

Use one `[data-plane]` section per agent process and map the delivery-team aliases in `[data-teams]`:

```ini
[data-teams]
team1=bddteam1
team2=bddteam2

[data-plane]
id=team1-data-plane
namespace=bddteam1
```

Each agent sends heartbeats, polls its assigned deployments, downloads the package, starts the configured runtime workers, injects deployment secrets, and reports instance health and log tails. The Control Plane only returns deployments assigned to that agent's `data-plane.id`, so applications remain isolated by data plane and namespace.

Start the complete flow after editing the INI:

```bash
cd /opt/tibco/esb/IntegrationFabricSoftware/scripts/linux
chmod 700 *.sh
./00-setup-and-register.sh
```

For multiple data planes on one Linux host, create a separate INI copy for each plane and run one agent per INI:

```bash
FABRIC_CONFIG_FILE=team1.ini ./05-start-data-plane-agent.sh > /opt/tibco/esb/IntegrationFabricSoftware/logs/team1-agent.log 2>&1 &
FABRIC_CONFIG_FILE=team2.ini ./05-start-data-plane-agent.sh > /opt/tibco/esb/IntegrationFabricSoftware/logs/team2-agent.log 2>&1 &
```

The updated `administrator` executable must be rebuilt and copied to the target Control Plane before using remote lifecycle operations. If the old executable is still running, it will continue to return the previous localhost-only adapter error.
