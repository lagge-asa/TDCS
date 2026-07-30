"""StateTracker 数据库状态变更测试。"""
from contextlib import contextmanager
from unittest.mock import MagicMock

from src.infrastructure.state_tracker import StateTracker
from src.infrastructure.file_ref import FileRef


class Row:
    def __init__(self, **values):
        self.__dict__.update(values)


class Result:
    def __init__(self, rowcount=1, rows=None):
        self.rowcount = rowcount
        self.rows = iter(rows or [])

    def fetchone(self):
        return next(self.rows, None)


class Conn:
    def __init__(self, results=None):
        self.results = iter(results or [])
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return next(self.results, Result())

    def commit(self):
        pass


class DB:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def master_conn(self):
        yield self.conn

    @contextmanager
    def slave_conn(self):
        yield self.conn


def test_try_claim_returns_true_when_update_succeeds():
    conn = Conn([Result(rowcount=1)])
    tracker = StateTracker(DB(conn), "instance-1")

    assert tracker.try_claim(FileRef("task", "file.csv", 123, 10, "hash")) is True
    assert "UPDATE" in conn.statements[0][0]
    assert conn.statements[0][1]["iid"] == "instance-1"


def test_try_claim_returns_false_when_other_worker_claimed():
    conn = Conn([Result(rowcount=0)])
    tracker = StateTracker(DB(conn), "instance-1")

    assert tracker.try_claim(FileRef("task", "file.csv", 123, 10, "hash")) is False


def test_mark_processing_and_success():
    conn = Conn([
        Result(rowcount=1),
        Result(rowcount=1),
        Result(rows=[Row(lid=42)]),
    ])
    tracker = StateTracker(DB(conn), "instance-1")

    assert tracker.mark_processing("task", "file.csv", 123) is True
    assert tracker.mark_success("task", "file.csv", 123, 10, 9, 25) == 42
    assert len(conn.statements) == 3


def test_failure_skip_and_archive_return_false_on_no_row():
    conn = Conn([
        Result(rowcount=0),
        Result(rowcount=0),
        Result(rowcount=0),
        Result(rowcount=0),
        Result(rowcount=0),
        Result(rowcount=0),
    ])
    tracker = StateTracker(DB(conn), "instance-1")

    assert tracker.mark_failed("task", "file.csv", 123, "ERR", "bad") == 1
    tracker.mark_skipped("task", "file.csv", 123, "empty")
    tracker.mark_archived("task", "file.csv", 123, "archive.csv")
