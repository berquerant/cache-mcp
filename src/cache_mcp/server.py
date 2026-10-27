from typing import Any

from mcp.server.mcpserver import MCPServer

from cache_mcp.logger import CacheMCPLogger
from cache_mcp.models import Config
from cache_mcp.service import CacheService


def _register_read_tools(mcp: MCPServer, service: CacheService) -> None:
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
        return service.get(
            key=key,
            version=version,
            type=type,
            name=name,
            args=args,
            dir=dir,
            stdin=stdin,
        )

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
        return service.exist(
            key=key,
            version=version,
            type=type,
            name=name,
            args=args,
            dir=dir,
            stdin=stdin,
        )

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
        return service.version(
            key=key,
            type=type,
            name=name,
            args=args,
            dir=dir,
            stdin=stdin,
        )


def _register_write_tools(mcp: MCPServer, service: CacheService) -> None:
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
        return service.set(
            type=type,
            name=name,
            dir=dir,
            ttl=ttl,
            stdout=stdout,
            stderr=stderr,
            success=success,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            args=args,
            description=description,
            stdin=stdin,
            status_code=status_code,
            status_string=status_string,
        )

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
        return service.delete(
            key=key,
            version=version,
            type=type,
            name=name,
            args=args,
            dir=dir,
            stdin=stdin,
        )

    @mcp.tool()
    def purge(all: bool = False) -> dict[str, Any]:
        """Purge cache files across all subdirectories and reclaim disk space.

        Args:
            all: When True, purges all cache files.
                 When False (default), purges only expired cache files.

        Returns:
            Dictionary with `success: bool`, `deleted_count: int`, `freed_bytes: int`, and `all: bool`.
        """
        return service.purge(all=all)


def create_mcp_server(config: Config) -> MCPServer:
    """Creates and configures MCPServer with 6 cache tools: get, set, exist, delete, version, purge."""
    mcp = MCPServer("cachemcp")
    logger = CacheMCPLogger(config.dir / "logs")
    service = CacheService(config=config, logger=logger)
    _register_read_tools(mcp, service)
    _register_write_tools(mcp, service)
    return mcp
