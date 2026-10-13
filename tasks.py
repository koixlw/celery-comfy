"""
Celery 任务：调用 ComfyUI API 生成图片

特点：
- 可被 activity_monitor.py 通过 Redis 协调暂停
- 暂停时自动中断 ComfyUI 并重新入队
- 重新入队的任务会在 pause 解除后才真正提交到 ComfyUI
"""
from celery import Celery
import requests
import time
import redis

# === 配置 ===
COMFY_URL = "http://127.0.0.1:8188"
BROKER_URL = 'redis://127.0.0.1:6379/0'
BACKEND_URL = 'redis://127.0.0.1:6379/0'
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0

app = Celery('tasks', broker=BROKER_URL, backend=BACKEND_URL)

# Redis 客户端（用于跨进程协调 monitor 和 worker）
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# Redis key 集中管理，方便 monitor 和 worker 对齐
KEY_PAUSE = "comfy:pause"             # "true" 表示用户在使用电脑，worker 必须暂停
KEY_CURRENT_PROMPT = "comfy:current_prompt_id"   # ComfyUI 当前正在跑的 prompt
KEY_CURRENT_TASK = "comfy:current_task_id"       # Celery 当前正在跑的 task
KEY_LAST_INTERRUPT = "comfy:last_interrupt_ts"   # 上次中断时间（给 monitor 参考）


def get_history(prompt_id):
    res = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10)
    return res.json()


def interrupt_comfy():
    """调用 ComfyUI /interrupt，立即停止当前任务（保留部分输出或完全中断）"""
    try:
        res = requests.post(f"{COMFY_URL}/interrupt", timeout=5)
        return res.json()
    except Exception as e:
        print(f"[worker] interrupt 异常: {e}")
        return None


def is_paused():
    """检查 monitor 是否发出暂停信号"""
    return r.get(KEY_PAUSE) == "true"


def wait_for_resume(poll_interval=2.0):
    """阻塞等待 pause 解除"""
    print("[worker] ⏸  暂停中，等待用户空闲...")
    while is_paused():
        time.sleep(poll_interval)
    print("[worker] ▶  恢复执行")


@app.task(bind=True)
def run_comfy_task(self, workflow_json):
    """可中断的 ComfyUI 任务。

    流程：
    1. 如果 pause=true，先等待
    2. 提交到 ComfyUI，轮询等待完成
    3. 轮询中如果 pause=true，中断 ComfyUI 并重新入队
    """
    task_id = self.request.id
    print(f"\n[worker] 任务启动 task_id={task_id}")

    # 登记当前任务，让 monitor 能看到
    r.set(KEY_CURRENT_TASK, task_id)

    # 启动时就处于暂停状态？那就先等
    if is_paused():
        wait_for_resume()

    # 提交工作流到 ComfyUI
    print(f"[worker] 提交 ComfyUI 工作流...")
    try:
        res = requests.post(f"{COMFY_URL}/prompt", json={"prompt": workflow_json}, timeout=30)
    except Exception as e:
        print(f"[worker] 提交异常: {e}")
        r.delete(KEY_CURRENT_PROMPT, KEY_CURRENT_TASK)
        return {"status": "error", "error": str(e)}

    if res.status_code != 200:
        err = res.text
        print(f"[worker] 提交失败 ({res.status_code}): {err}")
        r.delete(KEY_CURRENT_PROMPT, KEY_CURRENT_TASK)
        return {"status": "error", "error": err}

    prompt_id = res.json()["prompt_id"]
    r.set(KEY_CURRENT_PROMPT, prompt_id)
    print(f"[worker] ComfyUI prompt_id={prompt_id}，开始等待生成...")

    # 轮询等待生成完成
    try:
        while True:
            # 关键检查：是否要暂停？
            if is_paused():
                print(f"[worker] ⏸  检测到 pause 信号，中断 prompt={prompt_id}")
                interrupt_comfy()
                r.set(KEY_LAST_INTERRUPT, str(time.time()))
                # 重新入队（同一个 workflow），下一个 worker 会再次检查 pause
                print(f"[worker] 重新入队，等待空闲后继续...")
                run_comfy_task.apply_async(args=[workflow_json])
                return {"status": "paused", "prompt_id": prompt_id, "task_id": task_id}

            # 检查是否完成
            history = get_history(prompt_id)
            if prompt_id in history:
                break
            time.sleep(1)
    finally:
        # 不管正常完成还是异常，都清理
        r.delete(KEY_CURRENT_PROMPT)
        r.delete(KEY_CURRENT_TASK)

    output = history[prompt_id]["outputs"]
    print(f"[worker] ✅ prompt={prompt_id} 生成完成")
    return {
        "status": "done",
        "prompt_id": prompt_id,
        "task_id": task_id,
        "output": output,
    }
