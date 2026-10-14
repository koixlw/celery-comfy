"""
算力资源注册中心

每台机器上的 worker 启动时调用 register() 自我报到
调度器调用 list_alive() 拿到所有在线算力

数据存 Redis Hash，自动过期（30s 无心跳视为离线）
"""
import time
import json
import redis

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
HEARTBEAT_TTL = 30   # 秒 - 超过这个时间没心跳视为掉线
KEY_PREFIX = "resource:worker:"


def get_redis():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def register(worker_id, info: dict, ttl=HEARTBEAT_TTL):
    """Worker 报到：把自己的能力/地址写进 Redis

    info 应包含：
        hostname, ip, gpu_index, gpu_name, mem_total_mb, mem_free_mb,
        comfy_url, queue, max_concurrent
    """
    r = get_redis()
    info['last_heartbeat'] = time.time()
    info['worker_id'] = worker_id
    info['registered_at'] = info.get('registered_at', time.time())
    key = f"{KEY_PREFIX}{worker_id}"
    r.hset(key, mapping={k: str(v) for k, v in info.items()})
    r.expire(key, ttl)
    return True


def heartbeat(worker_id, current_load=0, current_task=""):
    """Worker 心跳：定期调一下证明自己还活着"""
    r = get_redis()
    key = f"{KEY_PREFIX}{worker_id}"
    if not r.exists(key):
        return False
    r.hset(key, mapping={
        'last_heartbeat': time.time(),
        'current_load': current_load,
        'current_task': current_task,
    })
    r.expire(key, HEARTBEAT_TTL)
    return True


def unregister(worker_id):
    """Worker 下线"""
    get_redis().delete(f"{KEY_PREFIX}{worker_id}")


def list_all():
    """列出所有注册过的 worker（不管死活）"""
    r = get_redis()
    workers = []
    for key in r.scan_iter(f"{KEY_PREFIX}*"):
        data = r.hgetall(key)
        if data:
            data['alive'] = (time.time() - float(data.get('last_heartbeat', 0))) < HEARTBEAT_TTL
            workers.append(data)
    return workers


def list_alive():
    """只列在线 worker"""
    return [w for w in list_all() if w.get('alive')]


def get_by_id(worker_id):
    """查单个 worker"""
    r = get_redis()
    data = r.hgetall(f"{KEY_PREFIX}{worker_id}")
    if data:
        data['alive'] = (time.time() - float(data.get('last_heartbeat', 0))) < HEARTBEAT_TTL
    return data


def cleanup_dead():
    """清理掉线 worker（一般不用，TTL 自动处理）"""
    removed = []
    for w in list_all():
        if not w.get('alive'):
            unregister(w['worker_id'])
            removed.append(w['worker_id'])
    return removed


# === 简化的命令行工具 ===
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print(f"\n{'Worker ID':<25} {'主机':<15} {'GPU':<8} {'显存':<10} {'队列':<8} {'状态'}")
        print("-" * 90)
        for w in list_all():
            status = "✅ 在线" if w.get('alive') else "❌ 离线"
            mem = f"{w.get('mem_free_mb', '?')}/{w.get('mem_total_mb', '?')}MB"
            print(f"{w.get('worker_id', '?'):<25} {w.get('hostname', '?'):<15} "
                  f"GPU{w.get('gpu_index', '?'):<6} {mem:<10} {w.get('queue', '?'):<8} {status}")
        print()
    else:
        print("用法: python resource_registry.py list")
