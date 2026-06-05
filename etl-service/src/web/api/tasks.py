"""
任务管理 API

GET  /api/v1/tasks/                  列出所有任务（含实时状态）
GET  /api/v1/tasks/<task_id>         单任务详情
POST /api/v1/tasks/<task_id>/pause   暂停
POST /api/v1/tasks/<task_id>/resume  恢复
POST /api/v1/tasks/<task_id>/trigger 立即扫描
POST /api/v1/tasks/<task_id>/enable  启用（含启动 watcher）
POST /api/v1/tasks/<task_id>/disable 禁用（含停止 watcher）
GET  /api/v1/tasks/<task_id>/stats   文件处理统计
"""

from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import text

from ..auth import require_auth

bp = Blueprint("tasks", __name__)


def _get_tm_or_404(task_id):
    tm = current_app.config.get("task_manager")
    cm = current_app.config.get("config_manager")
    if not cm or not cm.get_task(task_id):
        return None, (jsonify({"error": f"任务 '{task_id}' 不存在"}), 404)
    return tm, None


def _task_file_stats(db, task_id: str) -> dict:
    """查询该任务的文件处理统计."""
    if not db:
        return {}
    try:
        with db.slave_conn() as conn:
            row = conn.execute(text("""
                SELECT
                    COUNT(*)                                        AS total,
                    SUM(status='SUCCESS')                          AS success,
                    SUM(status='FAILED')                           AS failed,
                    SUM(status IN ('PENDING','CLAIMED','PROCESSING')) AS pending,
                    SUM(status='SKIPPED')                          AS skipped,
                    ROUND(AVG(CASE WHEN status='SUCCESS' THEN processing_time_ms END), 0)
                                                                   AS avg_ms,
                    SUM(row_count)                                 AS total_rows,
                    MAX(processed_at)                              AS last_processed
                FROM processed_files
                WHERE task_id = :tid
            """), {"tid": task_id}).mappings().first()
        if row:
            return {
                "total": int(row["total"] or 0),
                "success": int(row["success"] or 0),
                "failed": int(row["failed"] or 0),
                "pending": int(row["pending"] or 0),
                "skipped": int(row["skipped"] or 0),
                "avg_processing_ms": int(row["avg_ms"] or 0),
                "total_rows": int(row["total_rows"] or 0),
                "last_processed": str(row["last_processed"]) if row["last_processed"] else None,
            }
    except Exception:
        pass
    return {}


def _task_to_dict(task, db=None) -> dict:
    stats = _task_file_stats(db, task.task_id) if db else {}
    return {
        "task_id": task.task_id,
        "name": task.name,
        "enabled": task.enabled,
        "priority": task.priority,
        "monitor_folder": task.monitor_folder,
        "file_extensions": list(task.file_extensions),
        "recursive": task.recursive,
        "extractor": task.extractor,
        "batch_size": task.batch_size,
        "base_table": task.base_table,
        "max_retries": task.max_retries,
        "poll_interval": task.poll_interval,
        "stats": stats,
    }


# ─────────────────────────────────────────────────────────────────────────────

@bp.get("/")
@require_auth("viewer")
def list_tasks():
    cm = current_app.config["config_manager"]
    db = current_app.config.get("db")
    tasks = [_task_to_dict(t, db) for t in cm.config.tasks]
    return jsonify({"tasks": tasks, "total": len(tasks)})


@bp.get("/<task_id>")
@require_auth("viewer")
def get_task(task_id: str):
    cm = current_app.config.get("config_manager")
    task = cm.get_task(task_id) if cm else None
    if not task:
        return jsonify({"error": f"任务 '{task_id}' 不存在"}), 404
    db = current_app.config.get("db")
    return jsonify(_task_to_dict(task, db))


@bp.get("/<task_id>/stats")
@require_auth("viewer")
def task_stats(task_id: str):
    """任务文件处理统计（按日期分组）."""
    cm = current_app.config.get("config_manager")
    if not cm or not cm.get_task(task_id):
        return jsonify({"error": f"任务 '{task_id}' 不存在"}), 404

    db = current_app.config.get("db")
    if not db:
        return jsonify({"task_id": task_id, "daily": []})

    days = min(90, max(1, int(request.args.get("days", 7))))
    with db.slave_conn() as conn:
        rows = conn.execute(text("""
            SELECT
                DATE(created_at)           AS day,
                COUNT(*)                   AS total,
                SUM(status='SUCCESS')      AS success,
                SUM(status='FAILED')       AS failed,
                SUM(row_count)             AS rows_processed,
                ROUND(AVG(CASE WHEN status='SUCCESS' THEN processing_time_ms END),0) AS avg_ms
            FROM processed_files
            WHERE task_id=:tid
              AND created_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
            GROUP BY DATE(created_at)
            ORDER BY day ASC
        """), {"tid": task_id, "days": days}).mappings().all()

    return jsonify({
        "task_id": task_id,
        "days": days,
        "daily": [{
            "day": str(r["day"]),
            "total": int(r["total"]),
            "success": int(r["success"] or 0),
            "failed": int(r["failed"] or 0),
            "rows_processed": int(r["rows_processed"] or 0),
            "avg_ms": int(r["avg_ms"] or 0),
        } for r in rows],
    })


@bp.post("/<task_id>/pause")
@require_auth("operator")
def pause_task(task_id: str):
    tm, err = _get_tm_or_404(task_id)
    if err:
        return err
    if tm:
        tm.pause_task(task_id)
    return jsonify({"status": "paused", "task_id": task_id})


@bp.post("/<task_id>/resume")
@require_auth("operator")
def resume_task(task_id: str):
    tm, err = _get_tm_or_404(task_id)
    if err:
        return err
    if tm:
        tm.resume_task(task_id)
    return jsonify({"status": "resumed", "task_id": task_id})


@bp.post("/<task_id>/trigger")
@require_auth("operator")
def trigger_task(task_id: str):
    tm, err = _get_tm_or_404(task_id)
    if err:
        return err
    if tm:
        tm.trigger_task(task_id)
    return jsonify({"status": "triggered", "task_id": task_id})


@bp.post("/<task_id>/enable")
@require_auth("admin")
def enable_task(task_id: str):
    """启用任务并启动 watcher."""
    cm = current_app.config.get("config_manager")
    tm = current_app.config.get("task_manager")
    if not cm or not cm.get_task(task_id):
        return jsonify({"error": f"任务 '{task_id}' 不存在"}), 404
    if tm:
        tm.start_task(task_id)
    return jsonify({"status": "enabled", "task_id": task_id})


@bp.post("/<task_id>/disable")
@require_auth("admin")
def disable_task(task_id: str):
    """禁用任务并停止 watcher."""
    cm = current_app.config.get("config_manager")
    tm = current_app.config.get("task_manager")
    if not cm or not cm.get_task(task_id):
        return jsonify({"error": f"任务 '{task_id}' 不存在"}), 404
    if tm:
        tm.stop_task(task_id)
    return jsonify({"status": "disabled", "task_id": task_id})
