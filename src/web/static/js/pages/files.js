
async function loadFiles(page) {
 if (page) _filePage = page;
 const s = document.getElementById('fileStatusFilter').value;
 const t = document.getElementById('fileTaskFilter').value;
 let qs = `?page=${_filePage}&page_size=50`;
 if (s) qs += `&status=${s}`;
 if (t) qs += `&task_id=${t}`;
 // Update filter label and batch retry button
 const labels = {FAILED:'死信队列',SUCCESS:'已成功',PROCESSING:'处理中',PENDING:'待处理'};
 document.getElementById('fileFilterLabel').textContent = labels[s]||'全部';
 document.getElementById('batchRetryBtn').style.display = s==='FAILED' && hasRole('operator')?'inline-flex':'none';
 try {
 const data = await api('GET', '/api/v1/files/' + qs);
 const files = Array.isArray(data) ? data : (data.files || []);
 document.getElementById('fileTable').innerHTML = files.length
 ? files.map(f=>`<tr>
 <td style="font-family:monospace;font-size:12px;cursor:pointer;color:#2563eb" onclick="showFileDetail(${f.id})">${f.file_name}</td>
 <td style="color:#8e8e9a">${f.task_id||'—'}</td>
 <td>${badge(f.status)}</td>
 <td>${(f.row_count||0).toLocaleString()}</td>
 <td>${f.retry_count||0}</td>
 <td style="color:#dc2626;font-size:11px">${f.error_type||'—'}</td>
 <td style="color:#8e8e9a;font-size:11px">${(f.created_at||'').slice(0,19)}</td>
 <td>${f.status==='FAILED' && hasRole('operator')?`<button class="btn btn-ghost" style="padding:4px 10px" onclick="retryFile(${f.id})">重试</button>`:'—'}</td>
 </tr>`).join('')
 : '<tr><td colspan="8" class="empty">暂无数据</td></tr>';
 // 分页
 const total = data.total || 0;
 const pages = Math.ceil(total / 50);
 document.getElementById('filePager').innerHTML = total > 50
 ? `共 ${total} 条 &nbsp;
 ${_filePage>1?`<button class="btn btn-ghost" style="padding:4px 10px" onclick="loadFiles(${_filePage-1})">‹ 上一页</button>`:''}
 <span>第 ${_filePage}/${pages} 页</span>
 ${_filePage<pages?`<button class="btn btn-ghost" style="padding:4px 10px" onclick="loadFiles(${_filePage+1})">下一页 ›</button>`:''}`
 : `共 ${total} 条`;
 } catch {
 document.getElementById('fileTable').innerHTML = '<tr><td colspan="8" class="empty">加载失败</td></tr>';
 }
}

async function batchRetryFailed() {
 if (!confirm('确定要重试当前筛选的所有失败文件吗？')) return;
 const btn = document.getElementById('batchRetryBtn');
 btn.disabled = true; btn.textContent = '重试中...';
 const pageSize = 100;
 let page = 1;
 let count = 0;
 let total = 0;
 try {
  do {
   const data = await api('GET', `/api/v1/files/?status=FAILED&page=${page}&page_size=${pageSize}`);
   const files = Array.isArray(data) ? data : (data.files || []);
   total = data.total ?? total;
   for (const f of files) {
    try { await api('POST', `/api/v1/files/${f.id}/retry`); count++; } catch(_) {}
   }
   if (files.length < pageSize) break;
   page++;
  } while (page <= Math.ceil(total / pageSize));
  toast(`已提交 ${count}/${total || count} 个文件重试`);
  loadFiles();
 } catch(e) { toast('批量重试失败: '+e.message, 'err'); }
 finally { btn.disabled = false; btn.textContent = ' 批量重试失败文件'; }
}

async function showFileDetail(id) {
 try {
 const f = await api('GET', `/api/v1/files/${id}`);
 document.getElementById('fileDetailContent').innerHTML = `
 <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px">
 ${['file_name','task_id','status','row_count','valid_row_count','retry_count','processing_time_ms','created_at','processed_at'].map(k=>
 `<div class="mi"><span class="mk">${k}</span><span class="mv" style="font-size:12px">${f[k]??'—'}</span></div>`
 ).join('')}
 </div>
 ${f.error_type?`<div style="margin-bottom:10px"><div style="font-size:11px;color:#8e8e9a;margin-bottom:4px">错误类型</div><span class="badge badge-failed">${f.error_type}</span></div>`:''}
 ${f.error_message?`<div><div style="font-size:11px;color:#8e8e9a;margin-bottom:4px">错误详情</div><pre style="background:#fafafa;border-radius:8px;padding:12px;font-size:11px;color:#dc2626;overflow:auto;max-height:200px;white-space:pre-wrap">${f.error_message}</pre></div>`:''}
 ${f.file_path?`<div style="margin-top:10px"><div style="font-size:11px;color:#8e8e9a;margin-bottom:4px">文件路径</div><code style="font-size:11px;color:#5c5c68">${f.file_path}</code></div>`:''}`;
 openModal('fileDetailModal');
 } catch(e) { toast('加载失败：'+e.message, 'err'); }
}

async function retryFile(id) {
 try { await api('POST', `/api/v1/files/${id}/retry`); toast('已提交重试'); loadFiles(); }
 catch(e) { toast('重试失败：'+e.message, 'err'); }
}

// ─── 数据质量 ─────────────────────────────────────────────────────────────
