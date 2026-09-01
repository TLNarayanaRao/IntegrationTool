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

& "$root\scripts\build-java-bridge.ps1"
Assert-CommandSucceeded 'Java connector bridge build' $LASTEXITCODE

Push-Location "$root\backend"
try {
    $venvPath = "$root\backend\.venv"
    $buildPython = Join-Path $venvPath 'Scripts\python.exe'
    if (Test-Path $buildPython) {
        $existingVersion = & $buildPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        Assert-CommandSucceeded 'Existing Python version detection' $LASTEXITCODE
        if ($existingVersion.Trim() -ne '3.11') {
            Write-Host "backend\.venv uses Python $existingVersion; using an isolated Python 3.11 packaging environment instead."
            $venvPath = "$root\backend\build\.venv311"
            $buildPython = Join-Path $venvPath 'Scripts\python.exe'
        }
    }
    if (!(Test-Path $buildPython)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv $venvPath }
        else { python -m venv $venvPath }
        Assert-CommandSucceeded 'Python 3.11 packaging environment creation' $LASTEXITCODE
    }
    $runtimePython = & $buildPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    Assert-CommandSucceeded 'Python version detection' $LASTEXITCODE
    if ($runtimePython.Trim() -ne '3.11') {
        throw "Desktop runtime builds require Python 3.11, but the packaging environment uses Python $runtimePython. Install Python 3.11 x64 and retry."
    }
    # A venv created by older Python tooling can retain setuptools 65.x. That
    # release imports pkgutil.ImpImporter, which was removed in Python 3.12.
    # Upgrade the isolated build toolchain explicitly before PyInstaller runs.
    & $buildPython -m pip install --upgrade -r requirements-build.txt
    Assert-CommandSucceeded 'Python build-tool installation' $LASTEXITCODE
    & $buildPython -m pip install -r requirements.txt
    Assert-CommandSucceeded 'Python runtime dependency installation' $LASTEXITCODE
    & $buildPython "$root\scripts\verify-runtime-dependencies.py"
    Assert-CommandSucceeded 'Runtime connector dependency verification' $LASTEXITCODE
    & $buildPython -m compileall -q app run_sidecar.py
    Assert-CommandSucceeded 'Python 3.11 backend syntax verification' $LASTEXITCODE
    & $buildPython -c "import app.main; print('Backend application package import passed')"
    Assert-CommandSucceeded 'Backend application package verification' $LASTEXITCODE
    # Explicitly collect the local `app` package. Some clean Python 3.11
    # environments resolve generic namespace packages differently during
    # analysis, which can otherwise produce an EXE without app.main.
    & $buildPython -m PyInstaller --noconfirm --clean --name IntegrationFabricRuntime --add-data "$root\frontend\dist;frontend\dist" --paths "$root\backend" --hidden-import app.main --hidden-import ibm_db --hidden-import ibm_db_dbi --collect-submodules app --collect-submodules databricks run_sidecar.py
    Assert-CommandSucceeded 'Runtime executable build' $LASTEXITCODE
} finally { Pop-Location }

if (!(Test-Path "$root\backend\dist\IntegrationFabricRuntime\IntegrationFabricRuntime.exe")) {
    throw "Runtime executable output was not created."
}
Copy-Item -Recurse -Force "$root\java-bridge\build" "$root\backend\dist\IntegrationFabricRuntime\java-bridge"
& $buildPython "$root\scripts\smoke-test-packaged-runtime.py" "$root\backend\dist\IntegrationFabricRuntime\IntegrationFabricRuntime.exe"
Assert-CommandSucceeded 'Packaged runtime health check' $LASTEXITCODE
Write-Host "Electron sidecar ready: $root\backend\dist\IntegrationFabricRuntime"
