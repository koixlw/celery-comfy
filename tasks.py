"""
Celery 任务：多 ComfyUI 实例版本

每个 COMFY_INSTANCES 配置的 key 都自动生成一个 task：
    tasks.run_comfy_gpu0  -> 路由到 gpu0 队列
    tasks.run_comfy_gpu1  -> 路由到 gpu1 队列
    tasks.run_comfy_cpu   -> 路由到 cpu 队列

暂停逻辑（comfy:pause）依然是全局的：用户用电脑时所有实例都暂停
"""
from celery import Celery
import requests
import time
import redis
from comfy_instances import COMFY_INSTANCES, get_instance

# === Redis ===
BROKER_URL = 'redis://127.0.0.1:6379/0'
BACKEND_URL = 'redis://127.0.0.1:6379/0'
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0

app = Celery('tasks', broker=BROKER_URL, backend=BACKEND_URL)

# 自动生成 task_routes
app.conf.task_routes = {
    f'tasks.run_comfy_{name}': {'queue': name}
    for name in COMFY_INSTANCES
}
app.conf.task_default_queue = 'gpu0'

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# Redis key
KEY_PAUSE = "comfy:pause"


def key_prompt(instance):
    return f"comfy:{instance}:prompt_id"


def key_task(instance):
    return f"comfy:{instance}:task_id"


def key_active(instance):
    return f"comfy:{instance}:active_count"


def key_total(instance):
    return f"comfy:{instance}:total_count"


def is_paused():
    return r.get(KEY_PAUSE) == "true"


def wait_for_resume(poll=2.0):
    print("[worker] ⏸  暂停中，等待用户空闲...")
    while is_paused():
        time.sleep(poll)
    print("[worker] ▶  恢复执行")


def interrupt_comfy(url):
    try:
        return requests.post(f"{url}/interrupt", timeout=5).json()
    except Exception as e:
        print(f"[worker] interrupt 异常: {e}")
        return None


def _run_comfy_core(workflow_json, instance, task_id):
    """所有实例共享的执行逻辑"""
    cfg = get_instance(instance)
    url = cfg["url"]

    # 登记任务
    r.set(key_task(instance), task_id)
    r.incr(key_active(instance))
    r.incr(key_total(instance))

    try:
        # 启动时就暂停？先等
        if is_paused():
            wait_for_resume()

        # 提交到 ComfyUI
        print(f"[worker:{instance}] 提交工作流 → {url}")
        try:
            res = requests.post(f"{url}/prompt", json={"prompt": workflow_json}, timeout=30)
        except requests.exceptions.ConnectionError:
            print(f"[worker:{instance}] ❌ ComfyUI {url} 连不上（是否启动了？）")
            return {"status": "error", "error": f"ComfyUI {url} unreachable", "instance": instance}

        if res.status_code != 200:
            err = res.text[:200]
            print(f"[worker:{instance}] ❌ 提交失败: {err}")
            return {"status": "error", "error": err, "instance": instance}

        prompt_id = res.json()["prompt_id"]
        r.set(key_prompt(instance), prompt_id)
        print(f"[worker:{instance}] prompt_id={prompt_id}，开始等待...")

        # 轮询
        while True:
            if is_paused():
                print(f"[worker:{instance}] ⏸  暂停信号，中断 {prompt_id}")
                interrupt_comfy(url)
                # 重新入队：调本实例对应的 task
                _reenqueue(workflow_json, instance)
                return {"status": "paused", "prompt_id": prompt_id, "instance": instance}

            try:
                history = requests.get(f"{url}/history/{prompt_id}", timeout=10).json()
            except Exception as e:
                print(f"[worker:{instance}] 查 history 失败: {e}，重试...")
                time.sleep(1)
                continue

            if prompt_id in history:
                break
            time.sleep(1)

        output = history[prompt_id]["outputs"]
        print(f"[worker:{instance}] ✅ prompt={prompt_id} 完成")
        return {
            "status": "done",
            "prompt_id": prompt_id,
            "instance": instance,
            "output": output,
        }
    finally:
        r.delete(key_prompt(instance))
        r.delete(key_task(instance))
        r.decr(key_active(instance))


def _reenqueue(workflow_json, instance):
    """把任务重新扔回 instance 自己的队列"""
    task_func = globals().get(f"run_comfy_{instance}")
    if task_func:
        task_func.apply_async(args=[workflow_json])
    else:
        print(f"[worker] 找不到 run_comfy_{instance}，重入队失败！")


# === 动态生成每个实例对应的 task ===
def _make_task(instance):
    @app.task(bind=True, name=f'tasks.run_comfy_{instance}')
    def task(self, workflow_json):
        return _run_comfy_core(workflow_json, instance, self.request.id)
    return task


for _instance in COMFY_INSTANCES:
    globals()[f"run_comfy_{_instance}"] = _make_task(_instance)


# === 向后兼容：旧的 run_comfy_task 默认指向 gpu0 ===
def run_comfy_task(workflow_json):
    """兼容老代码：等价于 run_comfy_gpu0"""
    return run_comfy_gpu0(workflow_json)


run_comfy_task.delay = run_comfy_gpu0.delay
run_comfy_task.apply_async = run_comfy_gpu0.apply_async
run_comfy_task.AsyncResult = run_comfy_gpu0.AsyncResult
