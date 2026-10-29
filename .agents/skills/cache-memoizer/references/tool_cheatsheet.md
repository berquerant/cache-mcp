# MCP Tool Parameter Cheatsheet for `cache-mcp`

Quick reference for calling `cache-mcp` tools from AI agents.

---

## 1. `get` (Retrieve Cache)
Retrieves a valid, unexpired cache entry.

### Arguments
Either provide `key` directly (optionally including `@<version>` suffix), OR specify command context fields:
```json
{
  "key": "abcdef123456...64hex@1"
}
```
or with explicit version:
```json
{
  "key": "abcdef123456...64hex",
  "version": 1
}
```
or by command attributes:
```json
{
  "type": "command",
  "name": "git",
  "dir": "/path/to/repo",
  "args": ["log", "-n", "5"],
  "stdin": null,
  "version": "latest"
}
```

### Return Format
```json
{
  "hit": true,
  "key": "abcdef...@1",
  "version": 1,
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
Same input format as `get` (`key` or `type, name, dir, args, stdin`, plus optional `version`).

### Return Format
```json
{
  "hit": true,
  "key": "abcdef..."
}
```

---

## 3. `set` (Store Cache)
Saves execution results to cache as a new immutable version (incrementing version monotonically: 1, 2, ...).

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
  "key": "abcdef...@2",
  "version": 2,
  "message": null
}
```

---

## 4. `delete` (Delete Cache by Key)
Removes matching cache entries. If `version` is omitted, deletes all versions. If `version` is specified, deletes only that version.

### Arguments
Same input format as `get` (`key` or `type, name, dir, args, stdin`, plus optional `version`).

### Return Format
```json
{
  "hit": true,
  "deleted": true,
  "key": "abcdef...",
  "version": null,
  "deleted_count": 2
}
```

---

## 5. `version` (List Versions)
Lists all valid, unexpired versions for a key without reading file payloads.

### Arguments
Same input format as `get` (`key` or `type, name, dir, args, stdin`).

### Return Format
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

---

## 6. `purge` (Purge Caches)
Purges cache files across all subdirectories and reclaims disk space.

### Arguments
- `all` (`bool`, optional, default: `false`): When `false`, deletes only expired cache files. When `true`, deletes all cache files.

```json
{
  "all": false
}
```

### Return Format
```json
{
  "success": true,
  "deleted_count": 15,
  "freed_bytes": 1048576,
  "all": false,
  "message": null
}
```
