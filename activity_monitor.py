"""
键鼠活动监听 + ComfyUI 任务调度器

用法：
    1. 装依赖：pip install pynput redis requests
    2. 启动一个 PowerShell 窗口运行：python activity_monitor.py
    3. 另一个窗口照常跑 Celery worker 和提交任务
    4. 你用电脑时，ComfyUI 自动暂停；你停手 IDLE_THRESHOLD 秒后自动恢复

核心逻辑：
    - pynput 监听鼠标/键盘 → 更新"最后活动时间"
    - 主循环每秒检查：
        * 用户活动中（最近 IDLE_THRESHOLD 秒内有动作）
          → 写 Redis comfy:pause = true → 主动调 ComfyUI /interrupt
        * 用户空闲超过 IDLE_THRESHOLD 秒
          → 写 Redis comfy:pause = false → worker 自动继续
"""
import time
import threading
import requests
import redis
from pynput import mouse, keyboard

# === 配置 ===
COMFY_URL = "http://127.0.0.1:8188"
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0

# 空闲阈值：多久没动鼠标键盘算"空闲"（秒）
IDLE_THRESHOLD = 3.0

# 主循环检查间隔
POLL_INTERVAL = 1.0

# Redis key（必须和 tasks.py 里的对齐）
KEY_PAUSE = "comfy:pause"
KEY_CURRENT_PROMPT = "comfy:current_prompt_id"
KEY_CURRENT_TASK = "comfy:current_task_id"


# 用 list 包装是为了让嵌套函数能修改它（Python 的 closure 限制）
last_activity = [time.time()]


def on_activity(*args, **kwargs):
    """pynput 回调：只要鼠标/键盘有任何动作就刷新时间戳"""
    last_activity[0] = time.time()


def interrupt_comfy():
    """调用 ComfyUI /interrupt"""
    try:
        r = requests.post(f"{COMFY_URL}/interrupt", timeout=5)
        return r.status_code == 200
    except Exception as e:
        print(f"[monitor] interrupt 异常（可忽略，ComfyUI 可能没在跑）: {e}")
        return False


def main():
    # 连接 Redis
    rcli = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    print(f"[monitor] 已连接 Redis: {REDIS_HOST}:{REDIS_PORT}")

    # 初始状态：未暂停
    rcli.set(KEY_PAUSE, "false")

    # 启动鼠标监听
    mouse_listener = mouse.Listener(
        on_move=on_activity,      # 鼠标移动
        on_click=on_activity,     # 鼠标点击
        on_scroll=on_activity,    # 滚轮
    )
    # 启动键盘监听
    keyboard_listener = keyboard.Listener(
        on_press=on_activity,     # 按键
        on_release=on_activity,   # 松键
    )
    mouse_listener.start()
    keyboard_listener.start()
    print("[monitor] 鼠标 + 键盘监听已启动")

    print(f"[monitor] 空闲阈值 {IDLE_THRESHOLD}s。开始监控...")
    print("[monitor] 你用电脑时 ComfyUI 会自动暂停；停手 {}s 后自动恢复。".format(IDLE_THRESHOLD))
    print("[monitor] 按 Ctrl+C 退出\n")

    last_state = None  # 用来只在状态变化时打印

    try:
        while True:
            now = time.time()
            idle_for = now - last_activity[0]
            user_active = idle_for < IDLE_THRESHOLD

            # 读 worker 当前在做什么（仅用于显示）
            current_prompt = rcli.get(KEY_CURRENT_PROMPT) or "-"
            current_task = rcli.get(KEY_CURRENT_TASK) or "-"

            # 决定新状态
            new_state = "PAUSE" if user_active else "RESUME"

            # 状态变化时打印一行
            if new_state != last_state:
                if new_state == "PAUSE":
                    print(f"[monitor] ⚠️   检测到用户活动（{idle_for:.1f}s 内有动作）→ 暂停 ComfyUI")
                else:
                    print(f"[monitor] ✅  空闲 {IDLE_THRESHOLD}s+ → 恢复 ComfyUI")
                last_state = new_state

            # 把状态写入 Redis，worker 会读到
            rcli.set(KEY_PAUSE, "true" if user_active else "false")

            # 如果要暂停且 ComfyUI 正在跑，主动调一次 interrupt
            # （worker 自己也会检测到 pause，但主动调一次能更快响应）
            if user_active and current_prompt != "-":
                interrupt_comfy()

            # 每秒打一次状态（方便你观察）
            status_char = "⏸ PAUSE" if user_active else "▶ RESUME"
            print(
                f"\r[{status_char}] idle={idle_for:5.1f}s  prompt={current_prompt}  task={current_task[:8]}",
                end="",
                flush=True,
            )

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n[monitor] 收到 Ctrl+C，正在清理...")
        rcli.set(KEY_PAUSE, "false")
        mouse_listener.stop()
        keyboard_listener.stop()
        print("[monitor] 已退出。")


if __name__ == "__main__":
    main()
