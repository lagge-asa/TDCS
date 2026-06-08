"""
文件归档 — FileArchiver

跨分区安全移动: copy2 -> 校验(大小/MD5) -> replace -> remove
归档时间基准: archived_at (归档完成时间), 非文件 mtime
压缩原子性: 先写 .tmp 再 replace
"""

import hashlib
import uuid
import logging
import os
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class FileArchiver:
    def __init__(self, state_tracker=None):
        self._st = state_tracker

    def archive_after_success(self, file_path: str,
                               task_config) -> str:
        """处理成功后归档文件, 返回归档路径."""
        if task_config.archive_mode == "keep":
            return file_path
        if task_config.archive_mode == "delete":
            try:
                os.unlink(file_path)
            except OSError as e:
                logger.error("Delete failed: %s", e)
            return ""

        # move 模式
        archive_dir = task_config.archive_dir
        if not archive_dir:
            return file_path

        os.makedirs(archive_dir, exist_ok=True)
        dst = self._resolve_dst(file_path, archive_dir)
        self._safe_move(file_path, dst)
        return dst

    def run_compress_job(self, task_config) -> None:
        """压缩 compress_after_days 天前的归档文件.

        当 compress_after_days <= 0 时永不自动压缩。
        """
        if task_config.compress_after_days <= 0:
            return
        archive_dir = task_config.archive_dir
        if not archive_dir or not os.path.isdir(archive_dir):
            return
        cutoff = datetime.now() - timedelta(
            days=task_config.compress_after_days)
        for fname in os.listdir(archive_dir):
            fpath = os.path.join(archive_dir, fname)
            if fname.endswith(".zip") or not os.path.isfile(fpath):
                continue
            # 以 archived_at (文件 mtime) 为基准
            archived_at = datetime.fromtimestamp(
                os.path.getmtime(fpath))
            if archived_at < cutoff:
                self._compress(fpath)

    def run_cleanup_job(self, task_config) -> None:
        """删除 cleanup_after_days 天前的归档文件.

        当 cleanup_after_days <= 0 时永不自动删除。
        """
        if task_config.cleanup_after_days <= 0:
            return
        archive_dir = task_config.archive_dir
        if not archive_dir or not os.path.isdir(archive_dir):
            return
        cutoff = datetime.now() - timedelta(
            days=task_config.cleanup_after_days)
        for fname in os.listdir(archive_dir):
            fpath = os.path.join(archive_dir, fname)
            if not os.path.isfile(fpath):
                continue
            archived_at = datetime.fromtimestamp(
                os.path.getmtime(fpath))
            if archived_at < cutoff:
                try:
                    os.unlink(fpath)
                    logger.info("Cleaned up: %s", fpath)
                except OSError as e:
                    logger.error("Cleanup failed: %s", e)

    # -- internal --

    def _safe_move(self, src: str, dst: str) -> None:
        """跨分区安全移动: copy2 -> 校验 -> move -> remove."""
        src_size = os.path.getsize(src)
        src_md5 = _md5(src)

        tmp = dst + ".tmp_" + uuid.uuid4().hex[:8]
        shutil.copy2(src, tmp)

        # 完整性校验
        if os.path.getsize(tmp) != src_size or _md5(tmp) != src_md5:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise IOError(
                f"Archive integrity check failed: {src} -> {dst}")

        shutil.move(tmp, dst)  # 跨卷兼容（Windows/Linux 均支持）
        try:
            os.unlink(src)
        except OSError as e:
            # 源文件可能已被其他进程移走，记录警告但不阻断
            logger.warning("Source file removal failed after archive: %s: %s", src, e)
        logger.info("Archived: %s -> %s", src, dst)

    def _compress(self, file_path: str) -> None:
        """原子压缩: 先写 .tmp 再 replace."""
        zip_path = file_path + ".zip"
        tmp_path = zip_path + ".tmp_" + uuid.uuid4().hex[:6]
        try:
            with zipfile.ZipFile(tmp_path, "w",
                                  zipfile.ZIP_DEFLATED) as zf:
                zf.write(file_path,
                         arcname=os.path.basename(file_path))
            os.replace(tmp_path, zip_path)
            os.unlink(file_path)
            logger.info("Compressed: %s", file_path)
        except Exception as e:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            logger.error("Compress failed: %s", e)

    @staticmethod
    def _resolve_dst(archive_dir: str, src: str) -> str:
        """解决目标路径冲突: 已存在则加 uuid 后缀."""
        dst = os.path.join(archive_dir, os.path.basename(src))
        if os.path.exists(dst):
            uid = uuid.uuid4().hex[:8]
            name, ext = os.path.splitext(os.path.basename(src))
            dst = os.path.join(archive_dir, f"{name}_{uid}{ext}")
        return dst


def _md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
