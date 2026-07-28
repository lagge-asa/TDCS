"""
统一分页参数解析

用法:
    from .pagination import get_pagination

    page, page_size = get_pagination()
    # page 默认 1, page_size 默认 50, 最大 200
"""

from flask import request


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
