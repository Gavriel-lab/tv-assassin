@echo off
chcp 65001 >nul
title 电视刺客 · 专刺偷看电视神兽 (TV-Assassin)
cd /d "%~dp0"

echo ==================================================
echo   电视刺客 (TV-Assassin) · 智能电视防沉迷管家
echo ==================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo 【错误】未检测到 Python 环境！
    echo 请先前往 Python 官网下载安装 Python (建议 3.8 及以上版本):
    echo https://www.python.org/downloads/
    echo 安装时请务必勾选 "Add python.exe to PATH"！
    echo.
    pause
    exit /b
)

echo [1/2] 正在启动后台守护服务...
start /b python server.py

echo [2/2] 正在为您打开管理控制后台...
timeout /t 2 >nul
start http://localhost:3000

echo.
echo 🎉 系统已在后台持续运行！
echo 👉 电脑管理后台: http://localhost:3000
echo 👉 您也可以在手机浏览器中输入屏幕提示的局域网 IP 访问。
echo.
echo 如需关闭系统，直接关闭本窗口即可。
echo ==================================================
pause >nul
