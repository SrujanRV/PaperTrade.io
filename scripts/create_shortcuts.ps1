# create_shortcuts.ps1 - Generates Windows Desktop shortcut for PaperTrade.io

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopPath = [Environment]::GetFolderPath("Desktop")
$backendVenv = Join-Path $projectRoot "backend\venv\Scripts\pythonw.exe"
$launcherPyw = Join-Path $projectRoot "launcher.pyw"
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

# Clean up any legacy stop shortcut
$stopShortcutPath = Join-Path $desktopPath "Stop PaperTrade.lnk"
if (Test-Path $stopShortcutPath) {
    Remove-Item $stopShortcutPath -Force
    Write-Host "Cleaned up legacy Stop PaperTrade shortcut"
}
