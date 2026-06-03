@echo off
REM ===========================================================================
REM  Run this ONCE to put a "LogicGate" shortcut on your desktop.
REM  After that, double-click the desktop icon to start the app any time.
REM ===========================================================================
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$WshShell = New-Object -ComObject WScript.Shell;" ^
  "$Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\LogicGate.lnk');" ^
  "$Shortcut.TargetPath = '%~dp0start.bat';" ^
  "$Shortcut.WorkingDirectory = '%~dp0';" ^
  "$Shortcut.IconLocation = 'shell32.dll,13';" ^
  "$Shortcut.Description = 'LogicGate circuit designer';" ^
  "$Shortcut.Save();" ^
  "Write-Host 'Desktop shortcut created.' -ForegroundColor Green"

echo.
pause
