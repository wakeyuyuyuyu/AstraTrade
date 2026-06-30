@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AstraTrade 手动运行

echo ============================================
echo   AstraTrade — 手动运行 Agent
echo ============================================
echo.
echo 输入要执行的任务描述（例如）：
echo   "扫描市场并检查持仓"
echo   "检查候选股票的最新价格"
echo   "帮我做今日复盘和明日计划"
echo.
set /p TASK="任务: "

if "%TASK%"=="" (
    echo 任务不能为空
    pause
    exit /b
)

echo.
echo [*] 正在运行，请耐心等待...
echo.

".venv\Scripts\python.exe" -m runtime.launcher --mode manual --task "%TASK%"

echo.
echo [OK] 执行完毕
pause
