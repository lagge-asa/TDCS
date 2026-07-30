
async function loadUsers() {
 try {
 const data = await api('GET', '/api/v1/users/');
 const users = data.users || [];
 document.getElementById('userTable').innerHTML = users.length
 ? users.map(u=>`<tr>
 <td style="color:#8e8e9a">${u.id}</td>
 <td style="font-weight:600;color:#18181b">${u.username}</td>
 <td>${roleBadge(u.role)}</td>
 <td>${u.enabled?'<span style="color:#16a34a">● 启用</span>':'<span style="color:#dc2626">● 禁用</span>'}</td>
 <td style="color:#8e8e9a;font-size:11px">${(u.last_login||'从未').slice(0,19)}</td>
 <td style="color:#8e8e9a;font-size:11px">${(u.created_at||'').slice(0,19)}</td>
 <td style="display:flex;gap:6px">
 <button class="btn btn-ghost" style="padding:4px 10px" onclick="openChangeRole(${u.id},'${u.username}','${u.role}')">改角色</button>
 ${u.id != currentUser.id ? `<button class="btn btn-danger" style="padding:4px 10px" onclick="deleteUser(${u.id},'${u.username}')">删除</button>` : ''}
 </td>
 </tr>`).join('')
 : '<tr><td colspan="7" class="empty">暂无用户</td></tr>';
 } catch(e) {
 document.getElementById('userTable').innerHTML = `<tr><td colspan="7" class="empty">加载失败：${e.message}</td></tr>`;
 }
}

function openCreateUser() { openModal('createUserModal'); }

async function submitCreateUser() {
 const username = document.getElementById('newUsername').value.trim();
 const password = document.getElementById('newPassword').value;
 const role = document.getElementById('newRole').value;
 try {
 await api('POST', '/api/v1/users/', {username, password, role});
 toast(`用户 ${username} 创建成功`);
 closeModal('createUserModal');
 document.getElementById('newUsername').value = '';
 document.getElementById('newPassword').value = '';
 loadUsers();
 } catch(e) { toast('创建失败：'+e.message, 'err'); }
}

function openChangeRole(id, username, currentRole) {
 document.getElementById('roleModalId').value = id;
 document.getElementById('roleModalUser').textContent = username;
 document.getElementById('roleModalRole').value = currentRole;
 openModal('roleModal');
}

async function submitChangeRole() {
 const id = document.getElementById('roleModalId').value;
 const role = document.getElementById('roleModalRole').value;
 try {
 await api('PUT', `/api/v1/users/${id}/role`, {role});
 toast('角色修改成功');
 closeModal('roleModal');
 loadUsers();
 } catch(e) { toast('修改失败：'+e.message, 'err'); }
}

async function deleteUser(id, username) {
 if (!confirm(`确认删除用户 "${username}"？此操作不可恢复。`)) return;
 try {
 await api('DELETE', `/api/v1/users/${id}`);
 toast(`用户 ${username} 已删除`);
 loadUsers();
 } catch(e) { toast('删除失败：'+e.message, 'err'); }
}

// ─── 修改密码 ─────────────────────────────────────────────────────────────

function openPwdModal() {
 document.getElementById('pwdOld').value = '';
 document.getElementById('pwdNew').value = '';
 document.getElementById('pwdConfirm').value = '';
 openModal('pwdModal');
}

async function submitPwd() {
 const old_password = document.getElementById('pwdOld').value;
 const new_password = document.getElementById('pwdNew').value;
 const confirm = document.getElementById('pwdConfirm').value;
 if (new_password !== confirm) { toast('两次输入的新密码不一致', 'err'); return; }
 if (new_password.length < 6) { toast('新密码至少 6 位', 'err'); return; }
 try {
 await api('PUT', `/api/v1/users/${currentUser.id}/password`, {old_password, new_password});
 toast('密码修改成功，请重新登录');
 closeModal('pwdModal');
 setTimeout(logout, 1500);
 } catch(e) { toast('修改失败：'+e.message, 'err'); }
}

// ─── 审计日志 ─────────────────────────────────────────────────────────────
