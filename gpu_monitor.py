"""
GPU 状态监控器

读 nvidia-smi 获取显存/利用率，写到 Redis，给 scheduler 做负载均衡参考

用法：
    python gpu_monitor.py            # 前台运行
    python gpu_monitor.py --once     # 只跑一次打印
"""
import subprocess
import json
import time
import argparse
import redis
from comfy_instances import gpu_instances

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
POLL_INTERVAL = 5.0  # 秒

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def query_nvidia_smi():
    """调用 nvidia-smi，返回每张 GPU 的 {显存使用率, 显存剩余MB, 利用率}"""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        gpus = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            idx, name, mem_used, mem_total, util = parts
            gpus.append({
                "index": int(idx),
                "name": name,
                "mem_used_mb": int(mem_used),
                "mem_total_mb": int(mem_total),
                "mem_free_mb": int(mem_total) - int(mem_used),
                "mem_used_pct": round(int(mem_used) / int(mem_total) * 100, 1),
                "util_pct": int(util),
            })
        return gpus
    except FileNotFoundError:
        return None  # nvidia-smi 不在 PATH
    except Exception as e:
        print(f"[gpu_monitor] 异常: {e}")
        return None


def write_to_redis(gpus):
    """把每张 GPU 状态写入 Redis：gpu:N:mem_free, gpu:N:util"""
    if not gpus:
        return
    for g in gpus:
        idx = g["index"]
        r.set(f"gpu:{idx}:mem_free_mb", g["mem_free_mb"])
        r.set(f"gpu:{idx}:util_pct", g["util_pct"])
        r.set(f"gpu:{idx}:name", g["name"])


def print_status(gpus):
    if not gpus:
        print("[gpu_monitor] 没读到 GPU 信息（nvidia-smi 不在 PATH？或没装 NVIDIA 驱动？）")
        return
    print(f"\n{'GPU':<6} {'名称':<20} {'显存':<15} {'利用率':<8}")
    print("-" * 55)
    for g in gpus:
        mem = f"{g['mem_used_mb']}/{g['mem_total_mb']}MB ({g['mem_used_pct']}%)"
        print(f"{g['index']:<6} {g['name']:<20} {mem:<15} {g['util_pct']}%")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="只跑一次就退出")
    parser.add_argument("--interval", type=float, default=POLL_INTERVAL)
    args = parser.parse_args()

    print(f"[gpu_monitor] 开始监控 (间隔 {args.interval}s)，Ctrl+C 退出")

    if args.once:
        gpus = query_nvidia_smi()
        print_status(gpus)
        write_to_redis(gpus)
        return

    try:
        while True:
            gpus = query_nvidia_smi()
            write_to_redis(gpus)
            print_status(gpus)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[gpu_monitor] 退出")


if __name__ == "__main__":
    main()
