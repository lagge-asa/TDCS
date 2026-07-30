function _errorMessage(payload, fallback) {
 const error = payload && payload.error;
 if (error && typeof error === 'object') return error.message || error.detail || error.code || fallback;
 if (typeof error === 'string') return error;
 if (payload && typeof payload.message === 'string') return payload.message;
 return fallback;
}

async function api(method, path, body) {
 const opts = {method, headers: {'Content-Type': 'application/json'}};
 if (token) opts.headers['Authorization'] = 'Bearer ' + token;
 if (body !== undefined) opts.body = JSON.stringify(body);
 let r;
 try {
  r = await fetch(path, opts);
 } catch (e) {
  throw new Error('无法连接服务器，请检查服务是否运行');
 }
 const ct = r.headers.get('content-type') || '';
 const payload = ct.includes('json') ? await r.json().catch(() => ({})) : await r.text();
 if (r.status === 401) { logout(); throw new Error(_errorMessage(payload, '登录已失效，请重新登录')); }
 if (r.status === 403) throw new Error(_errorMessage(payload, '没有执行此操作的权限'));
 if (!r.ok) throw new Error(typeof payload === 'string' ? payload : _errorMessage(payload, `请求失败（${r.status}）`));
 if (typeof payload === 'string') return payload;
 if (payload && payload.success && payload.data !== undefined) return payload.data;
 return payload;
}


function nav(el, page) {
 const requiredRole = {users:'admin', audit:'admin', config:'viewer', tasks:'viewer', files:'viewer', monthly:'viewer', cleaner:'viewer'}[page] || 'viewer';
 if (!requireRole(requiredRole, '打开该页面')) return;
 if (!el || !document.getElementById('page-' + page)) return;
 document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
 document.querySelectorAll('nav a').forEach(a => a.classList.remove('active')); const labels={dashboard:'仪表盘',tasks:'任务管理',files:'文件状态',quality:'数据质量',metrics:'监控指标',monthly:'月表管理',config:'系统配置',users:'用户管理',audit:'审计日志',cleaner:'清洗工作台'}; document.getElementById('breadcrumb').textContent=labels[page]||page; document.getElementById('headerTime').textContent=new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
 document.getElementById('page-' + page).classList.add('active');
 el.classList.add('active');
 const fn = {dashboard:loadDashboard, tasks:loadTasks, files:loadFiles,
 quality:loadQualityInit, metrics:loadMetrics, config:loadConfig,
 users:loadUsers, audit:()=>loadAudit(1), monthly:loadMonthly,
 cleaner:loadCleanerTemplates};
 fn[page]?.();
}
