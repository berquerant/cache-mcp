import json
import multiprocessing
import time
from pathlib import Path

import pytest

from cache_mcp.lock import FileLock, LockTimeoutError
from cache_mcp.logger import CacheMCPLogger, truncate_value

# Table-Driven tests for truncate_value
TRUNCATE_TEST_CASES = [
    ("short_string", "hello world", "hello world"),
    (
        "exact_100_string",
        "a" * 100,
        "a" * 100,
    ),
    (
        "long_string_120",
        "a" * 120,
        "a" * 100 + "... (truncated, total length: 120)",
    ),
    ("integer_unchanged", 42, 42),
    ("bool_unchanged", True, True),
    ("none_unchanged", None, None),
    (
        "dict_with_long_strings",
        {"stdout": "x" * 105, "status": 0},
        {"stdout": "x" * 100 + "... (truncated, total length: 105)", "status": 0},
    ),
    (
        "list_with_long_string",
        ["cmd", "y" * 110],
        ["cmd", "y" * 100 + "... (truncated, total length: 110)"],
    ),
]


@pytest.mark.parametrize("case_name,input_val,expected", TRUNCATE_TEST_CASES)
def test_truncate_value(case_name: str, input_val: object, expected: object) -> None:
    assert truncate_value(input_val) == expected


def _hold_lock_child(lock_path: str, hold_seconds: float) -> None:
    lock = FileLock(lock_path, timeout=5.0)
    lock.acquire(exclusive=True)
    time.sleep(hold_seconds)
    lock.release()


# Table-Driven tests for FileLock behavior
LOCK_TEST_CASES = [
    ("exclusive_reentry", True, 0.5, True),
    (
        "exclusive_timeout",
        False,
        0.2,
        False,
    ),  # child holds 1.0s, parent waits 0.2s -> timeout
]


@pytest.mark.parametrize(
    "case_name,will_succeed,timeout,expected_success", LOCK_TEST_CASES
)
def test_file_lock(
    tmp_path: Path,
    case_name: str,
    will_succeed: bool,
    timeout: float,
    expected_success: bool,
) -> None:
    lock_file = tmp_path / "locks" / "test.lock"

    if will_succeed:
        lock = FileLock(lock_file, timeout=timeout)
        with lock:
            assert getattr(lock._local, "fd", None) is not None
        assert getattr(lock._local, "fd", None) is None
    else:
        # spawn child holding lock for 1 second
        proc = multiprocessing.Process(
            target=_hold_lock_child, args=(str(lock_file), 0.8)
        )
        proc.start()
        time.sleep(0.1)  # wait for child to grab lock

        lock = FileLock(lock_file, timeout=timeout, poll_interval=0.02)
        try:
            with pytest.raises(LockTimeoutError):
                lock.acquire(exclusive=True)
        finally:
            proc.join()


def test_file_lock_release_unacquired(tmp_path: Path) -> None:
    lock_file = tmp_path / "locks" / "test_unacquired.lock"
    lock = FileLock(lock_file)
    with pytest.raises(RuntimeError, match="Cannot release un-acquired FileLock"):
        lock.release()


def test_logger_rotation_and_format(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    logger = CacheMCPLogger(log_dir, max_bytes=500, backup_count=2)

    for i in range(10):
        logger.log_call(
            tool="test_tool",
            args={"arg": "value", "long": "z" * 120},
            result={"success": True},
            duration_ms=10,
        )

    assert (log_dir / "cachemcp.log").exists()
    lines = (log_dir / "cachemcp.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) > 0
    parsed = json.loads(lines[-1])
    assert parsed["tool"] == "test_tool"
    assert "... (truncated, total length: 120)" in parsed["args"]["long"]


def test_file_lock_non_contention_oserror_immediate_fail(
    tmp_path: Path, monkeypatch
) -> None:
    import errno
    import fcntl

    lock_file = tmp_path / "locks" / "test_error.lock"
    lock = FileLock(lock_file, timeout=5.0)

    def mock_flock(fd, op):
        raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(fcntl, "flock", mock_flock)

    start = time.monotonic()
    with pytest.raises(OSError) as exc_info:
        lock.acquire()
    duration = time.monotonic() - start

    assert exc_info.value.errno == errno.EINVAL
    # Must fail immediately without waiting for the 5-second deadline
    assert duration < 0.5


def test_logger_secure_permissions(tmp_path: Path) -> None:
    import stat

    log_dir = tmp_path / "secure_logs"
    logger = CacheMCPLogger(log_dir)
    logger.log_call("tool", {}, {}, 0)

    assert stat.S_IMODE(log_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((log_dir / "cachemcp.log").stat().st_mode) == 0o600
