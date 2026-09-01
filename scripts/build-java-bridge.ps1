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
if (Test-Path $runtime) { Remove-Item -Recurse -Force -LiteralPath $runtime }
& jlink --add-modules java.base,java.sql,java.naming,java.logging,java.management,java.security.jgss,java.xml,jdk.crypto.ec,jdk.naming.dns --strip-debug --no-header-files --no-man-pages --output $runtime
if ($LASTEXITCODE -ne 0) { throw "Bundled Java runtime creation failed with exit code $LASTEXITCODE" }
Write-Host "Java connector bridge ready: $output"
