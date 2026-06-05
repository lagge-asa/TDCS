"""
Worker 线程池 + per-task 熔断器 + Supervisor 自动重启

熔断器三态: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
- OPEN 时返回 REJECTED_CIRCUIT_OPEN, 不阻塞调用方
- per-task: 一个任务 OPEN 不影响其他任务
- HALF_OPEN 只允许一个试探请求

优化:
- WorkerTask dataclass 替代 tuple，扩展字段时向后兼容
- _supervise 引入退避策略：5 分钟内重启超过 3 次则停止并告警
"""

import queue
import threading
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

from ..core.exceptions import SkipFileError

logger = logging.getLogger(__name__)

# Supervisor 退避参数
_RESTART_WINDOW = 300   # 秒：滑动窗口
_RESTART_MAX = 3        # 窗口内最大重启次数


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class SubmitResult(Enum):
    QUEUED = "QUEUED"
    REJECTED_CIRCUIT_OPEN = "REJECTED_CIRCUIT_OPEN"
    REJECTED_HA_STANDBY = "REJECTED_HA_STANDBY"
    REJECTED_TASK_PAUSED = "REJECTED_TASK_PAUSED"
    QUEUE_FULL = "QUEUE_FULL"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: int = 60
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failures: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _half_open_in_progress: bool = field(default=False, init=False)
    _half_open_at: float = field(default=0.0, init=False)

    def allow(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._opened_at > self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_at = time.monotonic()
                    self._half_open_in_progress = False
                    return True
                return False
            # HALF_OPEN: 只允许一个试探; 超过 recovery_timeout 后重置卡死标志
            if self._half_open_in_progress:
                if time.monotonic() - self._half_open_at > self.recovery_timeout:
                    self._half_open_in_progress = False
                else:
                    return False
            self._half_open_in_progress = True
            self._half_open_at = time.monotonic()
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._half_open_in_progress = False
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._half_open_in_progress = False
            self._failures += 1
            if (self._state == CircuitState.HALF_OPEN
                    or self._failures >= self.failure_threshold):
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.error("Circuit OPEN for task (failures=%d)",
                             self._failures)

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state


@dataclass
class WorkerTask:
    """队列任务载体，替代 tuple，扩展字段时向后兼容."""
    priority: int
    task_id: str
    file_path: str
    file_mtime: int
    file_size: int
    file_hash: str

    # PriorityQueue 按第一个字段排序，需支持 < 比较
    def __lt__(self, other: "WorkerTask") -> bool:
        return self.priority < other.priority


class WorkerPool:
    """优先级队列 + per-task 熔断器 + Supervisor 自动重启."""

    def __init__(self, process_fn, num_workers: int,
                 queue_maxsize: int = 500):
        self._process_fn = process_fn
        self._queue: queue.PriorityQueue = queue.PriorityQueue(
            maxsize=queue_maxsize)
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._breaker_lock = threading.Lock()
        self._paused: set = set()
        self._paused_lock = threading.Lock()
        self._stop = threading.Event()
        self._workers = [
            threading.Thread(target=self._work,
                             daemon=True, name=f"Worker-{i}")
            for i in range(num_workers)
        ]
        self._num_workers = num_workers
        # Supervisor 退避：记录各 worker 的重启时间戳列表
        self._restart_times: Dict[int, list] = {
            i: [] for i in range(num_workers)}
        self._disabled_workers: set = set()  # 因频繁重启而停用的 worker 索引

    def start(self) -> None:
        for w in self._workers:
            w.start()
        threading.Thread(target=self._supervise,
                         daemon=True, name="WorkerSupervisor").start()

    def submit(self, priority: int, task_id: str, file_path: str,
               file_mtime: int, file_size: int, file_hash: str,
               is_active: bool = True) -> SubmitResult:
        if not is_active:
            return SubmitResult.REJECTED_HA_STANDBY
        with self._paused_lock:
            paused = task_id in self._paused
        if paused:
            return SubmitResult.REJECTED_TASK_PAUSED
        breaker = self._get_breaker(task_id)
        if not breaker.allow():
            return SubmitResult.REJECTED_CIRCUIT_OPEN
        try:
            self._queue.put_nowait(
                WorkerTask(priority, task_id, file_path,
                           file_mtime, file_size, file_hash))
            return SubmitResult.QUEUED
        except queue.Full:
            return SubmitResult.QUEUE_FULL

    def pause_task(self, task_id: str) -> None:
        with self._paused_lock:
            self._paused.add(task_id)

    def resume_task(self, task_id: str) -> None:
        with self._paused_lock:
            self._paused.discard(task_id)

    def get_breaker(self, task_id: str) -> CircuitBreaker:
        return self._get_breaker(task_id)

    def active_count(self) -> int:
        """当前存活的 worker 线程数."""
        return sum(1 for w in self._workers if w.is_alive())

    def queue_size(self) -> int:
        """当前队列积压数."""
        return self._queue.qsize()

    def breaker_states(self) -> dict:
        """返回各 task_id 的熔断器状态."""
        with self._breaker_lock:
            return {tid: cb.state.value
                    for tid, cb in self._breakers.items()}

    def stop(self) -> None:
        """发送停止信号并等待所有 worker 线程退出（最多 30s）。"""
        self._stop.set()
        for w in self._workers:
            w.join(timeout=30)
            if w.is_alive():
                logger.warning("Worker thread %s did not exit in 30s", w.name)

    def _get_breaker(self, task_id: str) -> CircuitBreaker:
        with self._breaker_lock:
            if task_id not in self._breakers:
                self._breakers[task_id] = CircuitBreaker()
            return self._breakers[task_id]

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                task: WorkerTask = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            breaker = self._get_breaker(task.task_id)
            try:
                self._process_fn(
                    task.task_id, task.file_path, task.file_mtime,
                    task.file_size, task.file_hash, breaker)
            except SkipFileError:
                pass  # 预期跳过，不计入熔断
            except Exception as e:
                logger.exception("Worker unhandled error: %s", e)
                breaker.record_failure()
            finally:
                self._queue.task_done()

    def _supervise(self) -> None:
        """检测死亡 Worker 并重启，带退避保护."""
        while not self._stop.is_set():
            now = time.monotonic()
            for i, w in enumerate(self._workers):
                if i in self._disabled_workers:
                    continue
                if not w.is_alive():
                    # 清理窗口外的旧记录
                    self._restart_times[i] = [
                        t for t in self._restart_times[i]
                        if now - t < _RESTART_WINDOW
                    ]
                    if len(self._restart_times[i]) >= _RESTART_MAX:
                        logger.error(
                            "Worker-%d restarted %d times in %ds, "
                            "disabling to prevent crash loop. "
                            "Manual intervention required.",
                            i, _RESTART_MAX, _RESTART_WINDOW)
                        self._disabled_workers.add(i)
                        continue
                    logger.warning("Worker-%d died, restarting...", i)
                    self._restart_times[i].append(now)
                    new_w = threading.Thread(
                        target=self._work,
                        daemon=True, name=f"Worker-{i}")
                    self._workers[i] = new_w
                    new_w.start()
            self._stop.wait(10)
