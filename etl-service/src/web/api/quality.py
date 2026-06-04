"""数据质量 API"""
from flask import Blueprint, jsonify, current_app
from ..auth import require_auth

bp = Blueprint("quality", __name__)


@bp.get("/<task_id>")
@require_auth("viewer")
def get_quality(task_id):
    return jsonify({"task_id": task_id, "reports": []})
