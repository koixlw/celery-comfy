# Celery + ComfyUI 多算力任务调度系统

一个用 Celery 调度多个 ComfyUI 实例的生产级工作流，支持**键鼠活动监听 + 自动暂停/恢复 + 智能路由**。

## ✨ 功能特性

- 🎨 **ComfyUI 集成**：通过 HTTP API 提交工作流
- 🚀 **多算力调度**：支持多 GPU / CPU 实例并行，按策略路由
- 🧠 **智能路由**：轮询 / 负载最低 / 随机 / 优先级
- 🖱️ **键鼠监听**：检测到用户活动自动中断所有 ComfyUI 实例
- ⏸️ **自动恢复**：用户空闲后任务自动继续
- 🔄 **任务中断重入队**：暂停时任务放回原队列，pause 解除后继续
- 📊 **GPU 监控**（可选）：读 nvidia-smi 写 Redis，给调度器做决策

## 📁 项目结构

```
celery_comfy/
├── comfy_instances.py     # 多实例配置（新增/删除 GPU 只改这个）
├── tasks.py               # Celery 任务（自动为每个实例生成）
├── submit_task.py         # 任务提交（支持显式/智能/批量）
├── scheduler.py           # 智能路由器
├── activity_monitor.py    # 键鼠监听 + 全实例调度
├── gpu_monitor.py         # GPU 状态采集
├── start_all.bat          # Windows 一键启动所有服务
├── requirements.txt
└── README.md
```

## 🏗️ 架构图

```
              submit_task.py
                    │
                    ▼
            ┌───────────────┐
            │  Smart        │
            │  Scheduler    │  ← 读 nvidia-smi / Redis 状态
            └───────┬───────┘
                    │ 选 instance (gpu0/gpu1/cpu)
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    [gpu0 队列] [gpu1 队列]  [cpu 队列]
        │           │           │
   Worker A     Worker B     Worker C
        │           │           │
        ▼           ▼           ▼
  ComfyUI:8188 ComfyUI:8189 ComfyUI:8190
  (CUDA 0)    (CUDA 1)     (CPU)

         ▲
         │  comfy:pause = true/false
         │
   activity_monitor.py (pynput)
```

## 🚀 快速开始

### 0. 修改配置

编辑 [comfy_instances.py](comfy_instances.py) 声明你的 ComfyUI 实例：

```python
COMFY_INSTANCES = {
    "gpu0": {"url": "http://127.0.0.1:8188", "device": "cuda:0", "max_concurrent": 1},
    # "gpu1": {"url": "http://127.0.0.1:8189", "device": "cuda:1", "max_concurrent": 1},  # 注释掉如果没有
    # "cpu":  {"url": "http://127.0.0.1:8190", "device": "cpu",    "max_concurrent": 2},
}
```

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 一键启动所有服务（Windows）

编辑 `start_all.bat` 里的 `COMFY_DIR`，然后双击运行。

或者手动启动（见下方）。

### 3. 手动启动

```powershell
# 窗口 1: Redis
redis-server

# 窗口 2: ComfyUI 主力
cd C:\ComfyUI
python main.py --port 8188 --listen 0.0.0.0

# 窗口 3: ComfyUI 副（如果有第二张卡）
cd C:\ComfyUI
set CUDA_VISIBLE_DEVICES=1
python main.py --port 8189 --listen 0.0.0.0

# 窗口 4-6: Celery workers（每个 GPU 一个）
cd C:\celery_comfy
python -m celery -A tasks worker -Q gpu0 -c 1 --pool=eventlet --loglevel=info
python -m celery -A tasks worker -Q gpu1 -c 1 --pool=eventlet --loglevel=info
python -m celery -A tasks worker -Q cpu  -c 2 --pool=eventlet --loglevel=info

# 窗口 7: 活动监听器
cd C:\celery_comfy
python activity_monitor.py

# 窗口 8: GPU 监控（可选）
cd C:\celery_comfy
python gpu_monitor.py
```

### 4. 提交任务

```bash
# 智能路由（轮询）
python submit_task.py

# 显式指定
python submit_task.py gpu0
python submit_task.py gpu1

# 选最闲的
python submit_task.py least

# VIP 任务
python submit_task.py gpu0 --priority high

# 批量 5 个到 gpu0
python submit_task.py gpu0 5
```

## 📋 调度策略对照

| 命令 | 策略 | 适用场景 |
|---|---|---|
| `python submit_task.py auto` | 轮询 | 默认，简单公平 |
| `python submit_task.py least` | 负载最低 | 想榨干所有 GPU |
| `python submit_task.py random` | 随机 | 压测 |
| `python submit_task.py gpu0` | 显式 | 知道目标 |

## 🖱️ 监听器行为

| 状态 | 行为 |
|---|---|
| 检测到鼠标/键盘活动 | `comfy:pause=true` + 给所有在线 ComfyUI 发 `/interrupt` |
| 空闲 IDLE_THRESHOLD 秒 | `comfy:pause=false`，worker 自动继续 |
| Worker 检测到 pause | 中断 ComfyUI + 任务重入队 |

## 🔧 常用操作

```bash
# 查看所有实例状态
python scheduler.py

# 查看 GPU 状态
python gpu_monitor.py --once

# 实时监控 GPU
python gpu_monitor.py

# 查 Redis 里的运行状态
redis-cli get comfy:pause
redis-cli keys 'comfy:*:prompt_id'
```

## ⚙️ 配置项

- **空闲阈值**：[activity_monitor.py](activity_monitor.py) 里的 `IDLE_THRESHOLD`
- **检查频率**：[activity_monitor.py](activity_monitor.py) 里的 `POLL_INTERVAL`
- **实例列表**：[comfy_instances.py](comfy_instances.py) 的 `COMFY_INSTANCES`
- **轮询 / 优先级 / 负载均衡**：[scheduler.py](scheduler.py) 的 `SmartScheduler`

## 📝 系统要求

- Python 3.9+
- Redis
- ComfyUI × N 个实例（每个跑在不同端口）
- NVIDIA GPU（可选，CPU 也能跑）

## 📜 License

MIT
