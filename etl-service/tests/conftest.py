"""pytest 全局 fixtures"""
import pytest
import yaml
import tempfile
from pathlib import Path


MINIMAL_CONFIG = {
    "service": {"instance_id": "test_host_1", "log_level": "INFO"},
    "database": {
        "master": {
            "host": "127.0.0.1", "port": 3306,
            "user": "etl_user", "password": "etl_dev_pass",
            "database": "etl_db",
        }
    },
    "web": {"host": "127.0.0.1", "port": 8080, "secret_key": "test_secret"},
    "tasks": [{
        "task_id": "test_task",
        "name": "Test Task",
        "monitor": {
            "folder_path": "D:\\data\\test",
            "file_extensions": [".csv"],
        },
        "etl": {
            "extractor": "csv",
            "transformer_module": "custom_etl.sample_cleaner",
            "transformer_function": "transform",
        },
        "table": {
            "base_table": "test_data",
            "partition_field": "business_date",
            "create_table_template": "sql_templates/order_template.sql",
        },
        "error_handling": {"dead_letter_dir": "D:\\dead_letters\\test"},
    }],
}


@pytest.fixture
def minimal_config_dict():
    return MINIMAL_CONFIG


@pytest.fixture
def config_file(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(yaml.dump(MINIMAL_CONFIG), encoding="utf-8")
    return str(f)


@pytest.fixture
def loaded_config_manager(config_file):
    from src.core.config import ConfigManager
    cm = ConfigManager(config_file)
    cm.load()
    return cm


@pytest.fixture
def task_config(loaded_config_manager):
    return loaded_config_manager.config.tasks[0]
