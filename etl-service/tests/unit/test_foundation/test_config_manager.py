"""测试 ConfigManager 热加载 + 不可变性"""
import os
import tempfile
import pytest
import yaml
from src.core.config import ConfigManager
from src.core.exceptions import ConfigValidationError

MINIMAL_CONFIG = {
    "service": {"instance_id": "test_host_1", "log_level": "INFO"},
    "database": {
        "master": {
            "host": "127.0.0.1", "port": 3306,
            "user": "u", "password": "p", "database": "etl_db",
        }
    },
    "web": {"host": "127.0.0.1", "port": 8080, "secret_key": "secret"},
    "tasks": [{
        "task_id": "t1", "name": "Task1",
        "monitor": {"folder_path": "D:\\data", "file_extensions": [".csv"]},
        "etl": {
            "extractor": "csv",
            "transformer_module": "m", "transformer_function": "f",
        },
        "table": {
            "base_table": "tbl", "partition_field": "dt",
            "create_table_template": "t.sql",
        },
        "error_handling": {"dead_letter_dir": "D:\\dead"},
    }],
}


@pytest.fixture
def config_file(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(yaml.dump(MINIMAL_CONFIG), encoding="utf-8")
    return str(f)


def test_load_success(config_file):
    cm = ConfigManager(config_file)
    cm.load()
    assert cm.config.instance_id == "test_host_1"
    assert len(cm.config.tasks) == 1


def test_config_is_frozen(config_file):
    cm = ConfigManager(config_file)
    cm.load()
    with pytest.raises(Exception):  # FrozenInstanceError
        cm.config.worker_threads = 99


def test_tasks_is_tuple(config_file):
    cm = ConfigManager(config_file)
    cm.load()
    assert isinstance(cm.config.tasks, tuple)


def test_hot_reload_invalid_keeps_old(config_file, tmp_path):
    cm = ConfigManager(config_file)
    cm.load()
    old_config = cm.config

    # 写入非法配置
    bad = tmp_path / "config.yaml"
    bad.write_text("service:\n  instance_id: x\n", encoding="utf-8")
    cm._path = str(bad)
    cm.reload()  # 不应抛异常

    # 旧配置保留
    assert cm.config is old_config


def test_hot_reload_success_notifies_listener(config_file, tmp_path):
    cm = ConfigManager(config_file)
    cm.load()

    called = []
    cm.add_listener(lambda old, new: called.append((old, new)))

    # 写入新的合法配置 (修改 log_level)
    new_cfg = {**MINIMAL_CONFIG}
    new_cfg["service"] = {**MINIMAL_CONFIG["service"], "log_level": "DEBUG"}
    new_file = tmp_path / "config2.yaml"
    new_file.write_text(yaml.dump(new_cfg), encoding="utf-8")
    cm._path = str(new_file)
    cm.reload()

    assert len(called) == 1
    assert called[0][1].log_level == "DEBUG"


def test_get_task(config_file):
    cm = ConfigManager(config_file)
    cm.load()
    task = cm.get_task("t1")
    assert task is not None
    assert task.task_id == "t1"
    assert cm.get_task("nonexistent") is None


def test_env_var_substitution(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DB_PASS", "my_secret")
    cfg = {**MINIMAL_CONFIG}
    cfg["database"] = {
        "master": {
            "host": "127.0.0.1", "port": 3306,
            "user": "u", "password": "${TEST_DB_PASS}", "database": "etl_db",
        }
    }
    f = tmp_path / "config.yaml"
    f.write_text(yaml.dump(cfg), encoding="utf-8")
    cm = ConfigManager(str(f))
    cm.load()
    assert "my_secret" in cm.config.db_master_dsn


def test_load_fails_on_invalid_config(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("not_valid: yaml: content\n", encoding="utf-8")
    cm = ConfigManager(str(f))
    with pytest.raises(ConfigValidationError):
        cm.load()
