# TDCS — Timed Data Collection Service

实验室侧定时数据采集服务。监听指定目录的文件变化，自动完成 Extract → Transform → Load 全流程，写入 MySQL 月分区表。

## 功能特性

- **多格式支持**：CSV / JSON / Excel 流式解析，全程不积累全量数据
- **沙箱转换**：清洗代码在独立子进程中执行，不继承父进程环境变量
- **月分区路由**：按数据中的日期字段自动路由到对应月表，自动建表
- **幂等写入**：`INSERT IGNORE` 保证重复处理不产生重复数据
- **熔断器**：per-task 熔断，一个任务故障不影响其他任务
- **高可用**：乐观锁心跳选主，支持多实例部署，崩溃后自动接管
- **字段加密**：Fernet 对称加密，密钥只从环境变量读取
- **热加载配置**：校验通过才替换，失败保留旧配置
- **Web 管理 API**：任务启停、手动触发、状态查询
- **Prometheus 监控 + 钉钉告警**
- **Windows 服务**：支持 `sc start/stop ETLService`

## 架构

```
文件系统
  │  watchdog 事件 / 轮询扫描
  ▼
WorkerPool (优先级队列 + 熔断器)
  │
  ▼
ETLPipeline
  ├── StreamingExtractor   CSV / JSON / Excel
  ├── TransformSandbox     子进程隔离
  ├── Encryption           Fernet (可选)
  ├── TableRouter          月分区路由 + 自动建表
  └── Loader               INSERT IGNORE 批量写入
  │
  ▼
MySQL 月分区表
```

## 项目结构

```
.
├── src/
│   ├── main.py              # 应用入口，组装并启动所有组件
│   ├── service.py           # Windows 服务包装
│   ├── core/                # 核心引擎：配置、管线、任务管理、文件处理
│   ├── etl/                 # ETL 五阶段：提取、沙箱转换、加密、路由、加载
│   ├── infrastructure/      # 基础设施：数据库、状态追踪、HA、归档、Worker 池
│   ├── web/                 # Flask Web 层：API、认证、Swagger、SPA 前端
│   ├── watcher/             # 文件监听：watchdog 事件 + 轮询兜底
│   ├── monitoring/          # 监控告警：Prometheus 指标 + 钉钉 Webhook
│   └── utils/               # 工具：日志、文件哈希、链路追踪
├── config/                  # 配置文件（含 .example 模板）
├── alembic/                 # 数据库迁移脚本
├── clean_templates/         # 内置清洗模板
├── custom_etl/              # 用户自定义清洗模块
├── scripts/                 # 工具脚本（SQL 初始化、技能验证等）
├── sql_templates/           # 预置 SQL 模板
├── tests/                   # 测试（unit + integration）
├── docker-compose.yml       # 开发环境：MySQL 8.0 + Redis 7
├── Makefile                 # 开发命令：test / fmt / lint
├── pyproject.toml           # 项目元数据
├── start.bat / start.sh     # 一键启动脚本
└── run.bat                  # 前台运行脚本
```

## 快速开始

### 1. 启动依赖（Docker）

```bash
docker-compose up -d
```

这会启动 MySQL 8.0（端口 3306，root 密码 `root_dev_pass`，数据库 `etl_dev`）和 Redis 7（端口 6379）。

### 2. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

```bash
cp config/config.yaml.example config/config.yaml
```

编辑 `config/config.yaml`，通过环境变量提供密码：

```bash
# Windows PowerShell
$env:DB_MASTER_PASSWORD = "etl_dev_pass"
$env:WEB_SECRET_KEY = "your_secret_at_least_16_chars"

# Linux / macOS
export DB_MASTER_PASSWORD=etl_dev_pass
export WEB_SECRET_KEY=your_secret_at_least_16_chars
```

### 4. 数据库迁移

```bash
alembic upgrade head
```

### 5. 运行

```bash
python -m src.main --config config/config.yaml
```

启动后访问：
- **Web UI**：<http://127.0.0.1:8080>
- **Swagger 文档**：<http://127.0.0.1:8080/docs>
- **Prometheus 指标**：<http://127.0.0.1:8080/metrics>
- **健康检查**：<http://127.0.0.1:8080/health>

### 6. Windows 服务（可选）

```bash
python -m src.service install
sc start ETLService
```

## 配置说明

| 配置项 | 说明 |
|--------|------|
| `service.instance_id` | 实例标识，支持 `${HOSTNAME}` / `${PID}` 占位符 |
| `database.master` | 主库连接，密码必须用 `${ENV_VAR}` |
| `database.slaves` | 从库列表，为空时读操作降级到主库 |
| `concurrency.worker_threads` | Worker 线程数，默认 4 |
| `encryption.enabled` | 是否启用字段加密 |
| `high_availability.enabled` | 是否启用多实例选主 |
| `tasks[].monitor.folder_path` | 监听目录 |
| `tasks[].etl.transformer_module` | 自定义清洗模块路径 |
| `tasks[].table.base_table` | 目标表前缀，月表格式：`{base_table}_YYYYMM` |
| `tasks[].table.retention_months` | 保留月数，超期标记 ARCHIVED |
| `tasks[].error_handling.on_row_error` | 行错误策略：`skip` / `abort` |
| `tasks[].archive.mode` | 归档模式：`move` / `keep` / `delete` |

## API 端点

所有 API 在 `/api/v1/` 下，需要 JWT Bearer Token 认证。RBAC 角色：`admin` > `operator` > `viewer`。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/tasks` | GET / POST | 任务列表 / 创建 |
| `/api/v1/tasks/<id>/start` | POST | 启动任务 |
| `/api/v1/tasks/<id>/stop` | POST | 停止任务 |
| `/api/v1/tasks/<id>/trigger` | POST | 手动触发一次处理 |
| `/api/v1/files` | GET | 文件处理日志查询 |
| `/api/v1/files/<id>/retry` | POST | 重试失败文件 |
| `/api/v1/quality` | GET | 数据质量报告 |
| `/api/v1/config` | GET / PUT | 查看 / 热加载配置 |
| `/api/v1/users` | GET / POST | 用户管理 |
| `/api/v1/dashboard` | GET | 运行概览统计 |
| `/api/v1/monthly/tables` | GET | 月表列表 |
| `/api/v1/monthly/archive` | POST | 归档过期月表 |
| `/api/v1/cleaners` | GET | 已注册清洗模板列表 |
| `/api/v1/audit-logs` | GET | 审计日志 |
| `/api/v1/system/info` | GET | 系统信息（版本、运行时长） |
| `/health` | GET | 健康检查（无需认证） |
| `/metrics` | GET | Prometheus 指标（无需认证） |

完整 Swagger 文档：<http://127.0.0.1:8080/docs>

## 月表生命周期

数据按日期字段路由到 `{base_table}_YYYYMM` 格式的月表，生命周期如下：

```
ACTIVE ──(每月1日)──→ ARCHIVED ──(手动)──→ DROPPED
```

- **ACTIVE**：当前可写入，每月新建
- **ARCHIVED**：超过 `retention_months` 自动标记，不可写入
- **DROPPED**：手动物理删除，不可恢复

`retention_months` 默认为 12，可在配置中调整。

## 文件处理 & 错误处理

### 文件生命周期

```
新文件到达 → CLAIMED（原子认领）→ PROCESSING（处理中）
  ├─ SUCCESS → 归档
  ├─ FAILED  → 重试（retry_count 自增）
  │               ├─ 超 max_retries → 死信目录
  │               └─ 熔断器触发 → 暂停该任务
  └─ SKIPPED → 跳过（空文件 / 格式不支持 / 重复文件）
```

### 错误分类

| 错误类型 | 行为 |
|----------|------|
| `RetryableError` | 网络/DB 瞬时故障 → 按退避策略自动重试 |
| `FatalError` | 配置/SQL/加密错误 → 不进重试，直接死信 + 钉钉告警 |
| `SkipFileError` | 空文件/格式不支持 → 标记 SKIPPED，不重试 |
| `SandboxError` | 清洗代码语法错误/超时 → 继承 FatalError |

### 熔断器

per-task 粒度，三态切换：
- **CLOSED**：正常处理
- **OPEN**：连续失败 ≥5 次，拒绝新任务，60s 后试探
- **HALF_OPEN**：放行一个请求，成功恢复 CLOSED，失败回到 OPEN

## 自定义清洗代码

在 `custom_etl/` 目录下创建模块，函数签名：

```python
def transform(rows: list[dict]) -> list[dict]:
    """
    rows: 原始行列表
    返回: 清洗后的行列表，返回 None 的行将被过滤
    """
    result = []
    for row in rows:
        # 清洗逻辑
        result.append(row)
    return result
```

在配置中指定：

```yaml
etl:
  transformer_module: "custom_etl.my_cleaner"
  transformer_function: "transform"
```

## 开发

```bash
pip install -r requirements.txt -r requirements-dev.txt

# 运行单元测试
make test

# 代码格式化
make fmt

# 类型检查 + lint
make lint
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `DB_MASTER_PASSWORD` | 主库密码 |
| `DB_SLAVE_PASSWORD` | 从库密码（如有） |
| `REDIS_PASSWORD` | Redis 密码（如有） |
| `WEB_SECRET_KEY` | Web API JWT 签名密钥 |
| `ETL_ENCRYPTION_KEY` | Fernet 加密密钥（启用加密时必填） |
| `DINGTALK_WEBHOOK` | 钉钉告警 Webhook |
| `DINGTALK_SECRET` | 钉钉告警签名密钥 |

## 技术栈

- Python 3.10+
- SQLAlchemy 2.0 · PyMySQL · MySQL 8.0
- watchdog · ijson · openpyxl · chardet
- Flask · waitress · PyJWT
- prometheus-client
- cryptography (Fernet)

## 高可用

- **乐观锁选主**：MySQL 单行 `version` 字段 + `UPDATE WHERE version = :ver`，心跳 10s/次
- **自动故障转移**：备节点检测心跳超时 30s 后抢占
- **读写分离**：主库写入 / 从库读取，从库故障自动摘除
- **降级模式**：`standalone`（单节点强撑）/ `pause`（MySQL 不可用时停止防脑裂）
- **共享存储**：多实例需挂载同一监听目录（NFS/SMB）

## 安全

- 密码/密钥**零硬编码**：YAML 中 `${ENV_VAR}` 占位，`.env*` 已 gitignore
- **Fernet 对称加密**：敏感字段按 `encrypt_fields` 列表加密落库
- **子进程沙箱**：清洗代码在独立进程中执行，AST 扫描拦截 `import os`/`eval` 等危险调用
- **Webhook SSRF 防护**：告警 Webhook 域名白名单 + 内网 IP 阻断
- **JWT + bcrypt 认证**：`admin` / `operator` / `viewer` 三级 RBAC
- **Flask-Limiter 限流**：防暴力破解
- **表名白名单**：`TableRouter` 只允许 `[a-zA-Z0-9_]+` 防 SQL 注入
