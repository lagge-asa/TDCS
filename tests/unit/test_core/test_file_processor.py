"""FileProcessor 生命周期测试。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core.file_processor import FileProcessor
from src.core.pipeline import PipelineResult, PipelineStatus
from src.infrastructure.file_ref import FileRef


@pytest.fixture
def file_ref():
    return FileRef("test_task", "/tmp/input.csv", 1000, 12, "hash")


def make_processor(task_config, result):
    state = MagicMock()
    state.try_claim.return_value = True
    state.mark_processing.return_value = True
    state.mark_failed.return_value = 1
    pipeline = MagicMock()
    pipeline.execute.return_value = result
    factory = MagicMock(return_value=pipeline)
    archiver = MagicMock()
    breaker = MagicMock()
    processor = FileProcessor(
        MagicMock(get_task=MagicMock(return_value=task_config)),
        state,
        factory,
        MagicMock(),
        archiver,
        task_manager=MagicMock(),
    )
    return processor, state, pipeline, archiver, breaker


def test_success_marks_success_and_archives(task_config, file_ref):
    result = PipelineResult(PipelineStatus.SUCCESS, raw_count=3, valid_count=2, elapsed_ms=8)
    processor, state, pipeline, archiver, breaker = make_processor(task_config, result)
    state.mark_success.return_value = 42
    archiver.archive_after_success.return_value = "/archive/input.csv"

    processor(file_ref, breaker)

    state.try_claim.assert_called_once()
    state.mark_processing.assert_called_once_with("test_task", file_ref.file_path, file_ref.file_mtime)
    state.mark_success.assert_called_once_with("test_task", file_ref.file_path, 1000, 3, 2, 8)
    archiver.archive_after_success.assert_called_once()
    state.mark_archived.assert_called_once_with(
        "test_task", file_ref.file_path, 1000, "/archive/input.csv"
    )
    breaker.record_success.assert_called_once()


def test_skipped_marks_skipped_without_breaker(task_config, file_ref):
    result = PipelineResult(PipelineStatus.SKIPPED, error=ValueError("bad row"))
    processor, state, _, archiver, breaker = make_processor(task_config, result)

    processor(file_ref, breaker)

    state.mark_skipped.assert_called_once_with(
        "test_task", file_ref.file_path, 1000, "bad row"
    )
    archiver.archive_after_success.assert_not_called()
    breaker.record_success.assert_not_called()


def with_retries(task_config, max_retries):
    from dataclasses import replace
    return replace(task_config, max_retries=max_retries)


def test_retry_marks_failed_and_does_not_dead_letter_before_limit(task_config, file_ref):
    task_config = with_retries(task_config, 3)
    result = PipelineResult(PipelineStatus.RETRY, error=TimeoutError("temporary"))
    processor, state, _, _, breaker = make_processor(task_config, result)
    processor._task_manager.move_to_dead_letter.reset_mock()

    processor(file_ref, breaker)

    state.mark_failed.assert_called_once()
    processor._task_manager.move_to_dead_letter.assert_not_called()
    breaker.record_failure.assert_not_called()


def test_retry_moves_to_dead_letter_at_limit(task_config, file_ref):
    task_config = with_retries(task_config, 3)
    result = PipelineResult(PipelineStatus.RETRY, error=TimeoutError("temporary"))
    processor, state, _, _, breaker = make_processor(task_config, result)
    state.mark_failed.return_value = 3

    processor(file_ref, breaker)

    processor._task_manager.move_to_dead_letter.assert_called_once_with(
        "test_task", file_ref.file_path
    )


def test_failed_marks_failed_and_notifies(task_config, file_ref):
    result = PipelineResult(PipelineStatus.FAILED, error=RuntimeError("fatal"))
    processor, state, _, _, breaker = make_processor(task_config, result)

    processor(file_ref, breaker)

    state.mark_failed.assert_called_once()
    processor._task_manager.move_to_dead_letter.assert_called_once_with(
        "test_task", file_ref.file_path
    )
    breaker.record_failure.assert_called_once()


def test_claim_race_skips_processing(task_config, file_ref):
    result = PipelineResult(PipelineStatus.SUCCESS)
    processor, state, pipeline, _, breaker = make_processor(task_config, result)
    state.try_claim.return_value = False

    processor(file_ref, breaker)

    pipeline.execute.assert_not_called()
    state.mark_processing.assert_not_called()


def test_pipeline_exception_marks_failed(task_config, file_ref):
    processor, state, pipeline, _, breaker = make_processor(
        task_config, PipelineResult(PipelineStatus.SUCCESS)
    )
    pipeline.execute.side_effect = RuntimeError("pipeline down")

    processor(file_ref, breaker)

    state.mark_failed.assert_called_once()
    breaker.record_failure.assert_called_once()
