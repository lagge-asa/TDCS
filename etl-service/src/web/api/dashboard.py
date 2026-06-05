"""
仪表盘聚合 API

GET /api/v1/dashboard/   一次返回仪表盘所有 KPI 数据
"""

from flask import Blueprint, jsonify, current_app
from sqlalchemy import text

from ..auth import require_auth

bp = Blueprint("dashboard", __name__)


@bp.get("/")
@require_auth("viewer")
def get_dashboard():
    cm = current_app.config.get("config_manager")
    db = current_app.config.get("db")
    ha = current_app.config.get("ha_elector")
    pool = current_app.config.get("worker_pool")

    # ── 任务统计 ──────────────────────────────────────────────────────────
    task_count = len(cm.config.tasks) if cm else 0
    enabled_count = sum(1 for t in cm.config.tasks if t.enabled) if cm else 0

    # ── 文件 KPI ──────────────────────────────────────────────────────────
    file_kpi = {"total": 0, "success": 0, "failed": 0, "pending": 0}
    total_rows = 0
    if db:
        try:
            with db.slave_conn() as conn:
                rows = conn.execute(text("""
                    SELECT status, COUNT(*) AS cnt
                    FROM processed_files
                    GROUP BY status
                """)).mappings().all()
                for r in rows:
                    s = r["status"].lower()
                    file_kpi["total"] += int(r["cnt"])
                    if s in file_kpi:
                        file_kpi[s] = int(r["cnt"])
                    elif s in ("claimed", "processing"):
                        file_kpi["pending"] += int(r["cnt"])

                total_rows = conn.execute(
                    text("SELECT COALESCE(SUM(row_count),0) FROM processed_files WHERE status='SUCCESS'")
                ).scalar() or 0
        except Exception:
            pass

    # ── 最近 10 条文件记录 ────────────────────────────────────────────────
    recent_files = []
    if db:
        try:
            with db.slave_conn() as conn:
                rrows = conn.execute(text("""
                    SELECT file_name, task_id, status, row_count,
                           processing_time_ms, processed_at, created_at
                    FROM processed_files
                    ORDER BY created_at DESC
                    LIMIT 10
                """)).mappings().all()
            recent_files = [{
                "file_name": r["file_name"],
                "task_id": r["task_id"],
                "status": r["status"],
                "row_count": r["row_count"],
                "processing_time_ms": r["processing_time_ms"],
                "time": str(r["processed_at"] or r["created_at"]),
            } for r in rrows]
        except Exception:
            pass

    # ── Worker Pool 状态 ──────────────────────────────────────────────────
    worker_info = {}
    if pool:
        try:
            worker_info = {
                "queue_size": pool.queue_size(),
                "active_workers": pool.active_count(),
            }
        except Exception:
            pass

    # ── HA 状态 ───────────────────────────────────────────────────────────
    ha_info = {"enabled": False}
    if ha:
        try:
            ha_info = {
                "enabled": True,
                "is_active": ha.is_active,
                "instance_id": ha.instance_id if hasattr(ha, "instance_id") else None,
            }
        except Exception:
            pass

    # ── DB 健康 ───────────────────────────────────────────────────────────
    db_ok = False
    if db:
        try:
            with db.slave_conn() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            pass

    return jsonify({
        "tasks": {
            "total": task_count,
            "enabled": enabled_count,
        },
        "files": {**file_kpi, "total_rows": int(total_rows)},
        "recent_files": recent_files,
        "workers": worker_info,
        "ha": ha_info,
        "health": {
            "db": db_ok,
            "status": "ok" if db_ok else "degraded",
        },
    })
