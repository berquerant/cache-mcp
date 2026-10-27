# Agent Guidelines for `cache-mcp`

This repository implements the `cache-mcp` Model Context Protocol (MCP) server for local, high-performance caching of command and tool execution results.

All AI agents operating in this repository must adhere to the following rules and guidelines.

---

## 1. Keeping Documentation & AGENTS.md Up to Date
When making structural changes to the project (adding/removing modules, commands, options, or conventions), **update this file** and `README.md` so they accurately reflect the current state of the codebase.

---

## 2. Natural Language Policy
- **Language**: English is strictly required for all natural language content throughout this repository:
  - Code comments and docstrings.
  - Commit messages and pull request descriptions.
  - Markdown documentation (`README.md`, reports, skill files).

---

## 3. Repository Layout

```text
cache-mcp/
├── .agents/
│   └── skills/
│       └── cache-memoizer/    # Agent skill for transparent cache-mcp interaction
├── .github/
│   ├── dependabot.yml         # Dependabot configuration (github-actions, uv)
│   └── workflows/
│       └── ci.yml             # GitHub Actions CI workflow (lint & test jobs)
├── scripts/
│   └── release.py             # Automated SemVer release script (bump, uv lock, commit, tag, push)
├── src/
│   └── cache_mcp/             # Main Python package
│       ├── __init__.py        # Package metadata
│       ├── __main__.py        # Entry point for `python -m cache_mcp`
│       ├── cli/               # CLI command suite and argument parsing
│       │   ├── __init__.py    # CLI entry point function `cli()`
│       │   ├── handlers.py    # Subcommand execution handlers (get, set, ...)
│       │   └── parser.py      # Argparse parser definitions
│       ├── lock.py            # Reentrant POSIX file lock with timeout
│       ├── logger.py          # Rotating audit logger & string value truncation
│       ├── main.py            # Top-level CLI entry point
│       ├── models.py          # Pydantic schemas, Config, key computation, and version parsing
│       ├── server.py          # MCPServer instance and tool definitions (get, set, exist, delete, version, purge)
│       ├── service.py         # Unified CacheService handling operations, formatting, and audit logging
│       └── storage.py         # CacheStorage engine (zstd, sharding, immutable versioning, FIFO eviction)
├── tests/
│   ├── test_cli.py            # Table-driven tests for CLI subcommands
│   ├── test_e2e_install.py    # E2E tests (wheel build, clean venv pip install, and CLI execution)
│   ├── test_lock_and_logger.py# Tests for file locking and structured logging
│   ├── test_models.py         # Tests for Config, CacheEntry, key derivation
│   ├── test_server.py         # Table-driven MCP tool roundtrip tests
│   ├── test_storage.py        # Table-driven unit tests for CacheStorage
│   └── test_storage_concurrency.py # Thread & process concurrency tests
├── Makefile                   # Task runner for dev workflows (check, format, mypy, test, release)
├── pyproject.toml             # Project metadata, Hatchling build backend, dependencies
├── uv.lock                    # uv lockfile for reproducible dependency management
└── README.md                  # User-facing documentation
```

---

## 4. Python Environment & Tooling
- **Python Version**: Requires Python 3.14+ (leverages standard library `compression.zstd`).
- **Package & Environment Manager**: Use `uv` for all environment management, dependency resolution, and running tools:
  - Dependency syncing: `uv sync`
  - Tool execution: `uv run ...`
- **Build System**: Uses `hatchling` (`[build-system]` in `pyproject.toml`).

---

## 5. Development Tasks & Verification Commands
- Use the provided `Makefile` targets:
  - `make check`: Run linters without file modification (`ruff check .` and `ruff format --check .`).
  - `make format`: Auto-fix lint violations and format code (`ruff check --fix .` and `ruff format .`).
  - `make mypy`: Run static type checking across `src`, `tests`, and `scripts`.
  - `make test`: Run unit, concurrency, and E2E test suites with `pytest`.
  - `make check-all`: Execute `check`, `mypy`, and `test` sequentially.
  - `make release VER=<version> [ARGS=--dry-run]`: Run automated release workflow.
- **Pre-Completion Rule**: Always run `make check-all` before concluding tasks to ensure zero regressions and clean formatting.

---

## 6. Coding Conventions & Design Constraints
- **Pattern Matching**: Prefer Python `match` statements over long `if-elif-else` chains for structural branching where applicable.
- **Platform Scope**: Target POSIX environments only. Concurrency control relies on `fcntl.flock`. Windows-specific handling is out of scope.
- **Storage & Cache Filename Convention**:
  - Filenames must follow `<key>_<created_ts>_<ttl_ts>_<version>.zst`.
  - Immutability: Existing cache entries are immutable and never overwritten. `set()` creates a new entry with monotonically increasing positive integer version.
  - Never perform unnecessary disk reads or zstd decompressions when answering metadata queries (such as in `exist()` and `version()`).
- **MCP Tool Protocol**:
  - Distinguish between expected business outcomes (cache miss, capacity quota skip) which return `isError: false` with structured payload (`hit: false`, `success: false`), and fatal system failures (I/O, lock timeout) which set `isError: true`.
- **Testing**:
  - Use Table-Driven Tests (`@pytest.mark.parametrize`) for comprehensive input-output validation.
  - Ensure thread and process concurrency tests pass reliably without deadlocks.

---

## 7. Release Process
Automated via `scripts/release.py` (or `make release VER=<version>`):
1. Validates SemVer format.
2. Checks git working tree is clean.
3. Checks tag collision against local and remote tags.
4. Executes full verification (`make check-all`).
5. Bumps version in `pyproject.toml`.
6. Runs `uv lock` to update `uv.lock`.
7. Creates commit `release: v<version>` and annotated tag `v<version>`.
8. Pushes branch and tag to remote (if configured and `--no-push` is not set).
