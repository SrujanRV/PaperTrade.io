# create_shortcuts.ps1 - Generates Windows Desktop shortcuts for PaperTrade.io

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopPath = [Environment]::GetFolderPath("Desktop")
$backendVenv = Join-Path $projectRoot "backend\venv\Scripts\pythonw.exe"
$launcherPyw = Join-Path $projectRoot "launcher.pyw"
$stopPyw = Join-Path $projectRoot "stop_server.pyw"
$appIcon = Join-Path $projectRoot "resources\app_icon.ico"

$wshShell = New-Object -ComObject WScript.Shell

# 1. Main App Shortcut
$appShortcutPath = Join-Path $desktopPath "PaperTrade.io.lnk"
$appShortcut = $wshShell.CreateShortcut($appShortcutPath)
$appShortcut.TargetPath = $backendVenv
$appShortcut.Arguments = "`"$launcherPyw`""
$appShortcut.WorkingDirectory = $projectRoot
$appShortcut.IconLocation = "$appIcon,0"
$appShortcut.Description = "PaperTrade.io - Paper Trading Terminal"
$appShortcut.WindowStyle = 7
$appShortcut.Save()

Write-Host "Created Desktop shortcut: $appShortcutPath"

# 2. Stop Server Shortcut
$stopShortcutPath = Join-Path $desktopPath "Stop PaperTrade.lnk"
$stopShortcut = $wshShell.CreateShortcut($stopShortcutPath)
$stopShortcut.TargetPath = $backendVenv
$stopShortcut.Arguments = "`"$stopPyw`""
$stopShortcut.WorkingDirectory = $projectRoot
$stopShortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,27"
$stopShortcut.Description = "Stop PaperTrade.io background server"
$stopShortcut.WindowStyle = 7
$stopShortcut.Save()

Write-Host "Created Desktop shortcut: $stopShortcutPath"
