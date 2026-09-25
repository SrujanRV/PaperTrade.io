@echo off
setlocal
echo Stopping PaperTrade.io server on port 8000...

for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr :8000 ^| findstr LISTENING') do (
    echo Terminating PID %%a...
    taskkill /F /T /PID %%a >nul 2>&1
)

echo PaperTrade server stopped.
