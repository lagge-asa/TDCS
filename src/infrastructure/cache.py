"""轻量线程安全 TTL + LRU 缓存。"""
from collections import OrderedDict
import threading
import time


class CacheManager:
    """进程内有界缓存，get 会刷新 LRU 顺序，过期项按访问时清理。"""

    def __init__(self, maxsize: int = 1024, ttl: float = 300):
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        if ttl <= 0:
            raise ValueError("ttl must be > 0")
        self._maxsize = maxsize
        self._ttl = ttl
        self._items = OrderedDict()
        self._lock = threading.RLock()

    def set(self, key, value) -> None:
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = (time.monotonic() + self._ttl, value)
            self._evict_expired()
            while len(self._items) > self._maxsize:
                self._items.popitem(last=False)

    def get(self, key, default=None):
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return default
            expires_at, value = item
            if expires_at <= time.monotonic():
                self._items.pop(key, None)
                return default
            self._items.move_to_end(key)
            return value

    def delete(self, key) -> None:
        with self._lock:
            self._items.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            self._evict_expired()
            return len(self._items)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, (deadline, _) in self._items.items() if deadline <= now]
        for key in expired:
            self._items.pop(key, None)
