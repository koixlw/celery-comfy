"""
Web 控制面板 - Flask

功能：
- 实时显示所有 ComfyUI 实例状态
- 显示 GPU 显存/利用率
- 显示当前任务、VIP 状态、暂停状态
- 一键暂停/恢复
- 通过 Web 提交任务
- 队列深度监控

启动：python web_dashboard.py
访问：http://127.0.0.1:5000
"""
import json
import time
import requests
import redis
from flask import Flask, render_template, jsonify, request
from comfy_instances import COMFY_INSTANCES, all_instances, get_instance

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
KEY_PAUSE = "comfy:pause"
KEY_VIP_PENDING = "comfy:vip_pending"

app = Flask(__name__)
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def _check_alive(url, timeout=2):
    try:
        return requests.get(f"{url}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


def _get_queue_depth(queue_name):
    """读 Celery 在 Redis 里的队列长度"""
    try:
        return r.llen(queue_name)
    except Exception:
        return -1


def _get_gpu_info():
    """从 Redis 读 GPU 状态（由 gpu_monitor.py 写入）"""
    gpus = []
    for i in range(8):
        mem_free = r.get(f"gpu:{i}:mem_free_mb")
        if mem_free is None:
            continue
        gpus.append({
            "index": i,
            "name": r.get(f"gpu:{i}:name") or f"GPU {i}",
            "mem_free_mb": int(mem_free),
            "util_pct": int(r.get(f"gpu:{i}:util_pct") or 0),
        })
    return gpus


@app.route('/')
def index():
    return render_template('dashboard.html', instances=COMFY_INSTANCES)


@app.route('/api/status')
def api_status():
    """全量状态查询"""
    data = {
        "timestamp": time.time(),
        "pause": r.get(KEY_PAUSE) == "true",
        "vip_pending": r.get(KEY_VIP_PENDING) == "true",
        "instances": {},
        "gpus": _get_gpu_info(),
        "queues": {},
        "totals": {"active": 0, "submitted": 0, "queued": 0},
    }
    for inst in all_instances():
        cfg = get_instance(inst)
        url = cfg["url"]
        active = int(r.get(f"comfy:{inst}:active_count") or 0)
        total = int(r.get(f"comfy:{inst}:total_count") or 0)
        qdepth = _get_queue_depth(inst)
        data["instances"][inst] = {
            "description": cfg["description"],
            "url": url,
            "device": cfg["device"],
            "max_concurrent": cfg["max_concurrent"],
            "alive": _check_alive(url),
            "active": active,
            "total": total,
            "queue_depth": qdepth,
            "prompt_id": r.get(f"comfy:{inst}:prompt_id") or "",
            "task_id": r.get(f"comfy:{inst}:task_id") or "",
        }
        data["totals"]["active"] += active
        data["totals"]["submitted"] += total
        if qdepth > 0:
            data["totals"]["queued"] += qdepth
        data["queues"][inst] = qdepth
    return jsonify(data)


@app.route('/api/pause', methods=['POST'])
def api_pause():
    r.set(KEY_PAUSE, "true")
    return jsonify({"ok": True, "pause": True})


@app.route('/api/resume', methods=['POST'])
def api_resume():
    r.set(KEY_PAUSE, "false")
    return jsonify({"ok": True, "pause": False})


@app.route('/api/interrupt', methods=['POST'])
def api_interrupt():
    """给所有在线 ComfyUI 发 interrupt"""
    interrupted = []
    for inst in all_instances():
        url = get_instance(inst)["url"]
        if not _check_alive(url):
            continue
        try:
            requests.post(f"{url}/interrupt", timeout=3)
            interrupted.append(inst)
        except Exception:
            pass
    return jsonify({"ok": True, "interrupted": interrupted})


@app.route('/api/submit', methods=['POST'])
def api_submit():
    """通过 Web 提交任务"""
    from tasks import run_comfy_gpu0, run_comfy_gpu1, run_comfy_cpu

    data = request.json or {}
    instance = data.get('instance', 'gpu0')
    priority = data.get('priority', 'normal')  # 'vip' or 'normal'
    workflow = data.get('workflow', {})

    if instance not in COMFY_INSTANCES:
        return jsonify({"ok": False, "error": f"未知实例: {instance}"}), 400
    if not workflow:
        return jsonify({"ok": False, "error": "workflow 不能为空"}), 400

    task_func = globals().get(f"run_comfy_{instance}")
    if not task_func:
        return jsonify({"ok": False, "error": f"找不到 task: {instance}"}), 500

    # VIP 任务：设置 pending 标志
    if priority == 'vip':
        r.set(KEY_VIP_PENDING, "true")

    priority_val = 9 if priority == 'vip' else 5
    task = task_func.apply_async(args=[workflow, priority], priority=priority_val)
    return jsonify({"ok": True, "task_id": task.id, "instance": instance, "priority": priority})


@app.route('/api/health')
def api_health():
    return jsonify({"ok": True, "service": "web_dashboard"})


if __name__ == '__main__':
    print("=" * 50)
    print("  ComfyUI 任务调度面板")
    print("  访问: http://127.0.0.1:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)
