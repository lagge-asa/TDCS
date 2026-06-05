"""
JWT 认证 + RBAC

JWT 存 Authorization Header, 天然免疫 CSRF.
三级权限: admin > operator > viewer
"""

import logging
from datetime import datetime, timezone, timedelta
from functools import wraps

import jwt
from flask import request, jsonify, current_app

logger = logging.getLogger(__name__)

ROLE_LEVELS = {"viewer": 1, "operator": 2, "admin": 3}


def generate_token(user_id: int, username: str,
                   role: str, expire_hours: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=expire_hours),
    }
    return jwt.encode(
        payload,
        current_app.config["SECRET_KEY"],
        algorithm="HS256",
    )


def require_auth(min_role: str = "viewer"):
    """装饰器: 验证 JWT + 角色权限."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return jsonify({"error": "Missing token"}), 401
            token = auth[7:]
            try:
                payload = jwt.decode(
                    token,
                    current_app.config["SECRET_KEY"],
                    algorithms=["HS256"],
                )
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Token expired",
                                "error_code": "token_expired"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "Invalid token",
                                "error_code": "token_invalid"}), 401

            user_role = payload.get("role", "viewer")
            if ROLE_LEVELS.get(user_role, 0) < ROLE_LEVELS.get(min_role, 0):
                return jsonify({"error": "Insufficient permissions"}), 403

            request.current_user = payload
            return fn(*args, **kwargs)
        return wrapper
    return decorator
