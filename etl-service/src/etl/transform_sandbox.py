"""
子进程沙箱 — TransformSandbox

清洗代码在独立子进程中执行:
- 不继承父进程环境变量 (env={} 防止密钥泄露)
- 超时后 terminate + kill, 确认资源释放
- 返回非 list 时抛 FatalError
- Windows 下 memory_mb 仅声明, 不 enforce
"""

import json
import os
import subprocess
import sys
import logging
from pathlib import Path

from ..core.exceptions import FatalError, RetryableError, SandboxError

logger = logging.getLogger(__name__)

_RUNNER = Path(__file__).parent / "_sandbox_runner.py"


class TransformSandbox:
    def __init__(self, custom_etl_dir: str):
        self.custom_etl_dir = custom_etl_dir

    def transform_batch(self, rows: list, module: str, func: str,
                        timeout: int = 30,
                        memory_mb: int = 256) -> list:
        """在子进程中执行清洗代码.

        memory_mb: Windows 下仅声明, 不通过 resource 限制.
        """
        payload = json.dumps(rows, ensure_ascii=False)
        try:
            proc = subprocess.Popen(
                [sys.executable, str(_RUNNER),
                 module, func, self.custom_etl_dir],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    "PYTHONPATH": self.custom_etl_dir,
                    "PYTHONIOENCODING": "utf-8",
                },
                text=True, encoding="utf-8",
                bufsize=-1,  # 全缓冲，防止单行大 JSON 撑满管道缓冲区导致死锁
            )
        except OSError as e:
            raise RetryableError(f"Failed to start sandbox process: {e}")
        try:
            stdout, stderr = proc.communicate(
                input=payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise RetryableError(
                f"Transform timed out (>{timeout}s)")

        if proc.returncode != 0:
            raise SandboxError(
                f"Transform failed: {stderr[:500]}")

        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            raise SandboxError(
                f"Transform returned invalid JSON: {stdout[:200]}")

        if not isinstance(result, list):
            raise SandboxError(
                "Transform function must return a list, "
                f"got {type(result).__name__}")
        return result

    @staticmethod
    def validate_syntax(code: str) -> tuple:
        """语法检查, 不执行代码."""
        import py_compile
        import tempfile
        with tempfile.NamedTemporaryFile(
                suffix=".py", mode="w",
                encoding="utf-8", delete=False) as f:
            f.write(code)
            tmp = f.name
        try:
            py_compile.compile(tmp, doraise=True)
            return True, ""
        except py_compile.PyCompileError as e:
            return False, str(e)
        finally:
            os.unlink(tmp)
