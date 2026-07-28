"""测试 trace_id ContextVar 上下文"""
import threading
import pytest
from src.utils.trace import (
    new_trace, get_trace_id, get_task_id,
    set_trace_id, set_task_id,
)


def test_new_trace_returns_unique_ids():
    t1 = new_trace("task_a")
    t2 = new_trace("task_b")
    assert t1 != t2
    assert len(t1) == 16


def test_new_trace_sets_task_id():
    new_trace("order_import")
    assert get_task_id() == "order_import"


def test_get_trace_id_after_new_trace():
    tid = new_trace("t1")
    assert get_trace_id() == tid


def test_trace_isolation_across_threads():
    """不同线程的 trace_id 互不干扰 (ContextVar 隔离)."""
    results = {}

    def worker(name, task_id):
        new_trace(task_id)
        import time; time.sleep(0.05)
        results[name] = (get_trace_id(), get_task_id())

    threads = [
        threading.Thread(target=worker, args=(f"t{i}", f"task_{i}"))
        for i in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 每个线程的 task_id 应该是自己设置的
    for i in range(5):
        assert results[f"t{i}"][1] == f"task_{i}"

    # 所有 trace_id 应该唯一
    trace_ids = [v[0] for v in results.values()]
    assert len(set(trace_ids)) == 5


def test_set_trace_id_explicit():
    set_trace_id("abc123")
    assert get_trace_id() == "abc123"


def test_default_empty_when_not_set():
    """新线程中未调用 new_trace 时返回空字符串."""
    result = {}

    def worker():
        result["trace"] = get_trace_id()
        result["task"] = get_task_id()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert result["trace"] == ""
    assert result["task"] == ""
