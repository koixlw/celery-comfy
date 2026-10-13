"""
任务提交脚本 - 多算力版本

用法示例：
    python submit_task.py                      # 智能路由（默认）
    python submit_task.py gpu0                 # 显式指定 gpu0
    python submit_task.py gpu1
    python submit_task.py auto                 # 智能路由（轮询）
    python submit_task.py least                # 智能路由（负载最低）
    python submit_task.py --priority high gpu0 # VIP 任务
    python submit_task.py batch 5 gpu0         # 批量提交 5 个
"""
import sys
import argparse
from tasks import run_comfy_gpu0, run_comfy_gpu1, run_comfy_cpu
from scheduler import SmartScheduler
from comfy_instances import COMFY_INSTANCES, all_instances

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


def submit_explicit(instance, workflow=None, priority=None):
    """显式提交到指定实例"""
    if instance not in COMFY_INSTANCES:
        print(f"❌ 未知实例 {instance}，可选: {all_instances()}")
        return None
    wf = workflow or BASE_WORKFLOW
    task_func = get_task_func(instance)
    kwargs = {"queue": instance}
    if priority == "high":
        kwargs["priority"] = 9  # Celery 0-9，9 最高
    task = task_func.apply_async(args=[wf], **kwargs)
    print(f"✅ [{instance}] task_id={task.id}")
    return task


def submit_auto(strategy="round_robin", workflow=None, priority=None):
    """智能路由：让 scheduler 挑一个实例"""
    wf = workflow or BASE_WORKFLOW
    sched = SmartScheduler()
    chosen = sched.pick(strategy=strategy)
    print(f"🧠 调度器选了 [{chosen}] (策略={strategy})")
    return submit_explicit(chosen, wf, priority)


def submit_batch(instance, n, priority=None):
    """批量提交 n 个任务到同一实例"""
    tasks = []
    task_func = get_task_func(instance)
    for i in range(n):
        wf = dict(BASE_WORKFLOW)
        wf["3"]["inputs"]["seed"] = 1000 + i
        kwargs = {"queue": instance}
        if priority == "high":
            kwargs["priority"] = 9
        task = task_func.apply_async(args=[wf], **kwargs)
        print(f"  [{i+1}/{n}] task_id={task.id}")
        tasks.append(task)
    return tasks


def main():
    parser = argparse.ArgumentParser(description="ComfyUI 任务提交")
    parser.add_argument("target", nargs="?", default="auto",
                        help=f"目标实例 ({'/'.join(all_instances())}) 或策略 (auto/least)")
    parser.add_argument("extra", nargs="?", default=None,
                        help="可选: batch N 表示批量 N 个")
    parser.add_argument("--priority", choices=["high", "normal"], default="normal",
                        help="任务优先级 (high=VIP)")
    args = parser.parse_args()

    # 批量模式
    if args.extra and args.extra.isdigit() and args.target in COMFY_INSTANCES:
        n = int(args.extra)
        print(f"📦 批量提交 {n} 个任务到 [{args.target}]")
        submit_batch(args.target, n, args.priority)
        return

    # 智能路由
    if args.target in ("auto", "least", "round_robin"):
        submit_auto(strategy=args.target, priority=args.priority)
        return

    # 显式指定
    submit_explicit(args.target, priority=args.priority)


if __name__ == "__main__":
    main()
