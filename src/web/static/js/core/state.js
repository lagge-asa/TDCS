// ── 安全的 localStorage 读写 ────────────────────────────────────────────────
function _safeGet(k) { try { return localStorage.getItem(k); } catch(_) { return null; } }
function _safeSet(k, v) { try { localStorage.setItem(k, v); } catch(_) {} }
function _safeDel(k) { try { localStorage.removeItem(k); } catch(_) {} }

let token = _safeGet('etl_token') || '';
let currentUser = null;
try { currentUser = JSON.parse(_safeGet('etl_user') || 'null'); } catch(_) { currentUser = null; }
let _filePage = 1, _auditPage = 1;
let _loginLock = false;
let _autoRefresh = null; // 仪表盘自动刷新定时器
