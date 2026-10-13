import os
import sys
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Self


class LockTimeoutError(Exception):
    """Raised when acquiring flock exceeds the specified timeout."""


class FileLock:
    """POSIX flock-based file lock with configurable polling timeout and thread safety.

    Why POSIX only:
        File locks rely on the POSIX `fcntl.flock` API for safe multi-process mutual
        exclusion. Windows locking behaviors (e.g. `msvcrt.locking`) have distinct
        semantics and are deliberately excluded from this server scope.

    Thread safety:
        In POSIX, `fcntl.flock` locks the underlying open file table entry, not the thread.
        To ensure thread safety and avoid race conditions on file descriptors when multiple
        threads within the same process call acquire/release on the same FileLock instance,
        FileLock uses an internal `threading.RLock` combined with thread-local lock state.
    """

    def __init__(
        self, lock_path: Path | str, timeout: float = 10.0, poll_interval: float = 0.05
    ) -> None:
        """Initialize FileLock instance.

        Args:
            lock_path: File path on disk used as the synchronization token.
            timeout: Maximum wait time in seconds before raising LockTimeoutError.
                Defaults to 10.0 seconds to prevent permanent server blockage from hung processes.
            poll_interval: Sleep interval in seconds between non-blocking lock attempts.
        """
        if sys.platform == "win32":
            raise NotImplementedError(
                "Windows is not supported. FileLock requires POSIX fcntl."
            )
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._thread_lock = threading.RLock()
        self._local = threading.local()

    def acquire(self, exclusive: bool = True) -> None:
        """Acquire the file lock using non-blocking flock polling until timeout."""
        import fcntl

        deadline = time.monotonic() + self.timeout

        # 1. Acquire in-process thread lock first
        acquired_thread = self._thread_lock.acquire(timeout=self.timeout)
        if not acquired_thread:
            raise LockTimeoutError(
                f"Failed to acquire in-process lock on {self.lock_path} within {self.timeout}s"
            )

        try:
            # Reentrant check for the same thread
            count = getattr(self._local, "count", 0)
            if count > 0:
                self._local.count += 1
                return

            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH

            while True:
                try:
                    fcntl.flock(fd, mode | fcntl.LOCK_NB)
                    self._local.fd = fd
                    self._local.count = 1
                    return
                except BlockingIOError, OSError:
                    if time.monotonic() >= deadline:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        raise LockTimeoutError(
                            f"Failed to acquire {'exclusive' if exclusive else 'shared'} lock on {self.lock_path} within {self.timeout}s"
                        )
                    time.sleep(self.poll_interval)
        except Exception:
            self._thread_lock.release()
            raise

    def release(self) -> None:
        """Release the file lock and close the associated file descriptor."""
        import fcntl

        count = getattr(self._local, "count", 0)
        if count <= 0:
            raise RuntimeError(
                f"Cannot release un-acquired FileLock on {self.lock_path}"
            )

        count -= 1
        self._local.count = count

        if count == 0:
            fd = getattr(self._local, "fd", None)
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                try:
                    os.close(fd)
                except OSError:
                    pass
                self._local.fd = None

        self._thread_lock.release()

    def __enter__(self) -> Self:
        """Context manager entry acquiring an exclusive lock."""
        self.acquire(exclusive=True)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit releasing the lock."""
        self.release()
