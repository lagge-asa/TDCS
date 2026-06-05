"""系统 API: /health, /metrics, /auth/login"""
import bcrypt
import logging
from flask import Blueprint, jsonify, request, current_app
from ..auth import generate_token, require_auth

logger = logging.getLogger(__name__)

# dummy hash 用于消除用户名枚举时序侧信道（用户不存在时也执行等耗时的 checkpw）
_dummy_hash_cache = None

def _get_dummy_hash() -> bytes:
    """懒加载 dummy hash：只在首次调用时计算一次。"""
    global _dummy_hash_cache
    if _dummy_hash_cache is None:
        _dummy_hash_cache = bcrypt.hashpw(b"dummy", bcrypt.gensalt())
    return _dummy_hash_cache

bp = Blueprint("system", __name__)


@bp.get("/health")
def health():
    """无需认证：检查服务及 DB 连通性，供 k8s readiness probe 使用."""
    db = current_app.config.get("db")
    if db:
        try:
            from sqlalchemy import text
            with db.master_conn() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            logger.warning("Health check DB failed: %s", e)
            return jsonify({"status": "degraded", "db": "connection failed"}), 503
    return jsonify({"status": "ok"})


@bp.get("/metrics")
def metrics():
    """Prometheus 格式指标."""
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        from flask import Response
        return Response(generate_latest(),
                        mimetype=CONTENT_TYPE_LATEST)
    except ImportError:
        return "# prometheus_client not installed\n", 200


@bp.post("/api/v1/auth/login")
def login():
    """登录：返回 JWT token。"""
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400

    db = current_app.config.get("db")
    if not db:
        return jsonify({"error": "DB unavailable"}), 503

    from sqlalchemy import text
    with db.master_conn() as conn:
        row = conn.execute(
            text("SELECT id, password_hash, role, enabled FROM users WHERE username=:u"),
            {"u": username}
        ).mappings().first()

        if not row or not row["enabled"]:
            # 消除用户名枚举时序侧信道：用户不存在时也执行一次 checkpw
            bcrypt.checkpw(password.encode(), _get_dummy_hash())
            return jsonify({"error": "Invalid credentials"}), 401

        stored = row["password_hash"]
        if isinstance(stored, str):
            stored = stored.encode()
        if not bcrypt.checkpw(password.encode(), stored):
            return jsonify({"error": "Invalid credentials"}), 401

        conn.execute(text("UPDATE users SET last_login=NOW() WHERE id=:id"), {"id": row["id"]})
        conn.commit()

    expire_hours = current_app.config.get("TOKEN_EXPIRE_HOURS", 8)
    token = generate_token(row["id"], username, row["role"], expire_hours=expire_hours)
    return jsonify({"token": token, "role": row["role"], "username": username})
