"""
watchdog 防抖事件处理 — EventHandler

3s 内重复事件只触发一次.
文件稳定性检查: 连续 3 次 mtime/size 不变才处理.
"""

import logging
import os
import threading
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)


class EventHandler(FileSystemEventHandler):
    """防抖文件事件处理：3s 内重复事件去重 + 文件稳定性检测后触发。"""

    def __init__(self, task_config, on_file_ready):
        self._cfg = task_config
        self._on_file_ready = on_file_ready
        self._pending: dict = {}
        self._lock = threading.Lock()

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_moved(self, event):
        """处理文件移动/重命名——某些写入模式（原子保存：写临时文件 → rename）只触发 on_moved."""
        if not event.is_directory:
            self._schedule(event.dest_path)

    def _schedule(self, file_path: str) -> None:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self._cfg.file_extensions:
            return
        with self._lock:
            if file_path in self._pending:
                self._pending[file_path].cancel()
            t = threading.Timer(
                self._cfg.debounce_seconds,
                self._check_stability,
                args=(file_path, 0),
            )
            self._pending[file_path] = t
            t.start()

    def _check_stability(self, file_path: str,
                          attempt: int) -> None:
        """连续 stability_check_count 次 mtime/size 不变才处理."""
        try:
            stat = os.stat(file_path)
        except OSError:
            # 文件消失：清理所有辅助键防内存泄漏
            with self._lock:
                self._pending.pop(file_path, None)
                self._pending.pop(f"{file_path}:prev", None)
                self._pending.pop(f"{file_path}:count", None)
            return

        key = f"{file_path}:prev"
        with self._lock:
            prev = self._pending.get(key)
            cur = (stat.st_mtime, stat.st_size)
            if prev == cur:
                count = self._pending.get(f"{file_path}:count", 0) + 1
            else:
                count = 1
            self._pending[key] = cur
            self._pending[f"{file_path}:count"] = count

        if count >= self._cfg.stability_check_count:
            # 文件稳定, 触发处理
            with self._lock:
                self._pending.pop(file_path, None)
                self._pending.pop(key, None)
                self._pending.pop(f"{file_path}:count", None)
            self._emit(file_path, stat)
        else:
            t = threading.Timer(
                self._cfg.stability_check_interval,
                self._check_stability,
                args=(file_path, attempt + 1),
            )
            with self._lock:
                self._pending[file_path] = t
            t.start()

    def _emit(self, file_path: str, stat) -> None:
        from ..infrastructure.file_ref import FileRef
        ref = FileRef.from_stat(self._cfg.task_id, file_path, stat)
        self._on_file_ready(ref)
