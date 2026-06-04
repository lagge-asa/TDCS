"""
数据质量 API

GET /api/v1/quality/<task_id>        某任务的质量报告列表（分页）
GET /api/v1/quality/<task_id>/latest 最新一条质量报告
GET /api/v1/quality/<task_id>/trend  近 N 天的质量趋势（用于折线图）
"""

from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import text

from ..auth import require_auth

bp = Blueprint("quality", __name__)


@bp.get("/<task_id>")
@require_auth("viewer")
def get_quality(task_id: str):
    """分页查询质量报告."""
    db = current_app.config.get("db")
    if not db:
        return jsonify({"task_id": task_id, "reports": [], "total": 0})

    page = max(1, int(request.args.get("page", 1)))
    page_size = min(100, max(1, int(request.args.get("page_size", 20))))
    offset = (page - 1) * page_size

    with db.slave_conn() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM data_quality_log WHERE task_id=:tid"),
            {"tid": task_id}
        ).scalar()
        rows = conn.execute(text("""
            SELECT id, task_id, file_id, file_path, batch_time,
                   total_rows, valid_rows, skipped_rows, error_rows,
                   null_rate, quality_score, processing_time_ms
            FROM data_quality_log
            WHERE task_id = :tid
            ORDER BY batch_time DESC
            LIMIT :limit OFFSET :offset
        """), {"tid": task_id, "limit": page_size, "offset": offset}
        ).mappings().all()

    reports = [_row_to_dict(r) for r in rows]
    return jsonify({
        "task_id": task_id,
        "reports": reports,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@bp.get("/<task_id>/latest")
@require_auth("viewer")
def get_latest_quality(task_id: str):
    """获取最新一条质量报告."""
    db = current_app.config.get("db")
    if not db:
        return jsonify({"error": "DB unavailable"}), 503

    with db.slave_conn() as conn:
        row = conn.execute(text("""
            SELECT id, task_id, file_id, file_path, batch_time,
                   total_rows, valid_rows, skipped_rows, error_rows,
                   null_rate, quality_score, processing_time_ms
            FROM data_quality_log
            WHERE task_id = :tid
            ORDER BY batch_time DESC
            LIMIT 1
        """), {"tid": task_id}).mappings().first()

    if not row:
        return jsonify({"task_id": task_id, "report": None})
    return jsonify({"task_id": task_id, "report": _row_to_dict(row)})


@bp.get("/<task_id>/trend")
@require_auth("viewer")
def get_quality_trend(task_id: str):
    """近 N 天每日平均质量评分趋势."""
    days = min(90, max(1, int(request.args.get("days", 30))))
    db = current_app.config.get("db")
    if not db:
        return jsonify({"task_id": task_id, "trend": []})

    with db.slave_conn() as conn:
        rows = conn.execute(text("""
            SELECT
                DATE(batch_time)                AS day,
                COUNT(*)                        AS batch_count,
                ROUND(AVG(quality_score), 2)    AS avg_score,
                ROUND(MIN(quality_score), 2)    AS min_score,
                SUM(total_rows)                 AS total_rows,
                SUM(error_rows)                 AS error_rows
            FROM data_quality_log
            WHERE task_id = :tid
              AND batch_time >= DATE_SUB(NOW(), INTERVAL :days DAY)
            GROUP BY DATE(batch_time)
            ORDER BY day ASC
        """), {"tid": task_id, "days": days}).mappings().all()

    trend = [{
        "day": str(r["day"]),
        "batch_count": r["batch_count"],
        "avg_score": float(r["avg_score"] or 0),
        "min_score": float(r["min_score"] or 0),
        "total_rows": r["total_rows"],
        "error_rows": r["error_rows"],
    } for r in rows]

    return jsonify({"task_id": task_id, "days": days, "trend": trend})


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "file_id": row["file_id"],
        "file_path": row["file_path"],
        "batch_time": str(row["batch_time"]) if row["batch_time"] else None,
        "total_rows": row["total_rows"],
        "valid_rows": row["valid_rows"],
        "skipped_rows": row["skipped_rows"] or 0,
        "error_rows": row["error_rows"],
        "null_rate": float(row["null_rate"] or 0),
        "quality_score": float(row["quality_score"] or 0),
        "processing_time_ms": row["processing_time_ms"],
    }
