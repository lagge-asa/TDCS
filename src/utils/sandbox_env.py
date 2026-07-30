"""
子进程环境变量构建 — SandboxEnv

统一敏感变量过滤策略。被 transform_sandbox 和 cleaners 两处共用。
"""

import os
from typing import FrozenSet, Optional


# 精确匹配的敏感键名
SENSITIVE_KEYS: FrozenSet[str] = frozenset({
    "DB_MASTER_PASSWORD", "DB_SLAVE_PASSWORD",
    "WEB_SECRET_KEY", "SECRET_KEY",
    "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "DINGTALK_SECRET", "WECOM_KEY",
})

# 关键词包含匹配（检查 key.upper() 是否包含任一关键词）
SENSITIVE_KEYWORDS: FrozenSet[str] = frozenset({
    "ETL_", "SECRET", "PASSWORD", "PASSWD", "TOKEN",
    "API_KEY", "APIKEY", "AWS_", "ENCRYPTION", "PRIVATE",
    "CREDENTIAL", "DB_PASS", "MYSQL_", "REDIS_PASS",
})


def build_sandbox_env(
    extra_path: str = "",
    *,
    keep_system_vars: bool = True,
    extra_remove: Optional[FrozenSet[str]] = None,
) -> dict:
    """构建子进程安全环境变量。

    过滤策略（双层）：
    1. 精确匹配 SENSITIVE_KEYS 中的键名 → 删除
    2. 键名转为大写后包含 SENSITIVE_KEYWORDS 中任一关键词 → 删除

    keep_system_vars=True 时保留 Windows 系统变量（SystemRoot/PATH 等）。
    extra_path 非空时强制设置 PYTHONPATH。
    """
    env = os.environ.copy() if keep_system_vars else {}
    if not keep_system_vars:
        # 精简模式：只保留 WHITELIST 中允许的键
        for k, v in os.environ.items():
            upper = k.upper()
            if any(kw in upper for kw in SENSITIVE_KEYWORDS):
                continue
            env[k] = v

    # 精确匹配删除
    for key in list(env.keys()):
        if key in SENSITIVE_KEYS:
            del env[key]
            continue
        if keep_system_vars:
            # 双模式：精确匹配 + 关键词匹配
            if any(kw in key.upper() for kw in SENSITIVE_KEYWORDS):
                del env[key]

    if extra_remove:
        for key in extra_remove:
            env.pop(key, None)

    if extra_path:
        env["PYTHONPATH"] = extra_path

    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONINSPECT", None)
    return env
