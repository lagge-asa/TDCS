"""
数据质量评分 — QualityReporter

评分公式: score = max(0, 100 - error_rate * 60 - null_rate * 40)
  - 50% 错误率 -> score = 70
  - 50% 错误 + 10% null -> score = 66
"""

import logging
from dataclasses import dataclass, field
from typing import Dict
from sqlalchemy import text

logger = logging.getLogger(__name__)


@dataclass
class QualityReport:
    total_rows: int
    valid_rows: int
    error_rows: int
    null_rate: float
    error_rate: float
    quality_score: float
    error_details: Dict = field(default_factory=dict)


class QualityReporter:
    def __init__(self, db):
        self.db = db

    def calculate(self, rows: list, error_rows: list,
                  required_fields: list = None,
                  total_override: int = None) -> QualityReport:
        """计算数据质量报告."""
        total = total_override if total_override is not None else (len(rows) if rows else 0)
        errors = len(error_rows) if error_rows else 0
        valid = total - errors

        # null_rate: 必填字段中 null 值比例
        null_rate = 0.0
        if required_fields and total > 0:
            null_count = sum(
                1 for row in rows
                for f in required_fields
                if row.get(f) is None or row.get(f) == ""
            )
            null_rate = null_count / (total * len(required_fields))

        error_rate = errors / total if total > 0 else 0.0

        # 精确评分公式
        score = max(0.0, 100.0 - error_rate * 60.0 - null_rate * 40.0)

        return QualityReport(
            total_rows=total,
            valid_rows=valid,
            error_rows=errors,
            null_rate=round(null_rate, 4),
            error_rate=round(error_rate, 4),
            quality_score=round(score, 2),
            error_details={},
        )

    def save(self, task_id: str, file_id: int, file_path: str,
             report: QualityReport, elapsed_ms: int) -> None:
        """将质量报告写入 data_quality_log."""
        with self.db.master_conn() as conn:
            conn.execute(text("""
                INSERT INTO data_quality_log
                    (task_id, file_id, file_path, total_rows, valid_rows,
                     error_rows, null_rate, quality_score, processing_time_ms)
                VALUES
                    (:tid, :fid, :fp, :tr, :vr, :er, :nr, :qs, :ms)
            """), dict(
                tid=task_id, fid=file_id, fp=file_path,
                tr=report.total_rows, vr=report.valid_rows,
                er=report.error_rows, nr=report.null_rate,
                qs=report.quality_score, ms=elapsed_ms,
            ))
            conn.commit()
