"""测试 Loader 幂等写入"""
from unittest.mock import MagicMock, patch
from src.etl.loader import Loader


def make_db():
    """构造带原生 DBAPI cursor mock 的 db 对象."""
    cursor = MagicMock()
    raw_conn = MagicMock()
    raw_conn.cursor.return_value.__enter__ = lambda s: cursor
    raw_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    sa_conn = MagicMock()
    sa_conn.connection.dbapi_connection = raw_conn
    sa_conn.__enter__ = lambda s: s
    sa_conn.__exit__ = MagicMock(return_value=False)

    db = MagicMock()
    db.master_conn.return_value = sa_conn
    return db, sa_conn, cursor


def test_load_batch_uses_insert_ignore():
    db, conn, cursor = make_db()
    loader = Loader(db)
    rows = [{"id": i, "val": f"v{i}"} for i in range(5)]
    loader.load_batch("order_data_202601", rows)
    sql = cursor.executemany.call_args[0][0]
    assert "INSERT IGNORE" in sql


def test_load_batch_uses_executemany():
    """1000 行应该只调用一次 executemany."""
    db, conn, cursor = make_db()
    loader = Loader(db)
    rows = [{"id": i, "val": i} for i in range(1000)]
    loader.load_batch("tbl", rows)
    assert cursor.executemany.call_count == 1


def test_load_batch_empty_returns_zero():
    db, conn, cursor = make_db()
    loader = Loader(db)
    result = loader.load_batch("tbl", [])
    assert result == 0
    cursor.executemany.assert_not_called()


def test_load_batch_returns_rowcount():
    """返回值应等于 cursor.rowcount (INSERT IGNORE 实际写入数)."""
    db, conn, cursor = make_db()
    cursor.rowcount = 3  # 模拟 2 行因重复被忽略
    loader = Loader(db)
    rows = [{"id": i} for i in range(5)]
    result = loader.load_batch("tbl", rows)
    assert result == 3
