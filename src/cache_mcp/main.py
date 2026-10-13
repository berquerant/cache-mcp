import argparse
from pathlib import Path

from cache_mcp.models import Config
from cache_mcp.server import create_mcp_server


def main() -> None:
    """CLI entry point for launching the Cache MCP Server over STDIO.

    Parses command-line configuration arguments, instantiates the MCPServer,
    and runs the standard input/output JSON-RPC event loop.
    """
    parser = argparse.ArgumentParser(description="Cache MCP Server")
    parser.add_argument("--dir", type=Path, required=True, help="Root cache directory")
    parser.add_argument(
        "--max-ttl", type=int, default=1800, help="Maximum allowed TTL in seconds"
    )
    parser.add_argument(
        "--max-cache-size",
        type=int,
        default=10 * 1024 * 1024,
        help="Max uncompressed cache entry size",
    )
    parser.add_argument(
        "--max-total-compressed-cache-size",
        type=int,
        default=500 * 1024 * 1024,
        help="Max total compressed cache size",
    )

    args = parser.parse_args()
    config = Config(
        dir=args.dir,
        max_ttl=args.max_ttl,
        max_cache_size=args.max_cache_size,
        max_total_compressed_cache_size=args.max_total_compressed_cache_size,
    )

    server = create_mcp_server(config)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
