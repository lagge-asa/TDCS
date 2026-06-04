"""测试 CacheManager TTL + LRU"""
import time
import threading
import pytest
from src.infrastructure.cache import CacheManager


def test_set_get():
    c = CacheManager(maxsize=10, ttl=60)
    c.set("k", "v")
    assert c.get("k") == "v"


def test_ttl_expiry():
    c = CacheManager(maxsize=10, ttl=1)
    c.set("k", "v")
    time.sleep(1.1)
    assert c.get("k") is None


def test_maxsize_eviction():
    c = CacheManager(maxsize=3, ttl=60)
    for i in range(5):
        c.set(f"k{i}", i)
    assert len(c) == 3
    # 最旧的 k0, k1 应被驱逐
    assert c.get("k0") is None
    assert c.get("k4") == 4


def test_lru_order():
    c = CacheManager(maxsize=3, ttl=60)
    c.set("a", 1); c.set("b", 2); c.set("c", 3)
    c.get("a")  # 访问 a, 使其成为最新
    c.set("d", 4)  # 应驱逐 b (最旧未访问)
    assert c.get("a") == 1
    assert c.get("b") is None


def test_thread_safety():
    c = CacheManager(maxsize=100, ttl=60)
    def writer(n):
        for i in range(50):
            c.set(f"k{n}_{i}", i)
    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(c) <= 100


def test_delete():
    c = CacheManager()
    c.set("k", "v")
    c.delete("k")
    assert c.get("k") is None
