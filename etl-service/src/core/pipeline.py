"""
流式 ETL Pipeline

逐 batch Extract -> Transform -> Load, 全程不积累全量数据.
PipelineResult.quality_report 直接引用 QualityReport 对象.
"""

import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from itertools import zip_longest
from typing import Optional

from .exceptions import RetryableError, FatalError, SkipFileError

logger = logging.getLogger(__name__)


class PipelineStatus(Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    RETRY = "RETRY"


@dataclass
class PipelineResult:
    status: PipelineStatus
    raw_count: int = 0
    valid_count: int = 0
    error_count: int = 0
    elapsed_ms: int = 0
    error: Optional[Exception] = None
    quality_report: Optional[object] = None  # QualityReport


class ETLPipeline:
    def __init__(self, extractor, sandbox, table_router,
                 loader, encryption=None, quality_reporter=None):
        self.extractor = extractor
        self.sandbox = sandbox
        self.table_router = table_router
        self.loader = loader
        self.encryption = encryption
        self.quality_reporter = quality_reporter

    def execute(self, file_path: str, task_config) -> PipelineResult:
        result = PipelineResult(status=PipelineStatus.SUCCESS)
        start = time.monotonic()
        error_rows = []

        try:
            for batch in self.extractor.stream(file_path, task_config):
                result.raw_count += len(batch)

                # Transform (子进程沙箱，无 transformer 时直接透传)
                if task_config.transformer_module:
                    transformed = self.sandbox.transform_batch(
                        batch,
                        task_config.transformer_module,
                        task_config.transformer_function,
                        timeout=task_config.sandbox_timeout,
                        memory_mb=task_config.sandbox_memory_mb,
                    )
                else:
                    transformed = batch
                # None 行视为过滤掉 (错误行)
                # 用 zip_longest 检测 transform 返回行数不足的情况
                _MISSING = object()  # 哨兵值：transform 未返回对应行
                valid = []
                for orig, out in zip_longest(batch, transformed,
                                             fillvalue=_MISSING):
                    if out is _MISSING:
                        # transform 返回行数少于输入，原始行计入错误
                        error_rows.append(orig)
                    elif out is not None:
                        valid.append(out)
                    else:
                        error_rows.append(orig)
                dropped = len(batch) - len(valid)
                result.valid_count += len(valid)
                result.error_count += dropped

                if not valid:
                    continue

                # Encrypt
                if self.encryption and self.encryption.enabled:
                    valid = self.encryption.encrypt_fields(
                        valid, task_config)

                # Route & Load
                grouped = self.table_router.group_by_table(
                    valid, task_config)
                for table_name, rows in grouped.items():
                    self.table_router.ensure_table_exists(
                        table_name, task_config)
                    self.loader.load_batch(table_name, rows)

        except SkipFileError as e:
            result.status = PipelineStatus.SKIPPED
            result.error = e
        except RetryableError as e:
            result.status = PipelineStatus.RETRY
            result.error = e
        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.error = e if isinstance(e, FatalError) else FatalError(str(e))

        result.elapsed_ms = int((time.monotonic() - start) * 1000)

        # 质量报告 (引用 QualityReport 对象, 非独立计算 score)
        if self.quality_reporter and result.raw_count > 0:
            result.quality_report = self.quality_reporter.calculate(
                rows=None,
                error_rows=error_rows,
                total_override=result.raw_count,
            )

        return result
