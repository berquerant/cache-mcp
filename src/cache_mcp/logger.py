import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, overload


@overload
def truncate_value(val: str, max_len: int = 100) -> str: ...


@overload
def truncate_value(val: list[Any], max_len: int = 100) -> list[Any]: ...


@overload
def truncate_value(val: dict[str, Any], max_len: int = 100) -> dict[str, Any]: ...


@overload
def truncate_value[T](val: T, max_len: int = 100) -> T: ...


def truncate_value(val: Any, max_len: int = 100) -> Any:
    """Truncate string-type values exceeding max_len characters while preserving container types.

    Why truncation:
        Tool executions frequently yield immense standard output/error (e.g. megabytes
        of build logs, git diffs). Writing untruncated blobs to log files degrades I/O,
        fills disk quickly, and wastes token contexts if agents inspect audit logs.
        Truncating to 100 characters preserves structural context while capping log footprint.

    Format:
        val[:100] + "... (truncated, total length: " + str(len(val)) + ")"
    """
    match val:
        case str():
            if len(val) > max_len:
                return f"{val[:max_len]}... (truncated, total length: {len(val)})"
            return val
        case list():
            items = [truncate_value(item, max_len=max_len) for item in val[:50]]
            if len(val) > 50:
                items.append(f"... (truncated {len(val) - 50} more items)")
            return items
        case dict():
            return {k: truncate_value(v, max_len=max_len) for k, v in val.items()}
        case _:
            return val


class CacheMCPLogger:
    """Audit logger writing JSONL logs to `<dir>/logs/cachemcp.log`.

    Why dedicated file over stdout:
        In standard MCP stdio mode, standard output is strictly reserved for JSON-RPC
        protocol framing. Emitting any diagnostic output to stdout corrupts JSON-RPC
        parsing and breaks the client-server connection.
    """

    def __init__(
        self,
        log_dir: Path | str,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 3,
    ) -> None:
        """Initialize audit logger with RotatingFileHandler.

        Args:
            log_dir: Directory where `cachemcp.log` is persisted.
            max_bytes: Maximum file size before rotation occurs (default: 10MB).
            backup_count: Number of rotated backup files to retain (default: 3).
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.log_dir, 0o700)
        except OSError:
            pass
        self.log_file = self.log_dir / "cachemcp.log"
        if not self.log_file.exists():
            try:
                fd = os.open(self.log_file, os.O_CREAT | os.O_WRONLY, 0o600)
                os.close(fd)
            except OSError:
                pass
        else:
            try:
                os.chmod(self.log_file, 0o600)
            except OSError:
                pass

        self._logger = logging.getLogger(f"cache_mcp_{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

        handler = RotatingFileHandler(
            str(self.log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)

    def log_call(
        self,
        tool: str,
        args: dict[str, Any],
        result: dict[str, Any],
        duration_ms: int,
        timestamp: str | None = None,
    ) -> None:
        """Write an audited tool execution record in JSONL format."""
        import datetime

        ts = timestamp or datetime.datetime.now(datetime.UTC).isoformat()
        entry = {
            "timestamp": ts,
            "tool": tool,
            "args": truncate_value(args),
            "result": truncate_value(result),
            "duration_ms": duration_ms,
        }
        self._logger.info(json.dumps(entry, ensure_ascii=False))
