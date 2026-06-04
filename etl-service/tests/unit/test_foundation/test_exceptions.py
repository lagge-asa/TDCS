"""测试异常体系"""
import pytest
from src.core.exceptions import (
    ETLError, RetryableError, FatalError, SkipFileError,
    DataQualityError, ConfigValidationError, SandboxError,
    RETRY_BACKOFF,
)


def test_exception_hierarchy():
    assert issubclass(RetryableError, ETLError)
    assert issubclass(FatalError, ETLError)
    assert issubclass(SkipFileError, ETLError)
    assert issubclass(DataQualityError, ETLError)
    assert issubclass(ConfigValidationError, ETLError)
    assert issubclass(SandboxError, FatalError)


def test_retry_backoff_values():
    assert RETRY_BACKOFF[1] == 5
    assert RETRY_BACKOFF[2] == 30
    assert RETRY_BACKOFF[3] == 120


def test_exceptions_are_catchable_as_base():
    with pytest.raises(ETLError):
        raise RetryableError("network timeout")

    with pytest.raises(FatalError):
        raise SandboxError("sandbox crashed")


def test_exception_messages():
    e = ConfigValidationError("worker_threads must be >= 1")
    assert "worker_threads" in str(e)
