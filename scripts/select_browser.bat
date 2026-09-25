@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "PYTHONW=%PROJECT_ROOT%\backend\venv\Scripts\pythonw.exe"
set "LAUNCHER=%PROJECT_ROOT%\launcher.pyw"

echo Opening PaperTrade Browser Selector...
start "" "%PYTHONW%" "%LAUNCHER%" --select-browser
