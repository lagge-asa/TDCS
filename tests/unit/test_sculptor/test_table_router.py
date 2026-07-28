"""测试 TableRouter 月表路由"""
import pytest
from unittest.mock import MagicMock, patch
from src.etl.table_router import TableRouter


def make_task_config(base_table="order_data",
                     partition_field="business_date",
                     partition_field_format="%Y-%m-%d",
                     task_id="t1",
                     create_table_template=""):
    cfg = MagicMock()
    cfg.base_table = base_table
    cfg.partition_field = partition_field
    cfg.partition_field_format = partition_field_format
    cfg.task_id = task_id
    cfg.create_table_template = create_table_template
    return cfg


def test_group_by_table_correct_month():
    db = MagicMock()
    router = TableRouter(db)
    cfg = make_task_config()
    rows = [{"business_date": "2026-01-15", "amount": 100}]
    groups = router.group_by_table(rows, cfg)
    assert "order_data_202601" in groups
    assert len(groups["order_data_202601"]) == 1


def test_group_by_table_multiple_months():
    db = MagicMock()
    router = TableRouter(db)
    cfg = make_task_config()
    rows = [
        {"business_date": "2026-01-01"},
        {"business_date": "2026-02-01"},
        {"business_date": "2026-01-31"},
    ]
    groups = router.group_by_table(rows, cfg)
    assert len(groups) == 2
    assert len(groups["order_data_202601"]) == 2
    assert len(groups["order_data_202602"]) == 1


def test_fallback_to_current_month_on_bad_date():
    from datetime import datetime
    db = MagicMock()
    router = TableRouter(db)
    cfg = make_task_config()
    rows = [{"business_date": "not-a-date"}]
    groups = router.group_by_table(rows, cfg)
    expected = "order_data_" + datetime.now().strftime("%Y%m")
    assert expected in groups


def test_fallback_when_field_missing():
    from datetime import datetime
    db = MagicMock()
    router = TableRouter(db)
    cfg = make_task_config()
    rows = [{"amount": 100}]  # no business_date
    groups = router.group_by_table(rows, cfg)
    expected = "order_data_" + datetime.now().strftime("%Y%m")
    assert expected in groups


def test_validate_table_name_injection():
    from src.etl.table_router import TableRouter
    with pytest.raises(ValueError):
        TableRouter._validate_table_name("order; DROP TABLE users--")
    with pytest.raises(ValueError):
        TableRouter._validate_table_name("1invalid")
    TableRouter._validate_table_name("order_data_202601")  # OK
