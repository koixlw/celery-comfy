"""
智能调度器 v2 - 支持多机器算力池

从 Redis resource pool 读取所有在线 worker
支持策略：round_robin / least_loaded / random / gpu_pick / model_aware
"""
import random
import time
import requests
import resource_registry as rr
from comfy_instances import COMFY_INSTANCES, all_instances, gpu_instances, get_instance


def is_alive(instance, timeout=2):
    """检查 ComfyUI 实例是否健康（向后兼容）"""
    url = get_instance(instance)["url"]
    try:
        res = requests.get(f"{url}/system_stats", timeout=timeout)
        return res.status_code == 200
    except Exception:
        return False


def get_active_count(instance):
    try:
        return int(rr.get_redis().get(f"comfy:{instance}:active_count") or 0)
    except Exception:
        return 0


def alive_instances():
    """传统方式：检查 comfy_instances 配置里的"""
    return [i for i in all_instances() if is_alive(i)]


def alive_workers_from_registry():
    """新方式：从资源池拿所有在线 worker"""
    workers = rr.list_alive()
    # 转成统一的格式
    result = []
    for w in workers:
        result.append({
            "worker_id": w.get("worker_id"),
            "queue": w.get("queue"),
            "comfy_url": w.get("comfy_url"),
            "hostname": w.get("hostname"),
            "ip": w.get("ip"),
            "gpu_index": int(w.get("gpu_index", 0)) if w.get("gpu_index") else 0,
            "gpu_name": w.get("gpu_name", "?"),
            "mem_free_mb": int(w.get("mem_free_mb", 0)),
            "mem_total_mb": int(w.get("mem_total_mb", 0)),
            "current_load": int(w.get("current_load", 0)),
            "max_concurrent": int(w.get("max_concurrent", 1)),
        })
    return result


class SmartScheduler:
    """调度器：支持多机器算力池"""

    def __init__(self):
        self._rr_counter = 0
        self._mode = "registry"  # "registry" 或 "config"（向后兼容）

    def pick(self, strategy="round_robin", task_hint=None):
        """根据策略挑一个 worker
        task_hint: 可选 dict, 如 {"model": "sdxl"} 用于 model_aware 策略
        """
        # 优先从资源池拿
        workers = alive_workers_from_registry()

        # 资源池空时回退到传统配置
        if not workers:
            self._mode = "config"
            return self._pick_from_config(strategy)

        self._mode = "registry"

        if strategy == "round_robin":
            return self._round_robin(workers)
        elif strategy == "least_loaded":
            return self._least_loaded(workers)
        elif strategy == "random":
            return random.choice(workers)
        elif strategy == "best_gpu":
            return self._best_gpu(workers)
        elif strategy == "model_aware":
            return self._model_aware(workers, task_hint or {})
        else:
            return self._round_robin(workers)

    def _round_robin(self, workers):
        queues = [w["queue"] for w in workers]
        chosen = queues[self._rr_counter % len(queues)]
        self._rr_counter += 1
        return chosen

    def _least_loaded(self, workers):
        """选当前任务最少、且有空闲槽位的 worker"""
        # 过滤：还有空闲槽位的
        available = [w for w in workers if w["current_load"] < w["max_concurrent"]]
        if not available:
            available = workers  # 全满了，选最闲的
        # 按 load/max 比例排序
        available.sort(key=lambda w: w["current_load"] / max(w["max_concurrent"], 1))
        return available[0]["queue"]

    def _best_gpu(self, workers):
        """选显存最多的 worker（适合大图）"""
        return max(workers, key=lambda w: w["mem_free_mb"])["queue"]

    def _model_aware(self, workers, hint):
        """根据模型提示挑 worker（未来扩展用）"""
        # 简单实现：显存多的优先
        return self._best_gpu(workers)

    def _pick_from_config(self, strategy):
        """回退：从 comfy_instances.py 配置里选"""
        alive = alive_instances()
        if not alive:
            return "gpu0"
        if strategy == "random":
            return random.choice(alive)
        chosen = alive[self._rr_counter % len(alive)]
        self._rr_counter += 1
        return chosen

    def status(self):
        """打印所有算力状态（同时显示资源池和配置）"""
        print("\n" + "=" * 70)
        print("  算力资源池（来自 Redis registry）")
        print("=" * 70)
        workers = alive_workers_from_registry()
        if workers:
            print(f"{'Worker':<22} {'主机':<12} {'GPU':<22} {'显存':<12} {'队列':<10} {'负载'}")
            print("-" * 70)
            for w in workers:
                mem = f"{w['mem_free_mb']}/{w['mem_total_mb']}MB"
                load = f"{w['current_load']}/{w['max_concurrent']}"
                print(f"{w['worker_id']:<22} {w['hostname']:<12} {w['gpu_name']:<22} {mem:<12} {w['queue']:<10} {load}")
        else:
            print("  (无在线 worker - 检查 worker_supervisor.py 是否运行)")

        print()
        print("=" * 70)
        print("  本地配置（comfy_instances.py）")
        print("=" * 70)
        for inst in all_instances():
            alive = is_alive(inst)
            active = get_active_count(inst)
            max_c = get_instance(inst)["max_concurrent"]
            url = get_instance(inst)["url"]
            status = "✅ 在线" if alive else "❌ 离线"
            print(f"  {inst:<8} {status:<8} {active}/{max_c:<8} {url}")
        print()


if __name__ == "__main__":
    SmartScheduler().status()
