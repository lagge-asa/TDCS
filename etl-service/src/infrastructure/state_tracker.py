"""
原子状态机 — StateTracker

核心设计:
- try_claim 使用 INSERT ... ON DUPLICATE KEY UPDATE 单条 SQL 原子完成
- rowcount == 1 作为成功标志 (INSERT 成功) 或 rowcount == 2 (UPDATE 成功)
- 彻底消除"先查后写"竞态
- claim_expires_at 防止实例崩溃后文件永久锁死
- mark_archived 更新归档路径和状态
"""

import os
from datetime import datetime, timezone, timedelta
from sqlalchemy import text

CLAIM_TIMEOUT_SECONDS = 600  # 10 分钟认领超时


class StateTracker:
    def __init__(self, db, instance_id: str):
        self.db = db
        self.instance_id = instance_id

    def try_claim(self, task_id: str, file_path: str,
                  file_mtime: int, file_size: int, file_hash: str) -> bool:
        """原子认领文件.

        返回 True = 本实例成功认领, 可以处理.
        使用 INSERT ... ON DUPLICATE KEY UPDATE 消除竞态.
        rowcount:
          1 = INSERT 成功 (新文件)
          2 = UPDATE 成功 (重新认领)
          0 = 无变化 (已被其他实例认领或已完成)
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=CLAIM_TIMEOUT_SECONDS)
        file_name = os.path.basename(file_path)

        with self.db.master_conn() as conn:
            result = conn.execute(text("""
                INSERT INTO processed_files
                    (task_id, file_path, file_name, file_mtime, file_size,
                     file_hash, status, claimed_by, claimed_at,
                     claim_expires_at, instance_id)
                VALUES
                    (:tid, :fp, :fn, :mt, :fs, :fh,
                     'CLAIMED', :iid, :now, :exp, :iid)
                ON DUPLICATE KEY UPDATE
                    status = IF(
                        (status = 'FAILED' AND retry_count < 3)
                        OR (status IN ('CLAIMED','PROCESSING')
                            AND claim_expires_at < :now),
                        'CLAIMED', status),
                    claimed_by = IF(
                        (status = 'FAILED' AND retry_count < 3)
                        OR (status IN ('CLAIMED','PROCESSING')
                            AND claim_expires_at < :now),
                        :iid, claimed_by),
                    claimed_at = IF(claimed_by = :iid, :now, claimed_at),
                    claim_expires_at = IF(claimed_by = :iid, :exp, claim_expires_at)
            """), dict(tid=task_id, fp=file_path, fn=file_name,
                       mt=file_mtime, fs=file_size, fh=file_hash,
                       iid=self.instance_id, now=now, exp=expires))
            conn.commit()

        # rowcount==1(INSERT成功) 或 ==2(UPDATE成功) 均表示本实例认领成功
        # 避免二次 SELECT，消除主从延迟窗口
        return result.rowcount in (1, 2)

    def mark_processing(self, task_id: str, file_path: str,
                        file_mtime: int) -> None:
        """CLAIMED -> PROCESSING. WHERE claimed_by 防止误更新."""
        with self.db.master_conn() as conn:
            conn.execute(text("""
                UPDATE processed_files SET status = 'PROCESSING'
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt AND claimed_by = :iid
                  AND status = 'CLAIMED'
            """), dict(tid=task_id, fp=file_path,
                       mt=file_mtime, iid=self.instance_id))
            conn.commit()

    def mark_success(self, task_id: str, file_path: str, file_mtime: int,
                     row_count: int, valid_count: int,
                     elapsed_ms: int) -> int:
        """PROCESSING -> SUCCESS. 返回 processed_files.id 供质量报告使用."""
        with self.db.master_conn() as conn:
            conn.execute(text("""
                UPDATE processed_files
                SET status = 'SUCCESS', processed_at = NOW(),
                    row_count = :rc, valid_row_count = :vc,
                    processing_time_ms = :ms
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt
            """), dict(tid=task_id, fp=file_path, mt=file_mtime,
                       rc=row_count, vc=valid_count, ms=elapsed_ms))
            # 用 LAST_INSERT_ID(id) trick 在同一连接内取主键，避免二次 SELECT
            row = conn.execute(text("""
                SELECT id FROM processed_files
                WHERE file_path = :fp AND file_mtime = :mt AND task_id = :tid
                LIMIT 1
            """), dict(fp=file_path, mt=file_mtime, tid=task_id)).fetchone()
            conn.commit()
        return row.id if row else 0

    def mark_failed(self, task_id: str, file_path: str, file_mtime: int,
                    error_type: str, error_msg: str) -> None:
        """PROCESSING -> FAILED, retry_count 自增."""
        with self.db.master_conn() as conn:
            conn.execute(text("""
                UPDATE processed_files
                SET status = 'FAILED',
                    error_type = :et, error_message = :em,
                    retry_count = retry_count + 1,
                    claim_expires_at = NULL
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt
            """), dict(tid=task_id, fp=file_path, mt=file_mtime,
                       et=error_type, em=error_msg))
            conn.commit()

    def mark_skipped(self, task_id: str, file_path: str,
                     file_mtime: int, reason: str) -> None:
        """PROCESSING -> SKIPPED."""
        with self.db.master_conn() as conn:
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
        """SUCCESS -> 更新 archive_path (归档完成后调用)."""
        with self.db.master_conn() as conn:
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
        """查询文件当前状态."""
        with self.db.slave_conn() as conn:
            row = conn.execute(text("""
                SELECT status FROM processed_files
                WHERE task_id = :tid AND file_path = :fp
                  AND file_mtime = :mt
            """), dict(tid=task_id, fp=file_path, mt=file_mtime)).fetchone()
        return row.status if row else None


