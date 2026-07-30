"""配置任务 API 的输入校验和安全合并测试。"""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.web.api.config_api import _merge_task_update, _validate_task_request


def test_task_request_rejects_invalid_id_and_empty_name():
    data, message = _validate_task_request({"task_id": "Bad-ID", "name": "ok"})
    assert data is None
    assert "task_id" in message

    data, message = _validate_task_request({"task_id": "valid_id", "name": "  "})
    assert data is None
    assert "name" in message


def test_task_request_accepts_nested_partial_update():
    data, message = _validate_task_request({"task_id": "valid_id", "monitor": {"recursive": True}})
    assert message is None
    assert data["monitor"]["recursive"] is True


def test_merge_task_update_preserves_unsubmitted_nested_fields():
    existing = {
        "task_id": "orders",
        "name": "订单",
        "enabled": True,
        "monitor": {
            "folder_path": "D:/in",
            "file_extensions": [".csv", ".xlsx"],
            "recursive": True,
            "debounce_seconds": 9,
        },
        "archive": {
            "mode": "move",
            "archive_dir": "D:/archive",
            "compress_after_days": 30,
        },
        "schedule": {"poll_interval": 12, "poll_incremental": False},
    }

    updated = _merge_task_update(existing, {"name": "新名称"})

    assert updated["name"] == "新名称"
    assert updated["monitor"]["folder_path"] == "D:/in"
    assert updated["monitor"]["file_extensions"] == [".csv", ".xlsx"]
    assert updated["monitor"]["recursive"] is True
    assert updated["monitor"]["debounce_seconds"] == 9
    assert updated["archive"]["mode"] == "move"
    assert updated["archive"]["archive_dir"] == "D:/archive"
    assert updated["archive"]["compress_after_days"] == 30
    assert updated["schedule"]["poll_interval"] == 12
    assert updated["schedule"]["poll_incremental"] is False
    assert updated["task_id"] == "orders"


def test_merge_task_update_rejects_task_id_change_at_api_validation():
    data, message = _validate_task_request({"task_id": "other"}, "orders")
    assert message is None
    assert data["task_id"] == "other"


@pytest.mark.parametrize("payload", [None, [], "text", 1])
def test_task_request_requires_json_object(payload):
    data, message = _validate_task_request(payload)
    assert data is None
    assert message == "请求体必须是 JSON 对象"
