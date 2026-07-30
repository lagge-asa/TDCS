"""
数据库连接池

- master_conn(): 写操作 (INSERT/UPDATE/DELETE)
- read_conn():   读操作 (SELECT), 当前等同于 master_conn()（单实例模式）
- 连接池由 SQLAlchemy create_engine 管理

优化:
- _create_engine 补充 read_timeout/write_timeout，防慢查询挂死连接池
- master_conn rollback 加保护，防止二次异常掩盖原始错误
"""

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

if TYPE_CHECKING:
    from ..core.config_models import AppConfig

logger = logging.getLogger(__name__)


class DatabaseManager:
    """连接池管理器."""

    def __init__(self, config: "AppConfig") -> None:
        self._master = self._create_engine(
            config.db_master_dsn,
            pool_size=config.db_master_pool_size,
            pool_timeout=config.db_master_pool_timeout,
            pool_recycle=config.db_master_pool_recycle,
            connect_timeout=config.db_master_connect_timeout,
        )
        logger.info("DatabaseManager initialized")

    @contextmanager
    def master_conn(self) -> Iterator:
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

    def read_conn(self):
        """获取读连接，当前等同于 master_conn()（单实例模式）."""
        return self.master_conn()

    # 向后兼容别名，逐步迁移到 read_conn()
    slave_conn = read_conn

    def dispose(self) -> None:
        """关闭连接池."""
        self._master.dispose()

    @staticmethod
    def _create_engine(dsn: str, pool_size: int = 5,
                        pool_timeout: int = 30,
                        pool_recycle: int = 3600,
                        connect_timeout: int = 10) -> Engine:
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
