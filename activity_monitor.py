"""
键鼠活动监听 + 多实例调度器

增强版（支持多 ComfyUI 实例）：
- 监听鼠标/键盘，更新最后活动时间
- 用户活动时：给所有在线实例发 pause + interrupt
- 空闲时：解除 pause
"""
import time
import requests
import redis
from pynput import mouse, keyboard
from comfy_instances import all_instances, get_instance
from scheduler import is_alive

# === 配置 ===
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
KEY_PAUSE = "comfy:pause"

IDLE_THRESHOLD = 3.0   # 停手几秒算"空闲"
POLL_INTERVAL = 1.0    # 检查频率

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
last_activity = [time.time()]


def on_activity(*args, **kwargs):
    last_activity[0] = time.time()


def interrupt_all_alive():
    """给所有在线 ComfyUI 实例发 interrupt"""
    interrupted = 0
    for inst in all_instances():
        if not is_alive(inst):
            continue
        url = get_instance(inst)["url"]
        try:
            requests.post(f"{url}/interrupt", timeout=3)
            interrupted += 1
        except Exception as e:
            print(f"\n[monitor] interrupt {inst} 失败: {e}")
    return interrupted


def get_running_prompts():
    """收集所有实例当前正在跑的 prompt（用于显示）"""
    out = {}
    for inst in all_instances():
        pid = r.get(f"comfy:{inst}:prompt_id")
        if pid:
            out[inst] = pid
    return out


def main():
    r.set(KEY_PAUSE, "false")
    print(f"[monitor] Redis 已连接: {REDIS_HOST}:{REDIS_PORT}")

    # 启动监听
    mouse.Listener(on_move=on_activity, on_click=on_activity, on_scroll=on_activity).start()
    keyboard.Listener(on_press=on_activity, on_release=on_activity).start()
    print("[monitor] 鼠标 + 键盘监听已启动")

    # 检查哪些 ComfyUI 在线
    alive = [i for i in all_instances() if is_alive(i)]
    print(f"[monitor] 在线 ComfyUI: {alive if alive else '⚠️  全部离线！'}")

    print(f"[monitor] 空闲阈值 {IDLE_THRESHOLD}s。按 Ctrl+C 退出\n")
    last_state = None

    try:
        while True:
            now = time.time()
            idle = now - last_activity[0]
            user_active = idle < IDLE_THRESHOLD
            new_state = "PAUSE" if user_active else "RESUME"

            if new_state != last_state:
                if new_state == "PAUSE":
                    print(f"\n[monitor] ⚠️   检测到用户活动（{idle:.1f}s 内）→ 暂停所有 ComfyUI")
                else:
                    print(f"\n[monitor] ✅  空闲 {IDLE_THRESHOLD}s+ → 恢复")
                last_state = new_state

            r.set(KEY_PAUSE, "true" if user_active else "false")

            if user_active:
                # 主动给所有在线实例发 interrupt（worker 自己也会检测，双保险）
                n = interrupt_all_alive()
                if n > 0:
                    print(f"[monitor]    已 interrupt {n} 个实例")

            # 状态行
            running = get_running_prompts()
            char = "⏸" if user_active else "▶"
            state = "PAUSE" if user_active else "RESUME"
            run_str = " ".join(f"{k}={v[:6]}" for k, v in running.items()) or "-"
            print(f"\r[{char} {state}] idle={idle:5.1f}s  running: {run_str}   ", end="", flush=True)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n[monitor] 收到 Ctrl+C，清理中...")
        r.set(KEY_PAUSE, "false")
        print("[monitor] 已退出。")


if __name__ == "__main__":
    main()
