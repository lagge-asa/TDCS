# CONTEXT.md — TDCS

> 定时数据采集服务（Timed Data Collection Service）。实验室侧 ETL 中间件，监听文件变化 → Extract → Transform → Load → MySQL 月分区表。

## 领域术语表（Ubiquitous Language）

| 术语 | 含义 |
|------|------|
| **Task** | 一个 ETL 任务配置，对应一个监控目录和一组处理规则 |
| **Claim** | 高可用下某个实例原子认领一个待处理文件，防止重复处理 |
| **Pipeline** | Extract → Transform → Encrypt → Route → Load 五阶段流水线 |
| **Sandbox** | 子进程隔离执行自定义清洗代码，不继承父进程环境变量 |
| **月表 (Monthly Table)** | 按 `{base_table}_{YYYYMM}` 命名的分区表 |
| **死信 (Dead Letter)** | 超过最大重试次数后移入隔离目录的文件 |
| **熔断器 (Circuit Breaker)** | per-task 的 CLOSED → OPEN → HALF_OPEN 三态保护 |
| **热插拔 (Hot-plug)** | 清洗模板文件新增/修改/删除无需重启即生效 |
| **稳定性检查 (Stability Check)** | 连续 N 次 mtime/size 不变才确认文件写完 |
| **防抖 (Debounce)** | N 秒内重复事件只触发一次 |

## 架构地图

```
文件系统
  │  watchdog 事件 + 轮询扫描（互补兜底）
  ▼
WorkerPool (优先级队列 + per-task 熔断器)
  │
  ▼
ETLPipeline
  ├── StreamingExtractor   CSV / JSON / Excel 流式解析
  ├── TransformSandbox     子进程隔离执行清洗代码
  ├── TableRouter          按 partition_field 路由到月表 + 自动建表
  └── Loader               INSERT IGNORE 幂等批量写入
  │
  ▼
MySQL 月分区表 + processed_files 状态表
```

### 模块职责

| 模块 | 文件 | 单一职责 |
|------|------|----------|
| 配置 | `core/config.py` + `config_models.py` + `config_validator.py` | 加载/热重载/校验，frozen dataclass 原子替换 |
| 流水线 | `core/pipeline.py` | ETL 五阶段串联，逐 batch 处理 |
| 文件处理 | `core/file_processor.py` | Claim → Process → 按状态分发（成功/重试/死信） |
| 任务调度 | `core/task_manager.py` | 多任务生命周期：启停/暂停/手动触发 |
| 提取 | `etl/extractor.py` | CSV/JSON/Excel 流式解析 |
| 沙箱 | `etl/transform_sandbox.py` + `_sandbox_runner.py` | 子进程隔离 + AST 安全扫描 |
| 路由 | `etl/table_router.py` | 月分区路由 + 自动建表 + per-table 粒度锁 |
| 加载 | `etl/loader.py` | INSERT IGNORE 幂等写入 + executemany 分片 |
| 清洗模板 | `etl/cleaner_registry.py` + `_cleaner_runner.py` | 热插拔模板注册 + pandas 子进程执行 |
| 月表生命 | `etl/monthly_lifecycle.py` | 过期月表归档（DROP 未实现） |
| 数据库 | `infrastructure/database.py` | QueuePool 连接池，master/slave 同池 |
| 状态追踪 | `infrastructure/state_tracker.py` | INSERT ON DUPLICATE KEY 原子认领 + 状态机 |
| 熔断器 | `infrastructure/worker_pool.py` | 三态熔断 + 优先级队列 + Supervisor 重启 |
| 归档 | `infrastructure/file_archiver.py` | 跨分区安全移动（copy2→校验→rename→remove） |
| 告警 | `monitoring/alerting.py` | Webhook/企业微信/钉钉 多通道 |
| 质量报告 | `monitoring/quality_reporter.py` | 评分公式 + 幂等写入 |
| 链路追踪 | `utils/trace.py` | ContextVar trace_id，避免线程池串扰 |
| Web API | `web/` | Flask + JWT RBAC + Swagger |
| 文件监听 | `watcher/` | watchdog 实时 + 轮询兜底 |

## 关键设计决策（ADR）

### ADR-1: frozen dataclass + 原子替换配置
- **原因**：热加载安全。校验通过 → 构建完整新对象 → 锁内替换引用。
- **后果**：`TaskConfig` 新增字段需同步修改 4 处（config_models、config._build_task、config_validator schema、config_api._build_task_dict）。

### ADR-2: INSERT ON DUPLICATE KEY 原子认领
- **原因**：消除"先查后写"竞态。单条 SQL 完成认领，rowcount 判断成功。
- **后果**：`claimed_at`/`claim_expires_at` 的 IF 条件必须与 status 更新条件一致（已修复）。

### ADR-3: 子进程隔离清洗
- **原因**：清洗代码不应访问父进程环境变量、数据库连接、文件系统。
- **后果**：`transform_sandbox.py`（通用批处理）和 `_cleaner_runner.py`（pandas 单文件）两个入口点存在协议差异。

### ADR-4: 单连接池模式
- **原因**：当前仅单 MySQL 实例。`slave_conn()` 直接返回 `master_conn()`。
- **后果**：命名具有误导性；日后加真实只读副本时需重构。

### ADR-5: 月表 DROP 延迟
- **原因**：安全第一。先标记 ARCHIVED，确认无误后再 DROP。
- **后果**：DROP 逻辑尚未实现，当前仅归档不删除。

### ADR-6: polling scanner 兜底 watchdog
- **原因**：watchdog 可能漏事件（on_moved 缺失、内核事件队列溢出）。
- **后果**：实时性降低 ≤ poll_interval 秒，但通过 try_claim 原子去重保证不重复处理。

### ADR-7: FileRef 值对象
- **原因**：消除 `(task_id, file_path, file_mtime, file_size, file_hash)` 五元组在 7+ 模块间裸传递的数据泥团。
- **后果**：`worker_pool.submit()`、`file_processor.__call__()`、`state_tracker.try_claim()` 接口从 5-6 参数缩小到 1-2 参数。

### ADR-8: 子进程环境过滤统一 (sandbox_env.py)
- **原因**：`transform_sandbox.py` 和 `cleaners.py` 两处独立实现了敏感环境变量过滤，策略不一致。
- **后果**：统一到 `utils/sandbox_env.py` 的 `build_sandbox_env()`，双层过滤（精确键名 + 关键词包含）。

### ADR-9: ProcessedFileRepository 提取
- **原因**：processed_files 表的 DML 内聚到单一 Repository 对象。
- **后果**：`StateTracker` 不再直接写 SQL，全部委托给 `ProcessedFileRepository`。

### ADR-10: Config 三层统一计划（未实施）
- **原因**：当前配置有 frozen dataclass + Pydantic Schema + 手动 _build() 三层平行表示。新增字段需同步改 4 处。
- **计划**：以 Pydantic v2 模型替代 frozen dataclass，`_build_task()` 由 `Schema.model_dump()` 替代。风险低，与现有 config_validator.py 一致。

## 已知技术债

- `月表 DROP 未实现` — 已移至 `table_router.archive_old_tables()`
- `数据库读写分离未实现` — `database.py` 已重命名为 `read_conn()`，保留 `slave_conn` 别名
- `HA 选主未集成到 main.py` — ha_elector 未初始化
- `Swagger 覆盖率约 35%` — 26 个端点未入文档
- `test_exceptions.py` / `test_cache.py` 预存导入错误 — 需更新测试
- `Config 三层统一 Pydantic` — 已记录为 ADR-10，待实施
