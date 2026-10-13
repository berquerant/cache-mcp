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

The server provides 5 MCP tools. Each tool accepts either a direct `key` (64-character SHA-256 hex string) or tool invocation attributes (`type`, `name`, `dir`, `args`, `stdin`).

### 1. `get` (Retrieve Cache)
Retrieves a valid, non-expired cache entry matching the key or execution parameters.

- **Arguments**:
  - `key` (`string`, optional): Direct cache key.
  - `type` (`string`, optional): Invocation type (`"command"`, `"mcp"`, etc.).
  - `name` (`string`, optional): Command or tool name (`"git"`, `"read_file"`, etc.).
  - `dir` (`string`, optional): Working directory path.
  - `args` (`list[string]`, optional, default: `[]`): Command arguments.
  - `stdin` (`string`, optional, default: `null`): Standard input string.
- **Return Value**:
  ```json
  {
    "hit": true,
    "key": "abcdef...",
    "data": { ... }
  }
  ```
  *Note: On cache miss, expiration, or storage error, returns `"hit": false` along with an optional `"reason"` string (e.g. `"miss"`, `"expired"`, `"invalid_key"`, `"timeout"`, or `"corrupt: ..."`) and optional `"error"` message. Expired files are lazily deleted on access.*

### 2. `set` (Store Cache)
Compresses and persists execution results using zstd.

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
    "key": "abcdef...",
    "message": null
  }
  ```

### 3. `exist` (Check Cache Presence)
Checks if a valid, non-expired cache entry exists for the given key without decompressing payload data.

- **Arguments**: Same as `get` (`key` or invocation parameters).
- **Return Value**:
  ```json
  {
    "hit": true,
    "key": "abcdef..."
  }
  ```

### 4. `delete` (Delete Cache Entry)
Deletes cache files matching the specified key.

- **Arguments**: Same as `get` (`key` or invocation parameters).
- **Return Value**:
  ```json
  {
    "hit": true,
    "deleted": true,
    "key": "abcdef..."
  }
  ```

### 5. `purge` (Purge All Caches)
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
