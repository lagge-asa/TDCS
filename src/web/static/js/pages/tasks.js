
async function loadTasks() {
 try {
 const data = await api('GET', '/api/v1/tasks/');
 const tasks = data.tasks || [];
 document.getElementById('taskList').innerHTML = tasks.length
 ? `<table><thead><tr><th>任务 ID</th><th>名称</th><th>状态</th><th>成功</th><th>失败</th><th>总行数</th><th>最后处理</th><th>操作</th></tr></thead><tbody>` +
 tasks.map(t => {
 const s = t.stats || {};
 const paused = t.paused;
 const circuit = t.circuit_state || 'CLOSED';
 const running = t.watcher_running;
 let statusHtml = '';
 let btns = [];
 if (!t.enabled) statusHtml = '<span class="badge badge-pending">⏸ 禁用</span>';
 else if (circuit === 'OPEN') statusHtml = '<span class="badge badge-failed">⚡ 熔断</span>';
 else if (paused) statusHtml = '<span class="badge badge-pending">⏸ 暂停</span>';
 else if (!running) statusHtml = '<span class="badge badge-failed">⚠ 未运行</span>';
 else statusHtml = '<span class="badge badge-success">● 运行</span>';
 if (hasRole('operator')) {
 if (paused) { btns.push(`<button class="btn btn-success" style="padding:5px 10px" onclick="taskAct('${t.task_id}','resume')">恢复</button>`); }
 else { btns.push(`<button class="btn btn-warning" style="padding:5px 10px" onclick="taskAct('${t.task_id}','pause')">暂停</button>`); }
 btns.push(`<button class="btn btn-primary" style="padding:5px 10px" onclick="taskAct('${t.task_id}','trigger')">扫描</button>`);
 }
 if (hasRole('admin')) {
 btns.push(t.enabled
 ? `<button class="btn btn-ghost" style="padding:5px 10px" onclick="taskAct('${t.task_id}','disable')">禁用</button>`
 : `<button class="btn btn-ghost" style="padding:5px 10px" onclick="taskAct('${t.task_id}','enable')">启用</button>`);
 btns.push(`<button class="btn btn-ghost" style="padding:5px 10px" onclick="openEditTask('${t.task_id}')">编辑</button>`);
 btns.push(`<button class="btn btn-danger" style="padding:5px 10px" onclick="deleteTaskConfig('${t.task_id}')">删除</button>`);
 }
 return `<tr>
 <td style="font-family:monospace;color:#2563eb">${t.task_id}</td>
 <td>${t.name}${circuit==='OPEN'?' <span style="color:#dc2626;font-size:10px">熔断</span>':''}</td>
 <td>${statusHtml}</td>
 <td style="color:#16a34a">${s.success??'—'}</td>
 <td style="color:#dc2626">${s.failed??'—'}</td>
 <td>${(s.total_rows||0).toLocaleString()}</td>
 <td style="color:#8e8e9a;font-size:11px">${(s.last_processed||'—').slice(0,19)}</td>
 <td style="display:flex;gap:6px;flex-wrap:wrap">${btns.join('')}</td>
 </tr>`;
 }).join('') + '</tbody></table>'
 : '<div class="empty">暂无任务</div>';
 } catch {
 document.getElementById('taskList').innerHTML = '<div class="empty">加载失败</div>';
 }
}

async function taskAct(id, action) {
 const btns = document.querySelectorAll(`button[onclick*="taskAct('${id}'"]`);
 btns.forEach(b => { b.disabled = true; b.style.opacity = '0.5'; });
 try {
 await api('POST', `/api/v1/tasks/${id}/${action}`);
 toast(`✅ ${action} → ${id}`);
 } catch(e) { toast('操作失败：' + e.message, 'err'); }
 loadTasks();
}

// ── 任务配置编辑器 ────────────────────────────────────────────────────
let _editTaskId = null;

function openNewTask() {
 if (!requireRole('admin', '新建任务')) return;
 _editTaskId = null;
 document.getElementById('taskConfigTitle').textContent = '新建任务';
 ['tfTaskId','tfName','tfFolder','tfBaseTable','tfPartitionField','tfTableTemplate','tfDeadLetter','tfTransformer','tfTransformerFn'].forEach(id=>document.getElementById(id).value='');
 ['tfPriority','tfBatchSize','tfDebounce','tfStabilityCount','tfMaxRetries','tfRetention'].forEach(id=>document.getElementById(id).value=document.getElementById(id).defaultValue);
 document.getElementById('tfTaskId').disabled = false;
 document.getElementById('tfSaveBtn').textContent = ' 创建';
 openModal('taskConfigModal');
}

async function openEditTask(taskId) {
 if (!requireRole('admin', '编辑任务')) return;
 try {
 const t = await api('GET', `/api/v1/config/tasks/${taskId}`);
 if (!t) { toast('任务不存在', 'err'); return; }
 _editTaskId = taskId;
 document.getElementById('taskConfigTitle').textContent = '编辑任务：' + taskId;
 document.getElementById('tfTaskId').value = taskId;
 document.getElementById('tfTaskId').disabled = true;
 document.getElementById('tfName').value = t.name||'';
 document.getElementById('tfPriority').value = t.priority||1;
 document.getElementById('tfEnabled').value = t.enabled!==false?'true':'false';
 const mon = t.monitor||{};
 document.getElementById('tfFolder').value = mon.folder_path||'';
 document.getElementById('tfExtensions').value = (mon.file_extensions||[]).join(', ');
 document.getElementById('tfDebounce').value = mon.debounce_seconds||3;
 document.getElementById('tfStabilityCount').value = mon.stability_check_count||3;
 const etl = t.etl||{};
 document.getElementById('tfExtractor').value = etl.extractor||'csv';
 document.getElementById('tfEncoding').value = etl.encoding||'auto';
 document.getElementById('tfBatchSize').value = etl.batch_size||1000;
 document.getElementById('tfTransformer').value = etl.transformer_module||'';
 document.getElementById('tfTransformerFn').value = etl.transformer_function||'';
 const tb = t.table||{};
 document.getElementById('tfBaseTable').value = tb.base_table||'';
 document.getElementById('tfPartitionField').value = tb.partition_field||'';
 document.getElementById('tfDateFormat').value = tb.partition_field_format||'%Y-%m-%d';
 document.getElementById('tfTableTemplate').value = tb.create_table_template||'';
 document.getElementById('tfRetention').value = tb.retention_months||12;
 const eh = t.error_handling||{};
 document.getElementById('tfMaxRetries').value = eh.max_retries||3;
 document.getElementById('tfDeadLetter').value = eh.dead_letter_dir||'';
 document.getElementById('tfOnRowError').value = eh.on_row_error||'skip';
 document.getElementById('tfSaveBtn').textContent = ' 保存';
 openModal('taskConfigModal');
 } catch(e) { toast('获取任务配置失败: '+e.message, 'err'); }
}

async function saveTaskConfig() {
 const g = id => document.getElementById(id)?.value.trim() || '';
 const data = {
 task_id: g('tfTaskId'), name: g('tfName'),
 enabled: document.getElementById('tfEnabled').value==='true',
 priority: parseInt(document.getElementById('tfPriority').value)||1,
 monitor_folder: g('tfFolder'),
 file_extensions: g('tfExtensions').split(',').map(s=>s.trim()).filter(Boolean),
 recursive: document.getElementById('tfRecursive')?.checked || false,
 debounce_seconds: parseInt(document.getElementById('tfDebounce').value)||3,
 stability_check_count: parseInt(document.getElementById('tfStabilityCount').value)||3,
 extractor: g('tfExtractor'), encoding: g('tfEncoding'),
 batch_size: parseInt(document.getElementById('tfBatchSize').value)||1000,
 transformer_module: g('tfTransformer'), transformer_function: g('tfTransformerFn'),
 base_table: g('tfBaseTable'), partition_field: g('tfPartitionField'),
 partition_field_format: g('tfDateFormat'),
 create_table_template: g('tfTableTemplate'),
 retention_months: parseInt(document.getElementById('tfRetention').value)||12,
 archive_old_tables: document.getElementById('tfArchiveOldTables')?.checked ?? true,
 max_retries: parseInt(document.getElementById('tfMaxRetries').value)||3,
 dead_letter_dir: g('tfDeadLetter'),
 on_row_error: g('tfOnRowError'),
 archive_mode: document.getElementById('tfArchiveMode')?.value || 'keep',
 archive_dir: g('tfArchiveDir'),
 compress_after_days: parseInt(document.getElementById('tfCompressAfterDays')?.value)||0,
 cleanup_after_days: parseInt(document.getElementById('tfCleanupAfterDays')?.value)||0,
 poll_interval: parseInt(document.getElementById('tfPollInterval')?.value)||60,
 poll_incremental: document.getElementById('tfPollIncremental')?.checked ?? true,
 sandbox_timeout: parseInt(document.getElementById('tfSandboxTimeout')?.value)||30,
 };
 if (!data.task_id) { toast('请输入任务 ID', 'err'); return; }
 try {
 if (_editTaskId) {
 await api('PUT', `/api/v1/config/tasks/${_editTaskId}`, data);
 toast('任务 '+_editTaskId+' 已更新');
 } else {
 await api('POST', '/api/v1/config/tasks', data);
 toast('任务 '+data.task_id+' 创建成功');
 }
 closeModal('taskConfigModal');
 loadTasks();
 } catch(e) { toast('保存失败: '+e.message, 'err'); }
}

async function deleteTaskConfig(taskId) {
 if (!confirm('确定删除任务 "'+taskId+'"? 此操作不可恢复。')) return;
 try {
 await api('DELETE', `/api/v1/config/tasks/${taskId}`);
 toast('任务 '+taskId+' 已删除');
 loadTasks();
 } catch(e) { toast('删除失败: '+e.message, 'err'); }
}

// ─── 文件状态 ─────────────────────────────────────────────────────────────
