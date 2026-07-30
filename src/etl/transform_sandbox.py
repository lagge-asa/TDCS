"""
子进程沙箱 — TransformSandbox

清洗代码在独立子进程中执行:
- 基于 os.environ.copy() 过滤敏感变量（而非 env={}），保留 Windows 必要系统变量
- 超时后 kill() 跨平台可靠终止
- stderr 保留尾部 2000 字符（根因通常在末尾）
- validate_syntax: py_compile 语法检查 + AST 危险调用扫描
"""

import ast
import json
import os
import subprocess
import sys
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.exceptions import FatalError, RetryableError, SandboxError
from ..utils.sandbox_env import build_sandbox_env

logger = logging.getLogger(__name__)

_RUNNER = Path(__file__).parent / "_sandbox_runner.py"
_STDERR_TAIL_SIZE = 2000

# 沙箱中禁止使用的危险调用（模块名或函数名）
_DANGEROUS_CALLS = frozenset({
    "os", "sys", "subprocess", "shutil", "socket", "urllib",
    "requests", "http", "ftplib", "smtplib", "pickle", "marshal",
    "importlib", "ctypes", "eval", "exec", "__import__",
    "open", "builtins",
})


class TransformSandbox:
    """清洗沙箱 — 子进程隔离执行自定义清洗代码."""

    def __init__(self, custom_etl_dir: str) -> None:
        self.custom_etl_dir: str = custom_etl_dir
        self._env = build_sandbox_env(extra_path=custom_etl_dir)

    def transform_batch(self, rows: List[dict], module: str, func: str,
                        timeout: int = 30) -> List[dict]:
        """在子进程中执行清洗代码."""
        payload = json.dumps(rows, ensure_ascii=False)
        try:
            proc = subprocess.Popen(
                [sys.executable, str(_RUNNER),
                 module, func, self.custom_etl_dir],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._env,
                text=True, encoding="utf-8",
                bufsize=-1,  # 全缓冲，防止单行大 JSON 撑满管道缓冲区导致死锁
            )
        except OSError as e:
            raise RetryableError(f"Failed to start sandbox process: {e}")

        try:
            stdout, stderr = proc.communicate(input=payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            # kill() 在 Windows/Linux 均可靠终止进程
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise RetryableError(f"Transform timed out (>{timeout}s)")

        if proc.returncode != 0:
            # 保留尾部 2000 字符，根因通常在末尾
            tail = stderr[-_STDERR_TAIL_SIZE:] if len(stderr) > _STDERR_TAIL_SIZE else stderr
            raise SandboxError(f"Transform failed: {tail}")

        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            preview = stdout[:200]
            raise SandboxError(
                f"Transform returned invalid JSON: {preview}")

        if not isinstance(result, list):
            raise SandboxError(
                "Transform function must return a list, "
                f"got {type(result).__name__}")
        return result

    @staticmethod
    def validate_syntax(code: str) -> tuple:
        """语法检查 + AST 危险调用扫描，不执行代码.

        返回 (ok: bool, message: str)。
        """
        import py_compile
        import tempfile

        # 1. 语法检查
        with tempfile.NamedTemporaryFile(
                suffix=".py", mode="w",
                encoding="utf-8", delete=False) as f:
            f.write(code)
            tmp = f.name
        try:
            py_compile.compile(tmp, doraise=True)
        except py_compile.PyCompileError as e:
            return False, f"SyntaxError: {e}"
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

        # 2. AST 危险调用扫描
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"

        violations = []
        for node in ast.walk(tree):
            # import os / import subprocess 等
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [alias.name.split(".")[0] for alias in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module.split(".")[0]] if node.module else [])
                )
                for name in names:
                    if name in _DANGEROUS_CALLS:
                        violations.append(
                            f"禁止 import '{name}'（行 {node.lineno}）")
            # eval(...) / exec(...) / __import__(...) 等直接调用
            elif isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name and func_name in _DANGEROUS_CALLS:
                    violations.append(
                        f"禁止调用 '{func_name}'（行 {node.lineno}）")

        if violations:
            return False, "危险调用: " + "; ".join(violations)

        return True, ""
