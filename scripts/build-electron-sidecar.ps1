$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Assert-CommandSucceeded([string]$Step, [int]$ExitCode) {
    if ($ExitCode -ne 0) {
        throw "$Step failed with exit code $ExitCode. Correct the first reported error before continuing."
    }
}

if (!(Test-Path "$root\frontend\node_modules\electron\dist\electron.exe")) {
    if (!(Test-Path "$root\frontend\node_modules\electron\install.js")) {
        throw "Electron dependencies are incomplete. Run npm ci successfully in frontend before desktop:installer."
    }
    Push-Location "$root\frontend"
    try {
        node node_modules\electron\install.js
        Assert-CommandSucceeded 'Electron binary download' $LASTEXITCODE
    } finally { Pop-Location }
}

Push-Location "$root\frontend"
try {
    npm.cmd run build
    Assert-CommandSucceeded 'Frontend production build' $LASTEXITCODE
} finally { Pop-Location }

Push-Location "$root\backend"
try {
    if (!(Test-Path .venv)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv .venv }
        else { python -m venv .venv }
    }
    $runtimePython = & .\.venv\Scripts\python.exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    Assert-CommandSucceeded 'Python version detection' $LASTEXITCODE
    if ($runtimePython.Trim() -ne '3.11') {
        throw "Desktop runtime builds require Python 3.11, but backend\.venv uses Python $runtimePython. Delete backend\.venv and install Python 3.11 x64 before rebuilding."
    }
    # A venv created by older Python tooling can retain setuptools 65.x. That
    # release imports pkgutil.ImpImporter, which was removed in Python 3.12.
    # Upgrade the isolated build toolchain explicitly before PyInstaller runs.
    & .\.venv\Scripts\python.exe -m pip install --upgrade -r requirements-build.txt
    Assert-CommandSucceeded 'Python build-tool installation' $LASTEXITCODE
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    Assert-CommandSucceeded 'Python runtime dependency installation' $LASTEXITCODE
    & .\.venv\Scripts\python.exe "$root\scripts\verify-runtime-dependencies.py"
    Assert-CommandSucceeded 'Runtime connector dependency verification' $LASTEXITCODE
    & .\.venv\Scripts\python.exe -m compileall -q app run_sidecar.py
    Assert-CommandSucceeded 'Python 3.11 backend syntax verification' $LASTEXITCODE
    & .\.venv\Scripts\python.exe -c "import app.main; print('Backend application package import passed')"
    Assert-CommandSucceeded 'Backend application package verification' $LASTEXITCODE
    # Explicitly collect the local `app` package. Some clean Python 3.11
    # environments resolve generic namespace packages differently during
    # analysis, which can otherwise produce an EXE without app.main.
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --name IntegrationFabricRuntime --add-data "$root\frontend\dist;frontend\dist" --paths "$root\backend" --hidden-import app.main --collect-submodules app run_sidecar.py
    Assert-CommandSucceeded 'Runtime executable build' $LASTEXITCODE
} finally { Pop-Location }

if (!(Test-Path "$root\backend\dist\IntegrationFabricRuntime\IntegrationFabricRuntime.exe")) {
    throw "Runtime executable output was not created."
}
& "$root\backend\.venv\Scripts\python.exe" "$root\scripts\smoke-test-packaged-runtime.py" "$root\backend\dist\IntegrationFabricRuntime\IntegrationFabricRuntime.exe"
Assert-CommandSucceeded 'Packaged runtime health check' $LASTEXITCODE
Write-Host "Electron sidecar ready: $root\backend\dist\IntegrationFabricRuntime"
