import time
from typing import Any

from cache_mcp.lock import LockTimeoutError
from cache_mcp.logger import CacheMCPLogger
from cache_mcp.models import CacheEntry, Config, compute_cache_key
from cache_mcp.storage import CacheStorage


def resolve_key(
    key: str | None,
    type_name: str | None = None,
    name: str | None = None,
    cmd_dir: str | None = None,
    args: list[str] | None = None,
    stdin: str | None = None,
) -> str | None:
    """Resolve cache key either from explicit key string or by computing from invocation arguments."""
    match (key, type_name, name, cmd_dir):
        case (str() as k, _, _, _) if k:
            return k
        case (_, str() as t, str() as n, str() as d) if t and n and d:
            return compute_cache_key(
                type=t, name=n, dir=d, args=args or [], stdin=stdin
            )
        case _:
            return None


class CacheService:
    """High-level service coordinating cache operations, output formatting, and audit logging."""

    def __init__(
        self,
        config: Config,
        storage: CacheStorage | None = None,
        logger: CacheMCPLogger | None = None,
    ) -> None:
        self.config = config
        self.storage = storage or CacheStorage(config)
        self.logger = logger

    def get(
        self,
        key: str | None = None,
        version: int | str | None = None,
        type: str | None = None,
        name: str | None = None,
        args: list[str] | None = None,
        dir: str | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve cached execution record."""
        start = time.perf_counter()
        target_key = resolve_key(key, type, name, dir, args, stdin)
        if target_key is None:
            res: dict[str, Any] = {
                "hit": False,
                "message": "Either 'key' or ('type', 'name', 'dir') must be provided",
            }
            if self.logger:
                self.logger.log_call(
                    "get",
                    {
                        "key": key,
                        "version": version,
                        "type": type,
                        "name": name,
                        "dir": dir,
                    },
                    res,
                    0,
                )
            return res

        try:
            get_res = self.storage.get(target_key, version=version)
            result: dict[str, Any] = {
                "hit": get_res.hit,
                "key": get_res.key,
                "version": get_res.version,
                "data": get_res.data.model_dump() if get_res.data else None,
            }
            if get_res.reason:
                result["reason"] = get_res.reason
        except LockTimeoutError as e:
            result = {
                "hit": False,
                "key": target_key,
                "version": None,
                "reason": "timeout",
                "error": str(e),
            }
        except Exception as e:
            result = {
                "hit": False,
                "key": target_key,
                "version": None,
                "reason": "system_error",
                "error": str(e),
            }

        duration_ms = int((time.perf_counter() - start) * 1000)
        if self.logger:
            self.logger.log_call(
                "get",
                {
                    "key": key,
                    "version": version,
                    "type": type,
                    "name": name,
                    "dir": dir,
                    "args": args,
                    "stdin": stdin,
                },
                result,
                duration_ms,
            )
        return result

    def set_entry(
        self,
        entry: CacheEntry,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Store a pre-constructed CacheEntry into compressed cache."""
        start = time.perf_counter()
        resolved_key = key or compute_cache_key(
            type=entry.type,
            name=entry.name,
            dir=entry.dir,
            args=entry.args,
            stdin=entry.stdin,
        )
        try:
            res = self.storage.set(resolved_key, entry)
            result = {
                "success": res.success,
                "key": res.key,
                "version": res.version,
                "message": res.message,
            }
        except LockTimeoutError as e:
            result = {
                "success": False,
                "key": resolved_key,
                "version": None,
                "message": str(e),
            }
        except Exception as e:
            result = {
                "success": False,
                "key": resolved_key,
                "version": None,
                "message": str(e),
            }

        duration_ms = int((time.perf_counter() - start) * 1000)
        if self.logger:
            self.logger.log_call(
                "set",
                {
                    "key": resolved_key,
                    "type": entry.type,
                    "name": entry.name,
                    "dir": entry.dir,
                    "args": entry.args,
                    "stdin": entry.stdin,
                    "stdout": entry.stdout,
                    "stderr": entry.stderr,
                    "success": entry.success,
                    "ttl": entry.ttl,
                },
                result,
                duration_ms,
            )
        return result

    def set(
        self,
        type: str,
        name: str,
        dir: str,
        ttl: int,
        stdout: str,
        stderr: str,
        success: bool,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
        args: list[str] | None = None,
        description: str | None = None,
        stdin: str | None = None,
        status_code: int | None = None,
        status_string: str | None = None,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Store command or tool execution result by constructing CacheEntry."""
        now = int(time.time())
        effective_ttl = min(ttl, self.config.max_ttl)
        ttl_ts = now + effective_ttl

        entry = CacheEntry(
            type=type,
            name=name,
            args=args or [],
            dir=dir,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            created_timestamp=now,
            ttl=effective_ttl,
            ttl_timestamp=ttl_ts,
            description=description,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            success=success,
            status_code=status_code,
            status_string=status_string,
        )
        return self.set_entry(entry, key=key)

    def exist(
        self,
        key: str | None = None,
        version: int | str | None = None,
        type: str | None = None,
        name: str | None = None,
        args: list[str] | None = None,
        dir: str | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Check whether a non-expired cache entry exists."""
        start = time.perf_counter()
        target_key = resolve_key(key, type, name, dir, args, stdin)
        if target_key is None:
            res = {
                "hit": False,
                "message": "Either 'key' or ('type', 'name', 'dir') must be provided",
            }
            if self.logger:
                self.logger.log_call(
                    "exist",
                    {
                        "key": key,
                        "version": version,
                        "type": type,
                        "name": name,
                        "dir": dir,
                    },
                    res,
                    0,
                )
            return res

        hit = self.storage.exist(target_key, version=version)
        result = {"hit": hit, "key": target_key}
        duration_ms = int((time.perf_counter() - start) * 1000)
        if self.logger:
            self.logger.log_call(
                "exist",
                {
                    "key": key,
                    "version": version,
                    "type": type,
                    "name": name,
                    "dir": dir,
                    "args": args,
                    "stdin": stdin,
                },
                result,
                duration_ms,
            )
        return result

    def delete(
        self,
        key: str | None = None,
        version: int | str | None = None,
        type: str | None = None,
        name: str | None = None,
        args: list[str] | None = None,
        dir: str | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Delete cache entries for a key (all versions or a specific version)."""
        start = time.perf_counter()
        target_key = resolve_key(key, type, name, dir, args, stdin)
        if target_key is None:
            res = {
                "hit": False,
                "deleted": False,
                "message": "Either 'key' or ('type', 'name', 'dir') must be provided",
            }
            if self.logger:
                self.logger.log_call(
                    "delete",
                    {
                        "key": key,
                        "version": version,
                        "type": type,
                        "name": name,
                        "dir": dir,
                    },
                    res,
                    0,
                )
            return res

        del_res = self.storage.delete(target_key, version=version)
        result = {
            "hit": del_res.hit,
            "deleted": del_res.deleted,
            "key": del_res.key,
            "version": del_res.version,
            "deleted_count": del_res.deleted_count,
        }
        duration_ms = int((time.perf_counter() - start) * 1000)
        if self.logger:
            self.logger.log_call(
                "delete",
                {
                    "key": key,
                    "version": version,
                    "type": type,
                    "name": name,
                    "dir": dir,
                    "args": args,
                    "stdin": stdin,
                },
                result,
                duration_ms,
            )
        return result

    def version(
        self,
        key: str | None = None,
        type: str | None = None,
        name: str | None = None,
        args: list[str] | None = None,
        dir: str | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """List all existing, non-expired versions for a key without reading payloads."""
        start = time.perf_counter()
        target_key = resolve_key(key, type, name, dir, args, stdin)
        if target_key is None:
            res: dict[str, Any] = {
                "hit": False,
                "key": None,
                "versions": [],
                "message": "Either 'key' or ('type', 'name', 'dir') must be provided",
            }
            if self.logger:
                self.logger.log_call(
                    "version",
                    {"key": key, "type": type, "name": name, "dir": dir},
                    res,
                    0,
                )
            return res

        ver_res = self.storage.version(target_key)
        result = {
            "hit": ver_res.hit,
            "key": ver_res.key,
            "versions": [v.model_dump() for v in ver_res.versions],
        }
        if ver_res.reason:
            result["reason"] = ver_res.reason
        duration_ms = int((time.perf_counter() - start) * 1000)
        if self.logger:
            self.logger.log_call(
                "version",
                {
                    "key": key,
                    "type": type,
                    "name": name,
                    "dir": dir,
                    "args": args,
                    "stdin": stdin,
                },
                result,
                duration_ms,
            )
        return result

    def purge(self, all: bool = False) -> dict[str, Any]:
        """Purge cache files across all subdirectories and reclaim disk space."""
        start = time.perf_counter()
        purge_res = self.storage.purge(all=all)
        result = {
            "success": purge_res.success,
            "deleted_count": purge_res.deleted_count,
            "freed_bytes": purge_res.freed_bytes,
            "all": purge_res.all,
            "message": purge_res.message,
        }
        duration_ms = int((time.perf_counter() - start) * 1000)
        if self.logger:
            self.logger.log_call("purge", {"all": all}, result, duration_ms)
        return result
