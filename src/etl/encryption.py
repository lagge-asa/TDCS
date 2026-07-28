"""
字段加密模块 — Encryption

使用 Fernet 对称加密.
密钥只从环境变量读取, 无硬编码.
"""

import os
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Encryption:
    """字段加密器 — Fernet 对称加密.

    密钥仅从环境变量读取，不硬编码。
    支持按任务配置的字段列表选择性加密。
    """

    def __init__(self, config: Any) -> None:
        """config: AppConfig.encryption"""
        self._enabled: bool = config.enabled
        self._fernet: Any = None
        if self._enabled:
            self._fernet = self._load_key(config.key_env)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def encrypt_fields(self, rows: List[dict], task_config: Any) -> List[dict]:
        """加密 task_config 中指定的敏感字段."""
        if not self._enabled or not self._fernet:
            return rows
        fields: List[str] = getattr(task_config, 'encrypt_fields', [])
        if not fields:
            return rows
        result: List[dict] = []
        for row in rows:
            r = dict(row)
            for f in fields:
                if f in r and r[f] is not None:
                    r[f] = self._fernet.encrypt(
                        str(r[f]).encode()).decode()
            result.append(r)
        return result

    def decrypt_fields(self, rows: List[dict], fields: List[str]) -> List[dict]:
        """解密指定字段 (查询时调用)."""
        if not self._enabled or not self._fernet:
            return rows
        result: List[dict] = []
        for row in rows:
            r = dict(row)
            for f in fields:
                if f in r and r[f] is not None:
                    try:
                        r[f] = self._fernet.decrypt(
                            r[f].encode()).decode()
                    except Exception:
                        logger.warning("Failed to decrypt field: %s", f)
            result.append(r)
        return result

    @staticmethod
    def _load_key(key_env: str) -> Any:
        from cryptography.fernet import Fernet
        key = os.environ.get(key_env)
        if not key:
            raise ValueError(
                f"Encryption key env var '{key_env}' not set")
        return Fernet(key.encode())
