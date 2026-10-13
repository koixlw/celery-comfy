"""
Celery 任务：多 ComfyUI 实例 + 自动重试 + 优先级

每个 COMFY_INSTANCES 配置的 key 都自动生成一个 task：
    tasks.run_comfy_gpu0  -> 路由到 gpu0 队列
    tasks.run_comfy_gpu1  -> 路由到 gpu1 队列
    tasks.run_comfy_cpu   -> 路由到 cpu 队列

新功能：
- 自动重试：网络错误 / ComfyUI 5xx 错误自动重试 3 次（指数退避）
- 优先级：支持 vip / normal，VIP 任务抢到 GPU，普通任务让位
- 暂停逻辑（comfy:pause）：用户用电脑时所有实例都暂停
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

# === 自动重试 & 优先级配置 ===
app.conf.update(
    task_routes={
        f'tasks.run_comfy_{name}': {'queue': name}
        for name in COMFY_INSTANCES
    },
    task_default_queue='gpu0',
    # 启用 Redis broker 的优先级支持
    broker_transport_options={
        'priority_steps': list(range(10)),
        'queue_order_strategy': 'priority',
    },
    # 任务在 worker 崩溃后会重新投递
    task_acks_late=True,
    # 每次只预取 1 个任务，避免 worker 霸占队列
    worker_prefetch_multiplier=1,
    # 序列化
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
)


# === 可重试异常 ===
class RetryableError(Exception):
    """网络错误 / 5xx 等可重试的错误"""
    pass


r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# Redis key
KEY_PAUSE = "comfy:pause"
KEY_VIP_PENDING = "comfy:vip_pending"  # 有 VIP 任务在等待


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


def is_vip_pending():
    return r.get(KEY_VIP_PENDING) == "true"


def wait_for_resume(poll=2.0):
    print("[worker] ⏸  暂停中，等待用户空闲...")
    while is_paused():
        time.sleep(poll)
    print("[worker] ▶  恢复执行")


def wait_for_vip_clear(poll=2.0):
    """普通任务让位：等 VIP 跑完"""
    print("[worker] ⭐ VIP 任务在排队，普通任务让位...")
    while is_vip_pending() and not is_paused():
        time.sleep(poll)


def interrupt_comfy(url):
    try:
        return requests.post(f"{url}/interrupt", timeout=5).json()
    except Exception as e:
        print(f"[worker] interrupt 异常: {e}")
        return None


def _priority_value(priority):
    """vip=9, normal=5"""
    return 9 if priority == 'vip' else 5


def _run_comfy_core(workflow_json, instance, task_id, priority='normal'):
    """所有实例共享的执行逻辑"""
    cfg = get_instance(instance)
    url = cfg["url"]

    r.set(key_task(instance), task_id)
    r.incr(key_active(instance))
    r.incr(key_total(instance))

    try:
        # === 启动时的优先级协商 ===
        if priority == 'vip':
            # VIP 任务：清除 pending 标志，告诉别人我来了
            r.delete(KEY_VIP_PENDING)
            print(f"[worker:{instance}] ⭐ VIP 任务，优先执行")
        else:
            # 普通任务：先看有没有 VIP 在等
            if is_vip_pending():
                wait_for_vip_clear()

        # 暂停检查
        if is_paused():
            wait_for_resume()

        # === 提交到 ComfyUI ===
        print(f"[worker:{instance}] 提交工作流 → {url}")
        try:
            res = requests.post(f"{url}/prompt", json={"prompt": workflow_json}, timeout=30)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            raise RetryableError(f"无法连接 ComfyUI {url}: {e}")
        except Exception as e:
            return {"status": "error", "error": str(e), "instance": instance}

        if res.status_code == 200:
            prompt_id = res.json()["prompt_id"]
        elif 500 <= res.status_code < 600:
            raise RetryableError(f"ComfyUI {res.status_code}: {res.text[:200]}")
        else:
            # 4xx 客户端错误，不重试
            return {"status": "error", "error": res.text[:200], "instance": instance, "code": res.status_code}

        r.set(key_prompt(instance), prompt_id)
        print(f"[worker:{instance}] prompt_id={prompt_id}，开始等待 (priority={priority})...")

        # === 轮询循环 ===
        while True:
            # 检查 1: VIP 让位（普通任务才检查）
            if priority != 'vip' and is_vip_pending():
                print(f"[worker:{instance}] ⭐ 让位给 VIP 任务")
                interrupt_comfy(url)
                _reenqueue(workflow_json, instance, priority=8)  # 8 < 9(VIP)
                return {"status": "yielded", "prompt_id": prompt_id, "instance": instance}

            # 检查 2: 用户活动暂停
            if is_paused():
                print(f"[worker:{instance}] ⏸  暂停信号，中断 {prompt_id}")
                interrupt_comfy(url)
                _reenqueue(workflow_json, instance, priority=priority)
                return {"status": "paused", "prompt_id": prompt_id, "instance": instance}

            # 检查 3: 是否完成
            try:
                history = requests.get(f"{url}/history/{prompt_id}", timeout=10).json()
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                raise RetryableError(f"查 history 失败: {e}")
            except Exception as e:
                print(f"[worker:{instance}] 查 history 异常: {e}，继续...")
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


def _reenqueue(workflow_json, instance, priority='normal'):
    """重新入队"""
    task_func = globals().get(f"run_comfy_{instance}")
    if task_func:
        task_func.apply_async(
            args=[workflow_json, priority],
            priority=_priority_value(priority),
        )
    else:
        print(f"[worker] 找不到 run_comfy_{instance}，重入队失败！")


# === 动态生成每个实例对应的 task（带重试配置）===
def _make_task(instance):
    @app.task(
        bind=True,
        name=f'tasks.run_comfy_{instance}',
        autoretry_for=(RetryableError,),
        retry_backoff=True,         # 指数退避: 1s, 2s, 4s
        retry_backoff_max=30,       # 最长 30s
        retry_jitter=True,          # 加随机抖动，避免雪崩
        max_retries=3,              # 最多重试 3 次
        acks_late=True,             # worker 崩溃后会重新投递
    )
    def task(self, workflow_json, priority='normal'):
        return _run_comfy_core(workflow_json, instance, self.request.id, priority)
    return task


for _instance in COMFY_INSTANCES:
    globals()[f"run_comfy_{_instance}"] = _make_task(_instance)


# === 向后兼容 ===
def run_comfy_task(workflow_json):
    return run_comfy_gpu0(workflow_json)


run_comfy_task.delay = run_comfy_gpu0.delay
run_comfy_task.apply_async = run_comfy_gpu0.apply_async
run_comfy_task.AsyncResult = run_comfy_gpu0.AsyncResult
