# Recommended TTL Guidelines by Operation Type

Choosing an appropriate TTL balances cache freshness with token and execution savings.

---

## 1. Guideline Matrix

| Operation Category | Examples | Recommended TTL | Rationale |
|:---|:---|:---|:---|
| **Immutable Git References** | `git show <commit>`, `git cat-file`, `git log <commit> -n 1` | **1800s (30m) or max** | Content addressed by commit hash never changes. |
| **Branch / Repo History** | `git log -n 10`, `git rev-parse HEAD` | **300s - 600s** | Infrequent updates during standard read tasks. |
| **Working Tree Inspection** | `git status`, `git diff` | **30s - 60s (or avoid caching)** | Modifies frequently during code editing. |
| **Read-Only System & Tools** | `which <cmd>`, `python --version`, `uname -a` | **1800s (30m)** | Environment configuration is generally static per session. |
| **Lint / Type Checks** | `ruff check`, `mypy` | **120s - 300s** | Useful when checking across multiple subagents/turns without edits. Invalidate upon file edit. |
| **Package / Dependency Inspection** | `pip list`, `uv tree`, `npm list` | **600s - 1800s** | Installed package state rarely changes during continuous turns. |
| **HTTP / API Read Calls** | `curl` documentation, MCP search lookups | **300s - 1800s** | Avoids rate limits and redundant roundtrips. |

---

## 2. Invalidation & Non-Cacheable Actions

### When to Invalidate or Avoid Caching
- **State Modifications**: Any operation modifying filesystem or repo state (`git commit`, `git checkout`, file edits, `pip install`) must **NOT** be cached.
- **Side-Effects**: Commands like `curl -X POST`, `rm`, `mv` should never be cached.
- **Dynamic Clock / Randomness**: Commands outputting random tokens, timestamps, or UUIDs should bypass cache.

### Invalidation Strategy
- When modifying a file or git commit, call `delete` on affected keys if you cached operations like `git status` or lint results.
- Or simply rely on short TTLs for working tree queries.
