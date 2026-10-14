# 多机算力共享部署指南

把多台电脑的 GPU 接入同一个 ComfyUI 任务池。

## 🏗️ 架构总览

```
┌────────────────────────────────────────────────────────┐
│  机器 A (你) - 中央调度机                                │
│                                                        │
│  Redis:6379    ←────── 所有 worker 连这里              │
│  Web Dashboard:5000  ← 浏览器开这里看全局              │
│  提交任务: submit_task.py                               │
│                                                        │
│  worker_supervisor → ComfyUI 8188                       │
└────────────┬───────────────────────────────────────────┘
             │
       ┌─────┴──────────────┐
       │                    │
┌──────▼────────┐   ┌───────▼─────────┐
│ 机器 B         │   │ 机器 C          │
│ 笔记本         │   │ 远程服务器       │
│                │   │                 │
│ worker_super.. │   │ worker_super..  │
│      ↓         │   │      ↓          │
│ ComfyUI 8188   │   │ ComfyUI 8188    │
│ (RTX 3060)     │   │ (A100)          │
└────────────────┘   └─────────────────┘
```

## 📋 三种部署模式

### 模式 1：单机（你现在这样）
- 1 台机器，1 个 GPU
- Redis + Worker + ComfyUI 都在本机
- 跑 `start_worker.bat`

### 模式 2：单机多 GPU
- 1 台机器，2-3 个 GPU
- 启动 2-3 个 ComfyUI（不同端口）
- 启动 2-3 个 Worker（不同队列）
- 跑 `start_all.bat`

### 模式 3：多机共享 ⭐ 本文重点
- N 台机器，N 个 GPU
- 1 个中央 Redis（必须在某台机器上，且要能跨网访问）
- 每台机器跑 `start_worker_supervised.bat`
- **关键前置**：所有机器能互相访问

## 🔧 多机部署步骤

### Step 1：解决跨网访问（最关键！）

三选一：

#### 选项 A：Tailscale（推荐，最简单）
1. 每台机器装 Tailscale：https://tailscale.com/download/windows
2. 登录同一个账号
3. 各机器会得到 100.x.x.x 的内网 IP
4. 互相 ping 得通就行

#### 选项 B：ZeroTier（备选）
- 跟 Tailscale 类似
- https://www.zerotier.com/

#### 选项 C：传统方案
- 端口转发：路由器开 6379/8188 端口
- 公网 IP：每台机器要公网 IP（一般家庭宽带没有）
- 防火墙：放行 6379、8188 端口

### Step 2：选一台机器当「中央机」

推荐选**你日常用的电脑**，因为你要在那提交任务、看 dashboard。

假设中央机 IP 是 `192.168.1.10`。

### Step 3：中央机启动 Redis
```powershell
# 中央机（192.168.1.10）
redis-server
```
**注意**：Redis 要能被其他机器访问。检查：
```powershell
# 其他机器测试
redis-cli -h 192.168.1.10 ping
# 期望返回 PONG
```

### Step 4：每台机器启动 ComfyUI
每台机器都要有 ComfyUI 跑着。可以用 Comfy Desktop 或者 Python 版。

### Step 5：每台机器启动 Worker
**关键：每台机器的环境变量不一样！**

#### 中央机（192.168.1.10）
```powershell
cd C:\celery_comfy
set REDIS_HOST=127.0.0.1
set COMFY_URL=http://127.0.0.1:8188
set QUEUE_NAME=desktop_main
set CUDA_VISIBLE_DEVICES=0
start_worker_supervised.bat
```

#### 笔记本（192.168.1.20）
```powershell
cd C:\celery_comfy
set REDIS_HOST=192.168.1.10      # 指向中央 Redis
set COMFY_URL=http://192.168.1.20:8188  # 本机的 ComfyUI
set QUEUE_NAME=laptop_3060
set CUDA_VISIBLE_DEVICES=0
start_worker_supervised.bat
```

#### 服务器（10.0.0.5，通过 Tailscale）
```powershell
cd C:\celery_comfy
set REDIS_HOST=100.100.0.1      # Tailscale IP
set COMFY_URL=http://100.100.0.2:8188
set QUEUE_NAME=server_a100
set CUDA_VISIBLE_DEVICES=0
start_worker_supervised.bat
```

### Step 6：在中央机启动 Dashboard
```powershell
cd C:\celery_comfy
start_dashboard.bat
```

打开 `http://127.0.0.1:5000`，**算力资源池**那一节应该列出所有机器 ✅

### Step 7：提交任务（自动路由到最闲的机器）
```powershell
python submit_task.py auto    # 智能路由
python submit_task.py least   # 选最闲
```

## 🔍 验证多机共享

### 看所有 worker
```powershell
python resource_registry.py list
```
应该列出所有机器 + 状态。

### 看 dashboard
打开 `http://127.0.0.1:5000` → 「算力资源池」表格

### 测试跨机提交
```powershell
# 提交到具体机器
python submit_task.py desktop_main
python submit_task.py laptop_3060
python submit_task.py server_a100
```

## ⚠️ 常见问题

### Q1: Worker 注册不上？
检查：
1. 中央 Redis 启动了？
2. 防火墙放行了 6379？
3. REDIS_HOST 写对了？
4. 跨网了吗？（要用 Tailscale 或同局域网）

### Q2: Worker 注册了但 ComfyUI 连不上？
检查：
1. COMFY_URL 写对了吗？（应该是 worker 自己机器的 IP）
2. ComfyUI 启动时开了 `--listen 0.0.0.0` 吗？
3. 防火墙放行 8188 了吗？

### Q3: 提交任务到某机器，但该机器 worker 收不到？
1. 看 worker 窗口：`celery@xxx ready.`
2. 看 worker 订阅的 queue 跟 submit 的 queue 一致？
3. Redis 里 `LLEN <queue_name>` 看队列深度

### Q4: Tailscale 还是连不上？
- 检查 Tailscale 状态：`tailscale status`
- 关闭 Windows 防火墙试试（临时）

## 📊 性能预估

| 网络 | 延迟 | 适用 |
|---|---|---|
| 同局域网 | < 1ms | ✅ 完美 |
| Tailscale | 5-50ms | ✅ 良好 |
| 公网（无 VPN） | 50-200ms | ⚠️ 慢 |
| 跨省/跨国 | > 200ms | ❌ 不推荐 |

## 🎯 进阶用法

### 按机器能力路由
未来可以扩展 `submit_task.py` 支持 hint：
```python
python submit_task.py --need-vram 20 --gpu-type rtx
```

### 任务优先级（已实现）
```python
python submit_task.py desktop_main vip
```

### 弹性扩容
某天朋友想借你的 GPU 跑任务：
1. 朋友机器上装本项目
2. 设 `REDIS_HOST=你的IP`
3. 跑 `start_worker_supervised.bat`
4. 他的 GPU 就加入你的池子 ✅

## 🔗 相关文件

- `resource_registry.py` - 注册中心
- `worker_supervisor.py` - Worker 监督器
- `start_worker_supervised.bat` - 多机启动脚本
- `scheduler.py` - 智能调度（已支持多机）
- `web_dashboard.py` - Dashboard（已支持多机显示）
