@echo off
chcp 65001 >nul
setlocal

set ROOT=%~dp0
set COMFY_DIR=C:\ComfyUI

echo.
echo ========================================
echo   Celery + ComfyUI 多算力启动器
echo ========================================
echo.

REM [1] 检查 Redis
echo [1/5] 检查 Redis...
redis-cli ping >nul 2>&1
if %errorlevel% neq 0 (
    echo   Redis 未启动，正在打开新窗口启动...
    start "Redis" cmd /k "redis-server"
    timeout /t 3 >nul
) else (
    echo   Redis 已在运行 ✅
)

REM [2] 启动 ComfyUI 实例
echo.
echo [2/5] 启动 ComfyUI 实例（每个开一个窗口）...
if exist "%COMFY_DIR%\main.py" (
    start "ComfyUI-gpu0:8188" cmd /k "cd /d %COMFY_DIR% && python main.py --port 8188 --listen 0.0.0.0"
    timeout /t 2 >nul
    start "ComfyUI-gpu1:8189" cmd /k "cd /d %COMFY_DIR% && set CUDA_VISIBLE_DEVICES=1 && python main.py --port 8189 --listen 0.0.0.0"
    timeout /t 2 >nul
    start "ComfyUI-cpu:8190"  cmd /k "cd /d %COMFY_DIR% && python main.py --port 8190 --listen 0.0.0.0 --cpu"
    echo   3 个 ComfyUI 已启动（请等 ~10s 加载完）
) else (
    echo   ⚠️  找不到 %COMFY_DIR%\main.py
    echo   请编辑 start_all.bat，把 COMFY_DIR 改成你的 ComfyUI 目录
)

REM [3] 启动 Celery workers
echo.
echo [3/5] 启动 Celery workers...
start "Worker-gpu0" cmd /k "cd /d %ROOT% && python -m celery -A tasks worker -Q gpu0 -c 1 --pool=eventlet --loglevel=info"
start "Worker-gpu1" cmd /k "cd /d %ROOT% && python -m celery -A tasks worker -Q gpu1 -c 1 --pool=eventlet --loglevel=info"
start "Worker-cpu"  cmd /k "cd /d %ROOT% && python -m celery -A tasks worker -Q cpu  -c 2 --pool=eventlet --loglevel=info"
echo   3 个 worker 已启动

REM [4] 启动活动监听器
echo.
echo [4/5] 启动活动监听器...
start "ActivityMonitor" cmd /k "cd /d %ROOT% && python activity_monitor.py"
echo   监听器已启动

REM [5] 启动 GPU 监控（可选）
echo.
echo [5/5] 启动 GPU 监控（可选，回车跳过）...
choice /C YN /N /T 5 /D N /M "是否启动 GPU 监控？(Y/N, 5s 后默认 N)"
if %errorlevel%==1 (
    start "GPUMonitor" cmd /k "cd /d %ROOT% && python gpu_monitor.py"
    echo   GPU 监控已启动
) else (
    echo   跳过 GPU 监控
)

echo.
echo ========================================
echo   全部启动完成！
echo ========================================
echo.
echo 已打开的窗口（按窗口标题区分）：
echo   - ComfyUI-gpu0:8188 / ComfyUI-gpu1:8189 / ComfyUI-cpu:8190
echo   - Worker-gpu0 / Worker-gpu1 / Worker-cpu
echo   - ActivityMonitor
echo.
echo 接下来：
echo   1. 等 ComfyUI 窗口显示 "To see the GUI go to: http://0.0.0.0:xxxx"
echo   2. 开新窗口执行: python submit_task.py
echo   3. 移动鼠标试试暂停效果
echo.
echo 关闭本窗口不会停止其他服务，要停就关对应的 cmd 窗口。
echo.
pause
