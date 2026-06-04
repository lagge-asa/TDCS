"""文件处理状态 API"""
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import text
from ..auth import require_auth

bp = Blueprint("files", __name__)


@bp.get("/")
@require_auth("viewer")
def list_files():
    db = current_app.config.get("db")
    if not db:
        return jsonify({"files": [], "total": 0})
    status = request.args.get("status")
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(200, max(1, int(request.args.get("page_size", 50))))
    offset = (page - 1) * page_size
    where = "WHERE status = :status" if status else ""
    params = {"limit": page_size, "offset": offset}
    if status:
        params["status"] = status
    with db.slave_conn() as conn:
        total = conn.execute(text(
            f"SELECT COUNT(*) FROM processed_files {where}"), params).scalar()
        rows = conn.execute(text(
            f"SELECT id, task_id, file_name, status, row_count, valid_row_count, "
            f"retry_count, error_type, processing_time_ms, created_at "
            f"FROM processed_files {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            params).mappings().all()
    files = [{"id": r["id"], "task_id": r["task_id"], "file_name": r["file_name"],
              "status": r["status"], "row_count": r["row_count"],
              "valid_row_count": r["valid_row_count"], "retry_count": r["retry_count"],
              "error_type": r["error_type"], "processing_time_ms": r["processing_time_ms"],
              "created_at": str(r["created_at"]) if r["created_at"] else None} for r in rows]
    return jsonify({"files": files, "total": total, "page": page, "page_size": page_size})


@bp.post("/<int:file_id>/retry")
@require_auth("operator")
def retry_file(file_id):
    db = current_app.config.get("db")
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    with db.master_conn() as conn:
        result = conn.execute(text(
            "UPDATE processed_files SET status='PENDING', retry_count=0, "
            "error_type=NULL, error_message=NULL WHERE id=:id"), {"id": file_id})
        conn.commit()
    if result.rowcount == 0:
        return jsonify({"error": "File not found"}), 404
    return jsonify({"status": "queued"})
