"""
API 统一响应信封

用法:
    from .response import ok, error, paginated

    return ok({"task_id": "t1", "name": "任务1"})
    return ok({"tasks": [...]}, meta={"count": 10})
    return paginated(items, page, page_size, total)
    return error("TASK_NOT_FOUND", "任务不存在", status=404)
"""

from flask import jsonify
from typing import Any, Optional


def ok(data: Any = None, meta: Optional[dict] = None, status: int = 200):
    """成功响应."""
    body: dict = {"success": True}
    if data is not None:
        body["data"] = data
    if meta:
        body["meta"] = meta
    return jsonify(body), status


def error(code: str, message: str, status: int = 400, details: Any = None):
    """错误响应."""
    body = {
        "success": False,
        "error": {"code": code, "message": message},
    }
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def paginated(items: list, page: int, page_size: int,
              total: int, status: int = 200):
    """分页响应."""
    return ok(
        data=items,
        meta={
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        },
        status=status,
    )
