"""
数据库连接池 + 读写分离

- master_conn(): 写操作 (INSERT/UPDATE/DELETE)
- slave_conn():  读操作 (SELECT), 无从库时降级到主库
- 连接池由 SQLAlchemy create_engine 管理
"""

import logging
import random
from contextlib import contextmanager
from typing import List

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from ..core.exceptions import RetryableError

logger = logging.getLogger(__name__)


class DatabaseManager:
    """连接池管理器, 支持读写分离."""

    def __init__(self, config):
        """
        config: AppConfig (frozen dataclass)
        """
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
        logger.info("DatabaseManager initialized, %d slave(s)",
                    len(self._slaves))

    @contextmanager
    def master_conn(self):
        """获取主库连接 (写操作)."""
        with self._master.connect() as conn:
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise

    @contextmanager
    def slave_conn(self):
        """获取从库连接 (读操作). 无从库或从库故障时降级到主库."""
        engine = random.choice(self._slaves) if self._slaves else self._master
        fallback = False
        try:
            with engine.connect() as conn:
                yield conn
                return
        except Exception:
            if engine is self._master:
                raise
            logger.warning("Slave conn failed, falling back to master")
            fallback = True
        if fallback:
            with self._master.connect() as conn:
                yield conn

    def check_master(self) -> bool:
        """检查主库连通性."""
        try:
            with self._master.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("Master DB health check failed: %s", e)
            return False

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
            max_overflow=pool_size * 2,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            pool_pre_ping=True,  # 自动检测断开的连接
            connect_args={"connect_timeout": connect_timeout},
        )
