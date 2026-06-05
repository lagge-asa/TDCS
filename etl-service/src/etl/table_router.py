"""
月表路由 — TableRouter

按 partition_field 字段值路由到对应月表.
表名格式: {base_table}_{YYYYMM}
自动建表 + 注册 monthly_table_registry.
表名白名单校验防 SQL 注入.

优化:
- _create_table 模板缺失时抛 FatalError（不再静默 fallback）
- ensure_table_exists 改为 per-table 粒度的锁，并发建不同月表不互斥
- _resolve_table 解析失败升级为 error 日志
- _validate_table_name 增加长度（≤64）和 strip 检查
"""

import re
import logging
import threading
from datetime import datetime
from sqlalchemy import text

from ..core.exceptions import FatalError

logger = logging.getLogger(__name__)

TABLE_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*$')
_MAX_TABLE_NAME_LEN = 64  # MySQL 表名最大长度


class TableRouter:
    def __init__(self, db, cache=None):
        self.db = db
        self._cache = cache
        self._created: set = set()
        # per-table 粒度的锁字典，并发建不同表时不互斥
        self._table_locks: dict = {}
        self._locks_lock = threading.Lock()  # 保护 _table_locks 字典本身

    def group_by_table(self, rows: list, task_config) -> dict:
        """将 rows 按月份分组到对应表名.

        返回: {table_name: [rows]}
        partition_field 解析失败时降级到当月表（记录 error 级日志）。
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

        # per-table 粒度锁：建不同月表时并发不互斥
        lock = self._get_table_lock(table_name)
        with lock:
            if table_name in self._created:  # double-check
                return
            with self.db.master_conn() as conn:
                # CREATE TABLE IF NOT EXISTS 本身幂等
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

    def _get_table_lock(self, table_name: str) -> threading.Lock:
        """按表名获取（或创建）专属锁."""
        with self._locks_lock:
            if table_name not in self._table_locks:
                self._table_locks[table_name] = threading.Lock()
            return self._table_locks[table_name]

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
                # 升级为 error 级别，数据静默写入错误分区是严重问题
                logger.error(
                    "Failed to parse partition_field '%s'='%s' "
                    "(format='%s'), falling back to current month. "
                    "Data may land in wrong partition!",
                    field, row.get(field), fmt)

        return f"{task_config.base_table}_{suffix}"

    def _create_table(self, conn, table_name: str, task_config) -> None:
        """按模板 SQL 创建月表.

        模板文件不存在时抛 FatalError（不再静默 fallback），
        防止业务字段全丢的数据静默丢失问题。
        """
        template_path = task_config.create_table_template
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                sql = f.read()
        except FileNotFoundError:
            raise FatalError(
                f"建表模板文件不存在: {template_path}。"
                f"请在任务配置中正确设置 create_table_template。"
                f"目标表: {table_name}")
        except OSError as e:
            raise FatalError(
                f"读取建表模板失败: {template_path}: {e}")

        # 替换模板中的表名占位符
        sql = sql.replace("{{TABLE_NAME}}", table_name)
        sql = sql.replace("{TABLE_NAME}", table_name)
        conn.execute(text(sql))

    @staticmethod
    def _validate_table_name(name: str) -> None:
        """白名单校验表名, 防止 SQL 注入.

        规则: 纯小写字母/数字/下划线，首字符为字母，长度 ≤ 64。
        """
        stripped = name.strip()
        if stripped != name:
            raise ValueError(
                f"Invalid table name '{name}': "
                "contains leading/trailing whitespace")
        if len(name) > _MAX_TABLE_NAME_LEN:
            raise ValueError(
                f"Invalid table name '{name}': "
                f"exceeds MySQL max length {_MAX_TABLE_NAME_LEN}")
        if not TABLE_NAME_RE.fullmatch(name):
            raise ValueError(
                f"Invalid table name '{name}': "
                "must match ^[a-z][a-z0-9_]*$ "
                "(lowercase letters, digits, underscores; start with letter)")
