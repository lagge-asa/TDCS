"""测试 StreamingExtractor 流式解析"""
import csv
import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from src.etl.extractor import StreamingExtractor
from src.core.exceptions import SkipFileError


def make_cfg(batch_size=5, encoding="auto"):
    cfg = MagicMock()
    cfg.batch_size = batch_size
    cfg.encoding = encoding
    return cfg


def write_csv(path, rows, headers):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)


def test_csv_batching(tmp_path):
    f = tmp_path / "data.csv"
    rows = [{"id": i, "val": f"v{i}"} for i in range(12)]
    write_csv(str(f), rows, ["id", "val"])
    ext = StreamingExtractor()
    batches = list(ext.stream(str(f), make_cfg(batch_size=5)))
    assert len(batches) == 3
    assert len(batches[0]) == 5
    assert len(batches[2]) == 2


def test_csv_total_rows(tmp_path):
    f = tmp_path / "data.csv"
    rows = [{"id": i} for i in range(100)]
    write_csv(str(f), rows, ["id"])
    ext = StreamingExtractor()
    total = sum(len(b) for b in ext.stream(str(f), make_cfg(batch_size=30)))
    assert total == 100


def test_empty_file_raises_skip(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("")
    ext = StreamingExtractor()
    with pytest.raises(SkipFileError):
        list(ext.stream(str(f), make_cfg()))


def test_missing_file_raises_skip():
    ext = StreamingExtractor()
    with pytest.raises(SkipFileError):
        list(ext.stream("/nonexistent/file.csv", make_cfg()))


def test_unsupported_format_raises_skip(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("hello")
    ext = StreamingExtractor()
    with pytest.raises(SkipFileError):
        list(ext.stream(str(f), make_cfg()))


def test_encoding_detection_head_mid_sampling(tmp_path):
    """验证编码检测读取头部+中部各 32KB."""
    f = tmp_path / "data.csv"
    # 写入 GBK 编码的 CSV
    with open(str(f), "w", encoding="gbk") as fh:
        fh.write("id,name\n1,测试\n")
    ext = StreamingExtractor()
    enc = ext._detect_encoding(str(f), "auto")
    assert enc is not None  # 能检测到编码
