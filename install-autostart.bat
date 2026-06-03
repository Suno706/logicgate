@echo off
REM ===========================================================================
REM  Run ONCE to make LogicGate auto-start every time you log in to Windows.
REM  The server will run silently in the background; just visit
REM  http://localhost:5000 in your browser whenever you want to use it.
REM
REM  To undo: delete the LogicGate shortcut from
REM    %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
REM ===========================================================================
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$startup = [Environment]::GetFolderPath('Startup');" ^
  "$WshShell = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $WshShell.CreateShortcut(\"$startup\LogicGate.lnk\");" ^
  "$lnk.TargetPath = '%~dp0start.bat';" ^
  "$lnk.Arguments = 'noopen';" ^
  "$lnk.WorkingDirectory = '%~dp0';" ^
  "$lnk.WindowStyle = 7;" ^
  "$lnk.IconLocation = 'shell32.dll,13';" ^
  "$lnk.Description = 'LogicGate circuit designer (auto-start)';" ^
  "$lnk.Save();" ^
  "Write-Host '';" ^
  "Write-Host 'LogicGate will now auto-start every time you log in.' -ForegroundColor Green;" ^
  "Write-Host 'It runs minimised in the background.' -ForegroundColor Green;" ^
  "Write-Host 'Just open http://localhost:5000 in your browser.' -ForegroundColor Green;"

echo.
echo Starting it now so you don't have to log out and back in...
start "" /min "%~dp0start.bat" noopen

echo.
pause
