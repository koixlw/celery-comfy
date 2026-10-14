@echo off
chcp 65001 >nul
cd /d %~dp0
echo.
echo ========================================
echo   Celery Worker (订阅 gpu0 队列)
echo   关闭窗口 = 停止服务
echo ========================================
echo.
python -m celery -A tasks worker -Q gpu0 -c 1 --pool=eventlet --loglevel=info
pause
