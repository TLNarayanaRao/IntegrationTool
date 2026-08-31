@echo off
set "ADMIN_EXE=%~dp0..\IntegrationFabricAdministrator.exe"
set "PID_FILE=%TEMP%\integration-fabric-administrator.pid"
if /I "%1"=="start" powershell -NoProfile -Command "$p=Start-Process -FilePath '%ADMIN_EXE%' -WindowStyle Hidden -PassThru; Set-Content -LiteralPath '%PID_FILE%' -Value $p.Id"
if /I "%1"=="run" "%ADMIN_EXE%"
if /I "%1"=="status" curl -s http://127.0.0.1:9080/api/health
if /I "%1"=="stop" powershell -NoProfile -Command "if(Test-Path -LiteralPath '%PID_FILE%'){$adminPid=Get-Content -LiteralPath '%PID_FILE%'; Stop-Process -Id $adminPid -ErrorAction SilentlyContinue; Remove-Item -LiteralPath '%PID_FILE%' -Force}"
if "%1"=="" echo Usage: fabricadmin.cmd start^|stop^|run^|status
