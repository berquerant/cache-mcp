"""CLI entry point for Cache MCP."""

import sys

from cache_mcp.cli import cli


def main() -> None:
    """Entry point for command execution."""
    sys.exit(cli())


if __name__ == "__main__":
    main()
