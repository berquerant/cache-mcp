import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from cache_mcp.logger import CacheMCPLogger
from cache_mcp.models import CacheEntry, Config, compute_cache_key
from cache_mcp.server import create_mcp_server
from cache_mcp.storage import CacheStorage


def _resolve_key(
    key: str | None,
    type_name: str | None,
    name: str | None,
    cmd_dir: str | None,
    args: list[str] | None,
    stdin: str | None,
) -> str | None:
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


def _read_json_payload(input_spec: str) -> str:
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


def _build_parser() -> argparse.ArgumentParser:
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


def cli(argv: list[str] | None = None) -> int:
    """CLI handler returning process exit code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    subcommands = {"server", "get", "set", "exist", "delete", "version", "purge"}

    # Backward compatibility: if no subcommand and not help, default to server
    if not any(arg in subcommands or arg in ("-h", "--help") for arg in raw_args):
        raw_args = ["server"] + raw_args

    parser = _build_parser()
    args = parser.parse_args(raw_args)

    config = Config(
        dir=args.cache_dir,
        max_ttl=args.max_ttl,
        max_cache_size=args.max_cache_size,
        max_total_compressed_cache_size=args.max_total_compressed_cache_size,
    )
    logger = (
        None if getattr(args, "no_log", False) else CacheMCPLogger(config.dir / "logs")
    )

    match args.subcommand:
        case "server":
            server = create_mcp_server(config)
            server.run(transport="stdio")
            return 0

        case "get":
            start = time.perf_counter()
            storage = CacheStorage(config)
            target_key = _resolve_key(
                args.key,
                args.type_name,
                args.name,
                args.cmd_dir,
                args.args,
                args.stdin,
            )
            if not target_key:
                err_output = {
                    "hit": False,
                    "error": "Either --key or (--type, --name, --cmd-dir) must be provided",
                }
                print(json.dumps(err_output), file=sys.stderr)
                if logger:
                    logger.log_call(
                        "get",
                        {
                            "key": args.key,
                            "type": args.type_name,
                            "name": args.name,
                            "dir": args.cmd_dir,
                        },
                        err_output,
                        0,
                    )
                return 2

            res = storage.get(target_key, version=args.version)
            output: dict[str, Any] = {
                "hit": res.hit,
                "key": res.key,
                "version": res.version,
                "data": res.data.model_dump() if res.data else None,
            }
            if res.reason:
                output["reason"] = res.reason
            duration_ms = int((time.perf_counter() - start) * 1000)
            if logger:
                logger.log_call(
                    "get",
                    {
                        "key": args.key,
                        "version": args.version,
                        "type": args.type_name,
                        "name": args.name,
                        "dir": args.cmd_dir,
                        "args": args.args,
                        "stdin": args.stdin,
                    },
                    output,
                    duration_ms,
                )
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return 0 if res.hit else 1

        case "exist":
            start = time.perf_counter()
            storage = CacheStorage(config)
            target_key = _resolve_key(
                args.key,
                args.type_name,
                args.name,
                args.cmd_dir,
                args.args,
                args.stdin,
            )
            if not target_key:
                err_output = {
                    "hit": False,
                    "error": "Either --key or (--type, --name, --cmd-dir) must be provided",
                }
                print(json.dumps(err_output), file=sys.stderr)
                if logger:
                    logger.log_call(
                        "exist",
                        {
                            "key": args.key,
                            "type": args.type_name,
                            "name": args.name,
                            "dir": args.cmd_dir,
                        },
                        err_output,
                        0,
                    )
                return 2

            hit = storage.exist(target_key, version=args.version)
            output = {"hit": hit, "key": target_key}
            duration_ms = int((time.perf_counter() - start) * 1000)
            if logger:
                logger.log_call(
                    "exist",
                    {
                        "key": args.key,
                        "version": args.version,
                        "type": args.type_name,
                        "name": args.name,
                        "dir": args.cmd_dir,
                        "args": args.args,
                        "stdin": args.stdin,
                    },
                    output,
                    duration_ms,
                )
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return 0 if hit else 1

        case "delete":
            start = time.perf_counter()
            storage = CacheStorage(config)
            target_key = _resolve_key(
                args.key,
                args.type_name,
                args.name,
                args.cmd_dir,
                args.args,
                args.stdin,
            )
            if not target_key:
                err_output = {
                    "deleted": False,
                    "error": "Either --key or (--type, --name, --cmd-dir) must be provided",
                }
                print(json.dumps(err_output), file=sys.stderr)
                if logger:
                    logger.log_call(
                        "delete",
                        {
                            "key": args.key,
                            "type": args.type_name,
                            "name": args.name,
                            "dir": args.cmd_dir,
                        },
                        err_output,
                        0,
                    )
                return 2

            del_res = storage.delete(target_key, version=args.version)
            output = {
                "hit": del_res.hit,
                "deleted": del_res.deleted,
                "key": del_res.key,
                "version": del_res.version,
                "deleted_count": del_res.deleted_count,
            }
            duration_ms = int((time.perf_counter() - start) * 1000)
            if logger:
                logger.log_call(
                    "delete",
                    {
                        "key": args.key,
                        "version": args.version,
                        "type": args.type_name,
                        "name": args.name,
                        "dir": args.cmd_dir,
                        "args": args.args,
                        "stdin": args.stdin,
                    },
                    output,
                    duration_ms,
                )
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return 0 if del_res.deleted else 1

        case "version":
            start = time.perf_counter()
            storage = CacheStorage(config)
            target_key = _resolve_key(
                args.key,
                args.type_name,
                args.name,
                args.cmd_dir,
                args.args,
                args.stdin,
            )
            if not target_key:
                err_output = {
                    "hit": False,
                    "error": "Either --key or (--type, --name, --cmd-dir) must be provided",
                }
                print(json.dumps(err_output), file=sys.stderr)
                if logger:
                    logger.log_call(
                        "version",
                        {
                            "key": args.key,
                            "type": args.type_name,
                            "name": args.name,
                            "dir": args.cmd_dir,
                        },
                        err_output,
                        0,
                    )
                return 2

            ver_res = storage.version(target_key)
            output = {
                "hit": ver_res.hit,
                "key": ver_res.key,
                "versions": [v.model_dump() for v in ver_res.versions],
            }
            if ver_res.reason:
                output["reason"] = ver_res.reason
            duration_ms = int((time.perf_counter() - start) * 1000)
            if logger:
                logger.log_call(
                    "version",
                    {
                        "key": args.key,
                        "type": args.type_name,
                        "name": args.name,
                        "dir": args.cmd_dir,
                        "args": args.args,
                        "stdin": args.stdin,
                    },
                    output,
                    duration_ms,
                )
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return 0 if ver_res.hit else 1

        case "set":
            start = time.perf_counter()
            storage = CacheStorage(config)
            entry: CacheEntry
            key: str
            now = int(time.time())

            if args.json_input:
                raw_json = _read_json_payload(args.json_input)
                data = json.loads(raw_json)
                key = args.key or data.get("key")
                if not key:
                    key = compute_cache_key(
                        type=data["type"],
                        name=data["name"],
                        dir=data["dir"],
                        args=data.get("args", []),
                        stdin=data.get("stdin"),
                    )
                entry = CacheEntry.model_validate(data)
            else:
                if not (args.type_name and args.name and args.cmd_dir):
                    if not args.key:
                        err_output = {
                            "success": False,
                            "error": "Must provide either --json or (--type, --name, --cmd-dir)",
                        }
                        print(json.dumps(err_output), file=sys.stderr)
                        if logger:
                            logger.log_call("set", {}, err_output, 0)
                        return 2
                    key = args.key
                    type_name = "cli"
                    cmd_name = "unknown"
                    cmd_dir = str(Path.cwd())
                else:
                    key = args.key or compute_cache_key(
                        type=args.type_name,
                        name=args.name,
                        dir=args.cmd_dir,
                        args=args.args or [],
                        stdin=args.stdin,
                    )
                    type_name = args.type_name
                    cmd_name = args.name
                    cmd_dir = args.cmd_dir

                effective_ttl = min(args.ttl, config.max_ttl)
                entry = CacheEntry(
                    type=type_name,
                    name=cmd_name,
                    dir=cmd_dir,
                    args=args.args or [],
                    stdin=args.stdin,
                    created_timestamp=now,
                    ttl=effective_ttl,
                    ttl_timestamp=now + effective_ttl,
                    stdout=args.stdout,
                    stderr=args.stderr,
                    success=args.success,
                    status_code=args.status_code,
                    status_string=args.status_string,
                    description=args.description,
                )

            set_res = storage.set(key, entry)
            output = {
                "success": set_res.success,
                "key": set_res.key,
                "version": set_res.version,
                "message": set_res.message,
            }
            duration_ms = int((time.perf_counter() - start) * 1000)
            if logger:
                logger.log_call(
                    "set",
                    {
                        "key": key,
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
                    output,
                    duration_ms,
                )
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return 0 if set_res.success else 1

        case "purge":
            start = time.perf_counter()
            storage = CacheStorage(config)
            p_res = storage.purge(all=args.all)
            output = {
                "success": p_res.success,
                "deleted_count": p_res.deleted_count,
                "freed_bytes": p_res.freed_bytes,
                "all": p_res.all,
                "message": p_res.message,
            }
            duration_ms = int((time.perf_counter() - start) * 1000)
            if logger:
                logger.log_call("purge", {"all": args.all}, output, duration_ms)
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return 0 if p_res.success else 1

        case _:
            parser.print_help()
            return 2


def main() -> None:
    """Entry point for command execution."""
    sys.exit(cli())


if __name__ == "__main__":
    main()
