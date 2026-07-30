
async function loadConfig() {
 try {
 const data = await api('GET', '/api/v1/config/');
 const tasks = data.tasks || [];
 delete data.tasks;
 document.getElementById('configInfo').innerHTML =
 Object.entries(data).map(([k, v]) => {
 const disp = typeof v === 'object' ? `<pre style="font-size:11px;color:#5c5c68;white-space:pre-wrap;margin-top:4px">${JSON.stringify(v,null,2)}</pre>` : `<span class="mv">${v}</span>`;
 return `<div class="mi" style="align-items:flex-start"><span class="mk" style="padding-top:2px">${k}</span>${disp}</div>`;
 }).join('') +
 (tasks.length ? `<div style="margin-top:16px"><div style="font-size:11px;color:#8e8e9a;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">任务列表 (${tasks.length})</div>` +
 tasks.map(t=>`<div class="mi"><span class="mk">${t.task_id}</span><span style="font-size:12px;color:#5c5c68">${t.name} · ${t.enabled?'<span style="color:#16a34a">启用</span>':'<span style="color:#dc2626">禁用</span>'}</span></div>`).join('') +
 '</div>' : '');
 } catch { document.getElementById('configInfo').innerHTML = '<div class="empty">加载失败（需要登录）</div>'; }
}

async function reloadConfig() {
 if (!requireRole('admin', '热重载配置')) return;
 const btn = document.getElementById('reloadBtn');
 btn.disabled = true; btn.textContent = '重载中...';
 try { await api('PUT', '/api/v1/config/reload'); toast('配置热重载成功'); loadConfig(); }
 catch(e) { toast('热重载失败：'+e.message, 'err'); }
 finally { btn.disabled = false; btn.textContent = ' 热重载配置'; }
}

// ─── 用户管理 ─────────────────────────────────────────────────────────────
