"""
批量加载器 — Loader

使用 INSERT IGNORE 保证幂等性:
- 同一文件重复处理不会产生重复数据
- 依赖业务主键唯一索引 (由建表模板定义)
- executemany 批量写入, 减少网络往返
"""

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _escape_column(name: str) -> str:
    """转义列名中的反引号，防止 SQL 注入/语法错误."""
    return f"`{name.replace('`', '``')}`"


class Loader:
    def __init__(self, db):
        self.db = db

    def load_batch(self, table_name: str, rows: list) -> int:
        """批量写入一批行到指定表.

        使用 INSERT IGNORE 保证幂等性.
        返回实际写入行数.
        """
        if not rows:
            return 0

        columns, data = self._prepare_rows(rows)
        col_list = ", ".join(_escape_column(c) for c in columns)
        placeholders = ", ".join("%s" for _ in columns)
        sql = (
            f"INSERT IGNORE INTO `{table_name}` "
            f"({col_list}) VALUES ({placeholders})"
        )
        written = self._execute_batch(sql, data)
        logger.debug("Loaded %d/%d rows into %s",
                     written, len(rows), table_name)
        return written

    def load_batch_upsert(self, table_name: str, rows: list,
                          update_cols: list) -> int:
        """ON DUPLICATE KEY UPDATE 版本 (用于需要更新的场景)."""
        if not rows:
            return 0

        columns, data = self._prepare_rows(rows)
        col_list = ", ".join(_escape_column(c) for c in columns)
        placeholders = ", ".join("%s" for _ in columns)
        updates = ", ".join(
            f"{_escape_column(c)} = VALUES({_escape_column(c)})"
            for c in update_cols
        )
        sql = (
            f"INSERT INTO `{table_name}` ({col_list}) "
            f"VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}"
        )
        self._execute_batch(sql, data)
        return len(data)

    # -- internal --

    @staticmethod
    def _prepare_rows(rows: list) -> tuple:
        """从行列表推断列名并转为元组列表.

        返回 (columns, data) — 列名列表和按列顺序排列的元组列表.
        行键不一致时：缺失键填 None，多余键忽略，不崩溃.
        """
        columns = list(rows[0].keys())
        data = [tuple(row.get(c) for c in columns) for row in rows]
        return columns, data

    def _execute_batch(self, sql: str, data: list) -> int:
        """通过 PyMySQL cursor 执行批量写入.

        使用位置占位符 %s 避免列名中的 : 和 . 被 SQLAlchemy 解析为绑定参数.
        返回 rowcount.
        """
        with self.db.master_conn() as conn:
            raw = conn.connection.dbapi_connection
            with raw.cursor() as cur:
                cur.executemany(sql, data)
                written = cur.rowcount
            raw.commit()
        return written
