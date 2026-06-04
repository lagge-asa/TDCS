"""
文件处理器 — FileProcessor

将 bootstrap() 中的 process_fn 闭包提取为独立类，便于单元测试。
"""

import logging

logger = logging.getLogger(__name__)


class FileProcessor:
    def __init__(self, config_manager, state_tracker, pipeline_factory,
                 quality_reporter, file_archiver):
        self._cm = config_manager
        self._st = state_tracker
        self._make_pipeline = pipeline_factory
        self._qr = quality_reporter
        self._archiver = file_archiver

    def __call__(self, task_id, file_path, file_mtime,
                 file_size, file_hash, breaker):
        from ..utils.trace import new_trace
        from ..core.pipeline import PipelineStatus
        new_trace(task_id)
        task_cfg = self._cm.get_task(task_id)
        if not task_cfg:
            return
        if not self._st.try_claim(task_id, file_path,
                                   file_mtime, file_size, file_hash):
            return
        self._st.mark_processing(task_id, file_path, file_mtime)
        pipeline = self._make_pipeline(task_id)
        try:
            result = pipeline.execute(file_path, task_cfg)
        except Exception as e:
            self._st.mark_failed(task_id, file_path, file_mtime,
                                  "UnhandledError", str(e))
            breaker.record_failure()
            return

        if result.status == PipelineStatus.SUCCESS:
            file_id = self._st.mark_success(
                task_id, file_path, file_mtime,
                result.raw_count, result.valid_count, result.elapsed_ms)
            if result.quality_report:
                try:
                    self._qr.save(task_id, file_id, file_path,
                                  result.quality_report, result.elapsed_ms)
                except Exception as e:
                    logger.warning("Quality report save failed: %s", e)
            archive_path = self._archiver.archive_after_success(
                file_path, task_cfg)
            if archive_path:
                self._st.mark_archived(task_id, file_path,
                                        file_mtime, archive_path)
            breaker.record_success()
        elif result.status == PipelineStatus.SKIPPED:
            self._st.mark_skipped(task_id, file_path, file_mtime,
                                   str(result.error))
        elif result.status == PipelineStatus.RETRY:
            # 可重试错误：标记失败但不计入熔断器，
            # 由 state_tracker 的 retry_count + claim_expires 机制驱动重试
            self._st.mark_failed(task_id, file_path, file_mtime,
                                  type(result.error).__name__,
                                  str(result.error))
            logger.warning("Retryable error for %s: %s",
                           file_path, result.error)
        else:
            # FAILED: 不可重试的致命错误，计入熔断器
            self._st.mark_failed(task_id, file_path, file_mtime,
                                  type(result.error).__name__,
                                  str(result.error))
            breaker.record_failure()
