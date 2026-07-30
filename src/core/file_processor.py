"""
文件处理器 — FileProcessor

将 bootstrap() 中的 process_fn 闭包提取为独立类，便于单元测试。

修复:
- RETRY 分支用 mark_failed() 返回的 retry_count，无需二次 DB 查询
- FAILED 分支也调用 move_to_dead_letter（致命错误同样需要归档）
- quality_report.score 通过 QualityReport.score 属性访问（quality_score 别名）
- mark_processing 失败时提前返回，避免后续处理
"""

import logging

logger = logging.getLogger(__name__)


class FileProcessor:
    """文件处理器 — 单接口：接收 FileRef → 执行完整 ETL 生命周期."""
    def __init__(self, config_manager, state_tracker, pipeline_factory,
                 quality_reporter, file_archiver,
                 alerter=None, task_manager=None):
        self._config_manager = config_manager
        self._state_tracker = state_tracker
        self._make_pipeline = pipeline_factory
        self._quality_reporter = quality_reporter
        self._archiver = file_archiver
        self._alerter = alerter
        self._task_manager = task_manager

    def __call__(self, ref: "FileRef", breaker) -> None:
        from ..utils.trace import new_trace
        from ..core.pipeline import PipelineStatus
        new_trace(ref.task_id)
        task_cfg = self._config_manager.get_task(ref.task_id)
        if not task_cfg:
            return

        if not self._state_tracker.try_claim(ref,
                                   max_retries=getattr(task_cfg, 'max_retries', 3)):
            return

        if not self._state_tracker.mark_processing(ref.task_id, ref.file_path, ref.file_mtime):
            logger.warning("mark_processing failed (race), skipping: %s", ref.file_path)
            return

        pipeline = self._make_pipeline(ref.task_id)
        try:
            result = pipeline.execute(ref.file_path, task_cfg)
        except Exception as e:
            self._state_tracker.mark_failed(ref.task_id, ref.file_path, ref.file_mtime,
                                  "UnhandledError", str(e))
            breaker.record_failure()
            return

        if result.status == PipelineStatus.SUCCESS:
            file_id = self._state_tracker.mark_success(
                ref.task_id, ref.file_path, ref.file_mtime,
                result.raw_count, result.valid_count, result.elapsed_ms)
            if result.quality_report:
                try:
                    self._quality_reporter.save(ref.task_id, file_id, ref.file_path,
                                  result.quality_report, result.elapsed_ms)
                    if self._alerter:
                        self._alerter.check_quality_alert(
                            ref.task_id, result.quality_report.score)
                except Exception as e:
                    logger.warning("Quality report save failed: %s", e)
            archive_path = self._archiver.archive_after_success(
                ref.file_path, task_cfg)
            if archive_path:
                self._state_tracker.mark_archived(ref.task_id, ref.file_path,
                                        ref.file_mtime, archive_path)
            breaker.record_success()

        elif result.status == PipelineStatus.SKIPPED:
            self._state_tracker.mark_skipped(ref.task_id, ref.file_path, ref.file_mtime,
                                   str(result.error))

        elif result.status == PipelineStatus.RETRY:
            max_retries = getattr(task_cfg, 'max_retries', 3)
            retry_count = self._state_tracker.mark_failed(
                ref.task_id, ref.file_path, ref.file_mtime,
                type(result.error).__name__, str(result.error))

            if retry_count >= max_retries:
                if self._task_manager:
                    self._task_manager.move_to_dead_letter(ref.task_id, ref.file_path)
                if self._alerter:
                    self._alerter.notify_dead_letter(ref.task_id, ref.file_path)
                logger.error("Dead letter after %d retries: %s",
                             retry_count, ref.file_path)
            else:
                logger.warning("Retryable error (%d/%d) for %s: %s",
                               retry_count, max_retries,
                               ref.file_path, result.error)

        else:
            self._state_tracker.mark_failed(ref.task_id, ref.file_path, ref.file_mtime,
                                  type(result.error).__name__,
                                  str(result.error))
            breaker.record_failure()
            if self._task_manager:
                self._task_manager.move_to_dead_letter(ref.task_id, ref.file_path)
            if self._alerter:
                self._alerter.notify_pipeline_failure(
                    ref.task_id, ref.file_path, str(result.error))
