"""
配置管理 API

GET  /api/v1/config/         查看当前运行时配置摘要
PUT  /api/v1/config/reload   热重载配置（admin，写审计日志）
"""

import json
import os
import re
import tempfile
import threading
import yaml
from flask import Blueprint, request, current_app
from sqlalchemy import text

from ..auth import require_auth
from ..response import ok, error

bp = Blueprint("config_api", __name__)

# 保护 config.yaml 并发读写（读→改→写→重载序列）
_config_lock = threading.Lock()


def _windows_drives():
    """返回当前服务器可访问的磁盘根目录。"""
    if os.name != "nt":
        return []
    import string
    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if os.path.isdir(root):
                drives.append({"name": root, "path": root})
        except OSError:
            # 某些映射盘或无权限磁盘可能在探测时抛出系统异常，跳过即可。
            continue
    return drives


@bp.get("/directories")
@require_auth("admin")
def list_directories():
    """列出服务器上的子目录，供任务监控目录选择器使用。"""
    raw_path = (request.args.get("path") or "").strip()
    path = os.path.abspath(raw_path or os.getcwd())
    if not os.path.isdir(path):
        return error("DIRECTORY_NOT_FOUND", "目录不存在", status=404)
    try:
        entries = []
        for item in os.scandir(path):
            if item.is_dir() and not item.name.startswith("."):
                entries.append({"name": item.name, "path": os.path.abspath(item.path)})
        entries.sort(key=lambda x: x["name"].lower())
        parent = os.path.dirname(path)
        return ok({
            "path": path,
            "parent": parent if parent != path else None,
            "directories": entries,
            # 磁盘根目录单独返回，前端可以从 D 盘切换到 C 盘等其他磁盘。
            "drives": _windows_drives(),
        })
    except (PermissionError, OSError) as exc:
        current_app.logger.warning("Cannot browse directory %s: %s", path, exc)
        return error("DIRECTORY_ACCESS_DENIED", "没有权限读取该目录", status=403)



@bp.get("/")
@require_auth("viewer")
def get_config():
    cm = current_app.config["config_manager"]
    cfg = cm.config
    pool = current_app.config.get("worker_pool")
    tm = current_app.config.get("task_manager")
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
                "paused": pool.is_task_paused(t.task_id) if pool else False,
                "circuit_state": pool.get_breaker_state(t.task_id) if pool else "CLOSED",
                "watcher_running": tm.is_running(t.task_id) if tm else False,
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

def _validate_task_request(data: object, task_id: str | None = None) -> tuple[dict | None, str | None]:
    if not isinstance(data, dict):
        return None, "请求体必须是 JSON 对象"
    candidate = data.get("task_id", task_id) or ""
    if not isinstance(candidate, str) or not re.fullmatch(r"^[a-z][a-z0-9_]*$", candidate):
        return None, "task_id 只能使用小写字母、数字和下划线，且必须以字母开头"
    if "name" in data and (not isinstance(data["name"], str) or not data["name"].strip()):
        return None, "name 必须是非空字符串"
    return data, None


def _read_config_yaml():
    cm = current_app.config["config_manager"]
    path = cm._path
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f.read()) or {}


def _write_config_yaml(data: dict):
    """使用同目录临时文件+原子替换写入配置。"""
    cm = current_app.config["config_manager"]
    path = cm._path
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".yaml.tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _validate_config_data(data: dict) -> list[str]:
    """调用启动时相同的配置校验器，防止非法任务写入 YAML。"""
    from ...core.config_validator import validate_config
    return validate_config(data)


def _save_and_reload(cfg: dict, old_cfg: dict) -> None:
    """保存并热重载；热重载失败时恢复旧文件和旧运行时配置。"""
    cm = current_app.config["config_manager"]
    errors = _validate_config_data(cfg)
    if errors:
        raise ValueError("配置校验失败: " + "; ".join(errors))
    _write_config_yaml(cfg)
    try:
        cm.reload()
    except Exception:
        try:
            _write_config_yaml(old_cfg)
            cm.reload()
        except Exception as rollback_error:
            raise RuntimeError(f"配置重载失败，且回滚失败: {rollback_error}") from rollback_error
        raise


@bp.post("/tasks")
@require_auth("admin")
def create_task():
    """创建新任务 — 写入 config.yaml 并热重载。"""
    task_data, validation_error = _validate_task_request(request.get_json(silent=True) or {})
    if validation_error:
        return error("INVALID_INPUT", validation_error, status=400)
    task_id = task_data.get("task_id", "").strip()
    with _config_lock:
        cfg = _read_config_yaml()
        old_cfg = yaml.safe_load(yaml.safe_dump(cfg, allow_unicode=True))
        existing = [t for t in cfg.get("tasks", []) if t.get("task_id") == task_id]
        if existing:
            return error("TASK_EXISTS", f"任务 '{task_id}' 已存在", status=409)
        new_task = _build_task_dict(task_data)
        cfg.setdefault("tasks", []).append(new_task)
        try:
            _save_and_reload(cfg, old_cfg)
        except ValueError as e:
            return error("INVALID_CONFIG", str(e), status=400)
        except Exception as e:
            return error("CONFIG_RELOAD_FAILED", f"配置重载失败，已回滚: {e}", status=500)
    return ok({"task_id": task_id, "message": "任务创建成功"})


@bp.put("/tasks/<task_id>")
@require_auth("admin")
def update_task(task_id):
    """更新已有任务配置。"""
    task_data, validation_error = _validate_task_request(request.get_json(silent=True) or {}, task_id)
    if validation_error:
        return error("INVALID_INPUT", validation_error, status=400)
    if task_data.get("task_id", task_id) != task_id:
        return error("TASK_ID_IMMUTABLE", "更新时不允许修改 task_id", status=400)
    with _config_lock:
        cfg = _read_config_yaml()
        old_cfg = yaml.safe_load(yaml.safe_dump(cfg, allow_unicode=True))
        tasks = cfg.get("tasks", [])
        idx = next((i for i, t in enumerate(tasks) if t.get("task_id") == task_id), None)
        if idx is None:
            return error("TASK_NOT_FOUND", f"任务 '{task_id}' 不存在", status=404)
        updated = _merge_task_update(tasks[idx], task_data)
        tasks[idx] = updated
        try:
            _save_and_reload(cfg, old_cfg)
        except ValueError as e:
            return error("INVALID_CONFIG", str(e), status=400)
        except Exception as e:
            return error("CONFIG_RELOAD_FAILED", f"配置重载失败，已回滚: {e}", status=500)
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
    with _config_lock:
        cfg = _read_config_yaml()
        old_cfg = yaml.safe_load(yaml.safe_dump(cfg, allow_unicode=True))
        tasks = cfg.get("tasks", [])
        new_tasks = [t for t in tasks if t.get("task_id") != task_id]
        if len(new_tasks) == len(tasks):
            return error("TASK_NOT_FOUND", f"任务 '{task_id}' 不存在", status=404)
        cfg["tasks"] = new_tasks
        try:
            _save_and_reload(cfg, old_cfg)
        except ValueError as e:
            return error("INVALID_CONFIG", str(e), status=400)
        except Exception as e:
            return error("CONFIG_RELOAD_FAILED", f"配置重载失败，已回滚: {e}", status=500)
    return ok({"task_id": task_id, "message": "任务已删除"})


def _deep_merge(base: dict, updates: dict) -> dict:
    """递归合并配置，避免表单更新覆盖未编辑的嵌套字段。"""
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _flatten_task_for_builder(task: dict) -> dict:
    """兼容旧版扁平字段和配置文件中的嵌套字段。"""
    data = dict(task)
    monitor = task.get("monitor") or {}
    etl = task.get("etl") or {}
    table = task.get("table") or {}
    errors = task.get("error_handling") or {}
    archive = task.get("archive") or {}
    schedule = task.get("schedule") or {}
    data.update({
        "monitor_folder": monitor.get("folder_path", task.get("monitor_folder", ".")),
        "file_extensions": monitor.get("file_extensions", task.get("file_extensions", [".csv"])),
        "recursive": monitor.get("recursive", task.get("recursive", False)),
        "debounce_seconds": monitor.get("debounce_seconds", 3),
        "stability_check_interval": monitor.get("stability_check_interval", 1),
        "stability_check_count": monitor.get("stability_check_count", 3),
        "extractor": etl.get("extractor", task.get("extractor", "csv")),
        "encoding": etl.get("encoding", "auto"),
        "batch_size": etl.get("batch_size", task.get("batch_size", 1000)),
        "transformer_module": etl.get("transformer_module", ""),
        "transformer_function": etl.get("transformer_function", ""),
        "sandbox_timeout": etl.get("sandbox_timeout", 30),
        "base_table": table.get("base_table", task.get("base_table", "data")),
        "partition_field": table.get("partition_field", ""),
        "partition_field_format": table.get("partition_field_format", "%Y-%m-%d"),
        "create_table_template": table.get("create_table_template", ""),
        "retention_months": table.get("retention_months", 12),
        "archive_old_tables": table.get("archive_old_tables", True),
        "max_retries": errors.get("max_retries", task.get("max_retries", 3)),
        "dead_letter_dir": errors.get("dead_letter_dir", ""),
        "archive_mode": archive.get("mode", "keep"),
        "archive_dir": archive.get("archive_dir", ""),
        "compress_after_days": archive.get("compress_after_days", 0),
        "cleanup_after_days": archive.get("cleanup_after_days", 0),
        "poll_interval": schedule.get("poll_interval", task.get("poll_interval", 60)),
        "poll_incremental": schedule.get("poll_incremental", True),
    })
    return data


def _merge_task_update(existing: dict, updates: dict) -> dict:
    """把表单扁平字段映射到嵌套配置，并保留未提交字段。"""
    result = _deep_merge(existing, updates)
    groups = {
        "monitor": {"folder_path": "monitor_folder", "file_extensions": "file_extensions", "recursive": "recursive", "debounce_seconds": "debounce_seconds", "stability_check_interval": "stability_check_interval", "stability_check_count": "stability_check_count"},
        "etl": {"extractor": "extractor", "encoding": "encoding", "batch_size": "batch_size", "transformer_module": "transformer_module", "transformer_function": "transformer_function", "sandbox_timeout": "sandbox_timeout"},
        "table": {"base_table": "base_table", "partition_field": "partition_field", "partition_field_format": "partition_field_format", "create_table_template": "create_table_template", "retention_months": "retention_months", "archive_old_tables": "archive_old_tables"},
        "error_handling": {"max_retries": "max_retries", "dead_letter_dir": "dead_letter_dir"},
        "archive": {"mode": "archive_mode", "archive_dir": "archive_dir", "compress_after_days": "compress_after_days", "cleanup_after_days": "cleanup_after_days"},
        "schedule": {"poll_interval": "poll_interval", "poll_incremental": "poll_incremental"},
    }
    flat = _flatten_task_for_builder(existing)
    flat.update(updates)
    rebuilt = _build_task_dict(flat)
    for section, mapping in groups.items():
        result[section] = _deep_merge(existing.get(section, {}), rebuilt.get(section, {}))
    for key in ("task_id", "name", "enabled", "priority"):
        if key in updates:
            result[key] = updates[key]
    result["task_id"] = existing.get("task_id")
    return result


def _build_task_dict(data: dict) -> dict:
    """从表单数据构建任务 dict（含默认值）。"""
    return {
        "task_id": data.get("task_id", ""),
        "name": data.get("name", data.get("task_id", "")),
        "enabled": data.get("enabled", True),
        "priority": data.get("priority", 1),
        "monitor": {
            "folder_path": data.get("monitor_folder", "."),
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
            "dead_letter_dir": data.get("dead_letter_dir", ""),
        },
        "archive": {
            "mode": data.get("archive_mode", "keep"),
            "archive_dir": data.get("archive_dir", ""),
            "compress_after_days": data.get("compress_after_days", 0),
            "cleanup_after_days": data.get("cleanup_after_days", 0),
        },
        "schedule": {
            "poll_interval": data.get("poll_interval", 60),
            "poll_incremental": data.get("poll_incremental", True),
        },
    }
