import sys

from cache_mcp.cli.handlers import (
    handle_delete,
    handle_exist,
    handle_get,
    handle_purge,
    handle_server,
    handle_set,
    handle_version,
)
from cache_mcp.cli.parser import build_parser
from cache_mcp.logger import CacheMCPLogger
from cache_mcp.models import Config


def cli(argv: list[str] | None = None) -> int:
    """CLI handler returning process exit code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    subcommands = {"server", "get", "set", "exist", "delete", "version", "purge"}

    # Backward compatibility: if no subcommand and not help, default to server
    if not any(arg in subcommands or arg in ("-h", "--help") for arg in raw_args):
        raw_args = ["server"] + raw_args

    parser = build_parser()
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
            return handle_server(config)
        case "get":
            return handle_get(args, config, logger)
        case "exist":
            return handle_exist(args, config, logger)
        case "delete":
            return handle_delete(args, config, logger)
        case "version":
            return handle_version(args, config, logger)
        case "set":
            return handle_set(args, config, logger)
        case "purge":
            return handle_purge(args, config, logger)
        case _:
            parser.print_help()
            return 2
