# Celery + ComfyUI 任务调度系统

一个用 Celery 调度 ComfyUI 推理任务的工作流，支持**键鼠活动监听 + 自动暂停/恢复**。

## ✨ 功能特性

- 🎨 **ComfyUI 集成**：通过 ComfyUI HTTP API 提交工作流任务
- 🖱️ **智能调度**：检测到用户使用电脑时自动中断任务，腾出 GPU
- ⏸️ **自动恢复**：用户空闲后任务自动从队列继续
- 🚀 **多算力路由**：支持把不同任务分发给不同的 GPU / CPU 实例
- 🔄 **任务中断重入队**：暂停时把任务放回队列，pause 解除后继续跑

## 📁 项目结构

```
celery_comfy/
├── tasks.py              # Celery 任务定义（可被暂停）
├── submit_task.py        # 任务提交脚本（支持多算力路由）
├── activity_monitor.py   # 键鼠监听 + 调度器
├── requirements.txt      # 依赖清单
└── README.md
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 Redis

```bash
redis-server
```

### 3. 启动 ComfyUI

```bash
# ComfyUI 目录
python main.py --listen 0.0.0.0 --port 8188
```

### 4. 启动 Celery Worker

```bash
cd celery_comfy
python -m celery -A tasks worker --pool=eventlet --loglevel=info
```

### 5. 启动活动监听器（新窗口）

```bash
cd celery_comfy
python activity_monitor.py
```

### 6. 提交任务（再开一个窗口）

```bash
cd celery_comfy
python submit_task.py
```

## ⚙️ 配置

### 修改 ComfyUI 地址

编辑 `tasks.py`：
```python
COMFY_URL = "http://127.0.0.1:8188"  # 改成你的 ComfyUI 地址
```

### 修改空闲阈值

编辑 `activity_monitor.py`：
```python
IDLE_THRESHOLD = 3.0  # 停手多少秒后恢复
```

## 🎬 工作流

1. **任务提交**：`submit_task.py` 把 workflow JSON 扔进 Celery 队列
2. **Worker 执行**：`tasks.py` 的 `run_comfy_task` 提交到 ComfyUI
3. **活动检测**：`activity_monitor.py` 用 pynput 监听鼠标键盘
4. **自动暂停**：检测到用户活动 → 写 Redis `comfy:pause=true` → Worker 调 ComfyUI `/interrupt` + 任务重入队
5. **自动恢复**：用户空闲 → 写 Redis `comfy:pause=false` → Worker 重新提交任务到 ComfyUI

## 📋 系统要求

- Python 3.9+
- Redis
- ComfyUI（含 HTTP API 开启）
- Windows / macOS / Linux

## 📝 License

MIT
