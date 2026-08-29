# Integration Fabric build and distribution

## Product outputs

Integration Fabric has three independently distributable components:

1. **Studio** — an Electron desktop IDE for Windows. It embeds the React designer and a packaged Python sidecar.
2. **Enterprise Administrator** — a Linux or Windows web control plane for on-premises package management.
3. **Runtime package** — a portable `.ifpkg`, `.tar.gz`, or `.ear`-compatible archive produced by Studio for either on-premises Administrator deployment or cloud/Kubernetes deployment.

## Build Studio on Windows

Prerequisites:

- Windows 10 or Windows 11 x64
- Node.js satisfying Vite's requirement (`20.19+` or `22.12+`)
- Python 3.11 x64 available through the `py` launcher
- Internet access on the build machine for the first dependency installation

Run from a normal PowerShell or Command Prompt. PowerShell is used internally by the npm build script, but installed Studio users do not need PowerShell, Node.js, or Python.

```powershell
cd D:\Integration-tool\IntegrationFabric\frontend
npm ci
npm run desktop:installer
```

Output:

```text
frontend\release\IntegrationFabricStudio-0.2.0-Setup.exe
```

The installer is machine-wide so different Windows users can launch Studio in parallel. Each user gets an independent local runtime port and workspace data directory under that user's application-data profile.

Useful development commands:

```powershell
npm run desktop:dev       # Vite UI in an Electron window with the Python sidecar
npm run desktop:unpacked  # Build without creating the installer
npm run desktop:installer # Build the sidecar and final Setup.exe
```

The unpacked executable is:

```text
frontend\release\win-unpacked\Integration Fabric Studio.exe
```

For production distribution, configure a company `.pfx` code-signing certificate in the CI/CD secret store and sign the installer and executables. Do not put certificate passwords in the repository.

## Build Enterprise Administrator on Windows

```powershell
cd D:\Integration-tool\IntegrationFabric
.\scripts\build-administrator.ps1
```

Or from the `frontend` directory:

```powershell
npm run administrator:windows
```

Outputs:

```text
administrator\dist\IntegrationFabricAdministrator\IntegrationFabricAdministrator.exe
administrator\release\IntegrationFabricAdministrator-Windows-x64.zip
```

Run it:

```powershell
$env:FABRIC_ADMIN_DATA_DIR = "D:\IntegrationFabricAdmin\data"
& .\administrator\dist\IntegrationFabricAdministrator\IntegrationFabricAdministrator.exe
```

Open `http://localhost:9080`. To listen on a different address or port, set `FABRIC_ADMIN_HOST` and `FABRIC_ADMIN_PORT`.

## Build Enterprise Administrator on Linux

PyInstaller produces native binaries, so the Linux artifact must be built on Linux or in a Linux CI runner. It cannot be produced directly by a Windows Python installation.

Prerequisites on a Debian/Ubuntu build host:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv
```

Build:

```bash
cd /path/to/IntegrationFabric
chmod +x scripts/build-administrator.sh administrator/bin/fabricadmin
./scripts/build-administrator.sh
```

Output:

```text
administrator/release/IntegrationFabricAdministrator-Linux-x64.tar.gz
```

Install and start:

```bash
sudo mkdir -p /opt/integration-fabric/administrator
sudo tar -xzf administrator/release/IntegrationFabricAdministrator-Linux-x64.tar.gz \
  -C /opt/integration-fabric/administrator --strip-components=1
sudo chmod +x /opt/integration-fabric/administrator/IntegrationFabricAdministrator
sudo chmod +x /opt/integration-fabric/administrator/bin/fabricadmin
export FABRIC_ADMIN_HOME=/opt/integration-fabric/administrator
./administrator/bin/fabricadmin start
./administrator/bin/fabricadmin status
```

The default Administrator URL is `http://linux-host:9080`.

## Run Administrator as a container

```bash
docker build -f Dockerfile.administrator -t integration-fabric-administrator:0.1.0 .
docker run -d --name fabric-admin -p 9080:9080 \
  -v fabric-admin-data:/var/lib/integration-fabric/administrator \
  integration-fabric-administrator:0.1.0
```

## Create deployment packages in Studio

Open **Packaging** in Project Explorer or select **Package** on the ribbon. Configure:

- Artifact name and version
- Target: **On-premises Linux** or **Cloud / Kubernetes**
- Target environment
- Archive: `.ifpkg`, `.tar.gz`, or `.ear`

An on-premises package contains an Administrator deployment descriptor. A cloud package contains a Docker build input and Kubernetes deployment manifest. Password property values are removed from both outputs and replaced by deployment-time secret requirements.

The `.ifproject` file remains the editable Studio project. The `.ifpkg` file is the immutable deployment artifact.
