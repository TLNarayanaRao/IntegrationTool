@echo off
set "ADMIN_EXE=%~dp0..\IntegrationFabricAdministrator.exe"
if /I "%1"=="start" start "Integration Fabric Administrator" /B "%ADMIN_EXE%"
if /I "%1"=="run" "%ADMIN_EXE%"
if /I "%1"=="status" curl -s http://127.0.0.1:9080/api/health
if "%1"=="" echo Usage: fabricadmin.cmd start^|run^|status
