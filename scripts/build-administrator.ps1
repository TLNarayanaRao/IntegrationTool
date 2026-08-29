$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$admin = Join-Path $root 'administrator'
Push-Location $admin
try {
    if (!(Test-Path .venv)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv .venv }
        else { python -m venv .venv }
    }
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
    & .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --name IntegrationFabricAdministrator --add-data "$admin\web;web" --paths "$admin" run_admin.py
    New-Item -ItemType Directory -Force -Path "$admin\dist\IntegrationFabricAdministrator\bin" | Out-Null
    Copy-Item -LiteralPath "$admin\bin\fabricadmin.cmd" -Destination "$admin\dist\IntegrationFabricAdministrator\bin\fabricadmin.cmd" -Force
    New-Item -ItemType Directory -Force -Path "$admin\release" | Out-Null
    $archive = "$admin\release\IntegrationFabricAdministrator-Windows-x64.zip"
    if (Test-Path $archive) { Remove-Item -LiteralPath $archive -Force }
    Compress-Archive -Path "$admin\dist\IntegrationFabricAdministrator\*" -DestinationPath $archive
    Write-Host "Windows Administrator ready: $admin\dist\IntegrationFabricAdministrator\IntegrationFabricAdministrator.exe"
    Write-Host "Windows distribution: $archive"
} finally { Pop-Location }
