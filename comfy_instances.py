"""
ComfyUI 实例配置中心

每个 key 是一个实例名（同时也是 Celery 队列名）
新增/删除 GPU 只需要改这一个文件，重启 worker 即可
"""

COMFY_INSTANCES = {
    "gpu0": {
        "url": "http://127.0.0.1:8188",
        "device": "cuda:0",
        "max_concurrent": 1,
        "model_hint": "sdxl",  # 用于按模型路由
        "description": "主力 GPU 0 - 高质量出图",
    },
    "gpu1": {
        "url": "http://127.0.0.1:8189",
        "device": "cuda:1",
        "max_concurrent": 1,
        "model_hint": "sd15",
        "description": "副 GPU 1 - 快速预览",
    },
    "cpu": {
        "url": "http://127.0.0.1:8190",
        "device": "cpu",
        "max_concurrent": 2,
        "model_hint": "sd15",
        "description": "CPU 实例 - 草稿/小图",
    },
}


def get_instance(name):
    """获取实例配置，找不到则列出所有可用"""
    if name not in COMFY_INSTANCES:
        raise ValueError(
            f"未知实例: {name}，可选: {list(COMFY_INSTANCES.keys())}"
        )
    return COMFY_INSTANCES[name]


def all_instances():
    return list(COMFY_INSTANCES.keys())


def gpu_instances():
    """返回所有 GPU 实例名（不含 cpu）"""
    return [k for k, v in COMFY_INSTANCES.items() if v["device"].startswith("cuda")]
