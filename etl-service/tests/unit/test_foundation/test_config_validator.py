"""测试配置校验"""
import pytest
from src.core.config_validator import validate_config

VALID_CONFIG = {
    "service": {"instance_id": "host1_1234", "log_level": "INFO"},
    "database": {
        "master": {
            "host": "127.0.0.1", "port": 3306,
            "user": "etl_user", "password": "secret",
            "database": "etl_db",
        }
    },
    "web": {"host": "127.0.0.1", "port": 8080, "secret_key": "abc"},
    "tasks": [{
        "task_id": "order_import",
        "name": "Orders",
        "monitor": {"folder_path": "D:\\data", "file_extensions": [".csv"]},
        "etl": {
            "extractor": "csv",
            "transformer_module": "custom_etl.cleaner",
            "transformer_function": "transform",
        },
        "table": {
            "base_table": "order_data",
            "partition_field": "date",
            "create_table_template": "sql_templates/order.sql",
        },
        "error_handling": {"dead_letter_dir": "D:\\dead"},
    }],
}


def test_valid_config_passes():
    errors = validate_config(VALID_CONFIG)
    assert errors == []


def test_missing_master_db():
    cfg = {**VALID_CONFIG, "database": {}}
    errors = validate_config(cfg)
    assert any("master" in e for e in errors)


def test_ha_requires_slaves():
    cfg = {
        **VALID_CONFIG,
        "high_availability": {"enabled": True, "degraded_mode": "pause"},
    }
    errors = validate_config(cfg)
    assert any("slave" in e.lower() for e in errors)


def test_duplicate_task_ids():
    task = VALID_CONFIG["tasks"][0]
    cfg = {**VALID_CONFIG, "tasks": [task, task]}
    errors = validate_config(cfg)
    assert any("duplicate" in e.lower() or "重复" in e for e in errors)


def test_invalid_on_row_error():
    import copy
    cfg = copy.deepcopy(VALID_CONFIG)
    cfg["tasks"][0]["error_handling"]["on_row_error"] = "invalid"
    errors = validate_config(cfg)
    assert errors  # 应该有校验错误


def test_invalid_worker_threads():
    cfg = {**VALID_CONFIG, "concurrency": {"worker_threads": 0}}
    errors = validate_config(cfg)
    assert errors
