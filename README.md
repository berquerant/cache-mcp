# Cache MCP Server (`cachemcp`)

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server providing safe, high-performance local caching for CLI commands and MCP tool invocations executed by AI agents.

It avoids duplicate executions under identical parameters and contexts, reducing latency, token consumption, external API quota usage, and rate-limit exhaustion.

---

## Key Features

- **Compressed Storage**: Fast compression with standard library zstd and 2-tier directory sharding.
- **Concurrency & Consistency**: Process-safe POSIX file locks (`fcntl.flock`, 10s timeout) and atomic writes.
- **Quota & FIFO Eviction**: In-memory capacity tracking with automatic expired cleanup and FIFO eviction.
- **Deterministic Keys**: SHA-256 over Canonical JSON with normalized working directory paths.
- **Safe Audit Logging**: Dedicated rotating log file isolated from STDIO JSON-RPC communication.


---

## Installation & Getting Started

This project uses [`uv`](https://github.com/astral-sh/uv) as its package manager.

### Dependency Setup

```bash
uv sync
```

### Starting the Server

Run the server over STDIO transport for MCP clients (Claude Desktop, Cursor, Antigravity, etc.):

```bash
uv run python -m cache_mcp.main --dir ~/.cache/cachemcp
```

#### CLI Options

| Option | Type | Default | Description |
|:---|:---|:---|:---|
| `--dir` | Path (`Path`) | **Required** | Root directory for cached files, locks, and logs. |
| `--max-ttl` | Integer (`int`) | `1800` (30m) | Upper bound for cache TTL in seconds. Values exceeding this are clamped. |
| `--max-cache-size` | Integer (`int`) | `10485760` (10MB) | Maximum uncompressed byte size for a single cache entry JSON payload. |
| `--max-total-compressed-cache-size` | Integer (`int`) | `524288000` (500MB) | Total disk budget (in bytes) for all compressed `.zst` files. Triggers eviction when exceeded. |

---

## Provided MCP Tools

The server provides 6 MCP tools. Each tool accepts either a direct `key` (64-character SHA-256 hex string, optionally with `@<version>` suffix such as `@1` or `@latest`) or tool invocation attributes (`type`, `name`, `dir`, `args`, `stdin`).

### 1. `get` (Retrieve Cache)
Retrieves a valid, non-expired cache entry matching the key or execution parameters.

- **Arguments**:
  - `key` (`string`, optional): Direct cache key (can include `@<version>` or `@latest`).
  - `version` (`int | string`, optional): Target version (e.g. `1`, `2`, `"latest"`). Defaults to latest valid version.
  - `type` (`string`, optional): Invocation type (`"command"`, `"mcp"`, etc.).
  - `name` (`string`, optional): Command or tool name (`"git"`, `"read_file"`, etc.).
  - `dir` (`string`, optional): Working directory path.
  - `args` (`list[string]`, optional, default: `[]`): Command arguments.
  - `stdin` (`string`, optional, default: `null`): Standard input string.
- **Return Value**:
  ```json
  {
    "hit": true,
    "key": "abcdef...@2",
    "version": 2,
    "data": { ... }
  }
  ```
  *Note: On cache miss, expiration, or storage error, returns `"hit": false` along with an optional `"reason"` string (e.g. `"miss"`, `"expired"`, `"invalid_key"`, `"timeout"`, or `"corrupt: ..."`) and optional `"error"` message. Expired files are lazily deleted on access.*

### 2. `set` (Store Cache)
Compresses and persists execution results as a new immutable version (incrementing version monotonically: 1, 2, ...). Existing versions are never overwritten.

- **Arguments**:
  - `type` (`string`, required), `name` (`string`, required), `dir` (`string`, required)
  - `ttl` (`int`, required), `stdout` (`string`, required), `stderr` (`string`, required), `success` (`bool`, required)
  - `start_timestamp` (`int`, optional), `end_timestamp` (`int`, optional)
  - `args` (`list[string]`, optional), `description` (`string`, optional)
  - `stdin` (`string`, optional), `status_code` (`int`, optional), `status_string` (`string`, optional)
- **Return Value**:
  ```json
  {
    "success": true,
    "key": "abcdef...@2",
    "version": 2,
    "message": null
  }
  ```

### 3. `exist` (Check Cache Presence)
Checks if a valid, non-expired cache entry exists for the given key and version without decompressing payload data.

- **Arguments**: Same as `get` (`key` or invocation parameters, plus optional `version`).
- **Return Value**:
  ```json
  {
    "hit": true,
    "key": "abcdef..."
  }
  ```

### 4. `version` (List Versions)
Lists all existing, non-expired versions for the given key without reading file payloads.

- **Arguments**: Same as `get` (`key` or invocation parameters).
- **Return Value**:
  ```json
  {
    "hit": true,
    "key": "abcdef...",
    "versions": [
      {
        "version": 1,
        "key": "abcdef...@1",
        "created_timestamp": 1776000000,
        "ttl_timestamp": 1776001800,
        "expired": false
      },
      {
        "version": 2,
        "key": "abcdef...@2",
        "created_timestamp": 1776000500,
        "ttl_timestamp": 1776002300,
        "expired": false
      }
    ]
  }
  ```

### 5. `delete` (Delete Cache Entry)
Deletes cache files matching the specified key. If `version` (or `@<version>`) is omitted, deletes all versions. If `version` is specified, deletes only that version.

- **Arguments**: Same as `get` (`key` or invocation parameters, plus optional `version`).
- **Return Value**:
  ```json
  {
    "hit": true,
    "deleted": true,
    "key": "abcdef...",
    "version": null,
    "deleted_count": 2
  }
  ```

### 6. `purge` (Purge All Caches)
Deletes all cached files across all subdirectories and resets the in-memory size tracker.

- **Arguments**: None.
- **Return Value**:
  ```json
  {
    "success": true,
    "deleted_count": 42,
    "freed_bytes": 1048576,
    "message": null
  }
  ```

---

## Command-Line Interface (CLI)

`cache-mcp` provides a full CLI corresponding to the MCP tools, returning structured JSON on stdout with standard exit codes (0 for hit/success, 1 for miss/not found, 2 for error):

```bash
# Start MCP STDIO Server (default if subcommand is omitted)
cache-mcp server --dir ~/.cache/cachemcp

# Store cache entry
cache-mcp set --dir ~/.cache/cachemcp --type command --name git --cmd-dir $(pwd) --args status --stdout "clean"

# Store via JSON string or file
cache-mcp set --dir ~/.cache/cachemcp --json '{"type": "command", "name": "test", "dir": "/tmp", "stdout": "ok", "stderr": "", "success": true, "ttl": 300, "created_timestamp": 1776000000, "ttl_timestamp": 1776000300}'

# Query cache entry (defaults to latest version)
cache-mcp get --dir ~/.cache/cachemcp --key <key>

# Query specific version
cache-mcp get --dir ~/.cache/cachemcp --key <key> --version 1
# or
cache-mcp get --dir ~/.cache/cachemcp --key <key>@1

# Check existence
cache-mcp exist --dir ~/.cache/cachemcp --key <key>

# List all versions
cache-mcp version --dir ~/.cache/cachemcp --key <key>

# Delete specific version or all versions
cache-mcp delete --dir ~/.cache/cachemcp --key <key> --version 1
cache-mcp delete --dir ~/.cache/cachemcp --key <key>

# Purge entire cache
cache-mcp purge --dir ~/.cache/cachemcp
```

---

## Design & Architecture Details

For comprehensive design rationale, concurrency analysis, and architecture decisions, see [cachemcp_report.md](cachemcp_report.md).

---

## Development & Testing

Common development workflows are automated via [`Makefile`](Makefile):

```bash
# Show available targets
make help

# Code style check (ruff check + ruff format --check)
make check

# Format and autofix
make format

# Type checking (mypy)
make mypy

# Run tests (pytest)
make test
make test-v   # verbose output

# Run all verification checks (format check, lint, mypy, pytest)
make check-all

# Clean cache directories and build artifacts
make clean

# Automated release (tests, version bump, uv lock, git commit, tag, push)
make release VER=0.2.0
make release VER=0.2.0 ARGS=--dry-run
```
