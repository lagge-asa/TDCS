"""
字段加密模块 — Encryption

使用 Fernet 对称加密.
密钥只从环境变量读取, 无硬编码.
"""

import os
import logging
from typing import List

logger = logging.getLogger(__name__)


class Encryption:
    def __init__(self, config):
        """config: AppConfig.encryption"""
        self._enabled = config.enabled
        self._fernet = None
        if self._enabled:
            self._fernet = self._load_key(config.key_env)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def encrypt_fields(self, rows: list, task_config) -> list:
        """加密 task_config 中指定的敏感字段."""
        if not self._enabled or not self._fernet:
            return rows
        fields = getattr(task_config, 'encrypt_fields', [])
        if not fields:
            return rows
        result = []
        for row in rows:
            r = dict(row)
            for f in fields:
                if f in r and r[f] is not None:
                    r[f] = self._fernet.encrypt(
                        str(r[f]).encode()).decode()
            result.append(r)
        return result

    def decrypt_fields(self, rows: list, fields: list) -> list:
        """解密指定字段 (查询时调用)."""
        if not self._enabled or not self._fernet:
            return rows
        result = []
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
    def _load_key(key_env: str):
        from cryptography.fernet import Fernet
        key = os.environ.get(key_env)
        if not key:
            raise ValueError(
                f"Encryption key env var '{key_env}' not set")
        return Fernet(key.encode())
