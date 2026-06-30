@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AstraTrade 工具菜单

:menu
cls
echo ============================================
echo   AstraTrade 工具菜单
echo ============================================
echo.
echo  1. 启动仪表盘 (Dashboard)
echo  2. 停止仪表盘
echo  3. 手动运行 Agent
echo  4. 查看控制台日志
echo  5. 退出
echo.
set /p CHOICE="请选择 (1-5): "

if "%CHOICE%"=="1" goto start_dash
if "%CHOICE%"=="2" goto stop_dash
if "%CHOICE%"=="3" goto run_agent
if "%CHOICE%"=="4" goto show_log
if "%CHOICE%"=="5" exit /b

echo 无效选择
timeout /t 2 >nul
goto menu

:start_dash
start start_dashboard.bat
goto menu

:stop_dash
start stop_dashboard.bat
goto menu

:run_agent
start run_agent.bat
goto menu

:show_log
if exist dashboard_console.log (
    type dashboard_console.log
) else (
    echo 暂无日志
)
echo.
pause
goto menu
