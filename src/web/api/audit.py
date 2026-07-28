"""
审计日志 API

GET /api/v1/audit-logs/    查询审计日志（admin，分页+过滤）
"""

from flask import Blueprint, request, current_app, Response
from sqlalchemy import text
import csv, io

from ..auth import require_auth
from ..response import ok, paginated
from ..pagination import get_pagination

bp = Blueprint("audit", __name__)


@bp.get("/")
@require_auth("admin")
def list_audit_logs():
    db = current_app.config.get("db")
    if not db:
        return ok({"logs": [], "total": 0})

    page, page_size = get_pagination()
    offset = (page - 1) * page_size

    username = request.args.get("username", "").strip()
    action = request.args.get("action", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    conditions = []
    params = {"limit": page_size, "offset": offset}

    if username:
        conditions.append("username = :username")
        params["username"] = username
    if action:
        conditions.append("action LIKE :action")
        params["action"] = f"%{action}%"
    if start_date:
        conditions.append("timestamp >= :start_date")
        params["start_date"] = start_date
    if end_date:
        conditions.append("timestamp <= :end_date")
        params["end_date"] = end_date + " 23:59:59"

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with db.slave_conn() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM audit_log {where}"), params
        ).scalar()
        rows = conn.execute(text(f"""
            SELECT id, timestamp, user_id, username, user_ip,
                   action, target, detail
            FROM audit_log {where}
            ORDER BY timestamp DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    logs = [{
        "id": r["id"],
        "timestamp": str(r["timestamp"]) if r["timestamp"] else None,
        "user_id": r["user_id"],
        "username": r["username"],
        "user_ip": r["user_ip"],
        "action": r["action"],
        "target": r["target"],
        "detail": r["detail"],
    } for r in rows]

    return paginated(logs, page, page_size, total)


@bp.get("/export")
@require_auth("admin")
def export_audit_csv():
    """导出审计日志为 CSV。"""
    db = current_app.config.get("db")
    if not db:
        return Response("no data", mimetype="text/csv")

    username = request.args.get("username", "").strip()
    action = request.args.get("action", "").strip()
    conditions = []
    params = {}
    if username:
        conditions.append("username = :username")
        params["username"] = username
    if action:
        conditions.append("action LIKE :action")
        params["action"] = f"%{action}%"
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with db.slave_conn() as conn:
        rows = conn.execute(text(f"""
            SELECT timestamp, username, user_ip, action, target
            FROM audit_log {where}
            ORDER BY timestamp DESC LIMIT 10000
        """), params).mappings().all()

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["时间", "用户", "IP", "操作", "目标"])
    for r in rows:
        w.writerow([r["timestamp"], r["username"], r["user_ip"], r["action"], r["target"]])
    csv_data = output.getvalue()
    return Response(csv_data, mimetype="text/csv; charset=utf-8-sig",
                    headers={"Content-Disposition": "attachment; filename=audit_logs.csv"})
