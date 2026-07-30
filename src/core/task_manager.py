"""
多任务生命周期管理 — TaskManager

职责:
- 启动/停止/暂停/恢复/手动触发任务
- 死信处理: retry_count >= max_retries -> move_to_dead_letter
"""

import logging
import os
import shutil
import threading
import uuid
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)


class TaskManager:
    """多任务生命周期管理器"""
    def __init__(self, config_manager, db, worker_pool,
                 state_tracker, ha_elector, file_archiver):
        self._cm = config_manager
        self._db = db
        self._pool = worker_pool
        self._st = state_tracker
        self._ha = ha_elector
        self._archiver = file_archiver
        self._watchers: Dict[str, object] = {}
        self._scanners: Dict[str, object] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._cm.add_listener(self._on_config_changed)

    def _on_config_changed(self, old_config, new_config) -> None:
        """配置成功热加载后同步运行中的 watcher/scanner。"""
        old_tasks = {t.task_id: t for t in (old_config.tasks if old_config else ())}
        new_tasks = {t.task_id: t for t in new_config.tasks}
        with self._lock:
            running_ids = set(self._watchers) | set(self._scanners)
        changed_ids = {
            task_id for task_id in running_ids & new_tasks.keys()
            if old_tasks.get(task_id) != new_tasks[task_id]
        }
        removed_or_disabled = {
            task_id for task_id in running_ids
            if task_id not in new_tasks or not new_tasks[task_id].enabled
        }
        for task_id in removed_or_disabled:
            self.stop_task(task_id)
            self._pool.resume_task(task_id)
        for task_id in changed_ids - removed_or_disabled:
            self.stop_task(task_id)
            self.start_task(task_id)
        for task_id, task in new_tasks.items():
            if task.enabled and task_id not in running_ids and task_id not in removed_or_disabled:
                self.start_task(task_id)

    def start_all(self) -> None:
        """启动所有已启用任务."""
        for task in self._cm.config.tasks:
            if task.enabled:
                self.start_task(task.task_id)

    def start_task(self, task_id: str) -> None:
        from ..watcher.event_handler import EventHandler
        from ..watcher.polling_scanner import PollingScanner
        from watchdog.observers import Observer

        task = self._cm.get_task(task_id)
        if not task:
            logger.error("Task not found: %s", task_id)
            return

        with self._lock:
            # 若已运行则先停止旧实例，防止线程泄漏
            if task_id in self._watchers or task_id in self._scanners:
                self._stop_task_locked(task_id)

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
        with self._lock:
            self._stop_task_locked(task_id)

    def _stop_task_locked(self, task_id: str) -> None:
        """内部：在持有 self._lock 时停止任务。"""
        if task_id in self._watchers:
            obs = self._watchers.pop(task_id)
            obs.stop()
            obs.join(timeout=5)
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

    def is_running(self, task_id: str) -> bool:
        """检查任务的 watcher 和 scanner 是否正在运行."""
        with self._lock:
            has_watcher = task_id in self._watchers
            has_scanner = task_id in self._scanners
            # observer 的 is_alive() 检查线程存活
            watcher_alive = has_watcher and self._watchers[task_id].is_alive()
            scanner_alive = (has_scanner and
                             self._scanners[task_id]._thread is not None and
                             self._scanners[task_id]._thread.is_alive())
        return watcher_alive or scanner_alive

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

    def _on_file_detected(self, ref: "FileRef") -> None:
        """文件检测回调 -> 提交到 WorkerPool."""
        from ..infrastructure.worker_pool import SubmitResult
        task = self._cm.get_task(ref.task_id)
        if not task:
            return
        result = self._pool.submit(
            ref,
            priority=task.priority,
            is_active=self._ha.is_active if self._ha else True,
        )
        if result != SubmitResult.QUEUED:
            logger.debug("Submit %s: %s", ref.file_path, result.value)
