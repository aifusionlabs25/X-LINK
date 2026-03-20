@echo off
TITLE X-AGENT Demo Server (Dojo)
cd /d "%~dp0"

:: Navigate to the Demo Server repository
cd /d "..\x-agent-website-a"

echo [1/2] Checking dependencies...
if not exist "node_modules" (
    echo [INFO] node_modules not found. Installing...
    call npm install
)

echo [2/2] Starting Agent Demo Server on port 3000...
echo [INFO] This server provides the QA lanes for the Dojo Console.
echo [TIP] If port 3000 is blocked, you may need to check for other 'node' processes.

:: Explicitly set port for Next.js
set PORT=3000
call npm run dev
