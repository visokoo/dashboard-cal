# install-startup-shortcut.ps1
#
# Creates a Windows Startup shortcut that launches dashboard-cal in kiosk mode
# whenever you sign in. Run this from PowerShell while you have the project
# venv active (or pass -PythonExe to point at a specific python).
#
# Usage:
#   pwsh -File .\scripts\install-startup-shortcut.ps1
#   pwsh -File .\scripts\install-startup-shortcut.ps1 -PythonExe "C:\path\to\python.exe"
#
# To uninstall: delete dashboard-cal.lnk from `shell:startup`.

param(
    [string]$PythonExe = "",
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

if (-not $PythonExe) {
    $venvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        $PythonExe = $venvPy
    } else {
        $PythonExe = (Get-Command python).Source
    }
}

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "dashboard-cal.lnk"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($shortcutPath)
$lnk.TargetPath = $PythonExe
$lnk.Arguments = "-m dashboard_cal"
$lnk.WorkingDirectory = $ProjectRoot
$lnk.WindowStyle = 7  # minimized; the Flet window will pop to fullscreen on its own
$lnk.Description = "dashboard-cal kiosk"
$lnk.IconLocation = "$PythonExe,0"
$lnk.Save()

Write-Host "Installed Startup shortcut at $shortcutPath"
Write-Host "  Python: $PythonExe"
Write-Host "  Working dir: $ProjectRoot"
Write-Host ""
Write-Host "Tip: also disable sleep on the Surface:"
Write-Host "    powercfg /change standby-timeout-ac 0"
Write-Host "    powercfg /change monitor-timeout-ac 0"
