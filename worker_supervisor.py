"""
Worker 监督器 - 包装 Celery worker

启动方式（在每台机器上）：
    set CUDA_VISIBLE_DEVICES=0
    set COMFY_URL=http://192.168.1.10:8188
    set QUEUE_NAME=desktop_4090
    set REDIS_HOST=192.168.1.10
    python worker_supervisor.py

功能：
- 启动 Celery worker 子进程
- 向中央 Redis 注册本机信息（GPU/显存/IP/ComfyUI地址）
- 定期心跳（10s 一次）
- worker 退出时自动注销
"""
import os
import sys
import time
import socket
import signal
import subprocess
import platform
import resource_registry as rr

# === 从环境变量读配置 ===
REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
QUEUE_NAME = os.environ.get("QUEUE_NAME", f"worker_{socket.gethostname()}")
CUDA_VISIBLE = os.environ.get("CUDA_VISIBLE_DEVICES", "0")
WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "1"))
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "10"))  # 秒

# 把 REDIS_HOST 透传给 resource_registry
rr.REDIS_HOST = REDIS_HOST
rr.REDIS_PORT = REDIS_PORT
rr.REDIS_DB = REDIS_DB


def get_local_ip():
    """取本机局域网 IP（不是 127.0.0.1）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_gpu_info():
    """读 nvidia-smi 拿本机 GPU 信息"""
    gpu_index = int(CUDA_VISIBLE.split(",")[0])
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if int(parts[0]) == gpu_index:
                    return {
                        "gpu_index": gpu_index,
                        "gpu_name": parts[1],
                        "mem_total_mb": int(parts[2]),
                        "mem_free_mb": int(parts[3]),
                    }
    except Exception as e:
        print(f"[supervisor] nvidia-smi 失败: {e}")
    return {"gpu_index": gpu_index, "gpu_name": "unknown", "mem_total_mb": 0, "mem_free_mb": 0}


def build_worker_id():
    """生成唯一 worker id"""
    return f"{socket.gethostname()}_gpu{CUDA_VISIBLE.split(',')[0]}_{os.getpid()}"


def main():
    worker_id = build_worker_id()
    ip = get_local_ip()
    gpu_info = get_gpu_info()

    info = {
        "hostname": socket.gethostname(),
        "ip": ip,
        "platform": platform.platform(),
        **gpu_info,
        "comfy_url": COMFY_URL,
        "queue": QUEUE_NAME,
        "max_concurrent": WORKER_CONCURRENCY,
        "pid": os.getpid(),
    }

    print("=" * 60)
    print(f"  Worker 监督器")
    print(f"  worker_id:    {worker_id}")
    print(f"  中央 Redis:   {REDIS_HOST}:{REDIS_PORT}")
    print(f"  本机 ComfyUI: {COMFY_URL}")
    print(f"  订阅队列:     {QUEUE_NAME}")
    print(f"  GPU:          {gpu_info['gpu_name']} ({gpu_info['mem_free_mb']}/{gpu_info['mem_total_mb']}MB)")
    print("=" * 60)

    # 注册到 Redis
    rr.register(worker_id, info)
    print(f"[supervisor] ✅ 已注册到资源池")

    # 启动 Celery worker 子进程
    celery_cmd = [
        sys.executable, "-m", "celery", "-A", "tasks", "worker",
        "-Q", QUEUE_NAME, "-c", str(WORKER_CONCURRENCY),
        "--pool=eventlet", "--loglevel=info",
    ]
    print(f"[supervisor] 启动: {' '.join(celery_cmd)}")
    proc = subprocess.Popen(celery_cmd)

    # 心跳循环
    stop_flag = [False]

    def handle_signal(signum, frame):
        print(f"\n[supervisor] 收到信号 {signum}，准备退出...")
        stop_flag[0] = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        while not stop_flag[0]:
            # worker 子进程挂了？
            if proc.poll() is not None:
                print(f"[supervisor] ⚠️  Celery worker 退出，code={proc.returncode}")
                break
            # 心跳
            rr.heartbeat(worker_id, current_load=0, current_task="")
            time.sleep(HEARTBEAT_INTERVAL)
    finally:
        # 清理
        print(f"[supervisor] 注销 worker...")
        rr.unregister(worker_id)
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        print(f"[supervisor] ✅ 已退出")


if __name__ == "__main__":
    main()
