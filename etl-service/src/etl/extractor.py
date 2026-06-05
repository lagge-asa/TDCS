"""
流式文件解析 — StreamingExtractor

CSV/JSON/Excel 逐 batch yield, 全程不积累全量数据.
内存上限: batch_size × 平均行宽 × 3
编码检测: 头部+中部各 32KB 采样

优化:
- SkipFileError 顶层 import（消除函数体内动态 import 开销）
- chardet 低置信度（<0.5）时 fallback 到 utf-8 并记录 warning
- _stream_json 支持 task_config.json_path 配置（默认 "item"）
- _stream_excel 捕获 PermissionError/OSError 给出友好提示
"""

import csv
import os
import logging
from pathlib import Path
from typing import Iterator

from ..core.exceptions import SkipFileError

logger = logging.getLogger(__name__)

# chardet 置信度低于此阈值时 fallback 到 utf-8
_MIN_CHARDET_CONFIDENCE = 0.5


class StreamingExtractor:
    def stream(self, file_path: str, task_config) -> Iterator[list]:
        """统一流式接口, 根据文件类型自动选择策略."""
        if not os.path.exists(file_path):
            raise SkipFileError(f"File not found: {file_path}")
        if os.path.getsize(file_path) == 0:
            raise SkipFileError(f"Empty file: {file_path}")

        ext = Path(file_path).suffix.lower()
        batch_size = task_config.batch_size
        encoding = self._detect_encoding(file_path, task_config.encoding)

        if ext == ".csv":
            yield from self._stream_csv(file_path, encoding, batch_size)
        elif ext == ".json":
            json_path = getattr(task_config, "json_path", "item")
            yield from self._stream_json(file_path, batch_size, json_path)
        elif ext in (".xlsx", ".xls"):
            yield from self._stream_excel(file_path, batch_size)
        else:
            raise SkipFileError(f"Unsupported format: {ext}")

    def _detect_encoding(self, file_path: str, hint: str) -> str:
        """检测文件编码.

        hint != 'auto' 时直接返回 hint。
        chardet 置信度 < 0.5 时 fallback 到 utf-8。
        """
        if hint != "auto":
            return hint

        size = os.path.getsize(file_path)
        try:
            import chardet
        except ImportError:
            logger.warning(
                "chardet not installed, falling back to utf-8 for %s",
                file_path)
            return "utf-8"

        # 头部 + 中部各 32KB 采样，不读全文件
        with open(file_path, "rb") as f:
            head = f.read(32768)
            mid = b""
            if size > 65536:
                f.seek(size // 2)
                mid = f.read(32768)

        detected = chardet.detect(head + mid)
        encoding = detected.get("encoding")
        confidence = detected.get("confidence", 0.0) or 0.0

        if not encoding or confidence < _MIN_CHARDET_CONFIDENCE:
            logger.warning(
                "Low chardet confidence (%.2f) for %s, falling back to utf-8",
                confidence, file_path)
            return "utf-8"

        return encoding

    def _stream_csv(self, file_path, encoding, batch_size) -> Iterator[list]:
        with open(file_path, "r", encoding=encoding,
                  errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            batch = []
            for row in reader:
                batch.append(dict(row))
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch

    def _stream_json(self, file_path, batch_size,
                     json_path: str = "item") -> Iterator[list]:
        """流式解析 JSON 文件.

        json_path: ijson 路径表达式，默认 "item"（顶层数组）。
        如顶层结构为 {"data": [...]}，可配置 json_path="data.item"。
        """
        try:
            import ijson
        except ImportError:
            raise SkipFileError(
                "ijson not installed, cannot parse JSON files")

        with open(file_path, "rb") as f:
            batch = []
            try:
                for item in ijson.items(f, json_path):
                    batch.append(item)
                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
            except Exception as e:
                raise SkipFileError(
                    f"JSON parse error in {file_path} "
                    f"(json_path='{json_path}'): {e}")
            if batch:
                yield batch

    def _stream_excel(self, file_path, batch_size) -> Iterator[list]:
        try:
            import openpyxl
        except ImportError:
            raise SkipFileError(
                "openpyxl not installed, cannot parse Excel files")

        try:
            wb = openpyxl.load_workbook(
                file_path, read_only=True, data_only=True)
        except PermissionError:
            raise SkipFileError(
                f"Excel file is locked by another process: {file_path}")
        except Exception as e:
            raise SkipFileError(
                f"Failed to open Excel file {file_path}: {e}")

        try:
            ws = wb.active
            if ws is None:
                raise SkipFileError(
                    f"Excel has no active sheet: {file_path}")
            headers = None
            batch = []
            for row in ws.iter_rows(values_only=True):
                if headers is None:
                    headers = [
                        str(c) if c is not None else f"col_{i}"
                        for i, c in enumerate(row)
                    ]
                    continue
                batch.append(dict(zip(headers, row)))
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch
        finally:
            wb.close()
