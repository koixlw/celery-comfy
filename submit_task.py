from tasks import run_comfy_task

# 这里替换成你从ComfyUI保存的【API格式工作流json】
# 在ComfyUI页面：Save(API)，复制出来粘贴在这里
# 注意：下面 ckpt_name / vae_name 是占位符，要改成你 ComfyUI/models 目录里实际存在的文件名
comfy_workflow = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 12345,
            "steps": 20,
            "cfg": 7,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoising": 1,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0]
        }
    },
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "your_model.safetensors"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "masterpiece, best quality, girl", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "worst quality, low quality", "clip": ["4", 1]}},
    "8": {"class_type": "VAELoader", "inputs": {"vae_name": "your_vae.safetensors"}},
    "9": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["8", 0]}},
    "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "celery_gen"}}
}


def submit_one():
    """提交单个任务，返回 task id"""
    task = run_comfy_task.delay(comfy_workflow)
    print(f"任务已送入队列，task id: {task.id}")
    print(f"查询结果：run_comfy_task.AsyncResult('{task.id}').get()")
    return task


def submit_batch(n=3):
    """批量提交 n 个任务，每个的 seed 不同"""
    tasks = []
    for i in range(n):
        wf = dict(comfy_workflow)
        wf["3"] = dict(wf["3"])
        wf["3"]["inputs"] = dict(wf["3"]["inputs"])
        wf["3"]["inputs"]["seed"] = 12345 + i
        task = run_comfy_task.delay(wf)
        print(f"[{i+1}/{n}] 任务已入队: {task.id}")
        tasks.append(task)
    return tasks


if __name__ == "__main__":
    # 默认提交 1 个任务；想批量改成 submit_batch(5)
    submit_one()
