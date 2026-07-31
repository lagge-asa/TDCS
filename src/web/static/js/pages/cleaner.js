
let _cleanerFile = null, _downloadToken = null, _sourceVisible = false;

function escapeHtml(value) {
 return String(value).replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}


let _directoryPath = '', _directoryParent = null;
async function openDirectoryPicker() {
 if (!requireRole('admin', '选择监控目录')) return;
 _directoryPath = document.getElementById('tfFolder')?.value.trim() || '';
 await loadDirectoryTree(_directoryPath);
 openModal('directoryPickerModal');
}
async function loadDirectoryTree(path) {
 try {
  const q = path ? '?path=' + encodeURIComponent(path) : '';
  const data = await api('GET', '/api/v1/config/directories' + q);
  _directoryPath = data.path; _directoryParent = data.parent;
  document.getElementById('dirCurrentPath').value = data.path;
  document.getElementById('dirParentBtn').disabled = !_directoryParent;
  const tree = document.getElementById('directoryTree');
  const dirs = data.directories || [];
  tree.innerHTML = dirs.length ? dirs.map(d => `<button type="button" class="btn btn-ghost" style="display:block;width:100%;text-align:left;margin:2px 0" onclick="loadDirectoryTree(${JSON.stringify(d.path)})">📁 ${escapeHtml(d.name)}</button>`).join('') : '<div class="empty">没有可进入的子目录</div>';
 } catch (e) { toast('读取目录失败：' + e.message, 'err'); }
}
function directoryUp() { if (_directoryParent) loadDirectoryTree(_directoryParent); }
function chooseCurrentDirectory() {
 document.getElementById('tfFolder').value = _directoryPath;
 closeModal('directoryPickerModal');
 toast('已选择监控目录');
}
function getSelectedExtensions() {
 const values = [...document.querySelectorAll('input[name="tfExt"]:checked')].map(x => x.value);
 const custom = document.getElementById('tfExtensionsCustom')?.value || '';
 return values.concat(custom.split(',').map(x => x.trim().toLowerCase()).filter(x => x && /^\.[a-z0-9]+$/.test(x))).filter((v, i, a) => a.indexOf(v) === i);
}
function setSelectedExtensions(exts) {
 const values = new Set((exts || []).map(x => x.toLowerCase()));
 document.querySelectorAll('input[name="tfExt"]').forEach(x => { x.checked = values.has(x.value); values.delete(x.value); });
 const custom = [...values];
 document.getElementById('tfExtensionsCustom').value = custom.join(', ');
}


async function loadCleanerTemplates() {
 const sel = document.getElementById('templateSelect');
 const cur = sel.value;
 sel.innerHTML = '<option value="">— 加载中… —</option>';
 try {
 const data = await api('GET', '/api/v1/cleaners/');
 const tpls = data.templates || [];
 document.getElementById('templateCount').textContent = `（${data.valid_count} 个可用，共 ${data.count} 个）`;
 const managementOptions = hasRole('operator') ? (tpls.length ? `<optgroup label="────────── 模板管理 ──────────"></optgroup>`+tpls.map(t=>`<option value="__edit_${t.name}" style="color:var(--accent);font-style:italic">编辑源码</option><option value="__del_${t.name}" style="color:var(--red);font-style:italic"> 删除模板</option>`).join('') : '') : '';
 sel.innerHTML = '<option value="">— 请选择模板 —</option>' +
 tpls.map(t=>`<option value="${t.name}" ${!t.valid?'disabled style="color:#dc2626"':''}>${t.valid?'':''} ${t.name}${t.description&&t.description!=='(无说明)'?' — '+t.description.split('\n')[0].slice(0,40):''}</option>`).join('') + managementOptions;
 if (cur && sel.querySelector(`option[value="${cur}"]`)) sel.value = cur;
 onTemplateSelected();
 } catch { sel.innerHTML = '<option value="">— 加载失败 —</option>'; }
}

function onTemplateSelected() {
 const name = document.getElementById('templateSelect').value;
 const runBtn = document.getElementById('runBtn');
 const srcBtn = document.getElementById('srcToggleBtn');
 // Handle edit/delete special values
 if (name.startsWith('__edit_')) {
 const tplName = name.slice(7);
 document.getElementById('templateSelect').value = tplName;
 openEditCleaner(tplName); return;
 }
 if (name.startsWith('__del_')) {
 const tplName = name.slice(6);
 document.getElementById('templateSelect').value = tplName;
 deleteCleaner(tplName); return;
 }
 document.getElementById('templateSource').style.display = 'none';
 _sourceVisible = false; srcBtn.textContent = '查看源码';
 if (!name) {
 document.getElementById('templateDesc').textContent = '';
 document.getElementById('templateDetail').innerHTML = '<span style="color:var(--text-muted)">请在左侧选择模板</span>';
 runBtn.disabled = true; srcBtn.disabled = true; return;
 }
 api('GET', `/api/v1/cleaners/${name}`).then(info => {
 document.getElementById('templateDesc').textContent = info.description||'(无说明)';
 document.getElementById('templateDetail').innerHTML =
 `<div style="margin-bottom:12px"><div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">模板名称</div><div style="color:var(--accent);font-family:monospace">${info.name}</div></div>
 <div style="margin-bottom:12px"><div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">说明</div><div style="color:var(--text)">${info.description||'(无说明)'}</div></div>
 <div style="margin-bottom:12px"><div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">文件</div><div style="color:var(--text-dim);font-family:monospace;font-size:12px">${info.file}</div></div>
 <div><div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">最后修改</div><div style="color:var(--text-dim);font-size:12px">${info.mtime_str}</div></div>
 <button class="btn btn-ghost" style="margin-top:12px;display:${hasRole('operator')?'inline-flex':'none'}" onclick="openEditCleaner('${info.name}')">编辑此模板</button>`;
 srcBtn._source = info.source||''; srcBtn.disabled = false;
 }).catch(()=>{ document.getElementById('templateDetail').innerHTML = '<span style="color:var(--red)">加载失败</span>'; });
 runBtn.disabled = !_cleanerFile || !hasRole('operator');
}

function toggleSource() {
 const pre = document.getElementById('templateSource');
 const btn = document.getElementById('srcToggleBtn');
 _sourceVisible = !_sourceVisible;
 pre.textContent = _sourceVisible ? (btn._source||'(源码为空)') : '';
 pre.style.display = _sourceVisible ? 'block' : 'none';
 btn.textContent = _sourceVisible ? '收起源码' : '查看源码';
}

// ── 模板编辑器 ──────────────────────────────────────────────────────────
let _editCleanerName = null;

function openNewCleaner() {
 if (!requireRole('operator', '新建清洗模板')) return;
 _editCleanerName = null;
 document.getElementById('cleanerEditTitle').textContent = '新建模板';
 document.getElementById('cleanerEditName').value = '';
 document.getElementById('cleanerEditName').disabled = false;
 document.getElementById('cleanerEditCode').value = 'import pandas as pd\n\ndef clean_data(df):\n """清洗函数：接收 DataFrame，返回清洗后的 DataFrame"""\n df = df.drop_duplicates()\n df.columns = df.columns.str.strip()\n return df\n';
 document.getElementById('cleanerEditMsg').textContent = '';
 document.getElementById('cleanerSaveBtn').textContent = ' 创建';
 openModal('cleanerEditModal');
}

async function openEditCleaner(name) {
 if (!requireRole('operator', '编辑清洗模板')) return;
 try {
 const info = await api('GET', `/api/v1/cleaners/${name}`);
 _editCleanerName = name;
 document.getElementById('cleanerEditTitle').textContent = '编辑模板：' + name;
 document.getElementById('cleanerEditName').value = name;
 document.getElementById('cleanerEditName').disabled = true;
 document.getElementById('cleanerEditCode').value = info.source || '';
 document.getElementById('cleanerEditMsg').textContent = '';
 document.getElementById('cleanerSaveBtn').textContent = ' 保存';
 openModal('cleanerEditModal');
 } catch(e) { toast('获取模板失败: '+e.message, 'err'); }
}

async function validateCleanerCode() {
 const code = document.getElementById('cleanerEditCode').value;
 if (!code.trim()) { document.getElementById('cleanerEditMsg').innerHTML = '<span style="color:var(--red)">代码为空</span>'; return; }
 try {
 const r = await api('POST', `/api/v1/cleaners/${_editCleanerName||'__new__'}/validate`, {code});
 document.getElementById('cleanerEditMsg').innerHTML = r.valid
 ? '<span style="color:var(--green)"> '+r.message+'</span>'
 : '<span style="color:var(--red)"> '+r.message+'</span>';
 } catch(e) { document.getElementById('cleanerEditMsg').innerHTML = '<span style="color:var(--red)">检查失败: '+e.message+'</span>'; }
}

async function saveCleaner() {
 if (!requireRole('operator', '保存清洗模板')) return;
 const name = document.getElementById('cleanerEditName').value.trim();
 const code = document.getElementById('cleanerEditCode').value;
 if (!name) { toast('请输入模板名称', 'err'); return; }
 if (!code.trim()) { toast('请输入代码', 'err'); return; }
 try {
 if (_editCleanerName) {
 await api('PUT', `/api/v1/cleaners/${_editCleanerName}`, {code});
 toast('模板 '+_editCleanerName+' 已更新');
 } else {
 await api('POST', '/api/v1/cleaners/create', {name, code});
 toast('模板 '+name+' 创建成功');
 }
 closeModal('cleanerEditModal');
 loadCleanerTemplates();
 } catch(e) { toast('保存失败: '+e.message, 'err'); }
}

async function deleteCleaner(name) {
 if (!requireRole('admin', '删除清洗模板')) return;
 if (!confirm('确定删除模板 "'+name+'"? 此操作不可恢复。')) return;
 try {
 await api('DELETE', `/api/v1/cleaners/${name}`);
 toast('模板 '+name+' 已删除');
 loadCleanerTemplates();
 } catch(e) { toast('删除失败: '+e.message, 'err'); }
}

function onFileSelected(input) {
 const file = input.files[0]; if (!file) return;
 _cleanerFile = file;
 document.getElementById('fileInfo').textContent = ` ${file.name} （${(file.size/1024).toFixed(1)} KB）`;
 document.getElementById('dropZone').style.borderColor = '#16a34a';
 document.getElementById('runBtn').disabled = !document.getElementById('templateSelect').value;
}

function handleFileDrop(e) {
 e.preventDefault();
 document.getElementById('dropZone').style.borderColor = '#e5e5ea';
 const file = e.dataTransfer.files[0]; if (!file) return;
 const fake = document.getElementById('cleanerFile');
 const dt = new DataTransfer(); dt.items.add(file); fake.files = dt.files;
 onFileSelected(fake);
}

async function runCleaner() {
 const name = document.getElementById('templateSelect').value;
 if (!name || !_cleanerFile) return;
 const btn = document.getElementById('runBtn');
 btn.disabled = true; btn.textContent = '清洗中...';
 document.getElementById('cleanerResult').style.display = 'none';
 _downloadToken = null;
 try {
 const fd = new FormData();
 fd.append('file', _cleanerFile); fd.append('template', name); fd.append('preview', 'true');
 const resp = await fetch('/api/v1/cleaners/run', {method:'POST', headers:{'Authorization':'Bearer '+token}, body:fd});
 const data = await resp.json();
 if (!resp.ok) { toast(data.error||'清洗失败', 'err'); return; }
 _downloadToken = data.download_token;
 document.getElementById('downloadBtn').disabled = !_downloadToken;
 document.getElementById('resultSummary').innerHTML =
 [['原始行数',data.original_rows,'#2563eb'],['清洗后',data.cleaned_rows,'#16a34a'],['删减行',data.dropped_rows,'#dc2626'],['耗时',data.elapsed_ms+'ms','#fbbf24']]
 .map(([l,v,c])=>`<div class="kpi" style="padding:12px 20px;flex:0"><div class="v" style="font-size:20px;color:${c}">${v}</div><div class="l">${l}</div></div>`).join('');
 const cols = data.columns||[];
 document.getElementById('previewHead').innerHTML = '<tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr>';
 const rows = data.preview||[];
 document.getElementById('previewBody').innerHTML = rows.length
 ? rows.map(r=>'<tr>'+cols.map(c=>`<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r[c]??''}</td>`).join('')+'</tr>').join('')
 : `<tr><td colspan="${cols.length}" class="empty">清洗后无数据</td></tr>`;
 document.getElementById('previewNote').textContent = rows.length>=50
 ? `预览前 50 行，点击「下载完整 CSV」获取全部 ${data.cleaned_rows} 行` : `共 ${data.cleaned_rows} 行（全部展示）`;
 document.getElementById('cleanerResult').style.display = 'block';
 toast(`清洗完成：${data.original_rows} → ${data.cleaned_rows} 行 (${data.elapsed_ms}ms)`);
 } catch(e) { toast('请求失败: '+e.message, 'err'); }
 finally { btn.disabled = false; btn.textContent = '运行清洗'; }
}

function downloadResult() {
 if (!_downloadToken) return;
 fetch(`/api/v1/cleaners/download/${_downloadToken}`, {headers:{'Authorization':'Bearer '+token}})
 .then(r=>r.ok?r.blob():r.json().then(e=>Promise.reject(e.error)))
 .then(blob=>{
 const url = URL.createObjectURL(blob);
 const a = Object.assign(document.createElement('a'),{href:url,download:''});
 document.body.appendChild(a); a.click(); document.body.removeChild(a);
 URL.revokeObjectURL(url);
 }).catch(e=>toast(String(e),'err'));
}

// ─── 启动 ─────────────────────────────────────────────────────────────────
