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
    """月表生命周期管理：超期归档（ARCHIVED），已归档表允许 DROP。"""

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
