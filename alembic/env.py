"""Alembic 环境配置

从 config.yaml 读取数据库 DSN，支持环境变量占位符替换。
使用手动 migration 模式（target_metadata=None），适合 text() SQL 项目。
"""

import os
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
import yaml

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── 从 YAML 配置读取 DSN ─────────────────────────────────────────────────

_ENV_VAR_RE = re.compile(r'\$\{([^}]+)\}')


def _resolve_env_vars(value: str) -> str:
    """替换字符串中的 ${ENV_VAR} 占位符."""
    def _replacer(m):
        return os.environ.get(m.group(1), "")
    return _ENV_VAR_RE.sub(_replacer, value)


def _build_dsn(db_cfg: dict) -> str:
    """从数据库配置构建 PyMySQL DSN."""
    user = _resolve_env_vars(db_cfg.get("user", ""))
    password = _resolve_env_vars(db_cfg.get("password", ""))
    host = db_cfg.get("host", "localhost")
    port = db_cfg.get("port", 3306)
    database = db_cfg.get("database", "etl_db")
    import urllib.parse
    return (
        f"mysql+pymysql://{user}:{urllib.parse.quote_plus(password)}"
        f"@{host}:{port}/{database}?charset=utf8mb4"
    )


def _get_dsn_from_yaml() -> str:
    """从 config.yaml 读取主库 DSN."""
    config_path = os.environ.get("ETL_CONFIG", "config/config.yaml")
    if not os.path.exists(config_path):
        # fallback: 尝试相对路径
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base, "config", "config.yaml")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    db = raw.get("database", {})
    master = db.get("master", {})
    if not master:
        raise RuntimeError("database.master not found in config.yaml")
    return _build_dsn(master)


# 覆盖 sqlalchemy.url
config.set_main_option("sqlalchemy.url", _get_dsn_from_yaml())

# ── 迁移目标 ─────────────────────────────────────────────────────────────

# 无 ORM 模型，使用手动 migration 模式
target_metadata = None


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本（不连接数据库）."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接连接数据库执行迁移."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
