@echo off
setlocal enabledelayedexpansion

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\PaperTrade.io.lnk"
set "PROJECT_ROOT=%~dp0.."
set "PYTHONW=%PROJECT_ROOT%\backend\venv\Scripts\pythonw.exe"
set "LAUNCHER=%PROJECT_ROOT%\launcher.pyw"
set "ICON=%PROJECT_ROOT%\resources\app_icon.ico"

echo ========================================================
echo   PaperTrade.io — Windows Startup Auto-Launch Manager
echo ========================================================
echo.

if exist "%SHORTCUT_PATH%" (
    echo Current Status: [ENABLED]
    echo PaperTrade is configured to start on Windows login.
    echo.
    if "%1"=="disable" goto do_disable
    if "%1"=="enable" (
        echo Already enabled.
        goto end
    )
    if "%1"=="status" goto end
    
    set /p "ans=Do you want to DISABLE auto-start on login? (y/n): "
    if /i "!ans!"=="y" goto do_disable
    goto end
) else (
    echo Current Status: [DISABLED]
    echo PaperTrade does NOT automatically start on Windows login.
    echo.
    if "%1"=="enable" goto do_enable
    if "%1"=="disable" (
        echo Already disabled.
        goto end
    )
    if "%1"=="status" goto end

    set /p "ans=Do you want to ENABLE auto-start on login? (y/n): "
    if /i "!ans!"=="y" goto do_enable
    goto end
)

:do_enable
echo.
echo Creating startup shortcut...
powershell -NoProfile -Command ^
    "$wsh = New-Object -ComObject WScript.Shell; " ^
    "$s = $wsh.CreateShortcut('%SHORTCUT_PATH%'); " ^
    "$s.TargetPath = '%PYTHONW%'; " ^
    "$s.Arguments = '\"%LAUNCHER%\"'; " ^
    "$s.WorkingDirectory = '%PROJECT_ROOT%'; " ^
    "$s.IconLocation = '%ICON%,0'; " ^
    "$s.Description = 'PaperTrade.io Background Startup'; " ^
    "$s.WindowStyle = 7; " ^
    "$s.Save();"
echo Auto-start on Windows login is now ENABLED.
goto end

:do_disable
echo.
echo Removing startup shortcut...
del /f /q "%SHORTCUT_PATH%" >nul 2>&1
echo Auto-start on Windows login is now DISABLED.
goto end

:end
echo.
echo Done.
if "%1"=="" pause
