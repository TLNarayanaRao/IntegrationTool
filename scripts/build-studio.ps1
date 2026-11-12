param(
    [string]$Version = $env:MINA_VERSION,
    [ValidateSet('nsis', 'dir')]
    [string]$Target = 'nsis',
    [switch]$PublicRelease,
    [string]$ComplianceReview = $env:MINA_COMPLIANCE_REVIEW
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
$previousVersion = $env:MINA_VERSION
try {
    $env:MINA_VERSION = $Version
    Write-Host "Building MINA Studio version $Version ($Target)"
    & npm.cmd run desktop:prepare
    if ($LASTEXITCODE -ne 0) { throw "Studio preparation failed with exit code $LASTEXITCODE." }
    if ($PublicRelease) {
        if ([string]::IsNullOrWhiteSpace($ComplianceReview)) { throw 'Public release requires an evidence-backed compliance review file; see compliance/release-review.example.json.' }
        $reviewPython = Join-Path $root 'backend\build\.venv311\Scripts\python.exe'
        & $reviewPython "$root\scripts\verify-release-compliance.py" "$root\compliance\generated\runtime" --review $ComplianceReview
        if ($LASTEXITCODE -ne 0) { throw 'Public release compliance review is incomplete.' }
    }
    # Finish resource edits/signing before hashing the unpacked payload, then
    # compile NSIS from that exact prepackaged directory.
    & .\node_modules\.bin\electron-builder.cmd --win dir "-c.extraMetadata.version=$Version"
    if ($LASTEXITCODE -ne 0) { throw "Electron Builder failed with exit code $LASTEXITCODE." }
    $buildPython = Join-Path $root 'backend\build\.venv311\Scripts\python.exe'
    $payload = Join-Path $frontend 'release\win-unpacked'
    foreach ($runtimeName in @('MINARuntime','MINAWorker')) {
        # Electron Builder may sign embedded EXEs. Refresh their manifests
        # after signing, before hashing the enclosing Studio payload.
        $embedded = Join-Path $payload "resources\runtime\$runtimeName"
        & $buildPython "$root\scripts\artifact-sbom.py" $embedded --output (Join-Path $embedded 'legal\SBOM.artifact.cdx.json') --version $Version
        if ($LASTEXITCODE -ne 0) { throw "Embedded $runtimeName SBOM generation failed." }
    }
    $oldManifest = Join-Path $payload 'resources\legal\SBOM.artifact.cdx.json'
    if (Test-Path -LiteralPath $oldManifest) { Remove-Item -LiteralPath $oldManifest }
    $softwareManifest = Join-Path $payload 'resources\legal\SBOM.software.cdx.json'
    & $buildPython "$root\scripts\artifact-sbom.py" $payload --output $softwareManifest --version $Version --software-only
    if ($LASTEXITCODE -ne 0) { throw 'Studio artifact compliance verification failed.' }
    if ($Target -eq 'nsis') {
        & .\node_modules\.bin\electron-builder.cmd --win nsis --prepackaged $payload "-c.extraMetadata.version=$Version"
        if ($LASTEXITCODE -ne 0) { throw 'NSIS packaging failed.' }
    }
    # NSIS adds/signs its elevation helper. Hash the final delivered payload,
    # not an earlier pre-installer snapshot. Keep the full hash manifest next
    # to the installer to avoid self-referential hashes inside the payload.
    $manifest = Join-Path $frontend "release\MINAStudio-$Version-Payload-SBOM.cdx.json"
    $inventoryArgs = @()
    if ($Target -eq 'nsis') { $inventoryArgs = @('--installer', (Join-Path $frontend "release\MINAStudio-$Version-Setup.exe")) }
    & $buildPython "$root\scripts\artifact-sbom.py" $payload --output $manifest --version $Version @inventoryArgs
    if ($LASTEXITCODE -ne 0) { throw 'Final payload SBOM generation failed.' }
    & $buildPython "$root\scripts\artifact-sbom.py" $payload --output $manifest --version $Version @inventoryArgs --verify
    if ($LASTEXITCODE -ne 0) { throw 'Packaged payload changed after SBOM generation.' }
    if ($Target -eq 'nsis') {
        & $buildPython "$root\scripts\verify-studio-installer.py" (Join-Path $frontend "release\MINAStudio-$Version-Setup.exe")
        if ($LASTEXITCODE -ne 0) { throw 'Extracted installer verification failed.' }
    }
    Write-Host "Studio version $Version ready under $frontend\release"
} finally {
    $env:MINA_VERSION = $previousVersion
    Pop-Location
}
