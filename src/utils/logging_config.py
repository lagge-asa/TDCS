"""
结构化 JSON 日志配置

每条日志自动注入 trace_id + task_id (来自 ContextVar).
支持日志轮转: 超过 10MB 自动切割, 保留 5 份.
"""

import json
import logging
import logging.handlers
import time
from pathlib import Path

from .trace import get_trace_id, get_task_id


class JsonFormatter(logging.Formatter):
    """将日志格式化为 JSON, 自动注入 trace_id 和 task_id."""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": get_trace_id(),
            "task_id": get_task_id(),
        }
        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)
        return json.dumps(log, ensure_ascii=False)


def setup_logging(log_level: str = "INFO",
                  log_dir: str = "logs",
                  log_file: str = "etl.log") -> None:
    """初始化日志系统.

    - 控制台: 彩色文本格式
    - 文件: JSON 格式 + 轮转 (10MB x 5)
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有 handler 防止重复
    root.handlers.clear()

    # 控制台 handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # 文件 handler (JSON + 轮转)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(Path(log_dir) / log_file),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)
