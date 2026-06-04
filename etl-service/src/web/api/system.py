"""系统 API: /health, /metrics, /auth/login"""
import bcrypt
from flask import Blueprint, jsonify, request, current_app
from ..auth import generate_token, require_auth

bp = Blueprint("system", __name__)


@bp.get("/health")
def health():
    """无需认证."""
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
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400

    db = current_app.config.get("db")
    if not db:
        return jsonify({"error": "DB unavailable"}), 503

    from sqlalchemy import text
    with db.slave_conn() as conn:
        row = conn.execute(
            text("SELECT id, password_hash, role, enabled FROM users WHERE username=:u"),
            {"u": username}
        ).mappings().first()

    if not row or not row["enabled"]:
        return jsonify({"error": "Invalid credentials"}), 401

    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return jsonify({"error": "Invalid credentials"}), 401

    # 更新 last_login
    with db.master_conn() as conn:
        conn.execute(text("UPDATE users SET last_login=NOW() WHERE id=:id"), {"id": row["id"]})
        conn.commit()

    token = generate_token(row["id"], username, row["role"], expire_hours=8)
    return jsonify({"token": token, "role": row["role"], "username": username})
