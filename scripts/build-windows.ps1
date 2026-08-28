$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root/frontend"; npm install; npm run build; Pop-Location
Push-Location "$root/backend"
if (!(Test-Path .venv)) { py -3.12 -m venv .venv }
& .\.venv\Scripts\pip install -r requirements.txt pyinstaller
& .\.venv\Scripts\pyinstaller --noconfirm --name IntegrationFabric --add-data "..\frontend\dist;frontend\dist" --paths . run_desktop.py
Pop-Location
if (Get-Command makensis -ErrorAction SilentlyContinue) { makensis "$root\scripts\installer.nsi" } else { Write-Host 'PyInstaller build complete. Install NSIS to generate setup.exe.' }
