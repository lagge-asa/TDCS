(async function() {
 if (currentUser && token) {
 // 验证存储的 token 是否仍然有效
 const valid = await _verifyStoredToken();
 if (valid) {
 enterApp();
 } else {
 // token 已过期或无效，清除并显示登录页
 token = ''; currentUser = null;
 _safeDel('etl_token'); _safeDel('etl_user');
 }
 }
})();
// ── 全局快捷键 ──────────────────────────────────────────────────────
function showHelp() {
 toast('快捷键: 1-9 切换页面 · R 刷新 · ? 帮助', 'ok');
}
document.addEventListener('keydown', e=>{
 if (e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT') return;
 const map = {1:'dashboard',2:'quality',3:'metrics',4:'tasks',5:'files',6:'monthly',7:'cleaner',8:'config',9:'audit'};
 if (map[e.key]) { nav(document.querySelector(`nav a[onclick*="${map[e.key]}"]`), map[e.key]); return; }
 if (e.key==='r'||e.key==='R') { const p = document.querySelector('.page.active'); if (p) { const fn = {dashboard:loadDashboard,tasks:loadTasks,files:loadFiles,metrics:loadMetrics,quality:()=>loadQuality(),config:loadConfig,audit:()=>loadAudit(1),monthly:loadMonthly,cleaner:loadCleanerTemplates}; const id = p.id.replace('page-',''); fn[id]?.(); } }
 if (e.key==='?') showHelp();
});
