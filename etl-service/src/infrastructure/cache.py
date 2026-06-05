"""
本地缓存 — CacheManager

TTL + maxsize LRU 缓存, 无外部依赖.

优化:
- set() 驱逐前先清过期条目，避免驱逐未过期的热点数据
- 后台定时清理线程（每 30s）批量清理过期条目，防止写多读少时内存积累
- get_or_set(key, factory) 防缓存击穿（singleflight 模式，同一 key 只有一个线程执行 factory）
"""

import time
import threading
from collections import OrderedDict
from typing import Any, Callable, Optional

# 后台清理间隔（秒）
_CLEANUP_INTERVAL = 30


class CacheManager:
    """线程安全的本地 TTL + LRU 缓存."""

    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        # per-key 计算锁，用于 get_or_set 的 singleflight
        self._inflight: dict = {}
        self._inflight_lock = threading.Lock()
        # 启动后台清理线程
        self._stop = threading.Event()
        t = threading.Thread(target=self._cleanup_loop,
                             daemon=True, name="CacheCleanup")
        t.start()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                return None
            value, expires_at = self._store[key]
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            # LRU: 移到末尾
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: int = None) -> None:
        ttl = ttl if ttl is not None else self._ttl
        expires_at = time.monotonic() + ttl
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, expires_at)
            # 超出 maxsize 时先驱逐过期条目，再按 LRU 驱逐
            if len(self._store) > self._maxsize:
                self._evict_expired_locked()
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def get_or_set(self, key: str, factory: Callable[[], Any],
                   ttl: int = None) -> Any:
        """获取缓存值，miss 时调用 factory 计算并缓存.

        singleflight 模式：同一 key 同时只有一个线程执行 factory，
        其余线程等待并复用结果，防止缓存击穿。
        """
        # 先快速检查缓存
        value = self.get(key)
        if value is not None:
            return value

        # 获取或创建该 key 专属的计算锁
        with self._inflight_lock:
            if key not in self._inflight:
                self._inflight[key] = threading.Lock()
            key_lock = self._inflight[key]

        with key_lock:
            # double-check：等锁期间可能已被其他线程填充
            value = self.get(key)
            if value is not None:
                return value
            value = factory()
            self.set(key, value, ttl)

        # 清理 inflight 锁（无需精确，只是减少内存占用）
        with self._inflight_lock:
            self._inflight.pop(key, None)

        return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stop(self) -> None:
        """停止后台清理线程（服务关闭时调用）."""
        self._stop.set()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    # -- internal --

    def _evict_expired_locked(self) -> int:
        """在已持锁的情况下批量清理过期条目，返回清理数量."""
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        return len(expired)

    def _cleanup_loop(self) -> None:
        """后台定时清理过期条目."""
        while not self._stop.wait(_CLEANUP_INTERVAL):
            with self._lock:
                removed = self._evict_expired_locked()
            if removed:
                logger_ref = __import__("logging").getLogger(__name__)
                logger_ref.debug("CacheCleanup: removed %d expired entries",
                                 removed)
