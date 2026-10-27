import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

CACHE_KEY_REGEX = re.compile(r"^[0-9a-zA-Z_-]{2,64}$")


def is_valid_cache_key(key: str) -> bool:
    """Validate that key is safe for filesystem path sharding (no slashes, dots, null bytes)."""
    return bool(CACHE_KEY_REGEX.match(key))


def parse_versioned_key(key: str) -> tuple[str, int | str | None] | None:
    """Parse a potentially versioned cache key into (base_key, version).

    Supports:
        - '<base_key>' -> (base_key, None)
        - '<base_key>@latest' -> (base_key, 'latest')
        - '<base_key>@<version>' -> (base_key, <int version>)

    Returns:
        (base_key, version) if key and version format are valid, else None.
    """
    if "@" in key:
        parts = key.split("@")
        if len(parts) != 2:
            return None
        base_key, ver_str = parts
        if not is_valid_cache_key(base_key):
            return None
        if ver_str == "latest":
            return base_key, "latest"
        if ver_str.isdigit() and int(ver_str) > 0:
            return base_key, int(ver_str)
        return None
    if is_valid_cache_key(key):
        return key, None
    return None


def format_versioned_key(base_key: str, version: int | str | None = None) -> str:
    """Format base cache key with version suffix if provided."""
    if version is not None:
        return f"{base_key}@{version}"
    return base_key


class VersionInfo(BaseModel):
    """Metadata representing an existing cache entry version."""

    version: int
    key: str
    created_timestamp: int
    ttl_timestamp: int
    expired: bool


class Config(BaseModel):
    """Server-wide runtime configuration parameters.

    Attributes:
        dir: Root directory path for storing cache files, locks, and logs.
        max_ttl: Maximum allowed TTL (in seconds). Any TTL requested by a client
            exceeding this value will be capped to prevent stale data accumulation.
        max_cache_size: Maximum uncompressed byte size for a single cache entry JSON payload.
            Prevents memory spikes during serialization/deserialization.
        max_total_compressed_cache_size: Total disk budget (in bytes) allocated for all
            compressed `.zst` cache files combined. Triggers FIFO eviction when exceeded.
    """

    dir: Path
    max_ttl: int
    max_cache_size: int
    max_total_compressed_cache_size: int


class CacheEntry(BaseModel):
    """Schema representing an individual cached execution record.

    Stores complete process/tool invocation context, execution outputs, and temporal
    metadata to enable transparent replay and cache auditing.
    """

    type: str
    name: str
    args: list[str] = Field(default_factory=list)
    dir: str
    created_timestamp: int
    ttl: int
    ttl_timestamp: int
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    description: str | None = None
    stdin: str | None = None
    stdout: str
    stderr: str
    success: bool
    status_code: int | None = None
    status_string: str | None = None


def normalize_dir(dir_path: str | Path) -> str:
    """Resolve directory to absolute real path.

    Why:
        Directory paths often contain slight syntactic variations (e.g. `/foo/bar` vs
        `/foo/bar/`, relative paths like `./src`, or symlinks). Resolving to an absolute
        canonical path guarantees deterministic hashing across diverse caller contexts.
    """
    return str(Path(dir_path).resolve())


def compute_cache_key(
    type: str,
    name: str,
    dir: str | Path,
    args: list[str] | None = None,
    stdin: str | None = None,
) -> str:
    """Compute a deterministic 64-character SHA-256 hex cache key using Canonical JSON.

    Why Canonical JSON:
        Simple string concatenation with delimiters risks
        accidental collision or injection if tool arguments or standard input happen
        to contain those delimiter sequences. Canonical JSON (sorted keys, compact separators,
        strictly typed values) guarantees unambiguous, deterministic serialization.

    Args:
        type: Invocation type ('command', 'mcp', etc.).
        name: Command or tool name ('git', 'read_file', etc.).
        dir: Working directory of the invocation (normalized automatically).
        args: Ordered list of command-line or tool arguments.
        stdin: Standard input string, or None if not provided.

    Returns:
        64-character hexadecimal SHA-256 digest string.
    """
    norm_dir = normalize_dir(dir)
    payload: dict[str, Any] = {
        "args": args if args is not None else [],
        "dir": norm_dir,
        "name": name,
        "stdin": stdin,
        "type": type,
    }
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()
