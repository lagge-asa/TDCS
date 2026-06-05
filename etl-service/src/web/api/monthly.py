"""
月表生命周期 API

GET  /api/v1/monthly/           查询月表注册表
POST /api/v1/monthly/run        手动触发月表生命周期检查（admin）
"""

from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import text

from ..auth import require_auth

bp = Blueprint("monthly", __name__)


@bp.get("/")
@require_auth("viewer")
def list_monthly_tables():
    db = current_app.config.get("db")
    if not db:
        return jsonify({"tables": [], "total": 0})

    task_id = request.args.get("task_id")
    params = {}
    where = ""
    if task_id:
        where = "WHERE task_id = :task_id"
        params["task_id"] = task_id

    with db.slave_conn() as conn:
        rows = conn.execute(text(f"""
            SELECT id, task_id, table_name, `year_month`,
                   lifecycle_status, row_count, created_at, archived_at
            FROM monthly_table_registry {where}
            ORDER BY `year_month` DESC
            LIMIT 200
        """), params).mappings().all()

    return jsonify({
        "tables": [{
            "id": r["id"],
            "task_id": r["task_id"],
            "table_name": r["table_name"],
            "year_month": r["year_month"],
            "status": r.get("lifecycle_status", "ACTIVE"),
            "row_count": r["row_count"],
            "created_at": str(r["created_at"]) if r["created_at"] else None,
            "archived_at": str(r["archived_at"]) if r.get("archived_at") else None,
        } for r in rows],
        "total": len(rows),
    })


@bp.post("/run")
@require_auth("admin")
def run_lifecycle():
    """手动触发月表生命周期检查."""
    cm = current_app.config.get("config_manager")
    db = current_app.config.get("db")
    if not cm or not db:
        return jsonify({"error": "服务未完全初始化"}), 503

    data = request.get_json() or {}
    task_id = data.get("task_id")  # 可选，不填则检查所有

    try:
        from ...etl.monthly_lifecycle import MonthlyTableLifecycle
        lifecycle = MonthlyTableLifecycle(db)
        ran = []
        for task in cm.config.tasks:
            if task_id and task.task_id != task_id:
                continue
            if task.retention_months > 0:
                lifecycle.run(task)
                ran.append(task.task_id)
        return jsonify({"status": "ok", "ran_for_tasks": ran})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
