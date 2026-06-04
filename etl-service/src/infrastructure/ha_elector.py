"""
HA Leader 选举 — HAElector

乐观锁心跳 + 降级模式:
- ACTIVE: 持有 Leader 锁, 正常处理
- STANDBY: 等待 Leader 超时后抢占
- standalone: MySQL 不可用时单节点继续处理
- pause: MySQL 不可用时停止处理 (防脑裂)

on_become_standby 在 is_active=False 后同步调用.
"""

import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)


class HAElector:
    def __init__(self, db, instance_id: str, config,
                 on_become_active=None, on_become_standby=None):
        """
        config: AppConfig.ha (HAConfig frozen dataclass)
        on_become_active: () -> None
        on_become_standby: () -> None  (在 is_active=False 后同步调用)
        """
        self._db = db
        self._instance_id = instance_id
        self._cfg = config
        self._on_active = on_become_active or (lambda: None)
        self._on_standby = on_become_standby or (lambda: None)
        self._is_active = False
        self._active_lock = threading.Lock()
        self._stop = threading.Event()

    @property
    def is_active(self) -> bool:
        with self._active_lock:
            return self._is_active

    def start(self) -> None:
        t = threading.Thread(target=self._loop,
                             daemon=True, name="HAElector")
        t.start()

    def stop(self) -> None:
        self._stop.set()
        with self._active_lock:
            was_active = self._is_active
            self._is_active = False
        if was_active:
            self._on_standby()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.is_active:
                    self._heartbeat()
                else:
                    self._try_takeover()
            except Exception as e:
                logger.error("HA election error: %s", e)
                self._handle_db_unavailable()
            self._stop.wait(self._cfg.heartbeat_interval)

    def _heartbeat(self) -> None:
        with self._db.master_conn() as conn:
            rows = conn.execute(text("""
                UPDATE leader SET last_heartbeat = NOW(3)
                WHERE id = 1 AND instance_id = :iid
            """), {"iid": self._instance_id}).rowcount
            conn.commit()
        if rows == 0:
            logger.warning("Heartbeat failed, becoming STANDBY")
            self._become_standby()

    def _try_takeover(self) -> None:
        timeout = self._cfg.failover_timeout
        with self._db.master_conn() as conn:
            row = conn.execute(text(
                "SELECT version, last_heartbeat FROM leader WHERE id = 1"
            )).fetchone()
            if not row:
                return
            if row.last_heartbeat:
                hb = row.last_heartbeat
                # 统一用数据库时间做差，避免 DB/App 时钟偏差导致误判
                now_db = conn.execute(text("SELECT NOW(3) as now")).fetchone().now
                if now_db.tzinfo is None:
                    now_db = now_db.replace(tzinfo=timezone.utc)
                if hb.tzinfo is None:
                    hb = hb.replace(tzinfo=timezone.utc)
                elapsed = (now_db - hb).total_seconds()
                if elapsed < timeout:
                    return
            affected = conn.execute(text("""
                UPDATE leader
                SET instance_id = :iid, last_heartbeat = NOW(3),
                    started_at = NOW(), version = version + 1
                WHERE id = 1 AND version = :ver
            """), {"iid": self._instance_id,
                   "ver": row.version}).rowcount
            conn.commit()
        if affected == 1:
            logger.info("Instance %s became ACTIVE Leader",
                        self._instance_id)
            with self._active_lock:
                self._is_active = True
            self._on_active()

    def _handle_db_unavailable(self) -> None:
        mode = self._cfg.degraded_mode
        if mode == "standalone":
            if not self.is_active:
                logger.warning("DB unavailable, standalone mode: ACTIVE")
                with self._active_lock:
                    self._is_active = True
                self._on_active()
        else:  # pause
            if self.is_active:
                logger.warning("DB unavailable, pause mode: STANDBY")
                self._become_standby()

    def _become_standby(self) -> None:
        with self._active_lock:
            self._is_active = False
        # on_become_standby 在 is_active=False 后同步调用
        self._on_standby()
