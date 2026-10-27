import time
from typing import Any

from mcp.server.mcpserver import MCPServer

from cache_mcp.lock import LockTimeoutError
from cache_mcp.logger import CacheMCPLogger
from cache_mcp.models import CacheEntry, Config, compute_cache_key
from cache_mcp.storage import CacheStorage


def _resolve_target_key(
    key: str | None,
    type: str | None,
    name: str | None,
    dir: str | None,
    args: list[str] | None,
    stdin: str | None,
) -> str | None:
    """Resolve cache key either from explicit key string or by computing from invocation arguments.

    Returns:
        64-character hex key string, or None if neither `key` nor required tuple (`type`, `name`, `dir`) is provided.
    """
    match (key, type, name, dir):
        case (str() as k, _, _, _) if k:
            return k
        case (_, str() as t, str() as n, str() as d) if t and n and d:
            return compute_cache_key(
                type=t, name=n, dir=d, args=args or [], stdin=stdin
            )
        case _:
            return None


def create_mcp_server(config: Config) -> MCPServer:
    """Creates and configures MCPServer with 6 cache tools: get, set, exist, delete, version, purge."""
    mcp = MCPServer("cachemcp")
    storage = CacheStorage(config)
    logger = CacheMCPLogger(config.dir / "logs")

    @mcp.tool()
    def get(
        key: str | None = None,
        version: int | str | None = None,
        type: str | None = None,
        name: str | None = None,
        args: list[str] | None = None,
        dir: str | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve cached execution record.

        Specify either `key` directly (fastest) or the parameter set (`type`, `name`, `dir`,
        `args`, `stdin`) to compute the key deterministically.

        Returns:
            Dictionary with `hit: bool`, `key: str`, `version: int | None`, `data: CacheEntry | None`,
            and optional `reason: str` / `error: str`.
        """
        start = time.perf_counter()
        target_key = _resolve_target_key(key, type, name, dir, args, stdin)
        if target_key is None:
            res: dict[str, Any] = {
                "hit": False,
                "message": "Either 'key' or ('type', 'name', 'dir') must be provided",
            }
            logger.log_call(
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
            get_res = storage.get(target_key, version=version)
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
        logger.log_call(
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

    @mcp.tool()
    def set(
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
    ) -> dict[str, Any]:
        """Store command or MCP tool execution result as a new immutable cache version.

        Automatic Attributes:
            - `created_timestamp`: Automatically stamped with current UNIX epoch seconds.
            - `effective_ttl`: Clamped to `min(ttl, config.max_ttl)` to prevent infinite retention.
            - `ttl_timestamp`: Calculated as `created_timestamp + effective_ttl`.
            - `version`: Monotonically incremented version (1, 2, ...).

        Returns:
            Dictionary with `success: bool`, `key: str`, `version: int | None`, and `message: str | None`.
        """
        start = time.perf_counter()
        call_args = {
            "type": type,
            "name": name,
            "args": args or [],
            "dir": dir,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "ttl": ttl,
            "description": description,
            "stdin": stdin,
            "stdout": stdout,
            "stderr": stderr,
            "success": success,
            "status_code": status_code,
            "status_string": status_string,
        }

        key = compute_cache_key(
            type=type, name=name, dir=dir, args=args or [], stdin=stdin
        )
        now = int(time.time())
        effective_ttl = min(ttl, config.max_ttl)
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

        try:
            res = storage.set(key, entry)
            result = {
                "success": res.success,
                "key": res.key,
                "version": res.version,
                "message": res.message,
            }
        except LockTimeoutError as e:
            result = {"success": False, "key": key, "version": None, "message": str(e)}
        except Exception as e:
            result = {"success": False, "key": key, "version": None, "message": str(e)}

        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.log_call("set", call_args, result, duration_ms)
        return result

    @mcp.tool()
    def exist(
        key: str | None = None,
        version: int | str | None = None,
        type: str | None = None,
        name: str | None = None,
        args: list[str] | None = None,
        dir: str | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Check whether a valid (unexpired) cache entry exists.

        Returns:
            Dictionary with `hit: bool` and `key: str`.
        """
        start = time.perf_counter()
        target_key = _resolve_target_key(key, type, name, dir, args, stdin)
        if target_key is None:
            res = {
                "hit": False,
                "message": "Either 'key' or ('type', 'name', 'dir') must be provided",
            }
            logger.log_call(
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

        hit = storage.exist(target_key, version=version)
        result = {"hit": hit, "key": target_key}
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.log_call(
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

    @mcp.tool()
    def delete(
        key: str | None = None,
        version: int | str | None = None,
        type: str | None = None,
        name: str | None = None,
        args: list[str] | None = None,
        dir: str | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Delete cache entries for a key (all versions or a specific version).

        Returns:
            Dictionary with `hit: bool`, `deleted: bool`, `key: str`, `version: int | str | None`,
            and `deleted_count: int`.
        """
        start = time.perf_counter()
        target_key = _resolve_target_key(key, type, name, dir, args, stdin)
        if target_key is None:
            res = {
                "hit": False,
                "deleted": False,
                "message": "Either 'key' or ('type', 'name', 'dir') must be provided",
            }
            logger.log_call(
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

        del_res = storage.delete(target_key, version=version)
        result = {
            "hit": del_res.hit,
            "deleted": del_res.deleted,
            "key": del_res.key,
            "version": del_res.version,
            "deleted_count": del_res.deleted_count,
        }
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.log_call(
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

    @mcp.tool()
    def version(
        key: str | None = None,
        type: str | None = None,
        name: str | None = None,
        args: list[str] | None = None,
        dir: str | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """List all existing, non-expired versions for a cache key without decompressing contents.

        Returns:
            Dictionary with `hit: bool`, `key: str`, and `versions: list[dict]`.
        """
        start = time.perf_counter()
        target_key = _resolve_target_key(key, type, name, dir, args, stdin)
        if target_key is None:
            res: dict[str, Any] = {
                "hit": False,
                "key": None,
                "versions": [],
                "message": "Either 'key' or ('type', 'name', 'dir') must be provided",
            }
            logger.log_call(
                "version",
                {"key": key, "type": type, "name": name, "dir": dir},
                res,
                0,
            )
            return res

        ver_res = storage.version(target_key)
        result = {
            "hit": ver_res.hit,
            "key": ver_res.key,
            "versions": [v.model_dump() for v in ver_res.versions],
        }
        if ver_res.reason:
            result["reason"] = ver_res.reason

        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.log_call(
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

    @mcp.tool()
    def purge() -> dict[str, Any]:
        """Purge all cache files across all subdirectories and reclaim disk space.

        Returns:
            Dictionary with `success: bool`, `deleted_count: int`, and `freed_bytes: int`.
        """
        start = time.perf_counter()
        purge_res = storage.purge()
        result = {
            "success": purge_res.success,
            "deleted_count": purge_res.deleted_count,
            "freed_bytes": purge_res.freed_bytes,
            "message": purge_res.message,
        }
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.log_call("purge", {}, result, duration_ms)
        return result

    return mcp
