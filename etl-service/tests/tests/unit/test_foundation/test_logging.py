"""测试结构化日志 + trace_id 注入"""
import json
import logging
import tempfile
import os
import pytest
from src.utils.logging_config import setup_logging, JsonFormatter
from src.utils.trace import new_trace, get_trace_id


def test_json_formatter_includes_trace_id():
    new_trace("order_import")
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0,
        msg="hello world", args=(), exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["trace_id"] == get_trace_id()
    assert data["task_id"] == "order_import"
    assert data["msg"] == "hello world"
    assert data["level"] == "INFO"


def test_json_formatter_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="src.core.config", level=logging.ERROR,
        pathname="", lineno=0,
        msg="config error", args=(), exc_info=None,
    )
    data = json.loads(formatter.format(record))
    assert "ts" in data
    assert "logger" in data
    assert data["logger"] == "src.core.config"


def test_setup_logging_creates_file(tmp_path):
    setup_logging(log_level="DEBUG", log_dir=str(tmp_path), log_file="test.log")
    logger = logging.getLogger("test_setup")
    logger.info("test message")
    log_file = tmp_path / "test.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "test message" in content


def test_log_rotation_config(tmp_path):
    """验证 RotatingFileHandler 配置正确 (10MB, 5 份)."""
    setup_logging(log_dir=str(tmp_path))
    root = logging.getLogger()
    import logging.handlers
    rotating = [
        h for h in root.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(rotating) == 1
    assert rotating[0].maxBytes == 10 * 1024 * 1024
    assert rotating[0].backupCount == 5
