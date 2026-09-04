$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$source = "$root\java-bridge\src\com\integrationfabric\bridge\FabricJavaBridge.java"
$output = "$root\java-bridge\build"
$classes = "$output\classes"
$runtime = "$output\runtime"

if (!(Get-Command javac -ErrorAction SilentlyContinue)) { throw 'JDK 17 or newer is required to build the Java connector bridge.' }
if (!(Get-Command jlink -ErrorAction SilentlyContinue)) { throw 'JDK jlink is required to create the bundled Java connector runtime.' }
New-Item -ItemType Directory -Force -Path $classes | Out-Null
& javac -encoding UTF-8 -d $classes $source
if ($LASTEXITCODE -ne 0) { throw "Java connector compilation failed with exit code $LASTEXITCODE" }
if (Test-Path $runtime) {
    # The Studio/runtime can leave the bundled JVM alive after a debug session.
    # Stop only java.exe launched from this exact build directory; never stop
    # an unrelated system or developer Java process.
    $runtimeJava = [System.IO.Path]::GetFullPath((Join-Path $runtime 'bin\java.exe'))
    $lockedProcesses = @(Get-Process -Name java,javaw -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -and ([System.IO.Path]::GetFullPath($_.Path) -ieq $runtimeJava) } catch { $false }
    })
    foreach ($process in $lockedProcesses) {
        Write-Host "Stopping project Java runtime process $($process.Id) before replacing the bundled runtime."
        Stop-Process -Id $process.Id -Force -ErrorAction Stop
    }
    if ($lockedProcesses.Count -gt 0) { Start-Sleep -Milliseconds 500 }

    $removed = $false
    for ($attempt = 1; $attempt -le 5 -and !$removed; $attempt++) {
        try {
            Remove-Item -Recurse -Force -LiteralPath $runtime -ErrorAction Stop
            $removed = $true
        } catch {
            if ($attempt -eq 5) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}
& jlink --add-modules java.base,java.sql,java.naming,java.logging,java.management,java.security.jgss,java.xml,jdk.crypto.ec,jdk.naming.dns --strip-debug --no-header-files --no-man-pages --output $runtime
if ($LASTEXITCODE -ne 0) { throw "Bundled Java runtime creation failed with exit code $LASTEXITCODE" }
Write-Host "Java connector bridge ready: $output"
