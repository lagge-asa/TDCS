"""
文件处理状态 API

GET  /api/v1/files/              查询文件列表（分页、过滤）
GET  /api/v1/files/<id>          单文件详情（含 error_message）
POST /api/v1/files/<id>/retry    手动重试
GET  /api/v1/files/summary       各状态汇总统计（用于仪表盘）
"""

from flask import Blueprint, request, current_app
from sqlalchemy import text

from ..auth import require_auth
from ..response import ok, error, get_pagination, paginated

bp = Blueprint("files", __name__)


def _file_row_to_dict(r, full=False) -> dict:
    d = {
        "id": r["id"],
        "task_id": r["task_id"],
        "file_name": r["file_name"],
        "file_path": r["file_path"] if full else None,
        "file_size": r["file_size"],
        "status": r["status"],
        "row_count": r["row_count"],
        "valid_row_count": r["valid_row_count"],
        "retry_count": r["retry_count"],
        "error_type": r["error_type"],
        "claimed_by": r.get("claimed_by"),
        "claim_expires_at": str(r.get("claim_expires_at")) if r.get("claim_expires_at") else None,
        "processing_time_ms": r["processing_time_ms"],
        "created_at": str(r["created_at"]) if r["created_at"] else None,
        "processed_at": str(r["processed_at"]) if r.get("processed_at") else None,
    }
    if full:
        d["error_message"] = r["error_message"]
        d["archive_path"] = r.get("archive_path")
        d["instance_id"] = r.get("instance_id")
        d["file_hash"] = r.get("file_hash")
    return {k: v for k, v in d.items() if v is not None or full}


@bp.get("/")
@require_auth("viewer")
def list_files():
    db = current_app.config.get("db")
    if not db:
        return ok({"files": [], "total": 0})

    status = request.args.get("status")
    task_id = request.args.get("task_id")
    page, page_size = get_pagination()
    offset = (page - 1) * page_size

    conditions = []
    params = {"limit": page_size, "offset": offset}
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if task_id:
        conditions.append("task_id = :task_id")
        params["task_id"] = task_id

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with db.slave_conn() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM processed_files {where}"), params
        ).scalar()
        rows = conn.execute(text(f"""
            SELECT id, task_id, file_name, file_path, file_size, status,
                   row_count, valid_row_count, retry_count, error_type,
                   claimed_by, claim_expires_at, archive_path,
                   processing_time_ms, created_at, processed_at
            FROM processed_files {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return paginated(
        [_file_row_to_dict(r) for r in rows],
        page, page_size, total,
    )


@bp.get("/summary")
@require_auth("viewer")
def files_summary():
    """各状态数量汇总，用于仪表盘 KPI."""
    db = current_app.config.get("db")
    if not db:
        return ok({})

    with db.slave_conn() as conn:
        rows = conn.execute(text("""
            SELECT
                status,
                COUNT(*)        AS cnt,
                SUM(row_count)  AS row_sum
            FROM processed_files
            GROUP BY status
        """)).mappings().all()
        # 总行数
        total_rows = conn.execute(
            text("SELECT SUM(row_count) FROM processed_files WHERE status='SUCCESS'")
        ).scalar() or 0

    summary = {r["status"]: {"count": int(r["cnt"]), "rows": int(r["row_sum"] or 0)} for r in rows}
    summary["_total_success_rows"] = int(total_rows)
    return ok(summary)


@bp.get("/<int:file_id>")
@require_auth("viewer")
def get_file(file_id: int):
    """单文件完整详情，含 error_message."""
    db = current_app.config.get("db")
    if not db:
        return error("DB_UNAVAILABLE", "DB unavailable", status=503)

    with db.slave_conn() as conn:
        row = conn.execute(text("""
            SELECT id, task_id, file_name, file_path, file_size, file_hash,
                   status, row_count, valid_row_count, retry_count,
                   error_type, error_message, claimed_by, claim_expires_at,
                   processing_time_ms, archive_path, instance_id,
                   created_at, processed_at
            FROM processed_files
            WHERE id = :id
        """), {"id": file_id}).mappings().first()

    if not row:
        return error("FILE_NOT_FOUND", "文件记录不存在", status=404)
    return ok(_file_row_to_dict(row, full=True))


@bp.post("/<int:file_id>/retry")
@require_auth("operator")
def retry_file(file_id: int):
    db = current_app.config.get("db")
    if not db:
        return error("DB_UNAVAILABLE", "DB unavailable", status=503)

    with db.master_conn() as conn:
        result = conn.execute(text("""
            UPDATE processed_files
            SET status='PENDING', retry_count=0,
                error_type=NULL, error_message=NULL,
                claim_expires_at=NULL, claimed_by=NULL
            WHERE id=:id AND status='FAILED'
        """), {"id": file_id})
        conn.commit()

    if result.rowcount == 0:
        with db.slave_conn() as conn:
            exists = conn.execute(text("SELECT 1 FROM processed_files WHERE id=:id"), {"id": file_id}).scalar()
        if exists:
            return error("FILE_NOT_RETRYABLE", "只有 FAILED 状态的文件可以重试", status=409)
        return error("FILE_NOT_FOUND", "文件记录不存在", status=404)
    return ok({"status": "queued", "file_id": file_id})
