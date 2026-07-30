const ROLE_LEVELS = {viewer: 1, operator: 2, admin: 3};
function hasRole(minRole) {
 return !!currentUser && (ROLE_LEVELS[currentUser.role] || 0) >= (ROLE_LEVELS[minRole] || 0);
}
function requireRole(minRole, action = '此操作') {
 if (hasRole(minRole)) return true;
 toast(`没有权限执行${action}，需要 ${minRole} 权限`, 'err');
 return false;
}

function applyPermissions() {
 const adminOnly = ['navUsers', 'navAudit'];
 adminOnly.forEach(id => {
  const el = document.getElementById(id);
  if (el) el.style.display = hasRole('admin') ? '' : 'none';
 });
 document.querySelectorAll('[data-min-role]').forEach(el => {
  el.disabled = !hasRole(el.dataset.minRole);
  el.title = el.disabled ? `需要 ${el.dataset.minRole} 权限` : '';
 });
}

function _decodeJwtPayload(jwt) {
 try {
 let payload = jwt.split('.')[1];
 if (!payload) throw new Error('invalid token format');
 payload = payload.replace(/-/g, '+').replace(/_/g, '/');
 while (payload.length % 4) payload += '=';
 return JSON.parse(atob(payload));
 } catch (e) {
 throw new Error('token 解析失败: ' + e.message);
 }
}

// ── 验证存储的 token 是否仍然有效 ────────────────────────────────────────────
async function _verifyStoredToken() {
 if (!token) return false;
 try {
 const r = await fetch('/api/v1/auth/me', {
 headers: { 'Authorization': 'Bearer ' + token }
 });
 if (r.ok) {
  const data = await r.json();
  const user = data.data || data;
  if (user.username && user.role) currentUser = user;
 }
 return r.ok;
 } catch (_) {
 return false;
 }
}

// ─── 核心工具 ──────────────────────────────────────────────────────────────

async function doLogin() {
 if (_loginLock) return;
 _loginLock = true;
 const btn = document.querySelector('#loginPage .btn-login');
 btn.disabled = true;
 btn.textContent = '登录中...';

 const u = document.getElementById('loginUser').value.trim();
 const p = document.getElementById('loginPass').value;
 const errEl = document.getElementById('loginErr');
 errEl.textContent = '';

 try {
 if (!u || !p) { errEl.textContent = '请输入用户名和密码'; return; }
 const r = await fetch('/api/v1/auth/login', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ username: u, password: p })
 });
 const data = await r.json().catch(() => ({}));
 const backendMessage = data && data.error && typeof data.error === 'object'
  ? (data.error.message || data.error.detail || data.error.code)
  : (data.error || data.message);
 if (!r.ok) {
 if (r.status === 429) {
 errEl.textContent = '登录尝试过于频繁，请 1 分钟后再试';
 } else if (r.status === 401) {
 errEl.textContent = '用户名或密码错误';
 } else if (r.status >= 500) {
 errEl.textContent = '服务器内部错误，请联系管理员';
 } else {
  errEl.textContent = backendMessage || '登录失败 (' + r.status + ')';
 }
 return;
 }
 token = data.data && data.data.token ? data.data.token : data.token;
 if (!token) { errEl.textContent = '服务器返回异常，缺少 token'; return; }
 const pl = _decodeJwtPayload(token);
 currentUser = { id: pl.sub, username: pl.username, role: pl.role };
 _safeSet('etl_token', token);
 _safeSet('etl_user', JSON.stringify(currentUser));
 enterApp();
 } catch (e) {
 if (e.name === 'TypeError' && e.message.includes('fetch')) {
 errEl.textContent = '无法连接服务器，请检查网络';
 } else if (e.name === 'TypeError' && e.message.includes('NetworkError')) {
 errEl.textContent = '网络连接失败，请检查服务是否运行';
 } else {
 errEl.textContent = '登录异常: ' + e.message;
 }
 } finally {
 _loginLock = false;
 btn.disabled = false;
 btn.textContent = '登 录';
 }
}
