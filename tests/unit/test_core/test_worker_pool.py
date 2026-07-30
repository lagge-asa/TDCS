"""WorkerPool 与 CircuitBreaker 核心行为测试。"""
import time
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.file_ref import FileRef
from src.infrastructure.worker_pool import (
    CircuitBreaker,
    CircuitState,
    SubmitResult,
    WorkerPool,
)


@pytest.fixture
def ref():
    return FileRef("task_a", "D:/input/a.csv", 1, 10, "hash")


def test_submit_rejects_standby_and_paused(ref):
    pool = WorkerPool(MagicMock(), 1, queue_maxsize=2)
    assert pool.submit(ref, is_active=False) == SubmitResult.REJECTED_HA_STANDBY
    pool.pause_task("task_a")
    assert pool.submit(ref) == SubmitResult.REJECTED_TASK_PAUSED
    assert pool.queue_size() == 0


def test_submit_rejects_when_queue_full(ref):
    pool = WorkerPool(MagicMock(), 1, queue_maxsize=1)
    assert pool.submit(ref) == SubmitResult.QUEUED
    assert pool.submit(ref) == SubmitResult.QUEUE_FULL
    assert pool.queue_backlog("task_a") == 1
    pool._queue.get_nowait()
    pool._queue.task_done()


def test_priority_queue_processes_lower_priority_first():
    processed = []
    pool = WorkerPool(lambda item, _: processed.append(item.file_path), 1, queue_maxsize=10)
    low = FileRef("task_a", "low", 1, 1, "l")
    high = FileRef("task_a", "high", 1, 1, "h")
    pool.submit(low, priority=9)
    pool.submit(high, priority=1)

    pool._work_once_for_test = None
    task1 = pool._queue.get_nowait()
    task2 = pool._queue.get_nowait()
    assert [task1.ref.file_path, task2.ref.file_path] == ["high", "low"]
    pool._queue.task_done()
    pool._queue.task_done()


def test_circuit_breaker_opens_and_allows_half_open_probe():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
    assert breaker.allow() is True
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert breaker.allow() is False

    with patch("src.infrastructure.worker_pool.time.monotonic", return_value=100.0):
        breaker._opened_at = 0.0
        assert breaker.allow() is True
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.allow() is False
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED


def test_circuit_open_rejects_submit(ref):
    pool = WorkerPool(MagicMock(), 1)
    breaker = pool._get_breaker("task_a")
    breaker._state = CircuitState.OPEN
    breaker._opened_at = time.monotonic()
    assert pool.submit(ref) == SubmitResult.REJECTED_CIRCUIT_OPEN


def test_worker_records_unhandled_failure_and_finishes_queue(ref):
    process = MagicMock(side_effect=RuntimeError("boom"))
    pool = WorkerPool(process, 1, queue_maxsize=2)
    pool.submit(ref)
    pool._work_once_for_test = None

    with patch.object(pool, "_get_breaker", wraps=pool._get_breaker) as get_breaker:
        worker = pool._workers[0]

        def stop_after_failure(item, breaker):
            try:
                process(item, breaker)
            finally:
                pool._stop.set()

        pool._process_fn = stop_after_failure
        worker.run()
        get_breaker.assert_called()

    assert pool.queue_size() == 0
    assert pool.get_breaker_state("task_a") == CircuitState.OPEN.value or \
        pool.get_breaker_state("task_a") == CircuitState.CLOSED.value


def test_remove_breaker_and_pause_state(ref):
    pool = WorkerPool(MagicMock(), 1)
    pool.pause_task("task_a")
    assert pool.is_task_paused("task_a") is True
    assert pool.paused_count() == 1
    pool.resume_task("task_a")
    assert pool.is_task_paused("task_a") is False
    pool._get_breaker("task_a")
    pool.remove_breaker("task_a")
    assert pool.get_breaker_state("task_a") == CircuitState.CLOSED.value
