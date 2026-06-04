"""清洗代码管理 API"""
import os
from flask import Blueprint, jsonify, request, current_app
from ..auth import require_auth
from ...etl.transform_sandbox import TransformSandbox

bp = Blueprint("cleaners", __name__)


@bp.post("/<name>/test")
@require_auth("operator")
def test_cleaner(name):
    data = request.get_json() or {}
    rows = data.get("rows", [])
    custom_dir = data.get("custom_etl_dir", "custom_etl")
    sb = TransformSandbox(custom_dir)
    try:
        result = sb.transform_batch(rows, name, "transform", timeout=10)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/<name>/validate")
@require_auth("operator")
def validate_cleaner(name):
    data = request.get_json() or {}
    code = data.get("code", "")
    ok, msg = TransformSandbox.validate_syntax(code)
    return jsonify({"valid": ok, "message": msg})
