
async function loadDashboard() {
 try {
 const d = await api('GET', '/api/v1/dashboard/');
 document.getElementById('kpiTasks').textContent = d.tasks?.enabled ?? '—';
 const paused = d.tasks?.paused || 0;
 document.getElementById('kpiSuccess').textContent = d.files?.success ?? '—';
 document.getElementById('kpiFailed').textContent = d.files?.failed ?? '—';
 document.getElementById('kpiRows').textContent = (d.files?.total_rows ?? 0).toLocaleString();
 // Paused / Circuit indicators
 const circuits = (d.workers||{}).circuits_open || [];
 const healthStatus = (d.health||{}).status || 'ok';

 // Worker / Queue
 const w = d.workers || {};
 document.getElementById('workerStatus').innerHTML =
 `<div class="mi"><span class="mk">活跃 Worker</span><span class="mv">${w.active_workers??'—'}</span></div>
 <div class="mi"><span class="mk">队列积压</span><span class="mv" style="color:${(w.queue_size||0)>200?'var(--red)':'var(--green)'}">${w.queue_size??'—'}</span></div>
 ${circuits.length ? `<div class="mi"><span class="mk">熔断任务</span><span class="mv" style="color:var(--red)">${circuits.join(', ')}</span></div>` : ''}
 ${paused ? `<div class="mi"><span class="mk">暂停任务</span><span class="mv" style="color:var(--amber)">${paused} 个</span></div>` : ''}
 <div class="mi"><span class="mk">数据库</span><span class="mv"><span class="dot ${(d.health||{}).db?'dot-green':'dot-red'}"></span>${(d.health||{}).db?'正常':'—'}</span></div>
 <div class="mi"><span class="mk">服务状态</span><span class="mv"><span class="dot ${healthStatus==='ok'?'dot-green':'dot-red'}"></span>${healthStatus}</span></div>
 <div class="mi"><span class="mk">HA</span><span class="mv">${(d.ha||{}).enabled?((d.ha||{}).is_active?'主节点':'备节点'):'standalone'}</span></div>
 <div style="color:var(--text-muted);font-size:10px;margin-top:6px;text-align:right">${new Date().toLocaleTimeString()}</div>`;

 // Pipeline visualization
 const tasks = d.tasks || [];
 document.getElementById('pipelineStatus').innerHTML = tasks.length
 ? tasks.map(t=>{
 const s = t.stats||{};
 const total = (s.pending||0)+(s.processing||0)+(s.success||0)+(s.failed||0)||1;
 const pPend = ((s.pending||0)/total*100).toFixed(0);
 const pProc = ((s.processing||0)/total*100).toFixed(0);
 const pSucc = ((s.success||0)/total*100).toFixed(0);
 const pFail = ((s.failed||0)/total*100).toFixed(0);
 return `<div style="margin-bottom:14px">
 <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
 <span style="font-size:12px;font-weight:600;color:var(--text-dim)"> ${t.name||t.task_id}</span>
 <span style="font-size:10px;color:var(--text-muted)">共 ${total} 文件</span>
 </div>
 <div style="display:flex;height:6px;border-radius:3px;overflow:hidden;gap:2px;background:var(--bg);padding:1px">
 <div title="待处理: ${s.pending||0}" style="width:${pPend}%;background:var(--text-muted);border-radius:2px;min-width:${pPend>0?'3px':'0'}"></div>
 <div title="处理中: ${s.processing||0}" style="width:${pProc}%;background:var(--accent);border-radius:2px;min-width:${pProc>0?'3px':'0'}"></div>
 <div title="成功: ${s.success||0}" style="width:${pSucc}%;background:var(--green);border-radius:2px;min-width:${pSucc>0?'3px':'0'}"></div>
 <div title="失败: ${s.failed||0}" style="width:${pFail}%;background:var(--red);border-radius:2px;min-width:${pFail>0?'3px':'0'}"></div>
 </div>
 <div style="display:flex;gap:14px;font-size:10px;color:var(--text-muted);margin-top:4px">
 <span> ${s.pending||0} 待处理</span> <span> ${s.processing||0} 处理中</span> <span> ${s.success||0} 成功</span> <span> ${s.failed||0} 失败</span>
 </div>
 </div>`;
 }).join('')
 : '<div class="empty">暂无任务 — 请先创建任务</div>';

 // 最近文件
 const recent = d.recent_files || [];
 document.getElementById('recentFiles').innerHTML = recent.length
 ? recent.map(f=>`<tr>
 <td style="font-family:monospace;font-size:12px">${f.file_name}</td>
 <td style="color:#8e8e9a">${f.task_id}</td>
 <td>${badge(f.status)}</td>
 <td>${(f.row_count||0).toLocaleString()}</td>
 <td>${f.processing_time_ms?f.processing_time_ms+'ms':'—'}</td>
 <td style="color:#8e8e9a;font-size:12px">${(f.time||'').slice(0,19)}</td>
 </tr>`).join('')
 : '<tr><td colspan="6" class="empty">暂无数据</td></tr>';
 } catch(e) {
 toast('仪表盘加载失败：' + e.message, 'err');
 }
}

// ─── 任务管理 ─────────────────────────────────────────────────────────────
