"""
多任务生命周期管理 — TaskManager

职责:
- 启动/停止/暂停/恢复/手动触发任务
- 死信处理: retry_count >= max_retries -> move_to_dead_letter
- 每月 1 日触发 MonthlyTableLifecycle
"""

import logging
import os
import shutil
import threading
import uuid
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self, config_manager, db, worker_pool,
                 state_tracker, ha_elector, file_archiver,
                 monthly_lifecycle=None):
        self._cm = config_manager
        self._db = db
        self._pool = worker_pool
        self._st = state_tracker
        self._ha = ha_elector
        self._archiver = file_archiver
        self._lifecycle = monthly_lifecycle
        self._watchers: Dict[str, object] = {}
        self._scanners: Dict[str, object] = {}
        self._stop = threading.Event()
        self._last_lifecycle_month: Optional[str] = None

    def start_all(self) -> None:
        """启动所有已启用任务."""
        for task in self._cm.config.tasks:
            if task.enabled:
                self.start_task(task.task_id)
        threading.Thread(target=self._monthly_check_loop,
                         daemon=True, name="MonthlyCheck").start()

    def start_task(self, task_id: str) -> None:
        from ..watcher.event_handler import EventHandler
        from ..watcher.polling_scanner import PollingScanner
        from watchdog.observers import Observer

        task = self._cm.get_task(task_id)
        if not task:
            logger.error("Task not found: %s", task_id)
            return

        # 若已运行则先停止旧实例，防止线程泄漏
        if task_id in self._watchers or task_id in self._scanners:
            self.stop_task(task_id)

        # watchdog 监听
        handler = EventHandler(task, self._on_file_detected)
        observer = Observer()
        observer.schedule(handler, task.monitor_folder,
                          recursive=task.recursive)
        observer.start()
        self._watchers[task_id] = observer

        # 增量轮询兜底
        scanner = PollingScanner(task, self._st, self._pool)
        scanner.start()
        self._scanners[task_id] = scanner
        logger.info("Task started: %s", task_id)

    def stop_task(self, task_id: str) -> None:
        if task_id in self._watchers:
            obs = self._watchers.pop(task_id)
            obs.stop()
            obs.join(timeout=5)  # 等待线程真正退出
        if task_id in self._scanners:
            self._scanners.pop(task_id).stop()

    def pause_task(self, task_id: str) -> None:
        self._pool.pause_task(task_id)

    def resume_task(self, task_id: str) -> None:
        self._pool.resume_task(task_id)

    def trigger_task(self, task_id: str) -> None:
        """手动触发立即扫描."""
        if task_id in self._scanners:
            self._scanners[task_id].scan_now()

    def move_to_dead_letter(self, task_id: str,
                             file_path: str) -> None:
        """将文件移动到死信目录."""
        task = self._cm.get_task(task_id)
        if not task or not task.dead_letter_dir:
            return
        os.makedirs(task.dead_letter_dir, exist_ok=True)
        name, ext = os.path.splitext(os.path.basename(file_path))
        # 用 uuid4 短码确保目标路径全局唯一，避免并发或同秒内冲突导致覆盖
        uid = uuid.uuid4().hex[:8]
        dst = os.path.join(task.dead_letter_dir, f"{name}_{uid}{ext}")
        try:
            shutil.move(file_path, dst)
            logger.warning("Moved to dead letter: %s -> %s",
                           file_path, dst)
        except FileNotFoundError:
            # 区分源文件缺失和目标目录消失，给出精确日志
            if not os.path.exists(file_path):
                logger.warning(
                    "Dead letter source not found (already moved?): %s", file_path)
            else:
                logger.error(
                    "Dead letter target dir missing: %s", task.dead_letter_dir)
        except Exception as e:
            logger.error("Failed to move to dead letter: %s", e)

    def _on_file_detected(self, task_id: str, file_path: str,
                           file_mtime: int, file_size: int,
                           file_hash: str) -> None:
        """文件检测回调 -> 提交到 WorkerPool."""
        from ..infrastructure.worker_pool import SubmitResult
        task = self._cm.get_task(task_id)
        if not task:
            return
        result = self._pool.submit(
            priority=task.priority,
            task_id=task_id,
            file_path=file_path,
            file_mtime=file_mtime,
            file_size=file_size,
            file_hash=file_hash,
            is_active=self._ha.is_active,
        )
        if result != SubmitResult.QUEUED:
            logger.debug("Submit %s: %s", file_path, result.value)

    def _monthly_check_loop(self) -> None:
        """每月 1 日触发月表生命周期管理."""
        import time
        while not self._stop.is_set():
            now = datetime.now()
            month_key = now.strftime("%Y%m")
            if (now.day == 1
                    and month_key != self._last_lifecycle_month
                    and self._lifecycle):
                for task in self._cm.config.tasks:
                    if task.retention_months > 0:
                        try:
                            self._lifecycle.run(task)
                        except Exception as e:
                            # 单个 task 失败不影响其他 task
                            logger.error("Monthly lifecycle error for task %s: %s",
                                         task.task_id, e)
                self._last_lifecycle_month = month_key
            self._stop.wait(3600)  # 每小时检查一次，stop 时可立即唤醒
