"""
增量轮询兜底 — PollingScanner

只扫描 mtime > last_scan_time 的文件.
仅支持本地 NTFS/ext4, 不支持 NFS/SMB.
"""

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


class PollingScanner:
    """增量轮询兜底扫描器：按 mtime 扫描新文件并提交到工作池。"""

    def __init__(self, task_config, state_tracker, worker_pool):
        self._cfg = task_config
        self._st = state_tracker
        self._pool = worker_pool
        self._last_scan_mtime: float = 0.0
        self._mtime_lock = threading.Lock()
        self._scan_lock = threading.Lock()  # 防止 scan_now() 和 _loop 并发扫描
        self._stop = threading.Event()
        self._thread: threading.Thread = None

    def start(self) -> None:
        if self._cfg.poll_interval <= 0:
            return
        self._thread = threading.Thread(
            target=self._loop, daemon=True,
            name=f"Poller-{self._cfg.task_id}")
        self._thread.start()

    def scan_now(self) -> None:
        """手动触发立即扫描."""
        threading.Thread(target=self._scan, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan()
            except Exception as e:
                logger.error("Poll scan error [%s]: %s",
                             self._cfg.task_id, e)
            self._stop.wait(self._cfg.poll_interval)

    def _scan(self) -> None:
        with self._scan_lock:
            self._scan_impl()

    def _scan_impl(self) -> None:
        folder = self._cfg.monitor_folder
        exts = self._cfg.file_extensions
        incremental = self._cfg.poll_incremental
        scan_start = time.time()
        found = 0

        with self._mtime_lock:
            last_mtime = self._last_scan_mtime

        for root, dirs, files in os.walk(folder):
            if not self._cfg.recursive:
                dirs.clear()
            for fname in sorted(files):
                if not any(fname.endswith(e) for e in exts):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    stat = os.stat(fpath)
                except OSError:
                    continue
                if incremental and stat.st_mtime <= last_mtime:
                    continue
                file_mtime = int(stat.st_mtime * 1000)
                # 先用 mtime+size 查状态，已成功且未变化则跳过 hash 计算
                db_status = self._st.get_status(
                    self._cfg.task_id, fpath, file_mtime)
                if db_status == 'SUCCESS':
                    continue
                from ..infrastructure.file_ref import FileRef
                ref = FileRef.from_stat(self._cfg.task_id, fpath, stat)
                self._pool.submit(ref, priority=getattr(self._cfg, 'priority', 5))
                found += 1

        with self._mtime_lock:
            # 只前进，不后退：并发扫描可能看到不同时间点，
            # 取最大值确保不遗漏文件
            self._last_scan_mtime = max(self._last_scan_mtime, scan_start)
        if found:
            logger.info("Poll [%s] found %d files",
                        self._cfg.task_id, found)
