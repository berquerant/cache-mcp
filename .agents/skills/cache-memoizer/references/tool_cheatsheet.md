# MCP Tool Parameter Cheatsheet for `cache-mcp`

Quick reference for calling `cache-mcp` tools from AI agents.

---

## 1. `get` (Retrieve Cache)
Retrieves a valid, unexpired cache entry.

### Arguments
Either provide `key` directly, OR specify command context fields:
```json
{
  "key": "abcdef123456...64hex"
}
```
or:
```json
{
  "type": "command",
  "name": "git",
  "dir": "/path/to/repo",
  "args": ["log", "-n", "5"],
  "stdin": null
}
```

### Return Format
```json
{
  "hit": true,
  "key": "abcdef...",
  "data": {
    "type": "command",
    "name": "git",
    "args": ["log", "-n", "5"],
    "dir": "/path/to/repo",
    "start_timestamp": 1776000000,
    "end_timestamp": 1776000001,
    "created_timestamp": 1776000001,
    "ttl": 1800,
    "ttl_timestamp": 1776001801,
    "stdout": "commit ...",
    "stderr": "",
    "success": true,
    "status_code": 0,
    "status_string": "OK"
  }
}
```
*Note: If `hit` is `false`, `data` is omitted and an optional `reason` (e.g. `"miss"`, `"expired"`, `"invalid_key"`, `"timeout"`, `"corrupt: ..."`) and `error` may be present.*

---

## 2. `exist` (Fast Existence Check)
Lightweight existence check without reading or decompressing file contents.

### Arguments
Same input format as `get` (`key` or `type, name, dir, args, stdin`).

### Return Format
```json
{
  "hit": true,
  "key": "abcdef..."
}
```

---

## 3. `set` (Store Cache)
Saves execution results to cache.

### Arguments
```json
{
  "type": "command",
  "name": "git",
  "dir": "/path/to/repo",
  "args": ["status", "--short"],
  "stdin": null,
  "ttl": 300,
  "stdout": " M file.py\n",
  "stderr": "",
  "success": true,
  "start_timestamp": 1776000000,
  "end_timestamp": 1776000001,
  "status_code": 0,
  "status_string": "OK",
  "description": "Git status short output"
}
```

### Return Format
```json
{
  "success": true,
  "key": "abcdef...",
  "message": null
}
```

---

## 4. `delete` (Delete Cache by Key)
Removes matching cache entries.

### Arguments
Same input format as `get`.

### Return Format
```json
{
  "hit": true,
  "deleted": true,
  "key": "abcdef..."
}
```

---

## 5. `purge` (Flush All Caches)
Clears all cached items and resets storage size tracker.

### Arguments
None (`{}`).

### Return Format
```json
{
  "success": true,
  "deleted_count": 15,
  "freed_bytes": 1048576,
  "message": null
}
```
