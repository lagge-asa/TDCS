"""配置管理 API"""
from flask import Blueprint, jsonify, request, current_app
from ..auth import require_auth

bp = Blueprint("config_api", __name__)


@bp.get("/")
@require_auth("viewer")
def get_config():
    cm = current_app.config["config_manager"]
    cfg = cm.config
    return jsonify({
        "instance_id": cfg.instance_id,
        "log_level": cfg.log_level,
        "worker_threads": cfg.worker_threads,
    })


@bp.put("/reload")
@require_auth("admin")
def reload_config():
    cm = current_app.config["config_manager"]
    cm.reload()
    return jsonify({"status": "reloaded"})
