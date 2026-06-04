"""
月表路由 — TableRouter

按 partition_field 字段值路由到对应月表.
表名格式: {base_table}_{YYYYMM}
自动建表 + 注册 monthly_table_registry.
表名白名单校验防 SQL 注入.
"""

import re
import logging
import threading
from datetime import datetime
from sqlalchemy import text

logger = logging.getLogger(__name__)

TABLE_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*$')


class TableRouter:
    def __init__(self, db, cache=None):
        self.db = db
        self._cache = cache
        self._created: set = set()
        self._create_lock = threading.Lock()  # 防止并发建表竞态

    def group_by_table(self, rows: list, task_config) -> dict:
        """将 rows 按月份分组到对应表名.

        返回: {table_name: [rows]}
        partition_field 解析失败时降级到当月表.
        """
        groups: dict = {}
        for row in rows:
            table_name = self._resolve_table(row, task_config)
            groups.setdefault(table_name, []).append(row)
        return groups

    def ensure_table_exists(self, table_name: str, task_config) -> None:
        """确保月表存在, 不存在则按模板创建并注册."""
        if table_name in self._created:
            return
        if self._cache and self._cache.get(f"table:{table_name}"):
            self._created.add(table_name)
            return

        self._validate_table_name(table_name)

        # 进程内锁：防止多 Worker 并发对同一表做"检查→建表"竞态
        with self._create_lock:
            if table_name in self._created:  # double-check
                return
            with self.db.master_conn() as conn:
                # CREATE TABLE IF NOT EXISTS 本身幂等，省去 information_schema 查询
                self._create_table(conn, table_name, task_config)

                year_month = table_name.rsplit("_", 1)[-1]
                year_month_fmt = f"{year_month[:4]}-{year_month[4:]}"
                conn.execute(text("""
                    INSERT IGNORE INTO monthly_table_registry
                        (task_id, table_name, `year_month`)
                    VALUES (:tid, :tn, :ym)
                """), dict(tid=task_config.task_id,
                           tn=table_name, ym=year_month_fmt))
                conn.commit()

            self._created.add(table_name)
            if self._cache:
                self._cache.set(f"table:{table_name}", True)

    # -- internal --

    def _resolve_table(self, row: dict, task_config) -> str:
        """解析行数据中的分区字段, 返回目标表名."""
        suffix = datetime.now().strftime("%Y%m")  # 默认当月
        field = task_config.partition_field
        fmt = task_config.partition_field_format

        if field and field in row and row[field]:
            try:
                dt = datetime.strptime(str(row[field]), fmt)
                suffix = dt.strftime("%Y%m")
            except (ValueError, TypeError):
                logger.warning(
                    "Failed to parse partition_field '%s'='%s', "
                    "falling back to current month",
                    field, row.get(field))

        return f"{task_config.base_table}_{suffix}"

    def _create_table(self, conn, table_name: str, task_config) -> None:
        """按模板 SQL 创建月表."""
        template_path = task_config.create_table_template
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                sql = f.read()
            # 替换模板中的表名占位符
            sql = sql.replace("{{TABLE_NAME}}", table_name)
            sql = sql.replace("{TABLE_NAME}", table_name)
            conn.execute(text(sql))
        except FileNotFoundError:
            # 模板不存在时使用通用建表语句
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))

    @staticmethod
    def _validate_table_name(name: str) -> None:
        """白名单校验表名, 防止 SQL 注入."""
        if not TABLE_NAME_RE.fullmatch(name):
            raise ValueError(
                f"Invalid table name '{name}': "
                "must match ^[a-z][a-z0-9_]*$")
