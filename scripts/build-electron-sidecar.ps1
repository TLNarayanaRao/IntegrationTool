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
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
    & .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --name IntegrationFabricRuntime --add-data "$root\frontend\dist;frontend\dist" --paths "$root\backend" run_sidecar.py
} finally { Pop-Location }

Write-Host "Electron sidecar ready: $root\backend\dist\IntegrationFabricRuntime"
