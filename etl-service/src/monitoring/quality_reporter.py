"""
数据质量评分 — QualityReporter

评分公式: score = max(0, 100 - error_rate * 60 - null_rate * 40)
  - 50% 错误率 -> score = 70
  - 50% 错误 + 10% null -> score = 66

QualityReport.score 是 quality_score 的别名属性，兼容下游访问。
save() 使用 INSERT ... ON DUPLICATE KEY UPDATE 保证幂等性。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
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

    @property
    def score(self) -> float:
        """quality_score 的别名，兼容下游 result.quality_report.score 访问."""
        return self.quality_score


class QualityReporter:
    def __init__(self, db):
        self.db = db

    def calculate(self, rows: Optional[List[dict]], error_rows: list,
                  required_fields: list = None,
                  total_override: int = None) -> QualityReport:
        """计算数据质量报告.

        rows=None 时跳过 null_rate 检测（流式 pipeline 不积累全量行）。
        error_details 记录各类问题的数量供前端展示。
        """
        total = total_override if total_override is not None else (
            len(rows) if rows else 0)
        errors = len(error_rows) if error_rows else 0
        valid = total - errors
        error_details: Dict = {}

        # null_rate: 必填字段中 null 值比例（仅在 rows 可用时计算）
        null_rate = 0.0
        if required_fields and rows and total > 0:
            null_count = 0
            field_nulls: Dict[str, int] = {}
            for row in rows:
                for f in required_fields:
                    if row.get(f) is None or row.get(f) == "":
                        null_count += 1
                        field_nulls[f] = field_nulls.get(f, 0) + 1
            null_rate = null_count / (total * len(required_fields))
            if field_nulls:
                error_details["null_fields"] = field_nulls
        elif required_fields and rows is None:
            # 流式模式无行数据，标记为未检测
            error_details["null_rate_skipped"] = "streaming mode, rows not accumulated"

        error_rate = errors / total if total > 0 else 0.0
        if errors > 0:
            error_details["transform_errors"] = errors

        # 精确评分公式
        score = max(0.0, 100.0 - error_rate * 60.0 - null_rate * 40.0)

        return QualityReport(
            total_rows=total,
            valid_rows=valid,
            error_rows=errors,
            null_rate=round(null_rate, 4),
            error_rate=round(error_rate, 4),
            quality_score=round(score, 2),
            error_details=error_details,
        )

    def save(self, task_id: str, file_id: int, file_path: str,
             report: QualityReport, elapsed_ms: int) -> None:
        """将质量报告写入 data_quality_log.

        - file_id <= 0 时跳过并告警（mark_success 未成功时返回 0）。
        - 使用 INSERT ... ON DUPLICATE KEY UPDATE 保证重跑幂等。
        """
        if not file_id or file_id <= 0:
            logger.warning(
                "Quality report skipped: invalid file_id=%s for %s",
                file_id, file_path)
            return

        try:
            with self.db.master_conn() as conn:
                conn.execute(text("""
                    INSERT INTO data_quality_log
                        (task_id, file_id, file_path, total_rows, valid_rows,
                         error_rows, null_rate, quality_score, processing_time_ms)
                    VALUES
                        (:tid, :fid, :fp, :tr, :vr, :er, :nr, :qs, :ms)
                    ON DUPLICATE KEY UPDATE
                        total_rows = VALUES(total_rows),
                        valid_rows = VALUES(valid_rows),
                        error_rows = VALUES(error_rows),
                        null_rate  = VALUES(null_rate),
                        quality_score = VALUES(quality_score),
                        processing_time_ms = VALUES(processing_time_ms)
                """), dict(
                    tid=task_id, fid=file_id, fp=file_path,
                    tr=report.total_rows, vr=report.valid_rows,
                    er=report.error_rows, nr=report.null_rate,
                    qs=report.quality_score, ms=elapsed_ms,
                ))
                conn.commit()
        except Exception as e:
            logger.error(
                "Failed to save quality report for file_id=%s: %s",
                file_id, e)
            raise
