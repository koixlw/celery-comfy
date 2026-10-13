"""
任务提交脚本 - 多算力 + VIP 优先级版本

用法示例：
    python submit_task.py                      # 智能路由（轮询）
    python submit_task.py gpu0                 # 显式指定 gpu0
    python submit_task.py least                # 智能路由（负载最低）
    python submit_task.py gpu0 vip             # VIP 任务
    python submit_task.py gpu0 5               # 批量 5 个
    python submit_task.py gpu0 5 vip           # 批量 5 个 VIP
"""
import sys
import argparse
import redis
from tasks import run_comfy_gpu0, run_comfy_gpu1, run_comfy_cpu
from scheduler import SmartScheduler
from comfy_instances import COMFY_INSTANCES, all_instances

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
KEY_VIP_PENDING = "comfy:vip_pending"
rcli = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# === 示例工作流（替换成你的真实 workflow JSON） ===
BASE_WORKFLOW = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 12345, "steps": 20, "cfg": 7,
            "sampler_name": "euler", "scheduler": "normal",
            "denoising": 1,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        }
    },
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "your_model.safetensors"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "masterpiece, best quality, girl", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "worst quality", "clip": ["4", 1]}},
    "8": {"class_type": "VAELoader", "inputs": {"vae_name": "your_vae.safetensors"}},
    "9": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["8", 0]}},
    "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "celery_gen"}}
}


def get_task_func(instance):
    return globals()[f"run_comfy_{instance}"]


def submit_one(instance, priority='normal', workflow=None):
    """提交单个任务"""
    if instance not in COMFY_INSTANCES:
        print(f"❌ 未知实例 {instance}，可选: {all_instances()}")
        return None

    task_func = get_task_func(instance)
    wf = workflow or BASE_WORKFLOW

    # VIP 任务：先设置 pending 标志（worker 会看到并让位）
    if priority == 'vip':
        rcli.set(KEY_VIP_PENDING, "true")

    priority_val = 9 if priority == 'vip' else 5
    task = task_func.apply_async(args=[wf, priority], priority=priority_val)
    icon = "⭐" if priority == 'vip' else "✅"
    print(f"{icon} [{instance}] ({priority}) task_id={task.id}")
    return task


def submit_batch(instance, n, priority='normal'):
    """批量提交 n 个任务"""
    tasks = []
    icon = "⭐" if priority == 'vip' else "📦"
    print(f"{icon} 批量提交 {n} 个 {priority} 任务到 [{instance}]")
    task_func = get_task_func(instance)
    priority_val = 9 if priority == 'vip' else 5

    if priority == 'vip':
        rcli.set(KEY_VIP_PENDING, "true")

    for i in range(n):
        wf = dict(BASE_WORKFLOW)
        wf["3"]["inputs"]["seed"] = 1000 + i
        task = task_func.apply_async(args=[wf, priority], priority=priority_val)
        print(f"  [{i+1}/{n}] task_id={task.id}")
        tasks.append(task)
    return tasks


def submit_auto(strategy='round_robin', priority='normal'):
    """智能路由"""
    sched = SmartScheduler()
    chosen = sched.pick(strategy=strategy)
    print(f"🧠 调度器选了 [{chosen}] (策略={strategy})")
    return submit_one(chosen, priority)


def main():
    parser = argparse.ArgumentParser(description="ComfyUI 任务提交")
    parser.add_argument("target", nargs="?", default="auto",
                        help="目标实例 (gpu0/gpu1/cpu) 或策略 (auto/least/round_robin)")
    parser.add_argument("count", nargs="?", type=int, default=None,
                        help="批量数量，如 5")
    parser.add_argument("priority", nargs="?", default="normal",
                        choices=["normal", "vip"],
                        help="优先级: normal（普通） 或 vip（VIP 抢 GPU）")
    args = parser.parse_args()

    # 批量模式
    if args.count and args.target in COMFY_INSTANCES:
        submit_batch(args.target, args.count, args.priority)
        return

    # 智能路由
    if args.target in ("auto", "least", "round_robin", "random"):
        submit_auto(strategy=args.target, priority=args.priority)
        return

    # 显式指定
    submit_one(args.target, args.priority)


if __name__ == "__main__":
    main()
