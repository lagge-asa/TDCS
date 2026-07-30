"""
原子状态机 — StateTracker

核心设计:
- try_claim 使用 INSERT ... ON DUPLICATE KEY UPDATE 单条 SQL 原子完成
- 彻底消除"先查后写"竞态
- mark_failed 返回最新 retry_count，避免调用方二次查询
- mark_success 用 LAST_INSERT_ID(id) trick 取主键，避免二次 SELECT

SQL 实现委托给 ProcessedFileRepository。
"""

from ..infrastructure.processed_file_repo import ProcessedFileRepository


class StateTracker:
    """原子状态机：基于 ProcessedFileRepository 的文件处理状态跟踪."""

    def __init__(self, db, instance_id: str,
                 claim_timeout: int = None):
        kwargs = {}
        if claim_timeout is not None:
            kwargs["claim_timeout"] = claim_timeout
        self._repo = ProcessedFileRepository(db, instance_id, **kwargs)
        self.instance_id = instance_id

    def try_claim(self, ref: "FileRef", max_retries: int = 3) -> bool:
        return self._repo.try_claim(
            ref.task_id, ref.file_path, ref.file_mtime,
            ref.file_size, ref.file_hash, max_retries)

    def try_claim_legacy(self, task_id: str, file_path: str,
                         file_mtime: int, file_size: int, file_hash: str,
                         max_retries: int = 3) -> bool:
        from .file_ref import FileRef
        return self.try_claim(
            FileRef(task_id, file_path, file_mtime, file_size, file_hash),
            max_retries)

    def mark_processing(self, task_id: str, file_path: str,
                        file_mtime: int) -> bool:
        return self._repo.mark_processing(task_id, file_path, file_mtime)

    def mark_success(self, task_id: str, file_path: str, file_mtime: int,
                     row_count: int, valid_count: int,
                     elapsed_ms: int) -> int:
        return self._repo.mark_success(
            task_id, file_path, file_mtime,
            row_count, valid_count, elapsed_ms)

    def mark_failed(self, task_id: str, file_path: str, file_mtime: int,
                    error_type: str, error_msg: str) -> int:
        return self._repo.mark_failed(
            task_id, file_path, file_mtime, error_type, error_msg)

    def mark_skipped(self, task_id: str, file_path: str,
                     file_mtime: int, reason: str) -> None:
        self._repo.mark_skipped(task_id, file_path, file_mtime, reason)

    def mark_archived(self, task_id: str, file_path: str,
                      file_mtime: int, archive_path: str) -> None:
        self._repo.mark_archived(task_id, file_path, file_mtime, archive_path)

    def get_status(self, task_id: str, file_path: str,
                   file_mtime: int) -> str | None:
        return self._repo.get_status(task_id, file_path, file_mtime)

    def get_retry_count(self, task_id: str, file_path: str,
                        file_mtime: int = None) -> int:
        return self._repo.get_retry_count(task_id, file_path, file_mtime)
