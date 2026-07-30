
async function loadMetrics() {
 try {
 const text = await api('GET', '/metrics');
 document.getElementById('metricsRawBlock').textContent = text || '无数据';
 // Parse key metrics into cards
 const m = {};
 const lines = text.split('\n');
 for (const l of lines) {
 if (l.startsWith('#') || !l.trim()) continue;
 const m2 = l.match(/^(\w+)\{.*?\}\s+([\d.]+)/);
 if (!m2) continue;
 const [, name, val] = m2;
 if (!m[name]) m[name] = 0;
 m[name] += parseFloat(val);
 }
 const cards = [
 {label:'处理文件总数',v:m['etl_files_processed_total']||0,color:'blue',fmt:v=>Math.round(v).toLocaleString()},
 {label:'成功行数',v:m['etl_rows_processed_total']||0,color:'green',fmt:v=>Math.round(v).toLocaleString()},
 {label:'失败行数',v:m['etl_rows_failed_total']||0,color:'red',fmt:v=>Math.round(v).toLocaleString()},
 {label:'队列积压',v:m['etl_queue_size']||0,color:'amber',fmt:v=>Math.round(v)},
 {label:'活跃Worker',v:m['etl_active_workers']||0,color:'blue',fmt:v=>Math.round(v)},
 {label:'错误总数',v:m['etl_errors_total']||0,color:'red',fmt:v=>Math.round(v).toLocaleString()},
 ];
 document.getElementById('metricsKPI').innerHTML =
 `<div class="kpi-row" style="grid-template-columns:repeat(${Math.min(cards.length,4)},1fr)">`+
 cards.map(c=>`<div class="kpi ${c.color}"><div class="v">${c.fmt(c.v)}</div><div class="l">${c.label}</div></div>`).join('')+
 '</div>';
 } catch { document.getElementById('metricsKPI').innerHTML = '<div class="empty">加载失败</div>'; }
}

// ─── 月表管理 ─────────────────────────────────────────────────────────────
