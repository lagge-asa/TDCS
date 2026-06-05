"""
用户管理 API

GET    /api/v1/users/              列出所有用户（admin）
POST   /api/v1/users/              创建用户（admin）
DELETE /api/v1/users/<id>          删除用户（admin）
PUT    /api/v1/users/<id>/password 修改密码（admin 或本人）
PUT    /api/v1/users/<id>/role     修改角色（admin）
GET    /api/v1/users/me            查看当前用户信息（任意已登录）
"""

import json
import re
import bcrypt
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import text

from ..auth import require_auth

# 用户名只允许字母、数字、下划线、连字符，长度 3-32
_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]{3,32}$')

bp = Blueprint("users", __name__)

_VALID_ROLES = {"admin", "operator", "viewer"}


def _audit(action: str, target: str, detail: dict = None):
    """写审计日志（失败不影响主流程）."""
    try:
        db = current_app.config.get("db")
        if not db:
            return
        user = getattr(request, "current_user", {})
        with db.master_conn() as conn:
            conn.execute(text("""
                INSERT INTO audit_log (user_id, username, user_ip, action, target, detail)
                VALUES (:uid, :uname, :ip, :action, :target, :detail)
            """), {
                "uid": user.get("sub"),
                "uname": user.get("username"),
                "ip": request.remote_addr,
                "action": action,
                "target": target,
                "detail": json.dumps(detail or {}),
            })
            conn.commit()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────

@bp.get("/me")
@require_auth("viewer")
def get_me():
    """当前登录用户信息."""
    u = request.current_user
    db = current_app.config.get("db")
    if not db:
        return jsonify({"id": u.get("sub"), "username": u.get("username"), "role": u.get("role")})
    with db.slave_conn() as conn:
        row = conn.execute(
            text("SELECT id, username, role, enabled, last_login, created_at FROM users WHERE id=:id"),
            {"id": u.get("sub")}
        ).mappings().first()
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify(_row_to_dict(row))


@bp.get("/")
@require_auth("admin")
def list_users():
    """列出所有用户."""
    db = current_app.config.get("db")
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    with db.slave_conn() as conn:
        rows = conn.execute(
            text("SELECT id, username, role, enabled, last_login, created_at FROM users WHERE enabled=1 ORDER BY id")
        ).mappings().all()
    return jsonify({"users": [_row_to_dict(r) for r in rows], "total": len(rows)})


@bp.post("/")
@require_auth("admin")
def create_user():
    """创建新用户."""
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "viewer").strip()

    if not username:
        return jsonify({"error": "用户名不能为空"}), 400
    if not _USERNAME_RE.match(username):
        return jsonify({"error": "用户名只允许字母、数字、下划线和连字符，长度 3-32"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400
    if role not in _VALID_ROLES:
        return jsonify({"error": f"角色必须是 {_VALID_ROLES} 之一"}), 400

    db = current_app.config.get("db")
    if not db:
        return jsonify({"error": "DB unavailable"}), 503

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    try:
        with db.master_conn() as conn:
            result = conn.execute(text(
                "INSERT INTO users (username, password_hash, role) VALUES (:u, :h, :r)"
            ), {"u": username, "h": pw_hash, "r": role})
            conn.commit()
            new_id = result.lastrowid
    except Exception as e:
        # 判断唯一约束冲突（MySQL 1062 / PostgreSQL 23505 / 通用 'Duplicate' 关键字）
        err_str = str(e)
        if "Duplicate" in err_str or "1062" in err_str or "23505" in err_str:
            return jsonify({"error": f"用户名 '{username}' 已存在"}), 409
        logger.error("create_user DB error: %s", e)
        return jsonify({"error": "创建用户失败"}), 500

    _audit("user.create", f"users/{new_id}", {"username": username, "role": role})
    return jsonify({"id": new_id, "username": username, "role": role}), 201


@bp.delete("/<int:user_id>")
@require_auth("admin")
def delete_user(user_id: int):
    """删除用户（不可删除自己）."""
    me = request.current_user
    if str(user_id) == str(me.get("sub")):
        return jsonify({"error": "不能删除自己"}), 400

    db = current_app.config.get("db")
    if not db:
        return jsonify({"error": "DB unavailable"}), 503

    with db.master_conn() as conn:
        row = conn.execute(
            text("SELECT username FROM users WHERE id=:id"), {"id": user_id}
        ).mappings().first()
        if not row:
            return jsonify({"error": "用户不存在"}), 404
        # 软删除：设置 enabled=false，保留审计历史
        conn.execute(text("UPDATE users SET enabled=0 WHERE id=:id"), {"id": user_id})
        conn.commit()

    _audit("user.delete", f"users/{user_id}", {"username": row["username"]})
    return jsonify({"status": "deleted", "id": user_id})


@bp.put("/<int:user_id>/password")
@require_auth("viewer")
def change_password(user_id: int):
    """修改密码：admin 可改任意人，普通用户只能改自己."""
    me = request.current_user
    is_admin = me.get("role") == "admin"
    is_self = str(user_id) == str(me.get("sub"))

    if not is_admin and not is_self:
        return jsonify({"error": "只能修改自己的密码"}), 403

    data = request.get_json() or {}
    new_pw = data.get("new_password") or ""
    if len(new_pw) < 6:
        return jsonify({"error": "新密码至少 6 位"}), 400
    if len(new_pw) > 72:
        return jsonify({"error": "密码最长 72 位（bcrypt 限制）"}), 400

    db = current_app.config.get("db")
    if not db:
        return jsonify({"error": "DB unavailable"}), 503

    # 非 admin 需要在同一事务内验证旧密码后再更新，防止并发竞态
    if not is_admin:
        old_pw = data.get("old_password") or ""
        with db.master_conn() as conn:
            row = conn.execute(
                text("SELECT password_hash FROM users WHERE id=:id AND enabled=1 FOR UPDATE"),
                {"id": user_id}
            ).mappings().first()
            if not row:
                return jsonify({"error": "用户不存在"}), 404
            stored = row["password_hash"]
            if isinstance(stored, str):
                stored = stored.encode()
            if not bcrypt.checkpw(old_pw.encode(), stored):
                return jsonify({"error": "旧密码错误"}), 401
            new_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
            conn.execute(
                text("UPDATE users SET password_hash=:h WHERE id=:id"), {"h": new_hash, "id": user_id}
            )
            conn.commit()
        _audit("user.password_change", f"users/{user_id}", {"by_admin": False})
        return jsonify({"status": "ok"})

    new_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    with db.master_conn() as conn:
        result = conn.execute(
            text("UPDATE users SET password_hash=:h WHERE id=:id"), {"h": new_hash, "id": user_id}
        )
        rowcount = result.rowcount   # 在连接关闭前读取
        conn.commit()
    if rowcount == 0:
        return jsonify({"error": "用户不存在"}), 404

    _audit("user.password_change", f"users/{user_id}", {"by_admin": is_admin})
    return jsonify({"status": "ok"})


@bp.put("/<int:user_id>/role")
@require_auth("admin")
def change_role(user_id: int):
    """修改用户角色."""
    me = request.current_user
    if str(user_id) == str(me.get("sub")):
        return jsonify({"error": "不能修改自己的角色"}), 400

    data = request.get_json() or {}
    new_role = (data.get("role") or "").strip()
    if new_role not in _VALID_ROLES:
        return jsonify({"error": f"角色必须是 {sorted(_VALID_ROLES)} 之一"}), 400

    db = current_app.config.get("db")
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    with db.master_conn() as conn:
        result = conn.execute(
            text("UPDATE users SET role=:r WHERE id=:id"), {"r": new_role, "id": user_id}
        )
        rowcount = result.rowcount  # 在连接关闭前读取
        conn.commit()
    if rowcount == 0:
        return jsonify({"error": "用户不存在"}), 404

    _audit("user.role_change", f"users/{user_id}", {"new_role": new_role})
    return jsonify({"status": "ok", "role": new_role})


# ─────────────────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "last_login": str(row["last_login"]) if row["last_login"] else None,
        "created_at": str(row["created_at"]) if row["created_at"] else None,
    }
