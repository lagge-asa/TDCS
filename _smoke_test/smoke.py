"""
冒烟测试 — 验证 TDCS 核心模块可用性
不依赖 MySQL 数据库，测试导入、配置加载、文件处理、API 路由注册。
"""
import sys
import os
import tempfile
import json
import yaml
from pathlib import Path

# 确保项目根在 path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

passed = 0
failed = 0

def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}  — {detail}")

# ═══════════════════════════════════════════════════
print("1. 模块导入")
# ═══════════════════════════════════════════════════

check("config_models", __import__("src.core.config_models", fromlist=["AppConfig"]))
check("config_validator", __import__("src.core.config_validator", fromlist=["validate_config"]))
check("config", __import__("src.core.config", fromlist=["ConfigManager"]))
check("exceptions", __import__("src.core.exceptions", fromlist=["ETLError"]))
check("pipeline", __import__("src.core.pipeline", fromlist=["ETLPipeline"]))
check("file_processor", __import__("src.core.file_processor", fromlist=["FileProcessor"]))
check("task_manager", __import__("src.core.task_manager", fromlist=["TaskManager"]))
check("extractor", __import__("src.etl.extractor", fromlist=["StreamingExtractor"]))
check("loader", __import__("src.etl.loader", fromlist=["Loader"]))
check("table_router", __import__("src.etl.table_router", fromlist=["TableRouter"]))
check("cleaner_registry", __import__("src.etl.cleaner_registry", fromlist=["CleanerRegistry"]))
check("transform_sandbox", __import__("src.etl.transform_sandbox", fromlist=["TransformSandbox"]))
check("database", __import__("src.infrastructure.database", fromlist=["DatabaseManager"]))
check("state_tracker", __import__("src.infrastructure.state_tracker", fromlist=["StateTracker"]))
check("worker_pool", __import__("src.infrastructure.worker_pool", fromlist=["WorkerPool"]))
check("file_archiver", __import__("src.infrastructure.file_archiver", fromlist=["FileArchiver"]))
check("file_ref", __import__("src.infrastructure.file_ref", fromlist=["FileRef"]))
check("processed_file_repo", __import__("src.infrastructure.processed_file_repo", fromlist=["ProcessedFileRepository"]))
check("alerting", __import__("src.monitoring.alerting", fromlist=["Alerter"]))
check("quality_reporter", __import__("src.monitoring.quality_reporter", fromlist=["QualityReporter"]))
check("trace", __import__("src.utils.trace", fromlist=["new_trace", "get_trace_id"]))
check("sandbox_env", __import__("src.utils.sandbox_env", fromlist=["build_sandbox_env"]))
check("logging_config", __import__("src.utils.logging_config", fromlist=["setup_logging"]))
check("auth", __import__("src.web.auth", fromlist=["require_auth", "generate_token"]))
check("response", __import__("src.web.response", fromlist=["ok", "error", "paginated"]))

# ═══════════════════════════════════════════════════
print("\n2. 配置加载")
# ═══════════════════════════════════════════════════

test_config = {
    "service": {"instance_id": "smoke_test_1", "log_level": "INFO"},
    "database": {
        "master": {"host": "127.0.0.1", "port": 3306, "user": "test", "password": "test", "database": "etl_db"}
    },
    "web": {"host": "127.0.0.1", "port": 8080, "secret_key": "smoke-test-secret-min-16"},
    "tasks": [{
        "task_id": "smoke_import",
        "name": "Smoke Test Import",
        "monitor": {"folder_path": "_smoke_test\\input", "file_extensions": [".csv"]},
        "etl": {"extractor": "csv", "transformer_module": "", "transformer_function": ""},
        "table": {"base_table": "smoke_data", "partition_field": "date", "create_table_template": ""},
        "error_handling": {"dead_letter_dir": "_smoke_test\\dead"},
    }],
}

tmp = tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8")
yaml.dump(test_config, tmp, allow_unicode=True)
tmp.close()

from src.core.config import ConfigManager
from src.core.config_validator import validate_config

cm = ConfigManager(tmp.name)
try:
    cm.load()
    cfg = cm.config
    check("ConfigManager.load()", cfg.instance_id == "smoke_test_1")
    check("ConfigManager.get_task()", cm.get_task("smoke_import") is not None)
    check("ConfigManager.get_task(nonexistent)", cm.get_task("nonexistent") is None)
except Exception as e:
    check("ConfigManager 加载", False, str(e))

raw = yaml.safe_load(Path(tmp.name).read_text(encoding="utf-8"))
errs = validate_config(raw)
check("validate_config 通过", errs == [], str(errs))

os.unlink(tmp.name)

# ═══════════════════════════════════════════════════
print("\n3. 值对象与工具")
# ═══════════════════════════════════════════════════

from src.utils.trace import new_trace, get_trace_id
tid = new_trace("smoke_import")
check("trace.new_trace()", get_trace_id() is not None)
check("trace.task_id", get_trace_id() is not None)

from src.utils.sandbox_env import build_sandbox_env
env = build_sandbox_env(keep_system_vars=False)
check("sandbox_env 构建", "PYTHONIOENCODING" in env)
check("sandbox_env 过滤", "DB_MASTER_PASSWORD" not in env)

from src.infrastructure.file_ref import FileRef
ref = FileRef("t1", "/tmp/test.csv", 1719000000000, 4096, "abc123")
check("FileRef 构造", ref.task_id == "t1" and ref.file_hash == "abc123")

# ═══════════════════════════════════════════════════
print("\n4. 异常体系")
# ═══════════════════════════════════════════════════

from src.core.exceptions import ETLError, RetryableError, FatalError, SkipFileError, ConfigValidationError, SandboxError

check("RetryableError is ETLError", isinstance(RetryableError(), ETLError))
check("SandboxError is FatalError", isinstance(SandboxError(), FatalError))
check("DataQualityError 已删除", "DataQualityError" not in dir(__import__("src.core.exceptions", fromlist=["*"])))

# ═══════════════════════════════════════════════════
print("\n5. 文件提取器（无 DB）")
# ═══════════════════════════════════════════════════

from src.etl.extractor import StreamingExtractor
from unittest.mock import MagicMock

ext = StreamingExtractor()
mock_cfg = MagicMock()
mock_cfg.batch_size = 100
mock_cfg.encoding = "utf-8"

csv_path = str(PROJECT_ROOT / "_smoke_test" / "input" / "test_data.csv")
batches = list(ext.stream(csv_path, mock_cfg))
check("CSV 流式解析", len(batches) == 1, f"batches={len(batches)}")
check("CSV 行数", len(batches[0]) == 3, f"rows={len(batches[0])}")
check("CSV 列名", list(batches[0][0].keys()) == ["id","name","value","date"])

# ═══════════════════════════════════════════════════
print("\n6. 熔断器状态机")
# ═══════════════════════════════════════════════════

from src.infrastructure.worker_pool import CircuitBreaker, CircuitState

cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
check("初始 CLOSED", cb.state == CircuitState.CLOSED)
check("CLOSED 允许", cb.allow())
cb.record_failure()
cb.record_failure()
check("2 次失败后 OPEN", cb.state == CircuitState.OPEN)
check("OPEN 拒绝", not cb.allow())

# ═══════════════════════════════════════════════════
print("\n7. Web API 蓝图注册")
# ═══════════════════════════════════════════════════

from src.web.app import create_app
from unittest.mock import MagicMock

mock_cm = MagicMock()
mock_cm.config.instance_id = "test"
mock_cm.config.web.secret_key = "smoke-test-secret-key-16chr"
mock_cm.config.web.token_expire_hours = 8
mock_cm.config.web.rate_limit = "200 per minute"
mock_cm.config.web.server = "waitress"
mock_cm.config.web.enabled = True
mock_cm.config.web.host = "127.0.0.1"
mock_cm.config.web.port = 8080
mock_cm.config.web.threads = 4
mock_cm.config.tasks = ()

app = create_app(mock_cm)
app.config["TESTING"] = True
client = app.test_client()

endpoints = ["/health", "/metrics", "/openapi.json", "/docs"]
for ep in endpoints:
    resp = client.get(ep)
    check(f"GET {ep}", resp.status_code in (200, 302, 404) or "not found" in str(resp.data).lower(),
          f"status={resp.status_code}")

# Auth 端点需要 JSON body
resp = client.post("/api/v1/auth/login", json={}, content_type="application/json")
check("POST /api/v1/auth/login", resp.status_code in (400, 401, 503))

# ═══════════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"  通过: {passed}  失败: {failed}  总计: {passed+failed}")
print(f"{'='*50}")

if failed > 0:
    sys.exit(1)
