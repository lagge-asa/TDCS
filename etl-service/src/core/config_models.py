"""
不可变配置数据模型

所有配置类均为 frozen dataclass, 一旦创建不可修改.
热加载时创建新对象并原子替换引用.
tasks 使用 tuple 而非 list 保证不可变.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class TaskConfig:
    """单个任务的不可变配置"""
    task_id: str
    name: str
    enabled: bool
    priority: int
    monitor_folder: str
    file_extensions: Tuple[str, ...]
    recursive: bool
    debounce_seconds: float
    stability_check_interval: float
    stability_check_count: int
    extractor: str
    encoding: str
    stream_threshold_mb: int
    batch_size: int
    transformer_module: str
    transformer_function: str
    sandbox_timeout: int
    sandbox_memory_mb: int
    base_table: str
    partition_field: str
    partition_field_format: str
    create_table_template: str
    retention_months: int
    archive_old_tables: bool
    max_retries: int
    retry_backoff: Tuple[int, ...]
    dead_letter_dir: str
    on_row_error: str
    archive_mode: str
    archive_dir: str
    retain_structure: bool
    compress_after_days: int
    cleanup_after_days: int
    poll_interval: int
    poll_incremental: bool


@dataclass(frozen=True)
class HAConfig:
    enabled: bool
    heartbeat_interval: int
    failover_timeout: int
    degraded_mode: str


@dataclass(frozen=True)
class WebConfig:
    enabled: bool
    host: str
    port: int
    secret_key: str
    token_expire_hours: int
    rate_limit: str
    server: str
    threads: int


@dataclass(frozen=True)
class EncryptionConfig:
    enabled: bool
    algorithm: str
    key_env: str


@dataclass(frozen=True)
class CacheLocalConfig:
    enabled: bool
    maxsize: int
    ttl: int


@dataclass(frozen=True)
class CacheRedisConfig:
    enabled: bool
    host: str
    port: int
    password: str
    db: int


@dataclass(frozen=True)
class CacheConfig:
    local: CacheLocalConfig
    redis: CacheRedisConfig


@dataclass(frozen=True)
class AlertingRuleConfig:
    failed_files_threshold: int
    quality_score_min: float
    queue_size_max: int


@dataclass(frozen=True)
class AlertingChannelConfig:
    type: str
    webhook: str
    secret: str


@dataclass(frozen=True)
class AlertingConfig:
    enabled: bool
    channels: Tuple[AlertingChannelConfig, ...]
    rules: AlertingRuleConfig


@dataclass(frozen=True)
class PrometheusConfig:
    enabled: bool
    port: int


@dataclass(frozen=True)
class MonitoringConfig:
    prometheus: PrometheusConfig
    alerting: AlertingConfig


@dataclass(frozen=True)
class AppConfig:
    """应用全局不可变配置"""
    instance_id: str
    log_level: str
    db_master_dsn: str
    db_master_pool_size: int
    db_master_pool_timeout: int
    db_master_pool_recycle: int
    db_master_connect_timeout: int
    db_slave_dsns: Tuple[str, ...]
    cache: CacheConfig
    worker_threads: int
    queue_maxsize: int
    task_timeout: int
    encryption: EncryptionConfig
    ha: HAConfig
    web: WebConfig
    monitoring: MonitoringConfig
    tasks: Tuple[TaskConfig, ...]
