@echo off
chcp 65001 >nul
cd /d %~dp0

REM ========================================
REM 多机算力共享 - Worker 启动脚本
REM ========================================
REM
REM 在新机器上运行时，设置这些环境变量：
REM   REDIS_HOST     中央 Redis 的 IP（必填）
REM   COMFY_URL      本机 ComfyUI 地址（默认 8188）
REM   QUEUE_NAME     本 worker 的队列名（默认 = 主机名）
REM   CUDA_VISIBLE_DEVICES  用哪张 GPU（默认 0）
REM
REM 示例（在我的台式机上）：
REM   set REDIS_HOST=192.168.1.10
REM   set COMFY_URL=http://192.168.1.10:8188
REM   set QUEUE_NAME=desktop_4090
REM   set CUDA_VISIBLE_DEVICES=0
REM

REM ----- 配置区（请按需修改） -----
if "%REDIS_HOST%"=="" set REDIS_HOST=127.0.0.1
if "%COMFY_URL%"=="" set COMFY_URL=http://127.0.0.1:8188
if "%QUEUE_NAME%"=="" set QUEUE_NAME=worker_local
if "%CUDA_VISIBLE_DEVICES%"=="" set CUDA_VISIBLE_DEVICES=0
if "%WORKER_CONCURRENCY%"=="" set WORKER_CONCURRENCY=1

echo.
echo ========================================
echo   Worker 监督器（多机算力共享模式）
echo ========================================
echo   REDIS_HOST:          %REDIS_HOST%
echo   COMFY_URL:           %COMFY_URL%
echo   QUEUE_NAME:          %QUEUE_NAME%
echo   CUDA_VISIBLE_DEVICES:%CUDA_VISIBLE_DEVICES%
echo   WORKER_CONCURRENCY:  %WORKER_CONCURRENCY%
echo ========================================
echo.

python worker_supervisor.py
pause
