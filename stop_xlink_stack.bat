@echo off
TITLE X-LINK Full Stack Stopper
cd /d "%~dp0"

echo [1/3] Stopping services on port 5001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5001 ^| findstr LISTENING') do (
    echo [INFO] Stopping process %%a on port 5001...
    taskkill /F /PID %%a >nul 2>&1
)

echo [2/3] Stopping services on port 3000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000 ^| findstr LISTENING') do (
    echo [INFO] Stopping process %%a on port 3000...
    taskkill /F /PID %%a >nul 2>&1
)

echo [3/3] Stopping Hermes Gateway...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\stop_hermes_gateway.ps1"

echo.
echo X-LINK services stopped.
exit /b 0
