"""
配置校验模块 - Pydantic v1

在 ConfigManager 加载/热加载时调用 validate_config(raw_dict),
返回错误列表, 空列表表示校验通过。
"""

import re
from typing import List, Optional
from pydantic import BaseModel, Field, validator, conint, confloat


class ServiceConfigSchema(BaseModel):
    instance_id: str
    log_level: str = "INFO"

    @validator("log_level", allow_reuse=True)
    def check_log_level(cls, v):
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got: {v}")
        return v.upper()


class DatabaseNodeSchema(BaseModel):
    host: str
    port: conint(ge=1, le=65535) = 3306
    user: str
    password: str
    database: str
    pool_size: conint(ge=1, le=100) = 5
    pool_timeout: conint(ge=5, le=300) = 30
    pool_recycle: conint(ge=300, le=86400) = 3600
    connect_timeout: conint(ge=1, le=120) = 10
    auth_plugin: str = "caching_sha2_password"


class CacheLocalSchema(BaseModel):
    enabled: bool = True
    maxsize: conint(ge=10, le=100000) = 1000
    ttl: conint(ge=10, le=86400) = 300


class CacheRedisSchema(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: conint(ge=1, le=65535) = 6379
    password: str = ""
    db: conint(ge=0, le=15) = 0


class CacheConfigSchema(BaseModel):
    local: CacheLocalSchema = CacheLocalSchema()
    redis: CacheRedisSchema = CacheRedisSchema()


class ConcurrencyConfigSchema(BaseModel):
    worker_threads: conint(ge=1, le=32) = 4
    queue_maxsize: conint(ge=10, le=10000) = 500
    task_timeout: conint(ge=10, le=3600) = 300


class EncryptionConfigSchema(BaseModel):
    enabled: bool = False
    algorithm: str = "fernet"
    key_env: str = "ETL_ENCRYPTION_KEY"


class HAConfigSchema(BaseModel):
    enabled: bool = False
    heartbeat_interval: conint(ge=3, le=120) = 10
    failover_timeout: conint(ge=10, le=300) = 30
    degraded_mode: str = "pause"

    @validator("degraded_mode", allow_reuse=True)
    def check_degraded_mode(cls, v):
        if v not in ("pause", "standalone"):
            raise ValueError("degraded_mode must be pause or standalone")
        return v


class WebConfigSchema(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: conint(ge=1, le=65535) = 8080
    secret_key: str
    token_expire_hours: conint(ge=1, le=168) = 8
    rate_limit: str = "200 per minute"
    server: str = "waitress"
    threads: conint(ge=1, le=32) = 4

    @validator("server", allow_reuse=True)
    def check_server(cls, v):
        if v not in ("waitress", "development"):
            raise ValueError("server must be waitress or development")
        return v


class PrometheusConfigSchema(BaseModel):
    enabled: bool = True
    port: conint(ge=1, le=65535) = 9090


class AlertingChannelSchema(BaseModel):
    kind: str  # maps from YAML key "type"
    webhook: str = ""
    secret: str = ""

    @validator("kind", allow_reuse=True)
    def check_kind(cls, v):
        if v not in ("dingtalk", "email", "webhook"):
            raise ValueError("channel type must be dingtalk/email/webhook")
        return v


class AlertingRuleSchema(BaseModel):
    failed_files_threshold: conint(ge=1) = 10
    quality_score_min: confloat(ge=0, le=100) = 80.0
    queue_size_max: conint(ge=10) = 400


class AlertingConfigSchema(BaseModel):
    enabled: bool = False
    channels: List[AlertingChannelSchema] = []
    rules: AlertingRuleSchema = AlertingRuleSchema()


class MonitoringConfigSchema(BaseModel):
    prometheus: PrometheusConfigSchema = PrometheusConfigSchema()
    alerting: AlertingConfigSchema = AlertingConfigSchema()


class MonitorConfigSchema(BaseModel):
    folder_path: str
    file_extensions: List[str] = Field(..., min_items=1)
    recursive: bool = False
    debounce_seconds: confloat(ge=0.5, le=60) = 3.0
    stability_check_interval: confloat(ge=0.5, le=10) = 1.0
    stability_check_count: conint(ge=1, le=10) = 3


class EtlConfigSchema(BaseModel):
    extractor: str
    encoding: str = "auto"
    stream_threshold_mb: conint(ge=1, le=10000) = 100
    batch_size: conint(ge=1, le=100000) = 1000
    transformer_module: str
    transformer_function: str
    sandbox_timeout: conint(ge=5, le=300) = 30
    sandbox_memory_mb: conint(ge=32, le=4096) = 256

    @validator("extractor", allow_reuse=True)
    def check_extractor(cls, v):
        if v not in ("csv", "json", "excel"):
            raise ValueError("extractor must be csv/json/excel")
        return v


class TableConfigSchema(BaseModel):
    base_table: str
    partition_field: str
    partition_field_format: str = "%Y-%m-%d"
    create_table_template: str
    retention_months: conint(ge=0) = 0
    archive_old_tables: bool = True

    @validator("base_table", allow_reuse=True)
    def check_base_table(cls, v):
        if not re.fullmatch(r'^[a-z][a-z0-9_]*$', v):
            raise ValueError(
                f"base_table must be lowercase alphanumeric+underscore: {v}")
        return v


class ErrorHandlingConfigSchema(BaseModel):
    max_retries: conint(ge=0, le=10) = 3
    retry_backoff: List[int] = [5, 30, 120]
    dead_letter_dir: str
    on_row_error: str = "skip"

    @validator("on_row_error", allow_reuse=True)
    def check_on_row_error(cls, v):
        if v not in ("skip", "abort"):
            raise ValueError("on_row_error must be skip or abort")
        return v


class ArchiveConfigSchema(BaseModel):
    mode: str = "move"
    archive_dir: str = ""
    retain_structure: bool = True
    compress_after_days: conint(ge=0) = 7
    cleanup_after_days: conint(ge=0) = 90

    @validator("mode", allow_reuse=True)
    def check_mode(cls, v):
        if v not in ("keep", "move", "delete"):
            raise ValueError("archive.mode must be keep/move/delete")
        return v


class ScheduleConfigSchema(BaseModel):
    poll_interval: conint(ge=0, le=86400) = 0
    poll_incremental: bool = True


class TaskConfigSchema(BaseModel):
    task_id: str
    name: str
    enabled: bool = True
    priority: conint(ge=1, le=10) = 5
    monitor: MonitorConfigSchema
    etl: EtlConfigSchema
    table: TableConfigSchema
    error_handling: ErrorHandlingConfigSchema
    archive: ArchiveConfigSchema = ArchiveConfigSchema()
    schedule: ScheduleConfigSchema = ScheduleConfigSchema()

    @validator("task_id", allow_reuse=True)
    def check_task_id(cls, v):
        if not re.fullmatch(r'^[a-z][a-z0-9_]*$', v):
            raise ValueError(
                f"task_id must be lowercase alphanumeric+underscore: {v}")
        return v


class AppConfigSchema(BaseModel):
    service: ServiceConfigSchema
    database: dict
    cache: CacheConfigSchema = CacheConfigSchema()
    concurrency: ConcurrencyConfigSchema = ConcurrencyConfigSchema()
    encryption: EncryptionConfigSchema = EncryptionConfigSchema()
    high_availability: HAConfigSchema = HAConfigSchema()
    web: WebConfigSchema
    monitoring: MonitoringConfigSchema = MonitoringConfigSchema()
    tasks: List[TaskConfigSchema] = Field(..., min_items=1)


def _normalize_raw(raw: dict) -> dict:
    """将 YAML 中 alerting.channels[].type 映射为 kind."""
    import copy
    raw = copy.deepcopy(raw)
    channels = (raw.get("monitoring", {})
                   .get("alerting", {})
                   .get("channels", []))
    for ch in channels:
        if "type" in ch and "kind" not in ch:
            ch["kind"] = ch.pop("type")
    return raw


def validate_config(raw: dict) -> List[str]:
    """校验原始配置字典, 返回错误列表. 空列表表示校验通过."""
    errors: List[str] = []
    raw = _normalize_raw(raw)

    try:
        AppConfigSchema(**raw)
    except Exception as e:
        errors.append(str(e))

    db_cfg = raw.get("database", {})
    master = db_cfg.get("master", {})
    if not master:
        errors.append("database.master is required")
    else:
        try:
            DatabaseNodeSchema(**master)
        except Exception as e:
            errors.append(f"database.master validation failed: {e}")

    for i, slave in enumerate(db_cfg.get("slaves", [])):
        try:
            DatabaseNodeSchema(**slave)
        except Exception as e:
            errors.append(f"database.slaves[{i}] validation failed: {e}")

    ha_cfg = raw.get("high_availability", {})
    if ha_cfg.get("enabled", False) and not db_cfg.get("slaves"):
        errors.append("HA mode requires at least one slave (database.slaves)")

    task_ids = [t.get("task_id") for t in raw.get("tasks", [])]
    if len(task_ids) != len(set(task_ids)):
        dup = [t for t in task_ids if task_ids.count(t) > 1]
        errors.append(f"Duplicate task_id: {dup}")

    return errors


def validate_standalone_single_node(config_dict: dict) -> Optional[str]:
    return None
