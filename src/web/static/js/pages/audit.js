
async function loadAudit(page) {
 if (page) _auditPage = page;
 const u = document.getElementById('auditUser').value.trim();
 const a = document.getElementById('auditAction').value.trim();
 let qs = `?page=${_auditPage}&page_size=50`;
 if (u) qs += `&username=${encodeURIComponent(u)}`;
 if (a) qs += `&action=${encodeURIComponent(a)}`;
 try {
 const data = await api('GET', '/api/v1/audit-logs/' + qs);
 const logs = data.logs || [];
 document.getElementById('auditTable').innerHTML = logs.length
 ? logs.map(l=>`<tr>
 <td style="font-size:11px;color:#8e8e9a">${(l.timestamp||'').slice(0,19)}</td>
 <td style="color:#2563eb">${l.username||'—'}</td>
 <td style="color:#8e8e9a;font-size:11px">${l.user_ip||'—'}</td>
 <td><span class="tag">${l.action||'—'}</span></td>
 <td style="font-size:11px;font-family:monospace;color:#5c5c68">${l.target||'—'}</td>
 <td style="font-size:11px;color:#8e8e9a;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l.detail||''}</td>
 </tr>`).join('')
 : '<tr><td colspan="6" class="empty">暂无审计记录</td></tr>';
 const total = data.total || 0;
 const pages = Math.ceil(total / 50);
 document.getElementById('auditPager').innerHTML = total > 50
 ? `共 ${total} 条 &nbsp;
 ${_auditPage>1?`<button class="btn btn-ghost" style="padding:4px 10px" onclick="loadAudit(${_auditPage-1})">‹ 上一页</button>`:''}
 <span>第 ${_auditPage}/${pages} 页</span>
 ${_auditPage<pages?`<button class="btn btn-ghost" style="padding:4px 10px" onclick="loadAudit(${_auditPage+1})">下一页 ›</button>`:''}`
 : `共 ${total} 条`;
 } catch(e) {
 document.getElementById('auditTable').innerHTML = `<tr><td colspan="6" class="empty">加载失败：${e.message}</td></tr>`;
 }
}

// ─── 清洗工作台 ───────────────────────────────────────────────────────────
