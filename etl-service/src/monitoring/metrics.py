"""
Prometheus 指标定义 — 12 个核心指标
"""

from prometheus_client import Counter, Gauge, Histogram

# 文件处理计数
files_processed = Counter(
    "etl_files_processed_total",
    "Total files processed",
    ["task_id", "status"],
)

# 处理耗时
processing_duration = Histogram(
    "etl_processing_duration_seconds",
    "File processing duration",
    ["task_id"],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120, 300],
)

# 数据行数
rows_processed = Counter(
    "etl_rows_processed_total",
    "Total rows processed",
    ["task_id"],
)

rows_failed = Counter(
    "etl_rows_failed_total",
    "Total rows failed",
    ["task_id"],
)

# 队列状态
queue_size = Gauge(
    "etl_queue_size",
    "Current queue size",
    ["task_id"],
)

# Worker 状态
active_workers = Gauge(
    "etl_active_workers",
    "Number of active workers",
)

# 熔断器状态
circuit_breaker_state = Gauge(
    "etl_circuit_breaker_open",
    "Circuit breaker open (1=open, 0=closed)",
    ["task_id"],
)

# HA 状态
ha_active = Gauge(
    "etl_ha_active",
    "HA active instance (1=active, 0=standby)",
)

# 质量评分
quality_score = Gauge(
    "etl_quality_score",
    "Latest data quality score",
    ["task_id"],
)

# 错误计数
errors_total = Counter(
    "etl_errors_total",
    "Total errors by type",
    ["task_id", "error_type"],
)

# 归档文件数
archived_files = Counter(
    "etl_archived_files_total",
    "Total files archived",
    ["task_id"],
)

# 死信文件数
dead_letter_files = Counter(
    "etl_dead_letter_files_total",
    "Total files moved to dead letter",
    ["task_id"],
)
