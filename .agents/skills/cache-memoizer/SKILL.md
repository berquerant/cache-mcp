---
name: cache-memoizer
description: >-
  Use this skill when running repetitive or expensive CLI commands or MCP tools,
  or when checking if prior execution results (e.g. git queries, API inspections, test suites)
  can be retrieved from the local cache-mcp server before re-running them.
---

# Cache Memoizer Skill

This skill teaches the agent how to efficiently interact with the `cache-mcp` server to memoize commands, avoid redundant executions, save token budget, and reduce latency.

---

## 1. When to Use This Skill

Activate this skill when:
- Executing read-only CLI commands that may have already run (e.g., `git log`, `git show <sha>`, dependency checks, build inspects).
- Querying MCP tools repeatedly with the same arguments.
- Running multi-step tasks or subagents where prior turns might have computed the necessary output.

**Do NOT cache:**
- Operations with side effects (file modifications, git commits, deployments, `rm`, `curl -X POST`).
- Real-time/volatile queries (clocks, random IDs, rapidly shifting status).

---

## 2. Core Workflow: Check -> Execute -> Cache

Follow this 3-step loop:

```
[Agent Task] ---> Step 1: Check Cache (exist or get)
                     |
         +-----------+-----------+
         | (Cache Hit)           | (Cache Miss)
         v                       v
[Use cached output]      Step 2: Run Actual Command / Tool
                                 |
                         Step 3: Save to Cache (set)
                                 |
                                 v
                         [Use command output]
```

### Step 1: Check Cache (`get` or `exist`)
Call the `get` tool from `cache-mcp`:
```json
{
  "type": "command",
  "name": "git",
  "dir": "<current_absolute_dir>",
  "args": ["log", "-n", "5"]
}
```
- If `hit: true`: Use `data.stdout` (or `data.stderr`, `data.status_code`) directly without executing the command.
- If `hit: false`: Proceed to Step 2.

> **Tip**:
> - If you only need to know whether an item exists before deciding on a branch (without needing the content), call `exist`. It checks metadata from filenames with zero disk reads and zero decompression.
> - Cache entries are immutable: calling `set` appends a new positive integer version. Query specific versions via `version: 1` or key suffix `@1` (defaults to latest valid version). Call `version` to list all versions.

### Step 2: Execute Actual Command
If cache missed, run the command normally. Capture:
- `stdout`, `stderr`, and exit code (`status_code`)
- (Optional) `start_timestamp` and `end_timestamp` (UNIX epoch seconds)

### Step 3: Save Result (`set`)
Call `set` on `cache-mcp` with an appropriate TTL:
```json
{
  "type": "command",
  "name": "git",
  "dir": "<current_absolute_dir>",
  "args": ["log", "-n", "5"],
  "ttl": 600,
  "stdout": "<captured stdout>",
  "stderr": "<captured stderr>",
  "success": true,
  "start_timestamp": 1776000000,
  "end_timestamp": 1776000001,
  "status_code": 0,
  "status_string": "OK"
}
```
*(Note: `start_timestamp`, `end_timestamp`, `status_code`, `status_string`, `stdin`, `args`, and `description` are optional.)*

---

## 3. Recommended TTLs

Refer to [ttl_guidelines.md](./references/ttl_guidelines.md) for full details:
- **Immutable Git Objects** (`git show <sha>`, `git cat-file`): **1800s (30m)**
- **Repo State / History** (`git log`, `git rev-parse HEAD`): **300s - 600s**
- **Working Tree State** (`git status`, `git diff`): **30s - 60s** (or avoid caching)
- **Tool / Environment Info** (`which <bin>`, `python --version`): **1800s (30m)**

---

## 4. Error Handling & Graceful Degradation

If calling `cache-mcp` fails (e.g. server unavailable, lock timeout after 10s, or disk quota full):
1. **Never block the user's task.**
2. Gracefully fall back to running the command directly without caching.
3. If cache files are corrupted or quota needs freeing, call `purge` or `delete`.

For detailed schemas and tool arguments, refer to [tool_cheatsheet.md](./references/tool_cheatsheet.md).
