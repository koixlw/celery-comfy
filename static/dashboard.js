// 自动刷新 + 控件交互
const REFRESH_MS = 2000;

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        return await res.json();
    } catch (e) {
        console.error('fetch status failed:', e);
        return null;
    }
}

function renderInstances(data) {
    const tbody = document.getElementById('inst-tbody');
    const insts = data.instances;
    const rows = Object.entries(insts).map(([name, info]) => {
        const aliveDot = info.alive
            ? '<span class="status-dot online"></span>在线'
            : '<span class="status-dot offline"></span>离线';
        const qDepth = info.queue_depth >= 0 ? info.queue_depth : '-';
        const task = info.task_id ? info.task_id.substring(0, 8) : '-';
        return `
            <tr>
                <td><strong>${name}</strong><br><small class="muted" style="padding:0">${info.description || ''}</small></td>
                <td>${aliveDot}</td>
                <td>${info.active}/${info.max_concurrent}</td>
                <td>${qDepth}</td>
                <td><code>${info.device}</code></td>
                <td>${task !== '-' ? `<span class="task-pill">${task}</span>` : '-'}</td>
            </tr>
        `;
    }).join('');
    tbody.innerHTML = rows || '<tr><td colspan="6" class="muted">无实例</td></tr>';
}

function renderWorkers(data) {
    const tbody = document.getElementById('workers-tbody');
    if (!data.workers || data.workers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="muted">无 worker 注册。运行 <code>start_worker_supervised.bat</code> 启动</td></tr>';
        return;
    }
    tbody.innerHTML = data.workers.map(w => {
        const aliveDot = w.alive
            ? '<span class="status-dot online"></span>在线'
            : '<span class="status-dot offline"></span>离线';
        const mem = `${w.mem_free_mb}/${w.mem_total_mb}MB`;
        return `
            <tr>
                <td><strong>${w.worker_id}</strong></td>
                <td>${w.hostname}<br><small class="muted" style="padding:0">${w.ip || ''}</small></td>
                <td>GPU ${w.gpu_index}: ${w.gpu_name}</td>
                <td>${mem}</td>
                <td><code>${w.queue}</code></td>
                <td>${w.current_load}/${w.max_concurrent}</td>
                <td>${aliveDot}</td>
            </tr>
        `;
    }).join('');
}

function renderGpus(data) {
    const grid = document.getElementById('gpu-grid');
    if (!data.gpus || data.gpus.length === 0) {
        grid.innerHTML = '<div class="muted">暂无数据（请先启动 gpu_monitor.py）</div>';
        return;
    }
    grid.innerHTML = data.gpus.map(g => {
        const memUsed = 0; // nvidia-smi 没传 used，简单用 free 推算
        const memTotal = memUsed + g.mem_free_mb;
        const memUsedPct = memTotal > 0 ? Math.round(memUsed / memTotal * 100) : 0;
        const utilClass = g.util_pct > 80 ? 'warn' : '';
        return `
            <div class="gpu-card">
                <h3>GPU ${g.index} · ${g.name}</h3>
                <div class="metric"><span>显存剩余</span><strong>${g.mem_free_mb} MB</strong></div>
                <div class="bar"><div class="bar-fill" style="width:${100 - memUsedPct}%"></div></div>
                <div class="metric"><span>GPU 利用率</span><strong>${g.util_pct}%</strong></div>
                <div class="bar"><div class="bar-fill ${utilClass}" style="width:${g.util_pct}%"></div></div>
            </div>
        `;
    }).join('');
}

function renderBadges(data) {
    const pauseBadge = document.getElementById('badge-pause');
    pauseBadge.textContent = data.pause ? '⏸ 已暂停' : '▶ 运行中';
    pauseBadge.classList.toggle('on', data.pause);

    const vipBadge = document.getElementById('badge-vip');
    vipBadge.classList.toggle('on', data.vip_pending);

    const activeBadge = document.getElementById('badge-active');
    activeBadge.textContent = `活跃 ${data.totals.active}`;
    activeBadge.classList.toggle('on', data.totals.active > 0);

    const queueBadge = document.getElementById('badge-queue');
    queueBadge.textContent = `队列 ${data.totals.queued}`;
    queueBadge.classList.toggle('on', data.totals.queued > 0);
}

async function refresh() {
    const data = await fetchStatus();
    if (!data) return;
    renderBadges(data);
    renderInstances(data);
    renderWorkers(data);
    renderGpus(data);
}

async function apiPause() {
    if (!confirm('确定要暂停所有 ComfyUI 任务？')) return;
    await fetch('/api/pause', { method: 'POST' });
    refresh();
}

async function apiResume() {
    await fetch('/api/resume', { method: 'POST' });
    refresh();
}

async function apiInterrupt() {
    if (!confirm('确定要立即中断所有 ComfyUI 生成？')) return;
    const res = await fetch('/api/interrupt', { method: 'POST' });
    const data = await res.json();
    alert(`已中断: ${data.interrupted.join(', ') || '无'}`);
    refresh();
}

async function apiSubmit() {
    const instance = document.getElementById('submit-instance').value;
    const priority = document.getElementById('submit-priority').value;
    const wfText = document.getElementById('submit-workflow').value.trim();
    const resultEl = document.getElementById('submit-result');

    if (!wfText) {
        resultEl.innerHTML = '<span style="color:#ef4444">Workflow 不能为空</span>';
        return;
    }

    let workflow;
    try {
        workflow = JSON.parse(wfText);
    } catch (e) {
        resultEl.innerHTML = `<span style="color:#ef4444">JSON 解析失败: ${e.message}</span>`;
        return;
    }

    resultEl.innerHTML = '<span class="muted">提交中...</span>';

    try {
        const res = await fetch('/api/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instance, priority, workflow }),
        });
        const data = await res.json();
        if (data.ok) {
            resultEl.innerHTML = `<span style="color:#10b981">✅ 已提交: ${data.task_id}</span>`;
            setTimeout(refresh, 500);
        } else {
            resultEl.innerHTML = `<span style="color:#ef4444">❌ ${data.error}</span>`;
        }
    } catch (e) {
        resultEl.innerHTML = `<span style="color:#ef4444">❌ 网络错误: ${e.message}</span>`;
    }
}

// 启动自动刷新
refresh();
setInterval(refresh, REFRESH_MS);
