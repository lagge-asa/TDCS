"""
清洗模板热插拔注册中心

扫描 clean_templates/ 目录下所有 .py 文件，自动维护模板列表。
通过 watchdog 监听文件变化，新增/修改/删除均实时生效，无需重启服务。

模板规范：
- 文件名即模板名（不含 .py）
- 必须包含 def clean_data(df: pd.DataFrame) -> pd.DataFrame
- 支持任意清洗逻辑
"""

import ast
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 不扫描的文件名
_EXCLUDE = {"__init__", "__pycache__", "conftest", "setup"}


def _extract_docstring(path: Path) -> str:
    """安全读取模块级 docstring，不执行代码。"""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        return ast.get_docstring(tree) or ""
    except Exception:
        return ""


def _has_clean_data_func(path: Path) -> bool:
    """静态检查文件是否包含 def clean_data(...) 函数定义。"""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "clean_data":
                return True
        return False
    except Exception:
        return False


class TemplateInfo:
    """单个清洗模板的元信息。"""

    __slots__ = ("name", "path", "description", "mtime", "valid", "error")

    def __init__(self, name: str, path: Path):
        self.name = name
        self.path = path
        self.description = ""
        self.mtime = 0.0
        self.valid = False
        self.error = ""
        self._refresh()

    def _refresh(self):
        try:
            self.mtime = self.path.stat().st_mtime
            self.description = _extract_docstring(self.path)
            if _has_clean_data_func(self.path):
                self.valid = True
                self.error = ""
            else:
                self.valid = False
                self.error = "未找到 def clean_data(df) 函数"
        except Exception as e:
            self.valid = False
            self.error = str(e)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "file": self.path.name,
            "description": self.description or "(无说明)",
            "valid": self.valid,
            "error": self.error,
            "mtime": self.mtime,
            "mtime_str": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(self.mtime)
            ),
        }


class CleanerRegistry:
    """
    热插拔清洗模板注册中心。

    用法::

        registry = CleanerRegistry("clean_templates")
        registry.start_watching()          # 启动 watchdog
        templates = registry.list_templates()
        path = registry.get_path("deduplicate")
        registry.stop_watching()           # 服务停止时调用
    """

    def __init__(self, templates_dir: str = "clean_templates"):
        self._dir = Path(templates_dir).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._templates: Dict[str, TemplateInfo] = {}
        self._observer = None
        self._scan()

    # ------------------------------------------------------------------ #
    # 公共接口
    # ------------------------------------------------------------------ #

    def list_templates(self) -> List[dict]:
        """返回所有模板信息列表，按名称排序。"""
        with self._lock:
            return sorted(
                [t.to_dict() for t in self._templates.values()],
                key=lambda x: x["name"],
            )

    def list_valid_templates(self) -> List[dict]:
        """仅返回语法合法（含 clean_data 函数）的模板。"""
        with self._lock:
            return sorted(
                [t.to_dict() for t in self._templates.values() if t.valid],
                key=lambda x: x["name"],
            )

    def get_path(self, name: str) -> Optional[Path]:
        """获取模板脚本的绝对路径，不存在或非法返回 None。"""
        with self._lock:
            info = self._templates.get(name)
            if info and info.valid:
                return info.path
            return None

    def get_source(self, name: str) -> Optional[str]:
        """读取模板源码，供前端预览。"""
        with self._lock:
            info = self._templates.get(name)
            if not info:
                return None
        try:
            return info.path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def get_templates_dir(self) -> Path:
        return self._dir

    # ------------------------------------------------------------------ #
    # watchdog 监控
    # ------------------------------------------------------------------ #

    def start_watching(self):
        """启动 watchdog 文件系统监控，实现热插拔。"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            registry = self

            class _Handler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory:
                        registry._on_file_event(Path(event.src_path))

                def on_modified(self, event):
                    if not event.is_directory:
                        registry._on_file_event(Path(event.src_path))

                def on_deleted(self, event):
                    if not event.is_directory:
                        registry._on_file_deleted(Path(event.src_path))

                def on_moved(self, event):
                    if not event.is_directory:
                        registry._on_file_deleted(Path(event.src_path))
                        registry._on_file_event(Path(event.dest_path))

            self._observer = Observer()
            self._observer.schedule(
                _Handler(), str(self._dir), recursive=False
            )
            self._observer.start()
            logger.info(
                "CleanerRegistry: watchdog started on %s", self._dir
            )
        except Exception as e:
            logger.warning(
                "CleanerRegistry: watchdog unavailable (%s), "
                "hot-reload disabled", e
            )

    def stop_watching(self):
        """停止 watchdog。"""
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("CleanerRegistry: watchdog stopped")

    # ------------------------------------------------------------------ #
    # 内部扫描
    # ------------------------------------------------------------------ #

    def _scan(self):
        """全量扫描目录，初始化模板注册表。"""
        found = 0
        for py_file in sorted(self._dir.glob("*.py")):
            name = py_file.stem
            if name in _EXCLUDE:
                continue
            self._register(name, py_file)
            found += 1
        logger.info(
            "CleanerRegistry: scanned %d template(s) from %s",
            found, self._dir,
        )

    def _register(self, name: str, path: Path):
        with self._lock:
            info = TemplateInfo(name, path)
            self._templates[name] = info
            status = "OK" if info.valid else f"INVALID({info.error})"
            logger.debug("CleanerRegistry: register [%s] %s", name, status)

    def _on_file_event(self, path: Path):
        if path.suffix != ".py":
            return
        name = path.stem
        if name in _EXCLUDE:
            return
        logger.info("CleanerRegistry: hot-reload [%s]", name)
        self._register(name, path)

    def _on_file_deleted(self, path: Path):
        if path.suffix != ".py":
            return
        name = path.stem
        with self._lock:
            if name in self._templates:
                del self._templates[name]
                logger.info("CleanerRegistry: unregistered [%s]", name)
