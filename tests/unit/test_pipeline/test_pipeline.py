"""测试 ETLPipeline 流式编排"""
import pytest
from unittest.mock import MagicMock, patch
from src.core.pipeline import ETLPipeline, PipelineStatus, PipelineResult
from src.core.exceptions import SkipFileError, RetryableError, FatalError


def make_task_config():
    cfg = MagicMock()
    cfg.transformer_module = "m"
    cfg.transformer_function = "f"
    cfg.sandbox_timeout = 30
    cfg.sandbox_memory_mb = 256
    cfg.partition_field = "date"
    cfg.partition_field_format = "%Y-%m-%d"
    cfg.base_table = "tbl"
    cfg.task_id = "t1"
    return cfg


def make_pipeline(extractor_batches, transform_result=None,
                  extractor_error=None, transform_error=None):
    extractor = MagicMock()
    if extractor_error:
        extractor.stream.side_effect = extractor_error
    else:
        extractor.stream.return_value = iter(extractor_batches)

    sandbox = MagicMock()
    if transform_error:
        sandbox.transform_batch.side_effect = transform_error
    else:
        sandbox.transform_batch.side_effect = (
            lambda rows, *a, **kw: transform_result or rows)

    router = MagicMock()
    router.group_by_table.return_value = {"tbl_202601": []}
    loader = MagicMock()
    loader.load_batch.return_value = 0

    return ETLPipeline(extractor, sandbox, router, loader)


def test_success_flow():
    rows = [{"id": i} for i in range(10)]
    p = make_pipeline([rows])
    result = p.execute("file.csv", make_task_config())
    assert result.status == PipelineStatus.SUCCESS
    assert result.raw_count == 10


def test_skip_file_error():
    p = make_pipeline([], extractor_error=SkipFileError("empty"))
    result = p.execute("file.csv", make_task_config())
    assert result.status == PipelineStatus.SKIPPED


def test_retryable_error():
    p = make_pipeline([[{"id": 1}]],
                      transform_error=RetryableError("timeout"))
    result = p.execute("file.csv", make_task_config())
    assert result.status == PipelineStatus.RETRY


def test_fatal_error():
    p = make_pipeline([[{"id": 1}]],
                      transform_error=FatalError("bad code"))
    result = p.execute("file.csv", make_task_config())
    assert result.status == PipelineStatus.FAILED


def test_multiple_batches():
    batches = [[{"id": i} for i in range(5)] for _ in range(3)]
    p = make_pipeline(batches)
    result = p.execute("file.csv", make_task_config())
    assert result.raw_count == 15


def test_elapsed_ms_set():
    p = make_pipeline([[{"id": 1}]])
    result = p.execute("file.csv", make_task_config())
    assert result.elapsed_ms >= 0
