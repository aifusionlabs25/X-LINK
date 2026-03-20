@echo off
TITLE X-LINK Hub Launcher
cd /d "%~dp0"

echo [1/4] Checking environment...
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe
    echo Please ensure you are in the X-LINK repository root.
    pause
    exit /b
)

echo [2/4] Cleaning up port 5001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5001 ^| findstr LISTENING') do (
    echo [INFO] Found existing process %%a on port 5001. Stopping it...
    taskkill /F /PID %%a >nul 2>&1
)

echo [3/4] Starting Synapse Bridge...
set PYTHONPATH=.
".venv\Scripts\python.exe" "tools\synapse_bridge.py"

if %ERRORLEVEL% neq 0 (
    echo [4/4] Bridge failed to start or crashed.
    pause
) else (
    echo [4/4] Bridge closed.
)
