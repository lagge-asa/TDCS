"""
配置管理 API

GET  /api/v1/config/         查看当前运行时配置摘要
PUT  /api/v1/config/reload   热重载配置（admin，写审计日志）
"""

import json
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import text

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
        "queue_maxsize": cfg.queue_maxsize,
        "task_timeout": cfg.task_timeout,
        "web": {
            "host": cfg.web.host,
            "port": cfg.web.port,
            "token_expire_hours": cfg.web.token_expire_hours,
            "rate_limit": cfg.web.rate_limit,
            "server": cfg.web.server,
        },
        "ha": {
            "enabled": cfg.ha.enabled,
            "heartbeat_interval": cfg.ha.heartbeat_interval,
            "failover_timeout": cfg.ha.failover_timeout,
        },
        "monitoring": {
            "prometheus_enabled": cfg.monitoring.prometheus.enabled,
            "alerting_enabled": cfg.monitoring.alerting.enabled,
            "alerting_channels": len(cfg.monitoring.alerting.channels),
        },
        "tasks": [
            {
                "task_id": t.task_id,
                "name": t.name,
                "enabled": t.enabled,
                "monitor_folder": t.monitor_folder,
                "file_extensions": list(t.file_extensions),
                "extractor": t.extractor,
                "base_table": t.base_table,
                "max_retries": t.max_retries,
                "poll_interval": t.poll_interval,
            }
            for t in cfg.tasks
        ],
    })


@bp.put("/reload")
@require_auth("admin")
def reload_config():
    cm = current_app.config["config_manager"]
    try:
        cm.reload()
    except Exception as e:
        return jsonify({"error": f"配置重载失败: {e}"}), 500

    # 写审计日志
    try:
        db = current_app.config.get("db")
        user = getattr(request, "current_user", {})
        if db:
            with db.master_conn() as conn:
                conn.execute(text("""
                    INSERT INTO audit_log (user_id, username, user_ip, action, target, detail)
                    VALUES (:uid, :uname, :ip, 'config.reload', 'config/config.yaml', :detail)
                """), {
                    "uid": user.get("sub"),
                    "uname": user.get("username"),
                    "ip": request.remote_addr,
                    "detail": json.dumps({"instance_id": cm.config.instance_id}),
                })
                conn.commit()
    except Exception:
        pass

    return jsonify({"status": "reloaded", "instance_id": cm.config.instance_id})
