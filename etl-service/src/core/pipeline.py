"""
流式 ETL Pipeline

逐 batch Extract -> Transform -> Load, 全程不积累全量数据.
PipelineResult.quality_report 直接引用 QualityReport 对象.

优化:
- load_batch 异常区分可重试（RetryableError）和不可重试（FatalError）
- ensure_table_exists 由 Pipeline 层维护进程级 set，避免每 batch 都加锁
- elapsed_ms 仅在正常完成时包含完整耗时
"""

import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from itertools import zip_longest
from typing import Optional

from .exceptions import RetryableError, FatalError, SkipFileError

logger = logging.getLogger(__name__)

# MySQL 瞬时可重试错误码
_MYSQL_RETRYABLE_ERRCODE = frozenset({
    1040,   # Too many connections
    1213,   # Deadlock found
    2006,   # MySQL server has gone away
    2013,   # Lost connection
    2055,   # Lost connection during query
})


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
        # 进程级缓存：已确认存在的表名，避免每 batch 都获取 table_router 内部锁
        self._known_tables: set = set()

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
                # zip_longest 检测 transform 返回行数不足的情况
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

                result.valid_count += len(valid)
                result.error_count += len(batch) - len(valid)

                if not valid:
                    continue

                # Encrypt
                if self.encryption and self.encryption.enabled:
                    valid = self.encryption.encrypt_fields(
                        valid, task_config)

                # Route & Load
                grouped = self.table_router.group_by_table(valid, task_config)
                for table_name, rows in grouped.items():
                    # 进程级 set 命中则跳过锁，首次 miss 才委托 table_router
                    if table_name not in self._known_tables:
                        self.table_router.ensure_table_exists(
                            table_name, task_config)
                        self._known_tables.add(table_name)
                    self._load_with_retry(table_name, rows)

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

        # 质量报告（仅在有数据时计算）
        if self.quality_reporter and result.raw_count > 0:
            result.quality_report = self.quality_reporter.calculate(
                rows=None,
                error_rows=error_rows,
                total_override=result.raw_count,
            )

        return result

    def _load_with_retry(self, table_name: str, rows: list) -> None:
        """执行 load_batch，区分可重试错误和致命错误."""
        try:
            self.loader.load_batch(table_name, rows)
        except Exception as e:
            # 识别 MySQL 瞬时错误（连接断开、死锁）-> RetryableError
            err_str = str(e)
            errno = getattr(e, "orig", None)
            if errno is not None:
                errno = getattr(errno, "args", [None])[0]
            if (errno in _MYSQL_RETRYABLE_ERRCODE
                    or "gone away" in err_str.lower()
                    or "deadlock" in err_str.lower()
                    or "lost connection" in err_str.lower()):
                raise RetryableError(f"DB transient error on {table_name}: {e}")
            # 其他错误（schema 不匹配、数据截断等）-> FatalError
            raise FatalError(f"Load failed on {table_name}: {e}")
