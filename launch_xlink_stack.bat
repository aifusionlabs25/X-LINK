@echo off
TITLE X-LINK Full Stack Launcher
cd /d "%~dp0"

echo [1/4] Ensuring Hermes Gateway is online...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\start_hermes_gateway.ps1"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Hermes Gateway failed to start.
    pause
    exit /b 1
)

echo [2/4] Starting X-LINK Hub...
start "X-LINK Hub" cmd /k call "%~dp0launch_hub.bat"

echo [3/4] Waiting for Synapse Bridge...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ready=$false; for($i=0; $i -lt 30; $i++){ try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5001/api/data' -TimeoutSec 2; if($r.StatusCode -eq 200){ $ready=$true; break } } catch {}; Start-Sleep -Seconds 1 }; if(-not $ready){ exit 1 }"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Synapse Bridge did not come online on port 5001.
    pause
    exit /b 1
)

echo [4/4] Opening Hub in Brave...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\open_xlink_brave.ps1"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Brave failed to start in X-LINK mode.
    pause
    exit /b 1
)

echo [5/5] Starting X-AGENT Dojo...
start "X-AGENT Dojo" cmd /k call "%~dp0launch_dojo.bat"

echo.
echo X-LINK startup sequence launched.
echo Keep your Hermes Gateway running in the background.
exit /b 0
