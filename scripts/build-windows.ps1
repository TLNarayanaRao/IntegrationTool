$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root/frontend"; npm install; npm run build; Pop-Location
& powershell -ExecutionPolicy Bypass -File "$root/scripts/build-java-bridge.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Java bridge build failed.' }
Push-Location "$root/backend"
if (!(Test-Path .venv)) { py -3.12 -m venv .venv }
& .\.venv\Scripts\pip install -r requirements.txt pyinstaller
& .\.venv\Scripts\pyinstaller --noconfirm --name IntegrationFabric --add-data "..\frontend\dist;frontend\dist" --paths . run_desktop.py
Pop-Location
if (!(Test-Path "$root/backend/dist/IntegrationFabric/IntegrationFabric.exe")) { throw 'PyInstaller runtime output was not created.' }
Copy-Item -Recurse -Force "$root/java-bridge/build" "$root/backend/dist/IntegrationFabric/java-bridge"
if (Get-Command makensis -ErrorAction SilentlyContinue) { makensis "$root\scripts\installer.nsi" } else { Write-Host 'PyInstaller build complete. Install NSIS to generate setup.exe.' }
