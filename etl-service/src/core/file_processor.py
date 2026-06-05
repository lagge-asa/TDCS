"""
文件处理器 — FileProcessor

将 bootstrap() 中的 process_fn 闭包提取为独立类，便于单元测试。
"""

import logging

logger = logging.getLogger(__name__)


class FileProcessor:
    def __init__(self, config_manager, state_tracker, pipeline_factory,
                 quality_reporter, file_archiver,
                 alerter=None, task_manager=None):
        self._cm = config_manager
        self._st = state_tracker
        self._make_pipeline = pipeline_factory
        self._qr = quality_reporter
        self._archiver = file_archiver
        self._alerter = alerter
        self._tm = task_manager  # 用于 move_to_dead_letter

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
                    # 质量评分告警检查
                    if self._alerter and hasattr(result.quality_report, 'score'):
                        self._alerter.check_quality_alert(
                            task_id, result.quality_report.score)
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
            # 可重试错误：检查是否已超过最大重试次数
            retry_count = self._st.get_retry_count(task_id, file_path)
            max_retries = task_cfg.max_retries if task_cfg else 3
            if retry_count >= max_retries:
                # 超过重试上限 -> 死信目录
                self._st.mark_failed(task_id, file_path, file_mtime,
                                      type(result.error).__name__,
                                      str(result.error))
                if self._tm:
                    self._tm.move_to_dead_letter(task_id, file_path)
                if self._alerter:
                    self._alerter.notify_dead_letter(task_id, file_path)
                logger.error("Dead letter after %d retries: %s",
                             retry_count, file_path)
            else:
                self._st.mark_failed(task_id, file_path, file_mtime,
                                      type(result.error).__name__,
                                      str(result.error))
                logger.warning("Retryable error (%d/%d) for %s: %s",
                               retry_count + 1, max_retries,
                               file_path, result.error)
        else:
            # FAILED: 不可重试的致命错误，计入熔断器，触发告警
            self._st.mark_failed(task_id, file_path, file_mtime,
                                  type(result.error).__name__,
                                  str(result.error))
            breaker.record_failure()
            if self._alerter:
                self._alerter.notify_pipeline_failure(
                    task_id, file_path, str(result.error))
