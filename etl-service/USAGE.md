# 使用说明

## 目录

1. [环境准备](#1-环境准备)
2. [数据库初始化](#2-数据库初始化)
3. [配置文件](#3-配置文件)
4. [自定义清洗代码](#4-自定义清洗代码)
5. [启动服务](#5-启动服务)
6. [Web API](#6-web-api)
7. [监控与告警](#7-监控与告警)
8. [高可用部署](#8-高可用部署)
9. [月表生命周期](#9-月表生命周期)
10. [常见问题](#10-常见问题)

---

## 1. 环境准备

**系统要求**
- Python 3.10+
- MySQL 8.0+
- （可选）Redis 7+，用于分布式缓存

**安装依赖**

```bash
pip install -r requirements.txt
```

**开发环境额外依赖**

```bash
pip install -r requirements-dev.txt
```

**使用 Docker 启动 MySQL 和 Redis（开发环境）**

```bash
docker-compose up -d mysql redis
```

---

## 2. 数据库初始化

```bash
mysql -u root -p < scripts/init_db.sql
```

初始化后会创建以下表：

| 表名 | 用途 |
|------|------|
| `users` | 用户账号与角色（RBAC） |
| `processed_files` | 文件处理状态机（核心） |
| `leader` | HA 选主锁 |
| `monthly_table_registry` | 月分区表元数据 |
| `data_quality_log` | 数据质量日志 |
| `audit_log` | 操作审计日志 |
| `config_history` | 配置变更历史 |
| `daily_statistics` | 每日统计汇总 |
| `heartbeat_history` | 实例心跳历史 |

初始管理员账号为 `admin`，**首次运行后必须修改密码**。

---

## 3. 配置文件

```bash
cp config/config.yaml.example config/config.yaml
```

**所有密码和密钥必须通过环境变量提供，不可明文写入配置文件。**

```bash
export DB_MASTER_PASSWORD=your_db_password
export WEB_SECRET_KEY=your_jwt_secret        # 建议 32 位随机字符串
export ETL_ENCRYPTION_KEY=your_fernet_key    # 启用加密时必填
export DINGTALK_WEBHOOK=https://...          # 启用钉钉告警时必填
export DINGTALK_SECRET=your_secret
```

### 3.1 数据库配置

```yaml
database:
  master:
    host: "127.0.0.1"
    port: 3306
    user: "etl_user"
    password: "${DB_MASTER_PASSWORD}"   # 引用环境变量
    database: "etl_db"
    pool_size: 5          # 连接池大小
    pool_timeout: 30      # 等待连接超时（秒）
    pool_recycle: 3600    # 连接回收周期（秒）
    connect_timeout: 10   # 建立连接超时（秒）
  slaves:                 # 从库列表，为空时读操作自动降级到主库
    - host: "slave1"
      password: "${DB_SLAVE_PASSWORD}"
      # 其余字段同 master
```

### 3.2 任务配置

每个任务对应一个监听目录，支持多任务并行。

```yaml
tasks:
  - task_id: "order_import"        # 唯一标识，不可重复
    name: "订单数据导入"
    enabled: true
    priority: 1                    # 数字越小优先级越高

    monitor:
      folder_path: "D:\\data\\orders"
      file_extensions: [".csv"]    # 只处理指定扩展名，空列表处理所有文件
      recursive: false             # 是否递归子目录
      debounce_seconds: 3          # 文件写入稳定等待时间
      stability_check_interval: 1  # 稳定性检查间隔（秒）
      stability_check_count: 3     # 连续检查次数，大小不变则认为写入完成

    etl:
      extractor: "csv"             # csv | json | excel
      encoding: "auto"             # auto 自动检测，或指定 utf-8 / gbk 等
      batch_size: 1000             # 每批处理行数
      transformer_module: "custom_etl.order_cleaner"   # 清洗模块
      transformer_function: "transform"                # 清洗函数名
      sandbox_timeout: 30          # 清洗超时（秒）
      sandbox_memory_mb: 256       # 清洗内存限制（Linux 生效）

    table:
      base_table: "order_data"           # 月表前缀，实际表名为 order_data_202501
      partition_field: "business_date"   # 用于路由月份的字段名
      partition_field_format: "%Y-%m-%d" # 字段日期格式
      create_table_template: "sql_templates/order_template.sql"  # 建表模板
      retention_months: 24         # 保留月数，0 表示永久保留

    error_handling:
      max_retries: 3               # 最大重试次数
      retry_backoff: [5, 30, 120]  # 各次重试等待秒数
      dead_letter_dir: "D:\\dead_letters\\orders"  # 超过重试次数后移入此目录
      on_row_error: "skip"         # skip（跳过错误行）| abort（回滚整批）

    archive:
      mode: "move"                 # move（归档）| keep（原地保留）| delete（删除）
      archive_dir: "D:\\archive\\orders"
      compress_after_days: 7       # N 天后压缩为 .zip
      cleanup_after_days: 90       # N 天后删除归档文件

    schedule:
      poll_interval: 60            # 轮询间隔（秒），0 表示仅用 watchdog 事件
      poll_incremental: true       # 只扫描上次轮询后新增的文件
```

### 3.3 建表模板

在 `sql_templates/` 目录下创建 SQL 文件，用 `{TABLE_NAME}` 作为表名占位符：

```sql
CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id    VARCHAR(64) NOT NULL,
    amount      DECIMAL(12,2),
    business_date DATE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_order_id (order_id),
    INDEX idx_date (business_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> 注意：模板文件只能包含**一条** `CREATE TABLE` 语句。

---

## 4. 自定义清洗代码

在 `custom_etl/` 目录下创建 Python 模块。

**函数签名**

```python
def transform(rows: list[dict]) -> list[dict]:
    """
    参数:
        rows: 原始行列表，每行为 dict，key 为列名
    返回:
        清洗后的行列表
        - 返回 None 的行会被过滤（计入 error_count）
        - 可以增减字段、修改值、拆分行
    """
    result = []
    for row in rows:
        # 过滤空行
        if not row.get("order_id"):
            result.append(None)
            continue
        # 类型转换
        row["amount"] = float(row.get("amount") or 0)
        result.append(row)
    return result
```

**注意事项**
- 清洗代码在**独立子进程**中执行，无法访问父进程的数据库连接、缓存等资源
- 不继承父进程环境变量，不要在清洗代码中读取 `os.environ`
- 超时（默认 30 秒）后进程会被强制终止，触发重试
- 语法错误会被捕获为 `SandboxError`，进入死信目录

**验证语法**

```python
from src.etl.transform_sandbox import TransformSandbox
ok, err = TransformSandbox.validate_syntax(open("custom_etl/my_cleaner.py").read())
print(ok, err)
```

---

## 5. 启动服务

### 直接运行

```bash
python -m src.main --config config/config.yaml
```

### Windows 服务

```bash
# 安装
python src/service.py install

# 启动 / 停止 / 重启
sc start ETLService
sc stop  ETLService
sc start ETLService

# 卸载
python src/service.py remove
```

### 热加载配置

修改 `config.yaml` 后，向进程发送 `SIGHUP`（Linux）或调用 API：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/config/reload \
  -H "Authorization: Bearer <token>"
```

配置校验失败时**自动保留旧配置**，不影响运行中的任务。

---

## 6. Web API

默认地址：`http://127.0.0.1:8080`

### 6.1 认证

所有接口（除 `/health`）需要 JWT Token。

```bash
# 登录获取 Token
curl -X POST http://127.0.0.1:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}'

# 响应
{"token": "eyJ..."}
```

后续请求在 Header 中携带：

```
Authorization: Bearer eyJ...
```

### 6.2 角色权限

| 角色 | 权限 |
|------|------|
| `viewer` | 查看任务、文件状态、质量报告 |
| `operator` | 在 viewer 基础上，可暂停/恢复/触发任务、重试文件 |
| `admin` | 全部权限，包括用户管理、配置热加载 |

### 6.3 接口列表

**系统**

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/health` | 无 | 健康检查 |
| GET | `/metrics` | 无 | Prometheus 指标 |
| POST | `/api/v1/auth/login` | 无 | 登录 |

**任务管理**

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/tasks` | viewer | 列出所有任务 |
| POST | `/api/v1/tasks/{task_id}/pause` | operator | 暂停任务 |
| POST | `/api/v1/tasks/{task_id}/resume` | operator | 恢复任务 |
| POST | `/api/v1/tasks/{task_id}/trigger` | operator | 立即触发扫描 |

**文件状态**

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/files` | viewer | 查询文件处理状态 |
| POST | `/api/v1/files/{file_id}/retry` | operator | 手动重试失败文件 |

**数据质量**

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/quality/{task_id}` | viewer | 查看质量报告 |

**用户管理**

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/users` | admin | 列出用户 |
| DELETE | `/api/v1/users/{user_id}` | admin | 删除用户 |

---

## 7. 监控与告警

### 7.1 Prometheus 指标

访问 `http://127.0.0.1:8080/metrics` 获取所有指标。

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `etl_files_processed_total` | Counter | 处理文件总数，按 `task_id` 和 `status` 分组 |
| `etl_processing_duration_seconds` | Histogram | 文件处理耗时分布 |
| `etl_rows_processed_total` | Counter | 处理行数 |
| `etl_rows_failed_total` | Counter | 失败行数 |
| `etl_queue_size` | Gauge | 当前队列积压数 |
| `etl_active_workers` | Gauge | 活跃 Worker 数 |
| `etl_circuit_breaker_open` | Gauge | 熔断器状态（1=开路，0=闭路） |
| `etl_ha_active` | Gauge | HA 主节点状态（1=主，0=备） |
| `etl_quality_score` | Gauge | 最新数据质量评分（0-100） |
| `etl_errors_total` | Counter | 错误总数，按错误类型分组 |
| `etl_archived_files_total` | Counter | 归档文件总数 |
| `etl_dead_letter_files_total` | Counter | 死信文件总数 |

**Prometheus 抓取配置示例**

```yaml
scrape_configs:
  - job_name: "etl-service"
    static_configs:
      - targets: ["127.0.0.1:8080"]
    metrics_path: "/metrics"
    scrape_interval: 15s
```

### 7.2 告警规则

在 `config.yaml` 中配置触发阈值：

```yaml
monitoring:
  alerting:
    enabled: true
    channels:
      - type: "dingtalk"
        webhook: "${DINGTALK_WEBHOOK}"
        secret: "${DINGTALK_SECRET}"
    rules:
      failed_files_threshold: 10    # 失败文件数超过此值触发告警
      quality_score_min: 80.0       # 质量评分低于此值触发告警
      queue_size_max: 400           # 队列积压超过此值触发告警
```

---

## 8. 高可用部署

多实例部署时，通过 MySQL 乐观锁选主，同一时刻只有一个实例处于 ACTIVE 状态处理文件。

```yaml
high_availability:
  enabled: true
  heartbeat_interval: 10    # 主节点心跳间隔（秒）
  failover_timeout: 30      # 心跳超时多少秒后备节点接管
  degraded_mode: "pause"    # MySQL 不可用时的降级策略
                            # pause: 停止处理（防脑裂，推荐）
                            # standalone: 继续处理（单节点场景）
```

**部署要求**
- 所有实例共享同一个 MySQL 数据库
- 每个实例的 `instance_id` 必须唯一（默认用 `${HOSTNAME}_${PID}` 自动区分）
- 监听目录必须是所有实例都能访问的共享存储（NFS / SMB）

**故障切换流程**

```
主节点崩溃
  → 备节点检测到心跳超时（failover_timeout 秒后）
  → 备节点通过乐观锁 UPDATE 抢占 leader 表
  → 备节点变为 ACTIVE，开始处理文件
  → 原主节点恢复后自动降为 STANDBY
```

---

## 9. 月表生命周期

数据按月自动分表，表名格式为 `{base_table}_YYYYMM`，例如 `order_data_202501`。

**自动触发**：每月 1 日 00:00 后首次启动时自动执行。

**生命周期状态**

```
ACTIVE → ARCHIVED → DROPPED
```

- `ACTIVE`：正常使用中
- `ARCHIVED`：超过 `retention_months`，标记归档（数据仍在，不删除）
- `DROPPED`：调用 `drop_archived` 后物理删除

**手动触发归档**（通过 Python）

```python
from src.etl.monthly_lifecycle import MonthlyTableLifecycle
lifecycle = MonthlyTableLifecycle(db)

# 标记超期表为 ARCHIVED（不删数据）
lifecycle.run(task_config)

# 物理 DROP 已 ARCHIVED 的表（不可恢复，谨慎操作）
lifecycle.drop_archived(task_config)
```

---

## 10. 常见问题

**Q: 文件被检测到但没有处理？**

检查以下几点：
1. 文件扩展名是否在 `file_extensions` 列表中
2. 文件是否仍在写入（等待 `debounce_seconds` + `stability_check_count` 次检查）
3. 该任务的熔断器是否已开路（查看 `etl_circuit_breaker_open` 指标）
4. HA 模式下当前实例是否为 STANDBY

**Q: 清洗代码修改后如何生效？**

清洗代码每次处理文件时都会重新加载（子进程模式），直接修改文件即可，无需重启服务。

**Q: 如何处理死信目录中的文件？**

修复数据或清洗代码后，将文件移回监听目录，服务会自动重新处理。或通过 API 手动触发重试：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/files/{file_id}/retry \
  -H "Authorization: Bearer <token>"
```

**Q: 如何生成 Fernet 加密密钥？**

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

将输出的字符串设置为环境变量 `ETL_ENCRYPTION_KEY`。

**Q: 数据库密码含特殊字符（如 `@`）怎么办？**

直接写入环境变量即可，服务会自动对密码进行 URL 编码：

```bash
export DB_MASTER_PASSWORD="p@ss/w0rd!"
```

**Q: 如何查看某个文件的处理状态？**

```sql
SELECT status, retry_count, error_type, error_message, processing_time_ms
FROM processed_files
WHERE file_path = '/path/to/file.csv'
ORDER BY created_at DESC
LIMIT 1;
```
