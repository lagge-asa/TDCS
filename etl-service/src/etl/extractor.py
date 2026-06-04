"""
流式文件解析 — StreamingExtractor

CSV/JSON/Excel 逐 batch yield, 全程不积累全量数据.
内存上限: batch_size × 平均行宽 × 3
编码检测: 头部+中部各 32KB 采样
"""

import csv
import os
import logging
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


class StreamingExtractor:
    def stream(self, file_path: str, task_config) -> Iterator[list]:
        """统一流式接口, 根据文件类型自动选择策略."""
        from ..core.exceptions import SkipFileError
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
            yield from self._stream_json(file_path, batch_size)
        elif ext in (".xlsx", ".xls"):
            yield from self._stream_excel(file_path, batch_size)
        else:
            raise SkipFileError(f"Unsupported format: {ext}")

    def _detect_encoding(self, file_path: str, hint: str) -> str:
        if hint != "auto":
            return hint
        # 头部 + 中部各 32KB 采样, 不读全文件
        size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            head = f.read(32768)
            if size > 65536:
                f.seek(size // 2)
                mid = f.read(32768)
            else:
                mid = b""
        import chardet
        detected = chardet.detect(head + mid)
        return detected.get("encoding") or "utf-8"

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

    def _stream_json(self, file_path, batch_size) -> Iterator[list]:
        import ijson
        with open(file_path, "rb") as f:
            batch = []
            for item in ijson.items(f, "item"):
                batch.append(item)
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch

    def _stream_excel(self, file_path, batch_size) -> Iterator[list]:
        import openpyxl
        wb = openpyxl.load_workbook(
            file_path, read_only=True, data_only=True)
        try:
            ws = wb.active
            if ws is None:
                raise SkipFileError(f"Excel has no active sheet: {file_path}")
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
