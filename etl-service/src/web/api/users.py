"""用户管理 API"""
from flask import Blueprint, jsonify, request, current_app
from ..auth import require_auth

bp = Blueprint("users", __name__)


@bp.get("/")
@require_auth("admin")
def list_users():
    return jsonify({"users": []})


@bp.delete("/<int:user_id>")
@require_auth("admin")
def delete_user(user_id):
    return jsonify({"status": "deleted"})
