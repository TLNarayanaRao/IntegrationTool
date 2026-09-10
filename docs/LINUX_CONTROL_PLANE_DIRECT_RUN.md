# Linux Control Plane: Direct Run Guide

This guide runs the Integration Fabric Control Plane directly from the shell. It does not use `systemctl` or require a systemd service. The Unix team only needs to provision the `/opt/integrationfabric` directory and its permissions.

## Directory layout

All Control Plane state, packages, runtime files, drivers, and logs are kept below one root directory:

```text
/opt/integrationfabric/
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
cd /opt/integrationfabric/source
chmod +x scripts/build-administrator.sh
./scripts/build-administrator.sh 2.4.0
```

The generated archive is:

```text
/opt/integrationfabric/source/administrator/release/IntegrationFabricAdministrator-2.4.0-Linux-x64.tar.gz
```

## Install the Control Plane files

```bash
mkdir -p /opt/integrationfabric/control-plane
mkdir -p /opt/integrationfabric/control-plane-data
mkdir -p /opt/integrationfabric/runtime/data
mkdir -p /opt/integrationfabric/apps
mkdir -p /opt/integrationfabric/drivers
mkdir -p /opt/integrationfabric/logs/control-plane
mkdir -p /opt/integrationfabric/logs/runtime
mkdir -p /opt/integrationfabric/run

tar -xzf /opt/integrationfabric/source/administrator/release/IntegrationFabricAdministrator-2.4.0-Linux-x64.tar.gz \
  -C /opt/integrationfabric/control-plane \
  --strip-components=1

cp /opt/integrationfabric/control-plane/IntegrationFabricAdministrator \
   /opt/integrationfabric/control-plane/integration-fabric-control-plane

chmod +x /opt/integrationfabric/control-plane/integration-fabric-control-plane
```

The copy step provides the requested executable name:

```text
/opt/integrationfabric/control-plane/integration-fabric-control-plane
```

## Configure the current shell

Run these commands in the same shell that starts the Control Plane:

```bash
export FABRIC_ADMIN_HOME=/opt/integrationfabric/control-plane
export FABRIC_ADMIN_HOST=0.0.0.0
export FABRIC_ADMIN_PORT=9080
export FABRIC_ADMIN_DATA_DIR=/opt/integrationfabric/control-plane-data
export FABRIC_ADMIN_LOG_DIR=/opt/integrationfabric/logs/control-plane
export FABRIC_ADMIN_PID_DIR=/opt/integrationfabric/run

export FABRIC_ADMIN_API_KEY='replace-with-a-long-admin-key'
export FABRIC_ADMIN_SECRET_KEY='replace-with-a-stable-encryption-key'
```

`FABRIC_ADMIN_SECRET_KEY` must remain stable. Changing it can make previously encrypted deployment secrets unreadable.

## Start directly in the background

```bash
cd /opt/integrationfabric/control-plane

nohup ./integration-fabric-control-plane \
  >> /opt/integrationfabric/logs/control-plane/administrator.log 2>&1 &

echo $! > /opt/integrationfabric/run/control-plane.pid
```

This is equivalent to running the executable with `&`, but `nohup` allows it to continue after the terminal session closes.

To run it only for the current terminal session instead:

```bash
cd /opt/integrationfabric/control-plane
./integration-fabric-control-plane \
  >> /opt/integrationfabric/logs/control-plane/administrator.log 2>&1 &
echo $! > /opt/integrationfabric/run/control-plane.pid
```

## Verify the process and health

```bash
cat /opt/integrationfabric/run/control-plane.pid
ps -fp "$(cat /opt/integrationfabric/run/control-plane.pid)"

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

The Control Plane needs a Linux runtime adapter to start on-premises applications. Configure the adapter only after the Linux runtime and its Python dependencies are available:

```bash
export FABRIC_ADMIN_RUNTIME_COMMAND='/usr/local/bin/integration-fabric-runtime --application {application} --environment {environment}'
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
/opt/integrationfabric/apps/<application-name>
```

After adding the runtime command, stop and restart the Control Plane from the same shell so it inherits the variable.

## View logs

Control Plane process logs:

```bash
tail -f /opt/integrationfabric/logs/control-plane/administrator.log
```

Control Plane application state, uploaded packages, deployment records, and deployment instance logs are stored below:

```text
/opt/integrationfabric/control-plane-data/
```

Runtime application logs are stored below:

```text
/opt/integrationfabric/logs/runtime/
```

## Stop manually

```bash
kill "$(cat /opt/integrationfabric/run/control-plane.pid)"
rm -f /opt/integrationfabric/run/control-plane.pid
```

Allow a short period for graceful shutdown. Use `kill -9` only if the process does not terminate normally.

## Important notes

- Do not copy the Windows `.exe` to Linux.
- Do not run the Control Plane from the Windows `backend` or Studio installation.
- SAP JCo native libraries and the Java bridge must be Linux-compatible.
- Configure SAP JCo drivers below `/opt/integrationfabric/drivers`.
- Existing packages containing `/opt/integration-fabric/...` should be regenerated with the new `/opt/integrationfabric/...` install root.
- If the Linux shell closes and `nohup` was not used, the background process may stop.
