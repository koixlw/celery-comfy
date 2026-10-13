"""
智能调度器：根据策略自动挑选 ComfyUI 实例

策略：
  - round_robin:  轮询（最简单）
  - least_loaded: 选当前活跃任务最少的实例
  - random:       随机选
  - priority:     VIP 任务给最闲的 GPU，普通任务给 cpu
"""
import random
import redis
import requests
from comfy_instances import COMFY_INSTANCES, all_instances, gpu_instances, get_instance

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def is_alive(instance, timeout=2):
    """检查 ComfyUI 实例是否健康"""
    url = get_instance(instance)["url"]
    try:
        res = requests.get(f"{url}/system_stats", timeout=timeout)
        return res.status_code == 200
    except Exception:
        return False


def get_active_count(instance):
    """从 Redis 读该实例当前活跃任务数"""
    try:
        return int(r.get(f"comfy:{instance}:active_count") or 0)
    except Exception:
        return 0


def get_max_concurrent(instance):
    return get_instance(instance).get("max_concurrent", 1)


def alive_instances():
    """返回所有健康的实例"""
    return [i for i in all_instances() if is_alive(i)]


class SmartScheduler:
    """智能调度器：支持多种路由策略"""

    def __init__(self):
        self._rr_counter = 0  # 轮询计数器

    def pick(self, strategy="round_robin"):
        """根据策略挑一个实例"""
        alive = alive_instances()
        if not alive:
            print("[scheduler] ⚠️  没有健康的 ComfyUI 实例！")
            return "gpu0"  # 兜底

        if strategy == "round_robin":
            return self._round_robin(alive)
        elif strategy == "least_loaded":
            return self._least_loaded(alive)
        elif strategy == "random":
            return random.choice(alive)
        else:
            return self._round_robin(alive)

    def _round_robin(self, alive):
        """轮询"""
        # 找到当前计数器对应的活实例
        while True:
            inst = all_instances()[self._rr_counter % len(all_instances())]
            self._rr_counter += 1
            if inst in alive:
                return inst

    def _least_loaded(self, alive):
        """选活跃数最少、且没满载的实例"""
        # 排序：活跃数/最大并发 比值小的优先
        def load(inst):
            active = get_active_count(inst)
            max_c = get_max_concurrent(inst)
            return active / max_c if max_c > 0 else 999

        alive_sorted = sorted(alive, key=load)
        # 跳过满载的
        for inst in alive_sorted:
            if get_active_count(inst) < get_max_concurrent(inst):
                return inst
        # 全满了，挑活跃最少的
        return alive_sorted[0]

    def status(self):
        """打印所有实例状态"""
        print("\n" + "=" * 60)
        print(f"{'实例':<8} {'状态':<6} {'活跃/上限':<10} {'URL':<25} {'描述'}")
        print("-" * 60)
        for inst in all_instances():
            alive = is_alive(inst)
            active = get_active_count(inst)
            max_c = get_max_concurrent(inst)
            url = get_instance(inst)["url"]
            desc = get_instance(inst)["description"]
            status = "✅ 在线" if alive else "❌ 离线"
            print(f"{inst:<8} {status:<6} {active}/{max_c:<8} {url:<25} {desc}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    # 直接运行：打印所有实例状态
    SmartScheduler().status()
