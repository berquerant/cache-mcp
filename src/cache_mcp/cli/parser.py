import argparse
import os
import sys
from pathlib import Path


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


def _create_common_parsers() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
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
    return common_root, common_sub


def _add_query_args(
    p: argparse.ArgumentParser,
    include_version: bool = True,
    ver_help: str = "Target version (e.g. 1, 2, 'latest')",
) -> None:
    p.add_argument(
        "--key", type=str, help="Cache key (optionally including @<version>)"
    )
    if include_version:
        p.add_argument("--version", type=str, default=None, help=ver_help)
    p.add_argument("--type", dest="type_name", type=str, help="Invocation type")
    p.add_argument("--name", type=str, help="Command/tool name")
    p.add_argument(
        "--cmd-dir", dest="cmd_dir", type=str, help="Command working directory"
    )
    p.add_argument(
        "--args", nargs="*", default=None, help="Command invocation arguments"
    )
    p.add_argument("--stdin", type=str, default=None, help="Standard input")


def _add_set_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--key",
        type=str,
        help="Explicit base key (optional if type/name/cmd-dir provided)",
    )
    p.add_argument(
        "--json",
        dest="json_input",
        type=str,
        help="JSON payload string or path to JSON file (or '-' for stdin)",
    )
    p.add_argument("--type", dest="type_name", type=str, help="Invocation type")
    p.add_argument("--name", type=str, help="Command/tool name")
    p.add_argument(
        "--cmd-dir", dest="cmd_dir", type=str, help="Command working directory"
    )
    p.add_argument("--ttl", type=int, default=1800, help="TTL in seconds")
    p.add_argument("--stdout", type=str, default="", help="Command stdout")
    p.add_argument("--stderr", type=str, default="", help="Command stderr")
    p.add_argument(
        "--success", action="store_true", default=True, help="Command success flag"
    )
    p.add_argument(
        "--failed",
        action="store_false",
        dest="success",
        help="Mark execution as failed",
    )
    p.add_argument("--status-code", type=int, default=0, help="Process exit code")
    p.add_argument("--status-string", type=str, default="OK", help="Status string")
    p.add_argument(
        "--args", nargs="*", default=None, help="Command invocation arguments"
    )
    p.add_argument("--stdin", type=str, default=None, help="Standard input")
    p.add_argument(
        "--description", type=str, default=None, help="Invocation description"
    )


def _register_subcommands(
    subparsers: argparse._SubParsersAction, common_sub: argparse.ArgumentParser
) -> None:
    subparsers.add_parser(
        "server",
        parents=[common_sub],
        help="Run MCP server over STDIO transport",
    )

    get_parser = subparsers.add_parser(
        "get",
        parents=[common_sub],
        help="Retrieve cache entry by key or command parameters",
    )
    _add_query_args(get_parser)

    exist_parser = subparsers.add_parser(
        "exist",
        parents=[common_sub],
        help="Check if cache entry exists without decompressing",
    )
    _add_query_args(exist_parser)

    del_parser = subparsers.add_parser(
        "delete",
        parents=[common_sub],
        help="Delete cache entry (all versions or specific version)",
    )
    _add_query_args(del_parser, ver_help="Target version to delete")

    ver_parser = subparsers.add_parser(
        "version",
        parents=[common_sub],
        help="List all existing versions for a key",
    )
    _add_query_args(ver_parser, include_version=False)

    set_parser = subparsers.add_parser(
        "set",
        parents=[common_sub],
        help="Store a new immutable version of a cache entry",
    )
    _add_set_args(set_parser)

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


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser for Cache MCP Server & CLI subcommands."""
    common_root, common_sub = _create_common_parsers()
    parser = argparse.ArgumentParser(
        description="Cache MCP Server & Command-Line Interface",
        parents=[common_root],
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")
    _register_subcommands(subparsers, common_sub)
    return parser
