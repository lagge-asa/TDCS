"""
数据库连接池 + 读写分离

- master_conn(): 写操作 (INSERT/UPDATE/DELETE)
- slave_conn():  读操作 (SELECT), 无从库时降级到主库
- 连接池由 SQLAlchemy create_engine 管理

优化:
- _create_engine 补充 read_timeout/write_timeout，防慢查询挂死连接池
- slave_conn 维护从库健康状态，故障从库短期摘除后自动恢复
- max_overflow 固定为 pool_size（而非 *2），防连接数爆炸
- master_conn rollback 加保护，防止二次异常掩盖原始错误
- 新增 check_slaves() 返回各从库延迟状态
"""

import logging
import random
import time
import threading
from contextlib import contextmanager
from typing import Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

from ..core.exceptions import RetryableError

logger = logging.getLogger(__name__)

# 从库故障后摘除的冷却时间（秒）
_SLAVE_COOLDOWN = 60


class DatabaseManager:
    """连接池管理器, 支持读写分离."""

    def __init__(self, config):
        self._master = self._create_engine(
            config.db_master_dsn,
            pool_size=config.db_master_pool_size,
            pool_timeout=config.db_master_pool_timeout,
            pool_recycle=config.db_master_pool_recycle,
            connect_timeout=config.db_master_connect_timeout,
        )
        self._slaves: List = [
            self._create_engine(dsn)
            for dsn in config.db_slave_dsns
        ]
        # 从库健康状态：{index: failed_at timestamp or None}
        self._slave_health: Dict[int, Optional[float]] = {
            i: None for i in range(len(self._slaves))
        }
        self._health_lock = threading.Lock()
        logger.info("DatabaseManager initialized, %d slave(s)",
                    len(self._slaves))

    @contextmanager
    def master_conn(self):
        """获取主库连接 (写操作)."""
        with self._master.connect() as conn:
            try:
                yield conn
            except Exception as exc:
                # rollback 加保护，防止连接断开时二次异常掩盖原始错误
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise exc

    @contextmanager
    def slave_conn(self):
        """获取从库连接 (读操作). 无从库或健康从库时降级到主库."""
        engine, slave_idx = self._pick_slave()
        if engine is self._master:
            with self._master.connect() as conn:
                yield conn
            return

        try:
            with engine.connect() as conn:
                yield conn
            # 成功后恢复健康状态
            if slave_idx is not None:
                with self._health_lock:
                    self._slave_health[slave_idx] = None
        except Exception:
            logger.warning("Slave[%d] conn failed, falling back to master",
                           slave_idx)
            # 标记从库故障时间
            if slave_idx is not None:
                with self._health_lock:
                    self._slave_health[slave_idx] = time.monotonic()
            with self._master.connect() as conn:
                yield conn

    def _pick_slave(self):
        """选择一个健康从库，全部故障时返回主库."""
        if not self._slaves:
            return self._master, None
        now = time.monotonic()
        with self._health_lock:
            healthy = [
                i for i, failed_at in self._slave_health.items()
                if failed_at is None or (now - failed_at) > _SLAVE_COOLDOWN
            ]
        if not healthy:
            logger.warning("All slaves unhealthy, using master for read")
            return self._master, None
        idx = random.choice(healthy)
        return self._slaves[idx], idx

    def check_master(self) -> bool:
        """检查主库连通性."""
        try:
            with self._master.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("Master DB health check failed: %s", e)
            return False

    def check_slaves(self) -> List[dict]:
        """检查各从库连通性，返回状态列表."""
        results = []
        now = time.monotonic()
        for i, engine in enumerate(self._slaves):
            with self._health_lock:
                failed_at = self._slave_health.get(i)
            in_cooldown = (
                failed_at is not None
                and (now - failed_at) <= _SLAVE_COOLDOWN
            )
            if in_cooldown:
                results.append({
                    "index": i, "status": "cooldown",
                    "cooldown_remaining": round(
                        _SLAVE_COOLDOWN - (now - failed_at), 1)
                })
                continue
            try:
                t0 = time.monotonic()
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                results.append({
                    "index": i, "status": "ok",
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1)
                })
            except Exception as e:
                results.append({"index": i, "status": "error",
                                 "error": str(e)})
        return results

    def dispose(self) -> None:
        """关闭所有连接池."""
        self._master.dispose()
        for s in self._slaves:
            s.dispose()

    @staticmethod
    def _create_engine(dsn: str, pool_size: int = 5,
                        pool_timeout: int = 30,
                        pool_recycle: int = 3600,
                        connect_timeout: int = 10):
        return create_engine(
            dsn,
            poolclass=QueuePool,
            pool_size=pool_size,
            # max_overflow 固定为 pool_size，防止高并发时连接数爆炸
            max_overflow=pool_size,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": connect_timeout,
                # 防止慢查询/网络抖动挂死连接池
                "read_timeout": 30,
                "write_timeout": 30,
            },
        )
