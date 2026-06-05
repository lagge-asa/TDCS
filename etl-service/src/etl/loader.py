"""
批量加载器 — Loader

使用 INSERT IGNORE 保证幂等性:
- 同一文件重复处理不会产生重复数据
- 依赖业务主键唯一索引 (由建表模板定义)
- executemany 批量写入, 减少网络往返

优化:
- _execute_batch 按 CHUNK_SIZE 分片，避免超 max_allowed_packet
- _prepare_rows 取所有行键并集，缺失键填 None，不因首行字段不足而截断
- load_batch_upsert 返回实际 rowcount（与 load_batch 语义一致）
- load_batch 记录 ignored 行数差（写入前后 rowcount 对比）
"""

import logging

logger = logging.getLogger(__name__)

# 每次 executemany 最多发送的行数，防止超出 MySQL max_allowed_packet
_CHUNK_SIZE = 1000


def _escape_column(name: str) -> str:
    """转义列名中的反引号，防止 SQL 注入/语法错误."""
    return f"`{name.replace('`', '``')}`"


class Loader:
    def __init__(self, db):
        self.db = db

    def load_batch(self, table_name: str, rows: list) -> int:
        """批量写入一批行到指定表.

        使用 INSERT IGNORE 保证幂等性.
        返回实际写入行数（忽略重复键后的净增量）。
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
        ignored = len(rows) - written
        if ignored > 0:
            logger.debug(
                "Loaded %d/%d rows into %s (%d ignored/duplicate)",
                written, len(rows), table_name, ignored)
        else:
            logger.debug("Loaded %d rows into %s", written, table_name)
        return written

    def load_batch_upsert(self, table_name: str, rows: list,
                          update_cols: list) -> int:
        """ON DUPLICATE KEY UPDATE 版本 (用于需要更新的场景).

        返回实际 rowcount（INSERT=1，UPDATE=2，无变化=0，MySQL 累加）。
        """
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
        return self._execute_batch(sql, data)

    # -- internal --

    @staticmethod
    def _prepare_rows(rows: list) -> tuple:
        """从行列表推断列名并转为元组列表.

        取所有行键的并集（而非仅首行），保证字段不齐时不静默截断。
        缺失键填 None；多余键按并集顺序排列。
        返回 (columns, data)。
        """
        if not rows:
            return [], []
        # 取所有行键并集，保持首行字段顺序优先（稳定插入顺序）
        seen: dict = {}
        for row in rows:
            for k in row.keys():
                seen.setdefault(k, None)
        columns = list(seen.keys())
        data = [tuple(row.get(c) for c in columns) for row in rows]
        return columns, data

    def _execute_batch(self, sql: str, data: list) -> int:
        """通过 PyMySQL cursor 执行批量写入，按 _CHUNK_SIZE 分片.

        使用位置占位符 %s 避免列名中的 : 和 . 被 SQLAlchemy 解析为绑定参数。
        返回累计 rowcount。
        """
        if not data:
            return 0
        total_written = 0
        with self.db.master_conn() as conn:
            raw = conn.connection.dbapi_connection
            with raw.cursor() as cur:
                for i in range(0, len(data), _CHUNK_SIZE):
                    chunk = data[i: i + _CHUNK_SIZE]
                    cur.executemany(sql, chunk)
                    total_written += cur.rowcount
            raw.commit()
        return total_written
