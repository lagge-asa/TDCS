
async function loadQualityInit() {
 try {
 const data = await api('GET', '/api/v1/tasks/');
 document.getElementById('qualityTaskSel').innerHTML =
 (data.tasks||[]).map(t=>`<option value="${t.task_id}">${t.name} (${t.task_id})</option>`).join('');
 } catch {}
}

async function loadQuality() {
 const id = document.getElementById('qualityTaskSel').value;
 if (!id) return;
 try {
 const data = await api('GET', `/api/v1/quality/${id}?page_size=20`);
 const reports = data.reports || [];
 // Summary KPI
 const latest = reports[0];
 if (latest) {
 const sc = latest.quality_score||0;
 const scCls = sc>=90?'green':sc>=70?'amber':'red';
 const scLabel = sc>=90?'优秀':sc>=70?'良好':'需关注';
 document.getElementById('qualitySummary').style.display = 'block';
 document.getElementById('qualitySummary').innerHTML = `
 <div class="kpi-row" style="grid-template-columns:repeat(4,1fr)">
 <div class="kpi ${scCls}"><div class="v">${sc}</div><div class="l">最新质量评分 · ${scLabel}</div></div>
 <div class="kpi blue"><div class="kpi-body"><div class="v">${(latest.total_rows||0).toLocaleString()}</div><div class="l">最新批处理行数</div></div>
 <div class="kpi gold"><div class="kpi-body"><div class="v">${(latest.valid_rows||0).toLocaleString()}</div><div class="l">有效行数</div></div>
 <div class="kpi ${latest.error_rows>0?'red':'green'}"><div class="v">${latest.error_rows||0}</div><div class="l">错误行数</div></div>
 </div>`;
 }
 document.getElementById('qualityResult').innerHTML = reports.length
 ? `<table><thead><tr><th>时间</th><th>总行</th><th>有效</th><th>错误</th><th>空值率</th><th>质量评分</th><th>耗时</th></tr></thead><tbody>` +
 reports.map(r=>`<tr>
 <td style="font-size:11px;color:var(--text-muted)">${(r.batch_time||'').slice(0,19)}</td>
 <td>${r.total_rows||0}</td>
 <td style="color:var(--green)">${r.valid_rows||0}</td>
 <td style="color:var(--red)">${r.error_rows||0}</td>
 <td>${((r.null_rate||0)*100).toFixed(1)}%</td>
 <td><strong class="${scoreClass(r.quality_score||0)}">${r.quality_score??'—'}</strong></td>
 <td style="color:var(--text-muted)">${r.processing_time_ms?r.processing_time_ms+'ms':'—'}</td>
 </tr>`).join('') + '</tbody></table>'
 : '<div class="empty">暂无质量报告（尚未处理任何文件）</div>';
 } catch(e) {
 document.getElementById('qualityResult').innerHTML = `<div class="empty">加载失败：${e.message}</div>`;
 }
}

async function loadQualityTrend() {
 const id = document.getElementById('qualityTaskSel').value;
 if (!id) { toast('请先选择任务', 'err'); return; }
 try {
 const data = await api('GET', `/api/v1/quality/${id}/trend?days=30`);
 const trend = data.trend || [];
 document.getElementById('qualityResult').innerHTML = trend.length
 ? `<div style="font-size:12px;color:#8e8e9a;margin-bottom:12px">近 30 天每日质量趋势</div>
 <table><thead><tr><th>日期</th><th>批次数</th><th>平均评分</th><th>最低评分</th><th>总行数</th><th>错误行</th></tr></thead><tbody>` +
 trend.map(r=>`<tr>
 <td>${r.day}</td><td>${r.batch_count}</td>
 <td><strong class="${scoreClass(r.avg_score)}">${r.avg_score}</strong></td>
 <td class="${scoreClass(r.min_score)}">${r.min_score}</td>
 <td>${(r.total_rows||0).toLocaleString()}</td>
 <td style="color:#dc2626">${r.error_rows||0}</td>
 </tr>`).join('') + '</tbody></table>'
 : '<div class="empty">近 30 天无质量数据</div>';
 } catch(e) {
 document.getElementById('qualityResult').innerHTML = `<div class="empty">加载失败：${e.message}</div>`;
 }
}

// ─── 监控 ─────────────────────────────────────────────────────────────────
