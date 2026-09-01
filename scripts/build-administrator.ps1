param([string]$Version = $env:FABRIC_VERSION)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$admin = Join-Path $root 'administrator'
if ([string]::IsNullOrWhiteSpace($Version)) { $Version = '2.1.0' }
$Version = $Version.Trim()
if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') { throw "Invalid semantic version '$Version'." }
Push-Location $admin
try {
    if (!(Test-Path .venv)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv .venv }
        else { python -m venv .venv }
    }
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
    $buildInfo = Join-Path $admin 'build\build_info.json'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $buildInfo) | Out-Null
    @{ version = $Version; builtAt = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $buildInfo -Encoding utf8
    & .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --name IntegrationFabricAdministrator --add-data "$admin\web;web" --add-data "$buildInfo;." --paths "$admin" run_admin.py
    New-Item -ItemType Directory -Force -Path "$admin\dist\IntegrationFabricAdministrator\bin" | Out-Null
    Copy-Item -LiteralPath "$admin\bin\fabricadmin.cmd" -Destination "$admin\dist\IntegrationFabricAdministrator\bin\fabricadmin.cmd" -Force
    New-Item -ItemType Directory -Force -Path "$admin\release" | Out-Null
    $archive = "$admin\release\IntegrationFabricAdministrator-$Version-Windows-x64.zip"
    if (Test-Path $archive) { Remove-Item -LiteralPath $archive -Force }
    Compress-Archive -Path "$admin\dist\IntegrationFabricAdministrator\*" -DestinationPath $archive
    Write-Host "Windows Administrator $Version ready: $admin\dist\IntegrationFabricAdministrator\IntegrationFabricAdministrator.exe"
    Write-Host "Windows distribution: $archive"
} finally { Pop-Location }
