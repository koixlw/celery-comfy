@echo off
chcp 65001 >nul
cd /d %~dp0
echo.
echo ========================================
echo   Web 控制面板
echo   访问: http://127.0.0.1:5000
echo   关闭窗口 = 停止服务
echo ========================================
echo.
python web_dashboard.py
pause
