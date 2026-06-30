@echo off
cd /d "%~dp0"
title AstraTrade Dashboard

echo ============================================
echo   AstraTrade Financial Agent System
echo ============================================
echo.

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ERROR] Python not found at %PYTHON%
    pause
    exit /b
)

netstat -ano 2>nul | findstr ":8787.*LISTENING" >nul
if not errorlevel 1 (
    echo [OK] Dashboard already running on port 8787
    start "" "http://127.0.0.1:8787"
    goto :eof
)

echo [*] Starting dashboard server (port 8787)...

start "" /MIN cmd /c ""%PYTHON%" "dashboard\server.py" "8787" > "dashboard_console.log" 2>&1"

echo [*] Waiting for server...
set WAIT=0
:wait_loop
ping -n 2 127.0.0.1 >nul
netstat -ano 2>nul | findstr ":8787.*LISTENING" >nul
if not errorlevel 1 goto server_ok
set /a WAIT+=1
if %WAIT% lss 7 goto wait_loop

echo [!] TIMEOUT - Dashboard did not start
type dashboard_console.log 2>nul
pause
exit /b

:server_ok
echo [OK] Dashboard ready at http://127.0.0.1:8787
start "" "http://127.0.0.1:8787"
echo.
echo Close this window to leave dashboard running in background.
echo To stop: run stop_dashboard.bat or close the Python window.
echo.
pause
