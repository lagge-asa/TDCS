function toast(msg, type) {
 const t = document.getElementById('toast');
 const icon = type === 'err' ? '✕' : '✓';
 t.innerHTML = `<span class="t-icon">${icon}</span><span class="t-body">${msg}</span>`;
 t.className = 'toast show ' + (type === 'err' ? 'err-t' : 'ok');
 clearTimeout(t._tid);
 t._tid = setTimeout(() => t.classList.remove('show'), 3500);
}

function badge(s) {
 const m = {SUCCESS:'badge-success',FAILED:'badge-failed',PROCESSING:'badge-processing',CLAIMED:'badge-processing'};
 return `<span class="badge ${m[s]||'badge-pending'}">${s||'—'}</span>`;
}
function roleBadge(r) {
 return `<span class="badge badge-${r||'viewer'}">${r||'viewer'}</span>`;
}

// ── 通用状态渲染 ─────────────────────────────────────────────────────────
function _loading(rows=5) {
 return '<tr>' + Array(rows).fill('<td><div class="skeleton sk-text"></div></td>').join('') + '</tr>'.repeat(3);
}
function _empty(msg='暂无数据', icon='📭') {
 return `<div class="empty-state"><div class="icon">${icon}</div><div class="msg">${msg}</div></div>`;
}
function _error(msg, retryFn) {
 let r = '';
 if (retryFn) r = `<span class="retry" onclick="(${retryFn.toString()})()">重试</span>`;
 return `<div class="err-card">⚠ ${msg}${r}</div>`;
}
function scoreClass(s) { return s>=80?'score-high':s>=60?'score-mid':'score-low'; }

function openModal(id) { document.getElementById(id).classList.add('show'); }
function closeModal(id) { document.getElementById(id).classList.remove('show'); }

// ─── 仪表盘 ───────────────────────────────────────────────────────────────
