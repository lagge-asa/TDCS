function enterApp() {
 document.getElementById('loginPage').style.display = 'none';
 document.getElementById('app').style.display = 'block';
 // 登入动画：侧边栏延迟滑入
 
 document.getElementById('sidebarUser').textContent = currentUser.username;
 document.getElementById('sidebarRole').textContent = currentUser.role;
 document.getElementById('headerTime').textContent = new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}); setInterval(function(){document.getElementById('headerTime').textContent=new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})},30000); document.getElementById('sidebarAvatar').textContent = (currentUser.username||'A')[0].toUpperCase();
 // admin-only 菜单
 if (currentUser.role === 'admin') {
 document.getElementById('navUsers').style.display = '';
 document.getElementById('navAudit').style.display = '';
 }
 applyPermissions();
 loadDashboard();
 // 仪表盘 30s 自动刷新
 if (_autoRefresh) clearInterval(_autoRefresh);
 _autoRefresh = setInterval(() => { if (document.getElementById('page-dashboard').classList.contains('active')) loadDashboard(); }, 30000);
 // 预填文件任务过滤器
 api('GET', '/api/v1/tasks/').then(d => {
 const sel = document.getElementById('fileTaskFilter');
 const msel = document.getElementById('monthlyTaskFilter');
 (d.tasks || []).forEach(t => {
 sel.innerHTML += `<option value="${t.task_id}">${t.name}</option>`;
 msel.innerHTML += `<option value="${t.task_id}">${t.name}</option>`;
 });
 }).catch(()=>{});
}

function logout() {
 token = ''; currentUser = null;
 _safeDel('etl_token'); _safeDel('etl_user');
 document.getElementById('app').style.display = 'none';
 document.getElementById('loginPage').style.display = 'flex';
 document.getElementById('navUsers').style.display = 'none';
 document.getElementById('navAudit').style.display = 'none';
}
