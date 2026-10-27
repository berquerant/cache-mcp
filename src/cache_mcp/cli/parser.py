import argparse
import os
import sys
from pathlib import Path

from cache_mcp.models import compute_cache_key


def resolve_key(
    key: str | None,
    type_name: str | None,
    name: str | None,
    cmd_dir: str | None,
    args: list[str] | None,
    stdin: str | None,
) -> str | None:
    """Resolve cache key either from explicit key string or by computing from invocation arguments."""
    if key:
        return key
    if type_name and name and cmd_dir:
        return compute_cache_key(
            type=type_name,
            name=name,
            dir=cmd_dir,
            args=args or [],
            stdin=stdin,
        )
    return None


def read_json_payload(input_spec: str) -> str:
    """Read JSON payload from stdin ('-'), a file path, or direct JSON string."""
    if input_spec == "-":
        return sys.stdin.read()
    stripped = input_spec.strip()
    if stripped.startswith(("{", "[")):
        return input_spec
    try:
        p = Path(input_spec)
        if p.is_file():
            return p.read_text(encoding="utf-8")
    except OSError:
        pass
    return input_spec


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser for Cache MCP Server & CLI subcommands."""
    common_root = argparse.ArgumentParser(add_help=False)
    common_root.add_argument(
        "--dir",
        "--cache-dir",
        dest="cache_dir",
        type=Path,
        default=Path(os.environ.get("CACHE_MCP_DIR", ".cachemcp")),
        help="Root cache storage directory (default: env CACHE_MCP_DIR or .cachemcp)",
    )
    common_root.add_argument(
        "--max-ttl", type=int, default=1800, help="Maximum allowed TTL in seconds"
    )
    common_root.add_argument(
        "--max-cache-size",
        type=int,
        default=10 * 1024 * 1024,
        help="Max uncompressed cache entry size",
    )
    common_root.add_argument(
        "--max-total-compressed-cache-size",
        type=int,
        default=500 * 1024 * 1024,
        help="Max total compressed cache size",
    )
    common_root.add_argument(
        "--no-log",
        action="store_true",
        default=False,
        help="Disable writing execution audit records to logs/cachemcp.log",
    )

    common_sub = argparse.ArgumentParser(add_help=False)
    common_sub.add_argument(
        "--dir",
        "--cache-dir",
        dest="cache_dir",
        type=Path,
        default=argparse.SUPPRESS,
        help="Root cache storage directory",
    )
    common_sub.add_argument(
        "--max-ttl",
        type=int,
        default=argparse.SUPPRESS,
        help="Maximum allowed TTL in seconds",
    )
    common_sub.add_argument(
        "--max-cache-size",
        type=int,
        default=argparse.SUPPRESS,
        help="Max uncompressed cache entry size",
    )
    common_sub.add_argument(
        "--max-total-compressed-cache-size",
        type=int,
        default=argparse.SUPPRESS,
        help="Max total compressed cache size",
    )
    common_sub.add_argument(
        "--no-log",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable writing execution audit records to logs/cachemcp.log",
    )

    parser = argparse.ArgumentParser(
        description="Cache MCP Server & Command-Line Interface",
        parents=[common_root],
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # server
    subparsers.add_parser(
        "server",
        parents=[common_sub],
        help="Run MCP server over STDIO transport",
    )

    # get
    get_parser = subparsers.add_parser(
        "get",
        parents=[common_sub],
        help="Retrieve cache entry by key or command parameters",
    )
    get_parser.add_argument(
        "--key", type=str, help="Cache key (optionally including @<version>)"
    )
    get_parser.add_argument(
        "--version", type=str, default=None, help="Target version (e.g. 1, 2, 'latest')"
    )
    get_parser.add_argument(
        "--type", dest="type_name", type=str, help="Invocation type"
    )
    get_parser.add_argument("--name", type=str, help="Command/tool name")
    get_parser.add_argument(
        "--cmd-dir", dest="cmd_dir", type=str, help="Command working directory"
    )
    get_parser.add_argument(
        "--args", nargs="*", default=None, help="Command invocation arguments"
    )
    get_parser.add_argument("--stdin", type=str, default=None, help="Standard input")

    # exist
    exist_parser = subparsers.add_parser(
        "exist",
        parents=[common_sub],
        help="Check if cache entry exists without decompressing",
    )
    exist_parser.add_argument(
        "--key", type=str, help="Cache key (optionally including @<version>)"
    )
    exist_parser.add_argument(
        "--version", type=str, default=None, help="Target version (e.g. 1, 2, 'latest')"
    )
    exist_parser.add_argument(
        "--type", dest="type_name", type=str, help="Invocation type"
    )
    exist_parser.add_argument("--name", type=str, help="Command/tool name")
    exist_parser.add_argument(
        "--cmd-dir", dest="cmd_dir", type=str, help="Command working directory"
    )
    exist_parser.add_argument(
        "--args", nargs="*", default=None, help="Command invocation arguments"
    )
    exist_parser.add_argument("--stdin", type=str, default=None, help="Standard input")

    # delete
    del_parser = subparsers.add_parser(
        "delete",
        parents=[common_sub],
        help="Delete cache entry (all versions or specific version)",
    )
    del_parser.add_argument(
        "--key", type=str, help="Cache key (optionally including @<version>)"
    )
    del_parser.add_argument(
        "--version", type=str, default=None, help="Target version to delete"
    )
    del_parser.add_argument(
        "--type", dest="type_name", type=str, help="Invocation type"
    )
    del_parser.add_argument("--name", type=str, help="Command/tool name")
    del_parser.add_argument(
        "--cmd-dir", dest="cmd_dir", type=str, help="Command working directory"
    )
    del_parser.add_argument(
        "--args", nargs="*", default=None, help="Command invocation arguments"
    )
    del_parser.add_argument("--stdin", type=str, default=None, help="Standard input")

    # version
    ver_parser = subparsers.add_parser(
        "version",
        parents=[common_sub],
        help="List all existing versions for a key",
    )
    ver_parser.add_argument("--key", type=str, help="Base cache key")
    ver_parser.add_argument(
        "--type", dest="type_name", type=str, help="Invocation type"
    )
    ver_parser.add_argument("--name", type=str, help="Command/tool name")
    ver_parser.add_argument(
        "--cmd-dir", dest="cmd_dir", type=str, help="Command working directory"
    )
    ver_parser.add_argument(
        "--args", nargs="*", default=None, help="Command invocation arguments"
    )
    ver_parser.add_argument("--stdin", type=str, default=None, help="Standard input")

    # set
    set_parser = subparsers.add_parser(
        "set",
        parents=[common_sub],
        help="Store a new immutable version of a cache entry",
    )
    set_parser.add_argument(
        "--key",
        type=str,
        help="Explicit base key (optional if type/name/cmd-dir provided)",
    )
    set_parser.add_argument(
        "--json",
        dest="json_input",
        type=str,
        help="JSON payload string or path to JSON file (or '-' for stdin)",
    )
    set_parser.add_argument(
        "--type", dest="type_name", type=str, help="Invocation type"
    )
    set_parser.add_argument("--name", type=str, help="Command/tool name")
    set_parser.add_argument(
        "--cmd-dir", dest="cmd_dir", type=str, help="Command working directory"
    )
    set_parser.add_argument("--ttl", type=int, default=1800, help="TTL in seconds")
    set_parser.add_argument("--stdout", type=str, default="", help="Command stdout")
    set_parser.add_argument("--stderr", type=str, default="", help="Command stderr")
    set_parser.add_argument(
        "--success", action="store_true", default=True, help="Command success flag"
    )
    set_parser.add_argument(
        "--failed",
        action="store_false",
        dest="success",
        help="Mark execution as failed",
    )
    set_parser.add_argument(
        "--status-code", type=int, default=0, help="Process exit code"
    )
    set_parser.add_argument(
        "--status-string", type=str, default="OK", help="Status string"
    )
    set_parser.add_argument(
        "--args", nargs="*", default=None, help="Command invocation arguments"
    )
    set_parser.add_argument("--stdin", type=str, default=None, help="Standard input")
    set_parser.add_argument(
        "--description", type=str, default=None, help="Invocation description"
    )

    # purge
    purge_parser = subparsers.add_parser(
        "purge",
        parents=[common_sub],
        help="Purge cache files (default: expired only, or all with --all)",
    )
    purge_parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Purge all cache entries instead of only expired entries",
    )

    return parser
