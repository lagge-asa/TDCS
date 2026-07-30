"""
API 统一响应信封 + 分页

用法:
    from .response import ok, error, paginated, get_pagination
"""

from flask import jsonify, request
from typing import Any

_DEFAULT_PAGE = 1
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


def get_pagination() -> tuple:
    """从请求参数中提取 page/page_size，返回 (page, page_size)."""
    try:
        page = max(1, int(request.args.get("page", _DEFAULT_PAGE)))
    except (ValueError, TypeError):
        page = _DEFAULT_PAGE
    try:
        page_size = int(request.args.get("page_size", _DEFAULT_PAGE_SIZE))
        page_size = max(1, min(page_size, _MAX_PAGE_SIZE))
    except (ValueError, TypeError):
        page_size = _DEFAULT_PAGE_SIZE
    return page, page_size


def ok(data: Any = None, meta: dict = None, status: int = 200):
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
