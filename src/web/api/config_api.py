"""
配置管理 API

GET  /api/v1/config/         查看当前运行时配置摘要
PUT  /api/v1/config/reload   热重载配置（admin，写审计日志）
"""

import json
import os
import yaml
from flask import Blueprint, request, current_app
from sqlalchemy import text

from ..auth import require_auth
from ..response import ok, error

bp = Blueprint("config_api", __name__)


@bp.get("/")
@require_auth("viewer")
def get_config():
    cm = current_app.config["config_manager"]
    cfg = cm.config
    return ok({
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
    old_cfg = cm.config  # 保存重载前的配置
    try:
        cm.reload()
    except Exception as e:
        return error("CONFIG_RELOAD_FAILED", f"配置重载失败: {e}", status=500)

    new_cfg = cm.config
    user = getattr(request, "current_user", {})
    db = current_app.config.get("db")

    if db:
        try:
            # 记录配置变更摘要
            diff = {
                "worker_threads": [old_cfg.worker_threads, new_cfg.worker_threads],
                "task_count": [len(old_cfg.tasks), len(new_cfg.tasks)],
                "log_level": [old_cfg.log_level, new_cfg.log_level],
            }
            changed = {k: v for k, v in diff.items() if v[0] != v[1]}
            with db.master_conn() as conn:
                # 审计日志
                conn.execute(text("""
                    INSERT INTO audit_log
                        (user_id, username, user_ip, action, target, detail)
                    VALUES (:uid, :uname, :ip, 'config.reload',
                            'config/config.yaml', :detail)
                """), {
                    "uid": user.get("sub"),
                    "uname": user.get("username"),
                    "ip": request.remote_addr,
                    "detail": json.dumps(
                        {"changed": changed,
                         "instance_id": new_cfg.instance_id}),
                })
                # 配置变更历史（适配实际表结构）
                conn.execute(text("""
                    INSERT INTO config_history
                        (config_type, config_key,
                         content_before, content_after, changed_by)
                    VALUES ('main', 'config/config.yaml',
                            :before, :after, :op)
                """), {
                    "op": user.get("username", "unknown"),
                    "before": json.dumps({
                        "worker_threads": old_cfg.worker_threads,
                        "log_level": old_cfg.log_level,
                        "task_ids": [t.task_id for t in old_cfg.tasks],
                    }),
                    "after": json.dumps({
                        "worker_threads": new_cfg.worker_threads,
                        "log_level": new_cfg.log_level,
                        "task_ids": [t.task_id for t in new_cfg.tasks],
                    }),
                })
                conn.commit()
        except Exception:
            pass

    return ok({"status": "reloaded",
                    "instance_id": new_cfg.instance_id})


# ── 任务配置 CRUD ──────────────────────────────────────────────────────

def _read_config_yaml():
    cm = current_app.config["config_manager"]
    path = cm._path
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f.read())

def _write_config_yaml(data: dict):
    cm = current_app.config["config_manager"]
    path = cm._path
    import yaml as _yaml
    with open(path, "w", encoding="utf-8") as f:
        _yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

@bp.post("/tasks")
@require_auth("admin")
def create_task():
    """创建新任务 — 写入 config.yaml 并热重载。"""
    task_data = request.get_json() or {}
    task_id = task_data.get("task_id", "").strip()
    if not task_id:
        return error("MISSING_FIELD", "缺少 task_id", status=400)
    cfg = _read_config_yaml()
    existing = [t for t in cfg.get("tasks", []) if t.get("task_id") == task_id]
    if existing:
        return error("TASK_EXISTS", f"任务 '{task_id}' 已存在", status=409)
    new_task = _build_task_dict(task_data)
    cfg.setdefault("tasks", []).append(new_task)
    _write_config_yaml(cfg)
    # Hot reload
    cm = current_app.config["config_manager"]
    try:
        cm.reload()
    except Exception as e:
        return error("CONFIG_RELOAD_FAILED", f"任务已写入但重载失败: {e}", status=500)
    return ok({"task_id": task_id, "message": "任务创建成功"})


@bp.put("/tasks/<task_id>")
@require_auth("admin")
def update_task(task_id):
    """更新已有任务配置。"""
    task_data = request.get_json() or {}
    cfg = _read_config_yaml()
    tasks = cfg.get("tasks", [])
    idx = next((i for i, t in enumerate(tasks) if t.get("task_id") == task_id), None)
    if idx is None:
        return error("TASK_NOT_FOUND", f"任务 '{task_id}' 不存在", status=404)
    updated = _build_task_dict({**tasks[idx], **task_data, "task_id": task_id})
    tasks[idx] = updated
    _write_config_yaml(cfg)
    cm = current_app.config["config_manager"]
    try:
        cm.reload()
    except Exception as e:
        return error("CONFIG_RELOAD_FAILED", f"更新已写入但重载失败: {e}", status=500)
    return ok({"task_id": task_id, "message": "任务更新成功"})


@bp.get("/tasks/<task_id>")
@require_auth("admin")
def get_task_config(task_id):
    """获取单个任务的完整配置。"""
    cfg = _read_config_yaml()
    tasks = cfg.get("tasks", [])
    task = next((t for t in tasks if t.get("task_id") == task_id), None)
    if not task:
        return error("TASK_NOT_FOUND", f"任务 '{task_id}' 不存在", status=404)
    return ok(task)


@bp.delete("/tasks/<task_id>")
@require_auth("admin")
def delete_task(task_id):
    """删除任务配置。"""
    cfg = _read_config_yaml()
    tasks = cfg.get("tasks", [])
    new_tasks = [t for t in tasks if t.get("task_id") != task_id]
    if len(new_tasks) == len(tasks):
        return error("TASK_NOT_FOUND", f"任务 '{task_id}' 不存在", status=404)
    cfg["tasks"] = new_tasks
    _write_config_yaml(cfg)
    cm = current_app.config["config_manager"]
    try:
        cm.reload()
    except Exception as e:
        return error("CONFIG_RELOAD_FAILED", f"删除已生效但重载失败: {e}", status=500)
    return ok({"task_id": task_id, "message": "任务已删除"})


def _build_task_dict(data: dict) -> dict:
    """从表单数据构建任务 dict（包含默认值）。"""
    return {
        "task_id": data.get("task_id", ""),
        "name": data.get("name", data.get("task_id", "")),
        "enabled": data.get("enabled", True),
        "priority": data.get("priority", 1),
        "monitor": {
            "folder_path": data.get("monitor_folder", "D:\\data\\input"),
            "file_extensions": data.get("file_extensions", [".csv"]),
            "recursive": data.get("recursive", False),
            "debounce_seconds": data.get("debounce_seconds", 3),
            "stability_check_interval": data.get("stability_check_interval", 1),
            "stability_check_count": data.get("stability_check_count", 3),
        },
        "etl": {
            "extractor": data.get("extractor", "csv"),
            "encoding": data.get("encoding", "auto"),
            "batch_size": data.get("batch_size", 1000),
            "transformer_module": data.get("transformer_module", ""),
            "transformer_function": data.get("transformer_function", ""),
            "sandbox_timeout": data.get("sandbox_timeout", 30),
            "sandbox_memory_mb": data.get("sandbox_memory_mb", 256),
        },
        "table": {
            "base_table": data.get("base_table", "data"),
            "partition_field": data.get("partition_field", ""),
            "partition_field_format": data.get("partition_field_format", "%Y-%m-%d"),
            "create_table_template": data.get("create_table_template", ""),
            "retention_months": data.get("retention_months", 12),
            "archive_old_tables": data.get("archive_old_tables", True),
        },
        "error_handling": {
            "max_retries": data.get("max_retries", 3),
            "retry_backoff": data.get("retry_backoff", [5, 30, 120]),
            "dead_letter_dir": data.get("dead_letter_dir", ""),
            "on_row_error": data.get("on_row_error", "skip"),
        },
        "archive": {
            "mode": data.get("archive_mode", "keep"),
            "archive_dir": data.get("archive_dir", ""),
            "retain_structure": data.get("retain_structure", True),
            "compress_after_days": data.get("compress_after_days", 0),
            "cleanup_after_days": data.get("cleanup_after_days", 0),
        },
        "schedule": {
            "poll_interval": data.get("poll_interval", 60),
            "poll_incremental": data.get("poll_incremental", True),
        },
    }
