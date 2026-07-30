"""
配置校验模块 — Pydantic v2

在 ConfigManager 加载/热加载时调用 validate_config(raw_dict),
返回错误列表, 空列表表示校验通过。
"""

import re
from typing import Annotated, List, Optional
from pydantic import BaseModel, Field, field_validator


# ── 便捷约束类型 ───────────────────────────────────────────────────────────

Port = Annotated[int, Field(ge=1, le=65535)]
PoolSize = Annotated[int, Field(ge=1, le=100)]
Seconds1to300 = Annotated[int, Field(ge=1, le=300)]
Seconds300to86400 = Annotated[int, Field(ge=300, le=86400)]


# ── Schema 定义 ────────────────────────────────────────────────────────────

class ServiceConfigSchema(BaseModel):
    instance_id: str
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def check_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got: {v}")
        return v.upper()


class DatabaseNodeSchema(BaseModel):
    host: str
    port: Port = 3306
    user: str
    password: str
    database: str
    pool_size: PoolSize = 5
    pool_timeout: Seconds1to300 = 30
    pool_recycle: Seconds300to86400 = 3600
    connect_timeout: Annotated[int, Field(ge=1, le=120)] = 10


class ConcurrencyConfigSchema(BaseModel):
    worker_threads: Annotated[int, Field(ge=1, le=32)] = 4
    queue_maxsize: Annotated[int, Field(ge=10, le=10000)] = 500
    task_timeout: Annotated[int, Field(ge=10, le=3600)] = 300


class HAConfigSchema(BaseModel):
    enabled: bool = False
    heartbeat_interval: Annotated[int, Field(ge=3, le=120)] = 10
    failover_timeout: Annotated[int, Field(ge=10, le=300)] = 30
    degraded_mode: str = "pause"

    @field_validator("degraded_mode")
    @classmethod
    def check_degraded_mode(cls, v: str) -> str:
        return v  # deprecated, kept for backward compat


class WebConfigSchema(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: Port = 8080
    secret_key: str = Field(..., min_length=16)
    token_expire_hours: Annotated[int, Field(ge=1, le=168)] = 8
    rate_limit: str = "200 per minute"
    server: str = "waitress"
    threads: Annotated[int, Field(ge=1, le=32)] = 4

    @field_validator("server")
    @classmethod
    def check_server(cls, v: str) -> str:
        if v not in ("waitress", "development"):
            raise ValueError("server must be waitress or development")
        return v


class PrometheusConfigSchema(BaseModel):
    enabled: bool = True
    port: Port = 9090


class AlertingChannelSchema(BaseModel):
    kind: str = Field("", alias="type", description="通道类型: webhook / wecom")
    webhook: str = ""
    secret: str = ""

    @field_validator("kind")
    @classmethod
    def check_kind(cls, v: str) -> str:
        if v not in ("webhook", "wecom"):
            raise ValueError("channel type must be webhook or wecom")
        return v


class AlertingRuleSchema(BaseModel):
    failed_files_threshold: Annotated[int, Field(ge=1)] = 10
    quality_score_min: Annotated[float, Field(ge=0, le=100)] = 80.0
    queue_size_max: Annotated[int, Field(ge=10)] = 400


class AlertingConfigSchema(BaseModel):
    enabled: bool = False
    channels: List[AlertingChannelSchema] = []
    rules: AlertingRuleSchema = AlertingRuleSchema()


class MonitoringConfigSchema(BaseModel):
    prometheus: PrometheusConfigSchema = PrometheusConfigSchema()
    alerting: AlertingConfigSchema = AlertingConfigSchema()


class MonitorConfigSchema(BaseModel):
    folder_path: str
    file_extensions: List[str]
    recursive: bool = False
    debounce_seconds: Annotated[float, Field(ge=0.5, le=60)] = 3.0
    stability_check_interval: Annotated[float, Field(ge=0.5, le=10)] = 1.0
    stability_check_count: Annotated[int, Field(ge=1, le=10)] = 3

    @field_validator("file_extensions")
    @classmethod
    def check_file_extensions(cls, v: List[str]) -> List[str]:
        if not v or len(v) < 1:
            raise ValueError("file_extensions must have at least 1 item")
        return v


class EtlConfigSchema(BaseModel):
    extractor: str
    encoding: str = "auto"
    batch_size: Annotated[int, Field(ge=1, le=100000)] = 1000
    transformer_module: str
    transformer_function: str
    sandbox_timeout: Annotated[int, Field(ge=5, le=300)] = 30

    @field_validator("extractor")
    @classmethod
    def check_extractor(cls, v: str) -> str:
        if v not in ("csv", "json", "excel"):
            raise ValueError("extractor must be csv/json/excel")
        return v


class TableConfigSchema(BaseModel):
    base_table: str
    partition_field: str
    partition_field_format: str = "%Y-%m-%d"
    create_table_template: str
    retention_months: Annotated[int, Field(ge=0)] = 0
    archive_old_tables: bool = True

    @field_validator("base_table")
    @classmethod
    def check_base_table(cls, v: str) -> str:
        if not re.fullmatch(r'^[a-z][a-z0-9_]*$', v):
            raise ValueError(
                f"base_table must be lowercase alphanumeric+underscore: {v}")
        return v


class ErrorHandlingConfigSchema(BaseModel):
    max_retries: Annotated[int, Field(ge=0, le=10)] = 3
    retry_backoff: List[int] = [5, 30, 120]
    dead_letter_dir: str


class ArchiveConfigSchema(BaseModel):
    mode: str = "move"
    archive_dir: str = ""
    compress_after_days: Annotated[int, Field(ge=0)] = 7
    cleanup_after_days: Annotated[int, Field(ge=0)] = 90

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v not in ("keep", "move", "delete"):
            raise ValueError("archive.mode must be keep/move/delete")
        return v


class ScheduleConfigSchema(BaseModel):
    poll_interval: Annotated[int, Field(ge=0, le=86400)] = 0
    poll_incremental: bool = True


class TaskConfigSchema(BaseModel):
    task_id: str
    name: str
    enabled: bool = True
    priority: Annotated[int, Field(ge=1, le=10)] = 5
    monitor: MonitorConfigSchema
    etl: EtlConfigSchema
    table: TableConfigSchema
    error_handling: ErrorHandlingConfigSchema
    archive: ArchiveConfigSchema = ArchiveConfigSchema()
    schedule: ScheduleConfigSchema = ScheduleConfigSchema()

    @field_validator("task_id")
    @classmethod
    def check_task_id(cls, v: str) -> str:
        if not re.fullmatch(r'^[a-z][a-z0-9_]*$', v):
            raise ValueError(
                f"task_id must be lowercase alphanumeric+underscore: {v}")
        return v


class AppConfigSchema(BaseModel):
    service: ServiceConfigSchema
    database: dict
    concurrency: ConcurrencyConfigSchema = ConcurrencyConfigSchema()
    high_availability: HAConfigSchema = HAConfigSchema()
    web: WebConfigSchema
    monitoring: MonitoringConfigSchema = MonitoringConfigSchema()
    tasks: List[TaskConfigSchema]

    @field_validator("tasks")
    @classmethod
    def check_tasks(cls, v: List[TaskConfigSchema]) -> List[TaskConfigSchema]:
        if not v or len(v) < 1:
            raise ValueError("tasks must have at least 1 item")
        return v


# ── 校验入口 ───────────────────────────────────────────────────────────────

def validate_config(raw: dict) -> List[str]:
    """校验原始配置字典, 返回错误列表. 空列表表示校验通过."""
    errors: List[str] = []

    try:
        AppConfigSchema.model_validate(raw)
    except Exception as e:
        errors.append(str(e))

    db_cfg = raw.get("database", {})
    master = db_cfg.get("master", {})
    if not master:
        errors.append("database.master is required")
    else:
        try:
            DatabaseNodeSchema.model_validate(master)
        except Exception as e:
            errors.append(f"database.master validation failed: {e}")

    for i, slave in enumerate(db_cfg.get("slaves", [])):
        try:
            DatabaseNodeSchema.model_validate(slave)
        except Exception as e:
            errors.append(f"database.slaves[{i}] validation failed: {e}")

    ha_cfg = raw.get("high_availability", {})
    if ha_cfg.get("enabled", False) and not db_cfg.get("slaves"):
        errors.append("HA mode requires at least one slave (database.slaves)")

    task_ids = [t.get("task_id") for t in raw.get("tasks", [])]
    if len(task_ids) != len(set(task_ids)):
        from collections import Counter
        dup = [t for t, c in Counter(task_ids).items() if c > 1]
        errors.append(f"Duplicate task_id: {dup}")

    return errors
