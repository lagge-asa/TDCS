"""
本地缓存 — CacheManager

TTL + maxsize LRU 缓存, 无外部依赖.
"""

import time
import threading
from collections import OrderedDict


class CacheManager:
    """线程安全的本地 TTL + LRU 缓存."""

    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
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

    def set(self, key: str, value, ttl: int = None) -> None:
        ttl = ttl if ttl is not None else self._ttl
        expires_at = time.monotonic() + ttl
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, expires_at)
            # 超出 maxsize 时驱逐最旧的
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
