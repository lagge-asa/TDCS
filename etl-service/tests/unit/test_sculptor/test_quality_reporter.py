"""测试数据质量评分"""
import pytest
from src.monitoring.quality_reporter import QualityReporter, QualityReport


class MockDB:
    class _conn:
        def execute(self, *a, **kw): pass
        def commit(self): pass
        def rollback(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def master_conn(self): return self._conn()


@pytest.fixture
def reporter():
    return QualityReporter(MockDB())


def test_score_no_errors(reporter):
    rows = [{"a": 1}, {"a": 2}]
    r = reporter.calculate(rows, [])
    assert r.quality_score == 100.0
    assert r.total_rows == 2
    assert r.valid_rows == 2


def test_score_50pct_errors(reporter):
    rows = [{"a": i} for i in range(100)]
    errors = rows[:50]
    r = reporter.calculate(rows, errors)
    # score = max(0, 100 - 0.5*60 - 0*40) = 70
    assert r.quality_score == 70.0
    assert r.error_rate == 0.5


def test_score_50pct_errors_10pct_null(reporter):
    rows = [{"a": i, "b": None if i < 10 else i} for i in range(100)]
    errors = rows[:50]
    r = reporter.calculate(rows, errors, required_fields=["b"])
    # null_rate = 10/100 = 0.1
    # score = max(0, 100 - 0.5*60 - 0.1*40) = 100 - 30 - 4 = 66
    assert r.quality_score == 66.0


def test_score_all_errors(reporter):
    rows = [{"a": i} for i in range(10)]
    r = reporter.calculate(rows, rows)
    # score = max(0, 100 - 1.0*60) = 40
    assert r.quality_score == 40.0


def test_empty_rows(reporter):
    r = reporter.calculate([], [])
    assert r.quality_score == 100.0
    assert r.total_rows == 0
