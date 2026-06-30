@echo off
cd /d "%~dp0"
title AstraTrade Stop

echo [*] Stopping AstraTrade dashboard...

PowerShell -NoProfile -Command ^
    "Get-CimInstance Win32_Process -Filter \"CommandLine like '%%dashboard/server.py%%' and Name = 'python.exe'\" ^| ^
    ForEach-Object { Write-Host ('  PID ' + $_.ProcessId + ' stopped'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

PowerShell -NoProfile -Command ^
    "Get-CimInstance Win32_Process -Filter \"CommandLine like '%%runtime.agent%%' and Name = 'python.exe'\" ^| ^
    ForEach-Object { Write-Host ('  Scheduler PID ' + $_.ProcessId + ' stopped'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

netstat -ano 2>nul | findstr ":8787.*LISTENING" >nul
if errorlevel 1 (
    echo [OK] Dashboard stopped
) else (
    echo [!] Port 8787 still in use
)

echo.
pause
