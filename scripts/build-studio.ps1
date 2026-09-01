param(
    [string]$Version = $env:FABRIC_VERSION,
    [ValidateSet('nsis', 'dir')]
    [string]$Target = 'nsis'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend'

if ([string]::IsNullOrWhiteSpace($Version)) {
    $package = Get-Content -LiteralPath (Join-Path $frontend 'package.json') -Raw | ConvertFrom-Json
    $Version = [string]$package.version
}
$Version = $Version.Trim()
if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
    throw "Version '$Version' is not valid semantic versioning. Use a value such as 2.4.0 or 2.4.0-rc.1."
}

Push-Location $frontend
try {
    Write-Host "Building Integration Fabric Studio version $Version ($Target)"
    & npm.cmd run desktop:prepare
    if ($LASTEXITCODE -ne 0) { throw "Studio preparation failed with exit code $LASTEXITCODE." }
    & .\node_modules\.bin\electron-builder.cmd --win $Target "-c.extraMetadata.version=$Version"
    if ($LASTEXITCODE -ne 0) { throw "Electron Builder failed with exit code $LASTEXITCODE." }
    Write-Host "Studio version $Version ready under $frontend\release"
} finally {
    Pop-Location
}
