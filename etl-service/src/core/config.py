"""
配置管理器

frozen dataclass + 原子替换 + 热加载.
密码/密钥强制走环境变量 ${VAR}.
standalone 模式仅允许单节点.
"""

import os
import re
import threading
import logging
from typing import Optional, Callable, List

from urllib.parse import quote

import yaml

from .config_models import (
    AppConfig, TaskConfig, HAConfig, WebConfig, EncryptionConfig,
    CacheConfig, CacheLocalConfig, CacheRedisConfig,
    MonitoringConfig, PrometheusConfig,
    AlertingConfig, AlertingRuleConfig, AlertingChannelConfig,
)
from .config_validator import validate_config
from .exceptions import ConfigValidationError

logger = logging.getLogger(__name__)

ConfigChangeListener = Callable[[AppConfig, AppConfig], None]


class ConfigManager:
    """配置管理器: frozen dataclass + 原子替换 + 热加载."""

    def __init__(self, config_path: str):
        self._path = config_path
        self._config: Optional[AppConfig] = None
        self._task_index: dict = {}  # task_id -> TaskConfig，O(1) 查找
        self._lock = threading.Lock()
        self._listeners: List[ConfigChangeListener] = []

    def load(self) -> None:
        """初始加载, 失败则抛异常阻止启动."""
        raw = self._read_yaml()
        errors = validate_config(raw)
        if errors:
            raise ConfigValidationError(
                "Configuration validation failed: " + str(errors))
        self._config = self._build(raw)
        self._task_index = {t.task_id: t for t in self._config.tasks}
        logger.info("Config loaded: %s, %d tasks",
                    self._config.instance_id, len(self._config.tasks))

    def reload(self) -> None:
        """热加载: 校验通过才替换, 失败保留旧配置."""
        try:
            raw = self._read_yaml()
            errors = validate_config(raw)
            if errors:
                raise ConfigValidationError(
                    "Hot-reload validation failed: " + str(errors))
            new_config = self._build(raw)
            new_task_index = {t.task_id: t for t in new_config.tasks}

            # 先在锁外执行所有 listener，记录失败
            with self._lock:
                old_config = self._config
                old_task_index = self._task_index
                listeners = list(self._listeners)

            failed = []
            for fn in listeners:
                try:
                    fn(old_config, new_config)
                except Exception as e:
                    logger.error("Config listener error [%s]: %s", fn.__name__, e)
                    failed.append(fn.__name__)

            if failed:
                # listener 失败时不更新配置，保持旧状态
                logger.warning("Hot-reload aborted: %d listener(s) failed: %s", len(failed), failed)
                raise ConfigValidationError(
                    f"Config reload aborted due to {len(failed)} listener failure(s): {failed}")

            # 全部 listener 成功，原子更新配置
            with self._lock:
                self._config = new_config
                self._task_index = new_task_index

            logger.info("Config hot-reloaded successfully")
        except Exception as e:
            logger.error("Config hot-reload failed, keeping old: %s", e)
            raise  # 让调用方（config_api）能正确返回 500

    @property
    def config(self) -> AppConfig:
        """当前配置 (frozen 对象, 读取无需锁)."""
        if self._config is None:
            raise ConfigValidationError("Configuration not loaded yet")
        return self._config

    def add_listener(self, fn: ConfigChangeListener) -> None:
        self._listeners.append(fn)

    def get_task(self, task_id: str) -> Optional[TaskConfig]:
        """O(1) 按 task_id 查找任务配置。"""
        return self._task_index.get(task_id)

    # -- internal --

    def _read_yaml(self) -> dict:
        with open(self._path, "r", encoding="utf-8") as f:
            content = f.read()

        # 跳过由 _resolve_instance_id 处理的内置模板变量，
        # 避免 HOSTNAME/PID 等非标准 env var 导致启动崩溃
        _BUILTIN_VARS = {"HOSTNAME", "PID"}

        def _env_replace(match):
            var = match.group(1)
            if var in _BUILTIN_VARS:
                return match.group(0)  # 保留原样，交给 _resolve_instance_id
            val = os.environ.get(var)
            if val is None:
                raise ConfigValidationError(
                    f"Required env var '${{{var}}}' is not set")
            return val

        content = re.sub(r'\$\{(\w+)\}', _env_replace, content)
        try:
            return yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ConfigValidationError(f"Invalid YAML: {e}") from e

    def _build(self, raw: dict) -> AppConfig:
        svc = raw["service"]
        db = raw["database"]
        cc = raw.get("concurrency", {})
        enc = raw.get("encryption", {})
        ha = raw.get("high_availability", {})
        web = raw.get("web", {})
        cache = raw.get("cache", {})
        mon = raw.get("monitoring", {})

        return AppConfig(
            instance_id=self._resolve_instance_id(svc["instance_id"]),
            log_level=svc.get("log_level", "INFO"),
            db_master_dsn=self._build_dsn(db["master"]),
            db_master_pool_size=db["master"].get("pool_size", 5),
            db_master_pool_timeout=db["master"].get("pool_timeout", 30),
            db_master_pool_recycle=db["master"].get("pool_recycle", 3600),
            db_master_connect_timeout=db["master"].get("connect_timeout", 10),
            db_slave_dsns=tuple(
                self._build_dsn(s) for s in db.get("slaves", [])),
            cache=self._build_cache(cache),
            worker_threads=cc.get("worker_threads", 4),
            queue_maxsize=cc.get("queue_maxsize", 500),
            task_timeout=cc.get("task_timeout", 300),
            encryption=EncryptionConfig(
                enabled=enc.get("enabled", False),
                algorithm=enc.get("algorithm", "fernet"),
                key_env=enc.get("key_env", "ETL_ENCRYPTION_KEY"),
            ),
            ha=HAConfig(
                enabled=ha.get("enabled", False),
                heartbeat_interval=ha.get("heartbeat_interval", 10),
                failover_timeout=ha.get("failover_timeout", 30),
                degraded_mode=ha.get("degraded_mode", "pause"),
            ),
            web=WebConfig(
                enabled=web.get("enabled", True),
                host=web.get("host", "127.0.0.1"),
                port=web.get("port", 8080),
                secret_key=web.get("secret_key", ""),
                token_expire_hours=web.get("token_expire_hours", 8),
                rate_limit=web.get("rate_limit", "200 per minute"),
                server=web.get("server", "waitress"),
                threads=web.get("threads", 4),
            ),
            monitoring=self._build_monitoring(mon),
            tasks=tuple(self._build_task(t) for t in raw.get("tasks", [])),
        )

    def _build_dsn(self, db: dict) -> str:
        user = quote(db["user"], safe="")
        password = quote(db["password"], safe="")
        return (
            "mysql+pymysql://" + user + ":" + password
            + "@" + db["host"] + ":" + str(db.get("port", 3306))
            + "/" + db["database"]
            + "?charset=utf8mb4"
        )

    def _build_cache(self, raw: dict) -> CacheConfig:
        lr = raw.get("local", {})
        rr = raw.get("redis", {})
        return CacheConfig(
            local=CacheLocalConfig(
                enabled=lr.get("enabled", True),
                maxsize=lr.get("maxsize", 1000),
                ttl=lr.get("ttl", 300),
            ),
            redis=CacheRedisConfig(
                enabled=rr.get("enabled", False),
                host=rr.get("host", "127.0.0.1"),
                port=rr.get("port", 6379),
                password=rr.get("password", ""),
                db=rr.get("db", 0),
            ),
        )

    def _build_monitoring(self, raw: dict) -> MonitoringConfig:
        pr = raw.get("prometheus", {})
        ar = raw.get("alerting", {})
        ru = ar.get("rules", {})
        chs = ar.get("channels", [])
        channels = tuple(
            AlertingChannelConfig(
                type=c.get("type", "webhook"),
                webhook=c.get("webhook", ""),
                secret=c.get("secret", ""),
            )
            for c in chs
        )
        return MonitoringConfig(
            prometheus=PrometheusConfig(
                enabled=pr.get("enabled", True),
                port=pr.get("port", 9090),
            ),
            alerting=AlertingConfig(
                enabled=ar.get("enabled", False),
                channels=channels,
                rules=AlertingRuleConfig(
                    failed_files_threshold=ru.get("failed_files_threshold", 10),
                    quality_score_min=ru.get("quality_score_min", 80.0),
                    queue_size_max=ru.get("queue_size_max", 400),
                ),
            ),
        )

    def _build_task(self, t: dict) -> TaskConfig:
        m = t["monitor"]
        e = t["etl"]
        tb = t["table"]
        eh = t["error_handling"]
        ar = t.get("archive", {})
        sc = t.get("schedule", {})
        return TaskConfig(
            task_id=t["task_id"], name=t["name"],
            enabled=t.get("enabled", True),
            priority=t.get("priority", 5),
            monitor_folder=m["folder_path"],
            file_extensions=tuple(m.get("file_extensions", [])),
            recursive=m.get("recursive", False),
            debounce_seconds=m.get("debounce_seconds", 3),
            stability_check_interval=m.get("stability_check_interval", 1),
            stability_check_count=m.get("stability_check_count", 3),
            extractor=e.get("extractor", "csv"),
            encoding=e.get("encoding", "auto"),
            stream_threshold_mb=e.get("stream_threshold_mb", 100),
            batch_size=e.get("batch_size", 1000),
            transformer_module=e["transformer_module"],
            transformer_function=e["transformer_function"],
            sandbox_timeout=e.get("sandbox_timeout", 30),
            sandbox_memory_mb=e.get("sandbox_memory_mb", 256),
            base_table=tb["base_table"],
            partition_field=tb["partition_field"],
            partition_field_format=tb.get("partition_field_format", "%Y-%m-%d"),
            create_table_template=tb.get("create_table_template", ""),
            retention_months=tb.get("retention_months", 0),
            archive_old_tables=tb.get("archive_old_tables", True),
            max_retries=eh.get("max_retries", 3),
            retry_backoff=tuple(eh.get("retry_backoff", [5, 30, 120])),
            dead_letter_dir=eh.get("dead_letter_dir", ""),
            on_row_error=eh.get("on_row_error", "skip"),
            archive_mode=ar.get("mode", "move"),
            archive_dir=ar.get("archive_dir", ""),
            retain_structure=ar.get("retain_structure", True),
            compress_after_days=ar.get("compress_after_days", 7),
            cleanup_after_days=ar.get("cleanup_after_days", 90),
            poll_interval=sc.get("poll_interval", 0),
            poll_incremental=sc.get("poll_incremental", True),
        )

    @staticmethod
    def _resolve_instance_id(template: str) -> str:
        result = template
        hostname = os.environ.get(
            "HOSTNAME", os.environ.get("COMPUTERNAME", "unknown"))
        result = result.replace("${HOSTNAME}", hostname)
        result = result.replace("${PID}", str(os.getpid()))
        return result
