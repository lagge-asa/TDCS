"""测试 TransformSandbox 子进程沙箱"""
import json
import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from src.etl.transform_sandbox import TransformSandbox
from src.core.exceptions import RetryableError, SandboxError


@pytest.fixture
def sandbox(tmp_path):
    # 创建示例清洗模块
    cleaner = tmp_path / "sample_cleaner.py"
    cleaner.write_text(
        "def transform(rows):\n"
        "    return [{**r, 'processed': True} for r in rows]\n"
    )
    return TransformSandbox(str(tmp_path))


def test_transform_success(sandbox):
    rows = [{"id": 1, "val": "a"}, {"id": 2, "val": "b"}]
    result = sandbox.transform_batch(rows, "sample_cleaner", "transform")
    assert len(result) == 2
    assert all(r["processed"] for r in result)


def test_sandbox_no_env_inheritance(sandbox, tmp_path):
    """子进程不能读取父进程的 DB_PASSWORD."""
    spy = tmp_path / "spy_cleaner.py"
    spy.write_text(
        "import os\n"
        "def transform(rows):\n"
        "    return [{'db_pass': os.environ.get('DB_PASSWORD', 'NOT_FOUND')}]\n"
    )
    os.environ["DB_PASSWORD"] = "super_secret"
    try:
        sb = TransformSandbox(str(tmp_path))
        result = sb.transform_batch([{}], "spy_cleaner", "transform")
        assert result[0]["db_pass"] == "NOT_FOUND"
    finally:
        del os.environ["DB_PASSWORD"]


def test_timeout_raises_retryable(tmp_path):
    loop = tmp_path / "loop_cleaner.py"
    loop.write_text(
        "def transform(rows):\n"
        "    while True: pass\n"
    )
    sb = TransformSandbox(str(tmp_path))
    with pytest.raises(RetryableError):
        sb.transform_batch([{}], "loop_cleaner", "transform", timeout=2)


def test_non_list_return_raises_sandbox_error(tmp_path):
    bad = tmp_path / "bad_cleaner.py"
    bad.write_text(
        "def transform(rows):\n"
        "    return {'key': 'value'}\n"
    )
    sb = TransformSandbox(str(tmp_path))
    with pytest.raises(SandboxError):
        sb.transform_batch([{}], "bad_cleaner", "transform")


def test_validate_syntax_valid():
    ok, msg = TransformSandbox.validate_syntax(
        "def transform(rows):\n    return rows\n")
    assert ok is True
    assert msg == ""


def test_validate_syntax_invalid():
    ok, msg = TransformSandbox.validate_syntax(
        "def transform(rows)\n    return rows\n")
    assert ok is False
    assert msg != ""


def test_validate_syntax_does_not_execute():
    """语法检查不执行代码."""
    import os
    marker = os.path.join(tempfile.gettempdir(), "etl_test_executed.txt")
    if os.path.exists(marker):
        os.unlink(marker)
    code = (
        f"import open; open(r'{marker}', 'w').write('executed')\n"
        "def transform(rows): return rows\n"
    )
    TransformSandbox.validate_syntax(code)
    assert not os.path.exists(marker)
