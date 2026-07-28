"""集成测试: 数据库相关组件

需要 MySQL 可用时才运行。设置环境变量 ETL_TEST_DB=1 启用。
"""

import os
import pytest

# 检查是否启用集成测试
_skip_integration = not os.environ.get("ETL_TEST_DB")

pytestmark = pytest.mark.skipif(
    _skip_integration,
    reason="Set ETL_TEST_DB=1 to run integration tests (requires MySQL)"
)


@pytest.fixture
def db_engine():
    """创建测试用的数据库引擎（使用测试库）。"""
    from sqlalchemy import create_engine
    dsn = os.environ.get(
        "ETL_TEST_DSN",
        "mysql+pymysql://root@127.0.0.1:3306/etl_test_db?charset=utf8mb4"
    )
    engine = create_engine(dsn, poolclass=None)
    yield engine
    engine.dispose()


@pytest.fixture
def db_manager():
    """创建 DatabaseManager 实例."""
    from unittest.mock import MagicMock

    config = MagicMock()
    config.db_master_dsn = os.environ.get(
        "ETL_TEST_DSN",
        "mysql+pymysql://root@127.0.0.1:3306/etl_test_db?charset=utf8mb4"
    )
    config.db_master_pool_size = 2
    config.db_master_pool_timeout = 10
    config.db_master_pool_recycle = 600
    config.db_master_connect_timeout = 5
    config.db_slave_dsns = ()

    from src.infrastructure.database import DatabaseManager
    return DatabaseManager(config)


class TestDatabaseConnection:
    """数据库连接测试."""

    def test_master_connection(self, db_manager):
        """测试主库连接可用."""
        with db_manager.master_conn() as conn:
            from sqlalchemy import text
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_slave_fallback_to_master(self, db_manager):
        """无从库时 slave_conn 降级到主库."""
        conn = db_manager.slave_conn()
        assert conn is not None
        conn.close()


class TestLoader:
    """Loader 批量写入测试."""

    def test_prepare_rows_union_keys(self):
        """_prepare_rows 测试：行键并集."""
        from src.etl.loader import Loader

        # 不需要真实 DB，直接测试静态方法
        columns, data = Loader._prepare_rows([
            {"a": 1, "b": 2},
            {"b": 3, "c": 4},
            {"a": 5},
        ])
        assert set(columns) == {"a", "b", "c"}
        assert len(data) == 3
        # 缺失键填 None
        assert data[2] == (5, None, None)


class TestStateTracker:
    """StateTracker 状态机测试."""

    def test_upsert_state(self, db_manager):
        """测试文件状态 upsert（需要真实 DB）。"""
        import time
        from src.infrastructure.state_tracker import StateTracker

        st = StateTracker(db_manager, "test_instance")

        # upsert a new file
        file_path = f"/tmp/test_file_{int(time.time())}.csv"
        result = st.upsert("test_task", file_path, time.time(), 1024, "abc123")
        assert result in ("INSERTED", "UPDATED", "DUPLICATE")

        # cleanup
        with db_manager.master_conn() as conn:
            from sqlalchemy import text
            conn.execute(
                text("DELETE FROM processed_files WHERE file_path = :fp"),
                {"fp": file_path}
            )
            conn.connection.dbapi_connection.commit()
