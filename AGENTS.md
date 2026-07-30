# AGENTS.md — TDCS

## Build & Test

```bash
# 安装依赖
pip install -r requirements.txt

# 运行全部测试（跳过预存问题的两个文件）
python -m pytest tests/ -q \
  --ignore=tests/unit/test_foundation/test_exceptions.py \
  --ignore=tests/unit/test_sculptor/test_cache.py

# 运行单个模块测试
python -m pytest tests/unit/test_pipeline/ -q

# 语法检查
python -m py_compile src/**/*.py

# 启动服务
python -m src.main
```

## 编码规范

### 类型注解
- 所有公共方法参数和返回值必须有类型注解
- 当前缺失：`file_processor.py:31 __call__`, `config.py:190 _build_task`
- 内部方法可使用 `-> None` 省略复杂类型

### 命名
- **禁止**单字母/双字母缩写字段名。`_cm` → `_config_manager`, `_st` → `_state_tracker`
- 模块级常量：`UPPER_SNAKE_CASE`
- 私有方法：`_leading_underscore`
- 魔法数字必须命名：`2000` → `_STDERR_TAIL_SIZE`, `1040` → `ERR_TOO_MANY_CONNECTIONS`

### 导入顺序
1. stdlib (`import os, logging`)
2. 第三方 (`from flask import ...`, `import yaml`)
3. 项目内部 (`from ..core.exceptions import ...`)
4. 禁止函数内延迟导入（除非解决循环依赖）

### 函数/类大小
- 函数 ≤ 50 行。超标函数：`cleaners.run_cleaner`(103), `config._build_task`(38), `config_api._build_task_dict`(46)
- 类 ≤ 300 行

### 错误处理
- API 端点：`except Exception: pass` 必须加 `logger.warning(..., exc_info=True)`
- 库代码：区分 `RetryableError` / `FatalError` / `SkipFileError`
- 不吞异常。必须有一条日志或向上传播

### 数据库
- 全部参数化查询 `text("... WHERE id = :id")` + 参数字典
- 禁止字符串拼接 SQL 值
- 新端点用 `db.master_conn()` 写、`db.slave_conn()` 读（目前同池）

## 架构规则

### 模块边界
- `etl/` — 纯数据处理，不依赖 Flask、不访问 request
- `web/api/` — 薄层：参数校验 → 调核心模块 → 返回 JSON
- `infrastructure/` — 数据库、文件系统、网络
- `core/` — 配置、流水线编排、任务调度

### 不可变配置
- `config_models.py` 中所有 dataclass 均为 `frozen=True`
- 热加载：构建新对象 → `ConfigManager._lock` 内原子替换
- 新增字段需同步 4 处：`config_models` → `config._build_task` → `config_validator` → `config_api._build_task_dict`

### 并发安全
- `task_manager._lock` 保护 `_watchers`/`_scanners` 字典
- `worker_pool._breaker_lock` 保护 `_breakers` 字典
- `state_tracker.try_claim()` 用 `INSERT ON DUPLICATE KEY` 做原子认领（无应用层锁）
- `table_router._get_table_lock()` 提供 per-table 粒度锁

### 文件处理的完整生命周期
```
文件到达 → try_claim → mark_processing → pipeline.execute
  ├─ SUCCESS → mark_success → archive → record_success
  ├─ SKIPPED → mark_skipped
  ├─ RETRY   → mark_failed → retry_count >= max? → dead_letter
  └─ FAILED  → mark_failed → record_failure → dead_letter → alert
```

### FileRef 值对象（ADR-7）
- `infrastructure/file_ref.py` — `frozen=True` dataclass，封装 `(task_id, file_path, file_mtime, file_size, file_hash)`
- `worker_pool.submit(ref, priority)` — 单参数替代 5 参数
- `file_processor.__call__(ref, breaker)` — 同理
- `state_tracker.try_claim(ref)` — 新接口，旧接口 `try_claim_legacy()` 保留过渡期
- `event_handler._emit()` / `polling_scanner._scan_impl()` — 构造 FileRef 后传递

### Extractor 格式注册表（ADR-8）
- `_FORMAT_REGISTRY: dict[str, tuple]` — 扩展名 → (方法, 描述) 映射
- 新增格式只需添加一行映射，不再修改 `stream()` 方法体

## 反模式（禁止）

| 反模式 | 替代方案 |
|--------|----------|
| `except Exception: pass` | `logger.warning(..., exc_info=True)` |
| 裸 dict 返回错误 | `jsonify({"success": False, ...})` |
| 字符串拼接 SQL | `text("... WHERE id = :id")` |
| 函数内延迟导入 | 顶层导入；循环依赖时用 TYPE_CHECKING |
| 内联正则/魔法数字 | 提取为模块级 `_CONSTANT` |
| 5 元组/3 元组在 8+ 方法间裸传 | 提炼 dataclass 值对象 |
| 复制粘贴 20+ 行相似逻辑 | 提取公共函数 |

## 相关技能

参考 `.reasonix/skills/` 下的审查技能：
- `/code-review` — 双轴审查（Standards + Spec）
- `/ponytail-review` — 找过度工程和死代码
- `/tdd` — 红-绿-重构循环
- `/diagnosing-bugs` — Bug 诊断循环

已安装 Matt Pocock 技能套件（41 个），使用 `/skill-name` 调用。
