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

### Corporate TLS certificate or proxy

`UNABLE_TO_GET_ISSUER_CERT_LOCALLY` from npm and `CERTIFICATE_VERIFY_FAILED` from pip mean the build machine does not trust the CA used by an HTTPS-inspecting corporate proxy. This is download trust, not Windows executable signing. Obtain the organization's root and intermediate CA chain from IT as one PEM file. Do not commit the certificate to this repository.

Configure both Node/npm and Python/pip from PowerShell, then open a new terminal:

```powershell
$ca = 'C:\Certificates\company-ca-chain.pem'
npm.cmd config set cafile "$ca" --location=user
npm.cmd config set strict-ssl true --location=user
py -3.11 -m pip config --user set global.cert "$ca"
[Environment]::SetEnvironmentVariable('NODE_EXTRA_CA_CERTS', $ca, 'User')
[Environment]::SetEnvironmentVariable('PIP_CERT', $ca, 'User')
```

For the current terminal, set the values as well:

```powershell
$env:NODE_EXTRA_CA_CERTS = $ca
$env:PIP_CERT = $ca
$env:REQUESTS_CA_BUNDLE = $ca
```

Keep SSL verification enabled. If the company requires an explicit proxy, obtain its URL from IT and additionally configure `npm config set https-proxy <proxy-url> --location=user`, `HTTPS_PROXY`, and `ELECTRON_GET_USE_PROXY=1`.

After a failed `npm ci`, close running Node/Electron processes and delete the incomplete `frontend\node_modules` directory before retrying. The desktop build script now stops at the first failed npm, pip, Electron, or PyInstaller command instead of reporting a misleading successful sidecar build.

The desktop runtime is built with Python 3.11. The AMQP 1.0 connector uses the prebuilt `python-qpid-proton-wheel` distribution because the upstream `python-qpid-proton` 0.40 source release does not provide a CPython 3.11 Windows wheel and otherwise requires Microsoft Visual C++ Build Tools. Before PyInstaller starts, the build imports every external connector module and fails if a package or native DLL is unavailable.

The unpacked executable is:

```text
frontend\release\win-unpacked\Integration Fabric Studio.exe
```

For production distribution, configure a company `.pfx` code-signing certificate through environment variables. A signing certificate is optional for producing an installer, but recommended for publisher identity and SmartScreen reputation:

```powershell
$env:WIN_CSC_LINK = 'C:\Certificates\integration-fabric-signing.pfx'
$env:WIN_CSC_KEY_PASSWORD = '<password-from-secret-store>'
npm.cmd run desktop:installer
```

Do not put the certificate or password in `package.json` or source control. Electron Builder automatically discovers `WIN_CSC_LINK`/`WIN_CSC_KEY_PASSWORD` (and supports `CSC_LINK`/`CSC_KEY_PASSWORD` as fallbacks).

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

For production configuration, API authentication, encrypted secrets, package validation rules, machine registration, runtime command adapters, lifecycle transitions, monitoring, audit, backup, and troubleshooting, see [ADMINISTRATOR_GUIDE.md](ADMINISTRATOR_GUIDE.md).

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
