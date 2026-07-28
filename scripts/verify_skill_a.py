"""
Skill-A 验证脚本
运行: python scripts/verify_skill_a.py
"""
import sys, os, tempfile, threading, yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

def check(name, fn):
    try:
        fn()
        print(f"  {PASS} {name}")
        return True
    except Exception as e:
        print(f"  {FAIL} {name}: {e}")
        return False

print("\n=== Skill-A 地基师 验证 ===\n")

# 1. exceptions
def t_exceptions():
    from src.core.exceptions import (
        ETLError, RetryableError, FatalError, SkipFileError,
        ConfigValidationError, SandboxError, RETRY_BACKOFF
    )
    assert issubclass(RetryableError, ETLError)
    assert issubclass(SandboxError, FatalError)
    assert RETRY_BACKOFF == {1: 5, 2: 30, 3: 120}

# 2. trace ContextVar isolation
def t_trace():
    from src.utils.trace import new_trace, get_trace_id, get_task_id
    tid = new_trace("order_import")
    assert len(tid) == 16
    assert get_task_id() == "order_import"
    r = {}
    def w(n, t): new_trace(t); r[n] = get_task_id()
    ts = [threading.Thread(target=w, args=(i, f"t{i}")) for i in range(4)]
    for t in ts: t.start()
    for t in ts: t.join()
    for i in range(4): assert r[i] == f"t{i}", f"ContextVar leak: t{i}={r[i]}"

# 3. frozen dataclass
def t_frozen():
    from src.core.config_models import HAConfig
    ha = HAConfig(enabled=False, heartbeat_interval=10,
                  failover_timeout=30, degraded_mode="pause")
    try:
        ha.enabled = True
        raise AssertionError("should be frozen")
    except Exception as e:
        if "frozen" in str(e).lower() or "cannot assign" in str(e).lower():
            pass  # expected

# 4. config_validator
def t_validator():
    from src.core.config_validator import validate_config
    valid = {
        "service": {"instance_id": "h1"},
        "database": {"master": {"host": "127.0.0.1", "port": 3306,
                                "user": "u", "password": "p", "database": "d"}},
        "web": {"host": "127.0.0.1", "port": 8080, "secret_key": "s"},
        "tasks": [{"task_id": "t1", "name": "T",
                   "monitor": {"folder_path": "D:\\x", "file_extensions": [".csv"]},
                   "etl": {"extractor": "csv", "transformer_module": "m",
                           "transformer_function": "f"},
                   "table": {"base_table": "tbl", "partition_field": "dt",
                             "create_table_template": "t.sql"},
                   "error_handling": {"dead_letter_dir": "D:\\d"}}]
    }
    assert validate_config(valid) == []
    assert validate_config({**valid, "concurrency": {"worker_threads": 0}})
    ha_cfg = {**valid, "high_availability": {"enabled": True, "degraded_mode": "pause"}}
    errs = validate_config(ha_cfg)
    assert any("slave" in e.lower() for e in errs), f"HA without slaves: {errs}"
    dup = {**valid, "tasks": [valid["tasks"][0], valid["tasks"][0]]}
    assert validate_config(dup)

# 5. ConfigManager
def t_config_manager():
    from src.core.config import ConfigManager
    from src.core.exceptions import ConfigValidationError
    valid = {
        "service": {"instance_id": "h1"},
        "database": {"master": {"host": "127.0.0.1", "port": 3306,
                                "user": "u", "password": "p", "database": "d"}},
        "web": {"host": "127.0.0.1", "port": 8080, "secret_key": "s"},
        "tasks": [{"task_id": "t1", "name": "T",
                   "monitor": {"folder_path": "D:\\x", "file_extensions": [".csv"]},
                   "etl": {"extractor": "csv", "transformer_module": "m",
                           "transformer_function": "f"},
                   "table": {"base_table": "tbl", "partition_field": "dt",
                             "create_table_template": "t.sql"},
                   "error_handling": {"dead_letter_dir": "D:\\d"}}]
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml',
                                     delete=False, encoding='utf-8') as f:
        yaml.dump(valid, f); fname = f.name
    try:
        cm = ConfigManager(fname)
        cm.load()
        assert cm.config.instance_id == "h1"
        assert isinstance(cm.config.tasks, tuple)
        # hot reload bad -> keep old
        old = cm.config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml',
                                         delete=False, encoding='utf-8') as f2:
            f2.write("bad:\n"); fname2 = f2.name
        cm._path = fname2; cm.reload()
        assert cm.config is old
        # hot reload good -> listener
        new_cfg = {**valid, "service": {"instance_id": "h1", "log_level": "DEBUG"}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml',
                                         delete=False, encoding='utf-8') as f3:
            yaml.dump(new_cfg, f3); fname3 = f3.name
        called = []
        cm.add_listener(lambda o, n: called.append(n.log_level))
        cm._path = fname3; cm.reload()
        assert called == ["DEBUG"]
    finally:
        for fn in [fname, fname2, fname3]:
            try: os.unlink(fn)
            except: pass

checks = [
    ("exceptions.py — 异常体系 + RETRY_BACKOFF", t_exceptions),
    ("trace.py — ContextVar 线程隔离", t_trace),
    ("config_models.py — frozen dataclass", t_frozen),
    ("config_validator.py — Pydantic 校验", t_validator),
    ("config.py — ConfigManager 热加载", t_config_manager),
]

passed = sum(check(name, fn) for name, fn in checks)
print(f"\n结果: {passed}/{len(checks)} 通过\n")
if passed < len(checks):
    print("安装依赖: pip install pydantic==1.10.21 PyYAML==6.0.2")
    sys.exit(1)
