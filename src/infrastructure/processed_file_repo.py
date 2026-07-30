"""
processed_files 表 Repository

将 processed_files 表的全部 DML 内聚到单一模块。
StateTracker 通过此 Repository 访问数据库，不再直接写 SQL。
"""

import os
from datetime import datetime, timezone, timedelta
from sqlalchemy import text


DEFAULT_CLAIM_TIMEOUT_SECONDS = 600  # 10 分钟


class ProcessedFileRepository:
    """processed_files 表的 DML 封装."""

    def __init__(self, db, instance_id: str,
                 claim_timeout: int = DEFAULT_CLAIM_TIMEOUT_SECONDS):
        self._db = db
        self._instance_id = instance_id
        self._claim_timeout = claim_timeout

    def try_claim(self, task_id: str, file_path: str,
                  file_mtime: int, file_size: int, file_hash: str,
                  max_retries: int = 3) -> bool:
        """原子认领文件。rowcount 1=INSERT 2=UPDATE 0=跳过."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self._claim_timeout)
        file_name = os.path.basename(file_path)

        with self._db.master_conn() as conn:
            result = conn.execute(text("""
                INSERT INTO processed_files
                    (task_id, file_path, file_name, file_mtime, file_size,
                     file_hash, status, claimed_by, claimed_at,
                     claim_expires_at, instance_id)
                VALUES (:tid, :fp, :fn, :mt, :fs, :fh,
                        'CLAIMED', :iid, :now, :exp, :iid)
                ON DUPLICATE KEY UPDATE
                    status = IF(
                        (status = 'FAILED' AND retry_count < :max_retries)
                        OR (status IN ('CLAIMED','PROCESSING')
                            AND claim_expires_at < :now),
                        'CLAIMED', status),
                    claimed_by = IF(
                        (status = 'FAILED' AND retry_count < :max_retries)
                        OR (status IN ('CLAIMED','PROCESSING')
                            AND claim_expires_at < :now),
                        :iid, claimed_by),
                    claimed_at = IF(
                        (status = 'FAILED' AND retry_count < :max_retries)
                        OR (status IN ('CLAIMED','PROCESSING')
                            AND claim_expires_at < :now),
                        :now, claimed_at),
                    claim_expires_at = IF(
                        (status = 'FAILED' AND retry_count < :max_retries)
                        OR (status IN ('CLAIMED','PROCESSING')
                            AND claim_expires_at < :now),
                        :exp, claim_expires_at)
            """), dict(tid=task_id, fp=file_path, fn=file_name,
                       mt=file_mtime, fs=file_size, fh=file_hash,
                       iid=self._instance_id, now=now, exp=expires,
                       max_retries=max_retries))
            conn.commit()
        return result.rowcount in (1, 2)

    def mark_processing(self, task_id: str, file_path: str,
                        file_mtime: int) -> bool:
        with self._db.master_conn() as conn:
            result = conn.execute(text("""
                UPDATE processed_files SET status = 'PROCESSING'
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt AND claimed_by = :iid
                  AND status = 'CLAIMED'
            """), dict(tid=task_id, fp=file_path,
                       mt=file_mtime, iid=self._instance_id))
            conn.commit()
        return result.rowcount > 0

    def mark_success(self, task_id: str, file_path: str, file_mtime: int,
                     row_count: int, valid_count: int,
                     elapsed_ms: int) -> int:
        with self._db.master_conn() as conn:
            conn.execute(text("""
                UPDATE processed_files
                SET status = 'SUCCESS', processed_at = NOW(),
                    row_count = :rc, valid_row_count = :vc,
                    processing_time_ms = :ms,
                    id = LAST_INSERT_ID(id)
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt
            """), dict(tid=task_id, fp=file_path, mt=file_mtime,
                       rc=row_count, vc=valid_count, ms=elapsed_ms))
            row = conn.execute(text("SELECT LAST_INSERT_ID() AS lid")).fetchone()
            conn.commit()
        return row.lid if row and row.lid else 0

    def mark_failed(self, task_id: str, file_path: str, file_mtime: int,
                    error_type: str, error_msg: str) -> int:
        with self._db.master_conn() as conn:
            result = conn.execute(text("""
                UPDATE processed_files
                SET status = 'FAILED',
                    error_type = :et, error_message = :em,
                    retry_count = retry_count + 1,
                    claim_expires_at = NULL
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt
            """), dict(tid=task_id, fp=file_path, mt=file_mtime,
                       et=error_type, em=error_msg))
            if result.rowcount > 0:
                row = conn.execute(text("""
                    SELECT retry_count FROM processed_files
                    WHERE task_id = :tid AND file_path = :fp
                      AND file_mtime = :mt LIMIT 1
                """), dict(tid=task_id, fp=file_path, mt=file_mtime)).fetchone()
                new_retry = row.retry_count if row else 1
            else:
                new_retry = 1
            conn.commit()
        return new_retry

    def mark_skipped(self, task_id: str, file_path: str,
                     file_mtime: int, reason: str) -> None:
        with self._db.master_conn() as conn:
            conn.execute(text("""
                UPDATE processed_files
                SET status = 'SKIPPED', error_message = :reason
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt
            """), dict(tid=task_id, fp=file_path,
                       mt=file_mtime, reason=reason))
            conn.commit()

    def mark_archived(self, task_id: str, file_path: str,
                      file_mtime: int, archive_path: str) -> None:
        with self._db.master_conn() as conn:
            conn.execute(text("""
                UPDATE processed_files
                SET archive_path = :ap
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt AND status = 'SUCCESS'
            """), dict(tid=task_id, fp=file_path,
                       mt=file_mtime, ap=archive_path))
            conn.commit()

    def get_status(self, task_id: str, file_path: str,
                   file_mtime: int) -> str | None:
        with self._db.read_conn() as conn:
            row = conn.execute(text("""
                SELECT status FROM processed_files
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt
            """), dict(tid=task_id, fp=file_path, mt=file_mtime)).fetchone()
        return row.status if row else None

    def get_retry_count(self, task_id: str, file_path: str,
                        file_mtime: int = None) -> int:
        with self._db.read_conn() as conn:
            if file_mtime is not None:
                row = conn.execute(text("""
                    SELECT retry_count FROM processed_files
                    WHERE task_id = :tid AND file_path = :fp
                      AND file_mtime = :mt LIMIT 1
                """), dict(tid=task_id, fp=file_path, mt=file_mtime)).fetchone()
            else:
                row = conn.execute(text("""
                    SELECT retry_count FROM processed_files
                    WHERE task_id = :tid AND file_path = :fp
                    ORDER BY file_mtime DESC LIMIT 1
                """), dict(tid=task_id, fp=file_path)).fetchone()
        return row.retry_count if row else 0
