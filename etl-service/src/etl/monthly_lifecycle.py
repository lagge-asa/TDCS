"""
月表生命周期管理 — MonthlyTableLifecycle

由 TaskManager 在每月 1 日调用.
归档: 超过 retention_months 的表标记 ARCHIVED (不删数据)
DROP: 已 ARCHIVED 的表才允许 DROP
"""

import logging
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from sqlalchemy import text

from .table_router import TABLE_NAME_RE

logger = logging.getLogger(__name__)


class MonthlyTableLifecycle:
    def __init__(self, db):
        self._db = db

    def run(self, task_config) -> None:
        """执行月表生命周期检查."""
        if task_config.retention_months <= 0:
            return
        cutoff = date.today() - relativedelta(
            months=task_config.retention_months)
        cutoff_str = cutoff.strftime("%Y-%m")

        with self._db.master_conn() as conn:
            # 标记超期表为 ARCHIVED (只改状态, 不删数据)
            conn.execute(text("""
                UPDATE monthly_table_registry
                SET lifecycle_status = 'ARCHIVED',
                    archived_at = NOW()
                WHERE task_id = :tid
                  AND year_month <= :cutoff
                  AND lifecycle_status = 'ACTIVE'
            """), dict(tid=task_config.task_id, cutoff=cutoff_str))
            conn.commit()
            logger.info("Archived tables older than %s for task %s",
                        cutoff_str, task_config.task_id)

    def drop_archived(self, task_config) -> None:
        """DROP 已 ARCHIVED 的表 (需要显式调用).

        逐表独立提交：先更新 registry 状态再 DROP，
        确保中途失败时 registry 与实际表状态一致。
        """
        with self._db.master_conn() as conn:
            rows = conn.execute(text("""
                SELECT table_name FROM monthly_table_registry
                WHERE task_id = :tid
                  AND lifecycle_status = 'ARCHIVED'
            """), {"tid": task_config.task_id}).fetchall()

        for row in rows:
            table_name = row.table_name
            if not TABLE_NAME_RE.fullmatch(table_name):
                logger.error("Skipping DROP: invalid table name '%s'", table_name)
                continue
            try:
                with self._db.master_conn() as conn:
                    # 先标记 DROPPED，再 DROP TABLE：即使 DROP 失败，下次也不会重试
                    conn.execute(text("""
                        UPDATE monthly_table_registry
                        SET lifecycle_status = 'DROPPED', dropped_at = NOW()
                        WHERE task_id = :tid AND table_name = :tn
                    """), dict(tid=task_config.task_id, tn=table_name))
                    conn.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))
                    conn.commit()
                logger.info("Dropped table: %s", table_name)
            except Exception as e:
                logger.error("Failed to drop table %s: %s", table_name, e)
