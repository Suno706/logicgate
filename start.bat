@echo off
REM ===========================================================================
REM  LogicGate one-click launcher.
REM  Double-click to start. Auto-opens browser. Closing this window stops it.
REM  Pass "minimized" arg to run hidden (used by autostart).
REM ===========================================================================
title LogicGate Server
cd /d "%~dp0"

echo Starting LogicGate at http://localhost:5000
echo Closing this window will stop the server.
echo.

REM Open the browser ~3 seconds after Flask is up (skip if "noopen" passed).
if /i not "%~1"=="noopen" (
  start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:5000"
)

REM Run Flask in the foreground.
python app.py

if errorlevel 1 (
  echo.
  echo ============================================
  echo Server stopped with an error. Press any key.
  echo ============================================
  pause >nul
)
