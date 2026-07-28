"""系统 API: /health, /metrics, /auth/login"""
import bcrypt
import logging
import time
import threading
from collections import defaultdict
from flask import Blueprint, request, current_app
from ..auth import generate_token, require_auth
from ..response import ok, error

logger = logging.getLogger(__name__)

# ── Login 爆破防护：每 IP 5次/分钟 ─────────────────────────────────────────
_LOGIN_RATE_LIMIT = 5       # 最大尝试次数
_LOGIN_RATE_WINDOW = 60     # 窗口秒数
_login_attempts: dict = defaultdict(list)
_login_lock = threading.Lock()


def _check_login_rate(ip: str) -> bool:
    """检查 IP 是否超过登录速率限制。返回 True 表示允许，False 表示被限."""
    now = time.time()
    with _login_lock:
        # 清理过期记录
        attempts = [t for t in _login_attempts.get(ip, [])
                    if now - t < _LOGIN_RATE_WINDOW]
        if len(attempts) >= _LOGIN_RATE_LIMIT:
            return False
        attempts.append(now)
        _login_attempts[ip] = attempts
        return True

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
            return ok({"status": "degraded", "db": "connection failed"}, status=503)
    return ok({"status": "ok"})


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
    """登录：返回 JWT token。每 IP 限制 5 次/分钟."""
    # 登录爆破防护
    client_ip = request.remote_addr or "unknown"
    if not _check_login_rate(client_ip):
        logger.warning("Login rate limit exceeded for IP: %s", client_ip)
        return error("RATE_LIMITED", "Too many login attempts, try again later", status=429)

    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return error("INVALID_INPUT", "Missing credentials", status=400)

    db = current_app.config.get("db")
    if not db:
        return error("DB_UNAVAILABLE", "DB unavailable", status=503)

    from sqlalchemy import text
    with db.master_conn() as conn:
        row = conn.execute(
            text("SELECT id, password_hash, role, enabled FROM users WHERE username=:u"),
            {"u": username}
        ).mappings().first()

        if not row or not row["enabled"]:
            # 消除用户名枚举时序侧信道：用户不存在时也执行一次 checkpw
            bcrypt.checkpw(password.encode(), _get_dummy_hash())
            return error("INVALID_CREDENTIALS", "Invalid credentials", status=401)

        stored = row["password_hash"]
        if isinstance(stored, str):
            stored = stored.encode()
        if not bcrypt.checkpw(password.encode(), stored):
            return error("INVALID_CREDENTIALS", "Invalid credentials", status=401)

        conn.execute(text("UPDATE users SET last_login=NOW() WHERE id=:id"), {"id": row["id"]})
        conn.commit()

    expire_hours = current_app.config.get("TOKEN_EXPIRE_HOURS", 8)
    token = generate_token(row["id"], username, row["role"], expire_hours=expire_hours)
    return ok({"token": token, "role": row["role"], "username": username})
