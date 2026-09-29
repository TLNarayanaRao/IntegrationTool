param([string]$Version = $env:FABRIC_VERSION, [ValidateSet('nsis','dir')][string]$Target = 'nsis')
$ErrorActionPreference = 'Stop'
$frontend = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend'
if ([string]::IsNullOrWhiteSpace($Version)) { $Version = (Get-Content (Join-Path $frontend 'package.json') -Raw | ConvertFrom-Json).version }
if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$') { throw 'Supply a semantic version, e.g. 1.2.0.' }
Push-Location $frontend
$previousVersion = $env:MINA_CP_VERSION
try {
    if (!(Test-Path 'node_modules/.bin/electron-builder.cmd')) { throw 'Run npm ci in frontend first.' }
    & node --test control-plane-desktop/policy.test.cjs control-plane-desktop/lifecycle.test.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Desktop client tests failed.' }
    $env:MINA_CP_VERSION = $Version
    & .\node_modules\.bin\electron-builder.cmd --config control-plane-desktop/builder.cjs --win $Target
    if ($LASTEXITCODE -ne 0) { throw 'Control Plane desktop packaging failed.' }
    Write-Host "Windows client ready under $frontend/release-control-plane. No Python backend is bundled."
} finally { $env:MINA_CP_VERSION = $previousVersion; Pop-Location }
