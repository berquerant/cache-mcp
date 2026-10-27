import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from cache_mcp.cli.parser import read_json_payload, resolve_key
from cache_mcp.logger import CacheMCPLogger
from cache_mcp.models import CacheEntry, Config, compute_cache_key
from cache_mcp.server import create_mcp_server
from cache_mcp.storage import CacheStorage


def handle_server(config: Config) -> int:
    """Launch the MCP server over STDIO transport."""
    server = create_mcp_server(config)
    server.run(transport="stdio")
    return 0


def handle_get(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp get` command."""
    start = time.perf_counter()
    storage = CacheStorage(config)
    target_key = resolve_key(
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


def handle_exist(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp exist` command."""
    start = time.perf_counter()
    storage = CacheStorage(config)
    target_key = resolve_key(
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


def handle_delete(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp delete` command."""
    start = time.perf_counter()
    storage = CacheStorage(config)
    target_key = resolve_key(
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


def handle_version(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp version` command."""
    start = time.perf_counter()
    storage = CacheStorage(config)
    target_key = resolve_key(
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


def handle_set(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp set` command."""
    start = time.perf_counter()
    storage = CacheStorage(config)
    entry: CacheEntry
    key: str
    now = int(time.time())

    if args.json_input:
        raw_json = read_json_payload(args.json_input)
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


def handle_purge(
    args: argparse.Namespace, config: Config, logger: CacheMCPLogger | None
) -> int:
    """Handle `cache-mcp purge` command."""
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
