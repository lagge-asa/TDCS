
async function loadMonthly() {
 const t = document.getElementById('monthlyTaskFilter').value;
 try {
 const data = await api('GET', '/api/v1/monthly/' + (t?`?task_id=${t}`:''));
 const tables = data.tables || [];
 document.getElementById('monthlyTable').innerHTML = tables.length
 ? tables.map(r=>`<tr>
 <td style="font-family:monospace;font-size:12px;color:#2563eb">${r.table_name}</td>
 <td style="color:#8e8e9a">${r.task_id}</td>
 <td>${r.year_month}</td>
 <td>${r.status==='ACTIVE'?'<span class="badge badge-success">ACTIVE</span>':r.status==='ARCHIVED'?'<span class="badge badge-pending">ARCHIVED</span>':'<span class="badge badge-failed">DROPPED</span>'}</td>
 <td>${(r.row_count||0).toLocaleString()}</td>
 <td style="color:#8e8e9a;font-size:11px">${(r.created_at||'').slice(0,19)}</td>
 <td style="color:#8e8e9a;font-size:11px">${r.archived_at?(r.archived_at||'').slice(0,19):'—'}</td>
 </tr>`).join('')
 : '<tr><td colspan="7" class="empty">暂无月表记录</td></tr>';
 } catch(e) {
 document.getElementById('monthlyTable').innerHTML = `<tr><td colspan="7" class="empty">加载失败：${e.message}</td></tr>`;
 }
}

async function runMonthlyLifecycle() {
 if (!requireRole('admin', '触发生命周期')) return;
 const btn = document.getElementById('monthlyRunBtn');
 btn.disabled = true; btn.textContent = '运行中...';
 try {
 const data = await api('POST', '/api/v1/monthly/run', {});
 toast(`生命周期完成，涉及任务: ${(data.ran_for_tasks||[]).join(', ')||'无'}`);
 loadMonthly();
 } catch(e) { toast('触发失败：'+e.message, 'err'); }
 finally { btn.disabled = false; btn.textContent = '手动触发生命周期'; }
}

// ─── 系统配置 ─────────────────────────────────────────────────────────────
