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

## 快速开始

### 1. 启动依赖

```bash
docker-compose up -d mysql redis
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

```bash
cp config/config.yaml.example config/config.yaml
```

编辑 `config/config.yaml`，通过环境变量提供密码：

```bash
export DB_MASTER_PASSWORD=your_password
export WEB_SECRET_KEY=your_secret
```

### 4. 运行

```bash
python -m src.main --config config/config.yaml
```

### 5. Windows 服务（可选）

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
