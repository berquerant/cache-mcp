import argparse
import json
import sys
from pathlib import Path

from cache_mcp.cli.parser import read_json_payload
from cache_mcp.logger import CacheMCPLogger
from cache_mcp.models import CacheEntry, Config
from cache_mcp.server import create_mcp_server
from cache_mcp.service import CacheService


def handle_server(config: Config) -> int:
    """Launch the MCP server over STDIO transport."""
    server = create_mcp_server(config)
    server.run(transport="stdio")
    return 0


def _validate_key_or_params(
    args: argparse.Namespace,
    tool_name: str,
    logger: CacheMCPLogger | None,
    error_key: str = "hit",
) -> bool:
    if not (args.key or (args.type_name and args.name and args.cmd_dir)):
        err_output = {
            error_key: False,
            "error": "Either --key or (--type, --name, --cmd-dir) must be provided",
        }
        print(json.dumps(err_output), file=sys.stderr)
        if logger:
            logger.log_call(
                tool_name,
                {
                    "key": args.key,
                    "type": args.type_name,
                    "name": args.name,
                    "dir": args.cmd_dir,
                },
                err_output,
                0,
            )
        return False
    return True


def handle_get(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp get` command."""
    if not _validate_key_or_params(args, "get", logger, error_key="hit"):
        return 2

    service = CacheService(config=config, logger=logger)
    res = service.get(
        key=args.key,
        version=args.version,
        type=args.type_name,
        name=args.name,
        dir=args.cmd_dir,
        args=args.args,
        stdin=args.stdin,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("hit") else 1


def handle_exist(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp exist` command."""
    if not _validate_key_or_params(args, "exist", logger, error_key="hit"):
        return 2

    service = CacheService(config=config, logger=logger)
    res = service.exist(
        key=args.key,
        version=args.version,
        type=args.type_name,
        name=args.name,
        dir=args.cmd_dir,
        args=args.args,
        stdin=args.stdin,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("hit") else 1


def handle_delete(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp delete` command."""
    if not _validate_key_or_params(args, "delete", logger, error_key="deleted"):
        return 2

    service = CacheService(config=config, logger=logger)
    res = service.delete(
        key=args.key,
        version=args.version,
        type=args.type_name,
        name=args.name,
        dir=args.cmd_dir,
        args=args.args,
        stdin=args.stdin,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("deleted") else 1


def handle_version(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp version` command."""
    if not _validate_key_or_params(args, "version", logger, error_key="hit"):
        return 2

    service = CacheService(config=config, logger=logger)
    res = service.version(
        key=args.key,
        type=args.type_name,
        name=args.name,
        dir=args.cmd_dir,
        args=args.args,
        stdin=args.stdin,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("hit") else 1


def handle_set(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp set` command."""
    service = CacheService(config=config, logger=logger)
    if args.json_input:
        raw_json = read_json_payload(args.json_input)
        data = json.loads(raw_json)
        entry = CacheEntry.model_validate(data)
        key = args.key or data.get("key")
        res = service.set_entry(entry, key=key)
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
            type_name = "cli"
            cmd_name = "unknown"
            cmd_dir = str(Path.cwd())
        else:
            type_name = args.type_name
            cmd_name = args.name
            cmd_dir = args.cmd_dir

        res = service.set(
            type=type_name,
            name=cmd_name,
            dir=cmd_dir,
            ttl=args.ttl,
            stdout=args.stdout,
            stderr=args.stderr,
            success=args.success,
            args=args.args,
            stdin=args.stdin,
            status_code=args.status_code,
            status_string=args.status_string,
            description=args.description,
            key=args.key,
        )

    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("success") else 1


def handle_purge(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp purge` command."""
    service = CacheService(config=config, logger=logger)
    res = service.purge(all=args.all)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("success") else 1
