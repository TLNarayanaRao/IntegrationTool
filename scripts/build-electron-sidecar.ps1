$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (!(Test-Path "$root\frontend\node_modules\electron\dist\electron.exe")) {
    Push-Location "$root\frontend"
    try { node node_modules\electron\install.js } finally { Pop-Location }
}

Push-Location "$root\frontend"
try {
    npm run build
} finally { Pop-Location }

Push-Location "$root\backend"
try {
    if (!(Test-Path .venv)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv .venv }
        else { python -m venv .venv }
    }
    # A venv created by older Python tooling can retain setuptools 65.x. That
    # release imports pkgutil.ImpImporter, which was removed in Python 3.12.
    # Upgrade the isolated build toolchain explicitly before PyInstaller runs.
    & .\.venv\Scripts\python.exe -m pip install --upgrade -r requirements-build.txt
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --name IntegrationFabricRuntime --add-data "$root\frontend\dist;frontend\dist" --paths "$root\backend" run_sidecar.py
} finally { Pop-Location }

Write-Host "Electron sidecar ready: $root\backend\dist\IntegrationFabricRuntime"
