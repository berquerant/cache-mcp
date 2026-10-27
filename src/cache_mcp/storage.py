import os
import time
import uuid
from compression import zstd
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from cache_mcp.lock import FileLock
from cache_mcp.models import (
    CacheEntry,
    Config,
    VersionInfo,
    format_versioned_key,
    parse_versioned_key,
)


@dataclass
class StorageResult:
    success: bool
    key: str | None = None
    version: int | None = None
    message: str | None = None


@dataclass
class GetResult:
    hit: bool
    key: str
    version: int | None = None
    data: CacheEntry | None = None
    reason: str | None = None


@dataclass
class DeleteResult:
    hit: bool
    deleted: bool
    key: str
    version: int | str | None = None
    deleted_count: int = 0


@dataclass
class VersionResult:
    hit: bool
    key: str
    versions: list[VersionInfo] = field(default_factory=list)
    reason: str | None = None


@dataclass
class PurgeResult:
    success: bool
    deleted_count: int
    freed_bytes: int
    message: str | None = None


class CacheStorage:
    """Core storage engine managing compressed immutable cache files on disk.

    Architecture & Invariants:
        - Sharding: Two-level directory structure using first 2 chars of SHA-256 key (`<dir>/<key[:2]>/`).
        - File Naming Scheme: `<key>_<created_timestamp>_<ttl_timestamp>_<version>.zst`. Embeds temporal metadata
          and version directly in filenames, enabling fast metadata extraction without reading or
          decompressing file contents.
        - Immutability: Existing cache versions are never overwritten. `set()` creates a new entry with
          monotonically increasing version (1, 2, 3...).
        - Compression: Standard library `compression.zstd` at default Level 3.
        - Concurrency: Coordinated via POSIX `FileLock` with 10s timeout on `<dir>/locks/lockfile`.
        - Capacity & Eviction: Tracks total compressed bytes in-memory. When capacity is exceeded,
          expired files are purged first, followed by FIFO eviction (oldest `created_timestamp` removed first).
        - Atomic Writes: Writes to a unique `.tmp_<pid>_<uuid>.zst` in the destination directory, then
          uses `os.replace` (atomic rename within the same filesystem) to prevent torn reads.
    """

    def __init__(self, config: Config) -> None:
        """Initialize CacheStorage and restore in-memory size ledger.

        Args:
            config: Server configuration specifying storage root and capacity budgets.
        """
        self.config = config
        self.root_dir = config.dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(self.root_dir / "locks" / "lockfile", timeout=10.0)
        self._total_compressed_size = 0
        self._init_scan_total_size()

    def _init_scan_total_size(self) -> None:
        """Scan all .zst files on startup to initialize the in-memory size ledger."""
        total = 0
        for p in self.root_dir.glob("*/*.zst"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        self._total_compressed_size = total

    @property
    def total_compressed_size(self) -> int:
        return self._total_compressed_size

    def _get_sub_dir(self, key: str) -> Path:
        sub = self.root_dir / key[:2]
        sub.mkdir(parents=True, exist_ok=True)
        return sub

    @staticmethod
    def _parse_cache_file_info(path: Path) -> tuple[str, int, int, int, int] | None:
        """Parse (key, created_timestamp, ttl_timestamp, version, file_size) from a cache file.

        Supports standard format: `<key>_<created_timestamp>_<ttl_timestamp>_<version>.zst`.
        Also supports legacy format: `<key>_<created_timestamp>_<ttl_timestamp>.zst` (as version 1).
        Returns None if parsing fails or path is inaccessible.
        """
        try:
            parts = path.stem.rsplit("_", maxsplit=3)
            size = path.stat().st_size
            match parts:
                case [key, created_str, ttl_str, ver_str]:
                    return key, int(created_str), int(ttl_str), int(ver_str), size
                case [key, created_str, ttl_str]:
                    # Legacy format fallback
                    return key, int(created_str), int(ttl_str), 1, size
                case _:
                    return None
        except ValueError, OSError:
            pass
        return None

    def _unlink_and_deduct(self, path: Path, size: int) -> bool:
        """Remove file from disk and deduct size from in-memory ledger."""
        try:
            path.unlink(missing_ok=True)
            self._total_compressed_size -= size
            return True
        except OSError:
            return False

    def _find_files_by_key(
        self, base_key: str
    ) -> list[tuple[Path, int, int, int, int]]:
        """Find all files starting with <base_key>_ in <base_key[:2]>.

        Returns:
            List of (Path, created_timestamp, ttl_timestamp, version, file_size).
        """
        sub = self.root_dir / base_key[:2]
        if not sub.exists():
            return []
        results = []
        prefix = f"{base_key}_"
        for p in sub.iterdir():
            if p.is_file() and p.name.startswith(prefix) and p.name.endswith(".zst"):
                info = self._parse_cache_file_info(p)
                if info is not None and info[0] == base_key:
                    results.append((p, info[1], info[2], info[3], info[4]))
        return results

    def _find_and_clean_files(
        self, base_key: str, now: int
    ) -> tuple[
        list[tuple[Path, int, int, int, int]], list[tuple[Path, int, int, int, int]]
    ]:
        """Find all versions for base_key and lazily evict expired versions.

        Returns:
            (valid_files, expired_files)
        """
        files = self._find_files_by_key(base_key)
        valid: list[tuple[Path, int, int, int, int]] = []
        expired: list[tuple[Path, int, int, int, int]] = []
        for item in files:
            p, _, ttl_ts, _, sz = item
            if ttl_ts <= now:
                self._unlink_and_deduct(p, sz)
                expired.append(item)
            else:
                valid.append(item)
        return valid, expired

    def get(self, key: str, version: int | str | None = None) -> GetResult:
        """Retrieve and decompress cached record by key and optional version.

        Args:
            key: Direct cache key (may optionally include `@<version>` suffix).
            version: Explicit version ('latest', integer version, or None).

        Returns:
            GetResult containing hit status, data, and metadata.
        """
        parsed = parse_versioned_key(key)
        if parsed is None:
            return GetResult(hit=False, key=key, reason="invalid_key")

        base_key, key_ver = parsed
        target_ver = version if version is not None else key_ver
        if isinstance(target_ver, str) and target_ver != "latest":
            try:
                target_ver = int(target_ver)
            except ValueError:
                return GetResult(hit=False, key=key, reason="invalid_version")

        with self.lock:
            now = int(time.time())
            valid_files, expired_files = self._find_and_clean_files(base_key, now)

            if not valid_files and not expired_files:
                target_key_str = format_versioned_key(base_key, target_ver)
                return GetResult(
                    hit=False,
                    key=target_key_str,
                    version=target_ver if isinstance(target_ver, int) else None,
                    reason="miss",
                )

            # Resolve target file
            target_file: tuple[Path, int, int, int, int] | None = None
            if target_ver is None or target_ver == "latest":
                if not valid_files:
                    return GetResult(
                        hit=False,
                        key=format_versioned_key(base_key, target_ver),
                        reason="expired",
                    )
                # Pick latest version
                valid_files.sort(key=lambda x: x[3], reverse=True)
                target_file = valid_files[0]
            else:
                # Specific integer version
                assert isinstance(target_ver, int)
                for item in valid_files:
                    if item[3] == target_ver:
                        target_file = item
                        break
                if target_file is None:
                    # Check if it was among expired
                    for item in expired_files:
                        if item[3] == target_ver:
                            return GetResult(
                                hit=False,
                                key=format_versioned_key(base_key, target_ver),
                                version=target_ver,
                                reason="expired",
                            )
                    return GetResult(
                        hit=False,
                        key=format_versioned_key(base_key, target_ver),
                        version=target_ver,
                        reason="miss",
                    )

            target_path, _, _, resolved_ver, _ = target_file
            resolved_key_str = format_versioned_key(base_key, resolved_ver)

            # Read and decompress
            try:
                compressed_data = target_path.read_bytes()
                decompressed_data = zstd.decompress(compressed_data)
                entry = CacheEntry.model_validate_json(
                    decompressed_data.decode("utf-8")
                )
                return GetResult(
                    hit=True, key=resolved_key_str, version=resolved_ver, data=entry
                )
            except (zstd.ZstdError, ValidationError, UnicodeDecodeError) as e:
                return GetResult(
                    hit=False,
                    key=resolved_key_str,
                    version=resolved_ver,
                    reason=f"corrupt: {e}",
                )
            except OSError as e:
                return GetResult(
                    hit=False,
                    key=resolved_key_str,
                    version=resolved_ver,
                    reason=f"io_error: {e}",
                )
            except Exception as e:
                return GetResult(
                    hit=False,
                    key=resolved_key_str,
                    version=resolved_ver,
                    reason=f"unknown_error: {e}",
                )

    def exist(self, key: str, version: int | str | None = None) -> bool:
        """Check whether a non-expired cache entry exists for the given key and version.

        Avoids reading file contents or decompressing zstd data.
        """
        parsed = parse_versioned_key(key)
        if parsed is None:
            return False

        base_key, key_ver = parsed
        target_ver = version if version is not None else key_ver
        if isinstance(target_ver, str) and target_ver != "latest":
            try:
                target_ver = int(target_ver)
            except ValueError:
                return False

        with self.lock:
            now = int(time.time())
            valid_files, _ = self._find_and_clean_files(base_key, now)

            if target_ver is None or target_ver == "latest":
                return len(valid_files) > 0
            return any(item[3] == target_ver for item in valid_files)

    def delete(self, key: str, version: int | str | None = None) -> DeleteResult:
        """Delete cache files for a key.

        If version is omitted or None, deletes all versions.
        If version is provided, deletes only that specified version.
        """
        parsed = parse_versioned_key(key)
        if parsed is None:
            return DeleteResult(hit=False, deleted=False, key=key)

        base_key, key_ver = parsed
        target_ver = version if version is not None else key_ver
        if isinstance(target_ver, str) and target_ver != "latest":
            try:
                target_ver = int(target_ver)
            except ValueError:
                return DeleteResult(hit=False, deleted=False, key=key)

        with self.lock:
            files = self._find_files_by_key(base_key)
            if not files:
                target_key_str = format_versioned_key(base_key, target_ver)
                return DeleteResult(
                    hit=False,
                    deleted=False,
                    key=target_key_str,
                    version=target_ver,
                    deleted_count=0,
                )

            if target_ver is None:
                # Delete all versions
                deleted_count = 0
                for p, _, _, _, sz in files:
                    if self._unlink_and_deduct(p, sz):
                        deleted_count += 1
                return DeleteResult(
                    hit=True,
                    deleted=deleted_count > 0,
                    key=base_key,
                    version=None,
                    deleted_count=deleted_count,
                )
            elif target_ver == "latest":
                # Delete highest version
                files.sort(key=lambda x: x[3], reverse=True)
                latest_p, _, _, latest_v, sz = files[0]
                deleted = self._unlink_and_deduct(latest_p, sz)
                target_key_str = format_versioned_key(base_key, latest_v)
                return DeleteResult(
                    hit=True,
                    deleted=deleted,
                    key=target_key_str,
                    version=latest_v,
                    deleted_count=1 if deleted else 0,
                )
            else:
                # Delete specific version
                target_files = [f for f in files if f[3] == target_ver]
                if not target_files:
                    target_key_str = format_versioned_key(base_key, target_ver)
                    return DeleteResult(
                        hit=False,
                        deleted=False,
                        key=target_key_str,
                        version=target_ver,
                        deleted_count=0,
                    )
                deleted_count = 0
                for p, _, _, _, sz in target_files:
                    if self._unlink_and_deduct(p, sz):
                        deleted_count += 1
                target_key_str = format_versioned_key(base_key, target_ver)
                return DeleteResult(
                    hit=True,
                    deleted=deleted_count > 0,
                    key=target_key_str,
                    version=target_ver,
                    deleted_count=deleted_count,
                )

    def version(self, key: str) -> VersionResult:
        """List all valid, non-expired versions for the given key without reading payloads."""
        parsed = parse_versioned_key(key)
        if parsed is None:
            return VersionResult(hit=False, key=key, reason="invalid_key")

        base_key, _ = parsed
        with self.lock:
            now = int(time.time())
            valid_files, _ = self._find_and_clean_files(base_key, now)
            valid_files.sort(key=lambda x: x[3])  # sort by version ascending

            versions = [
                VersionInfo(
                    version=ver,
                    key=format_versioned_key(base_key, ver),
                    created_timestamp=created_ts,
                    ttl_timestamp=ttl_ts,
                    expired=False,
                )
                for _, created_ts, ttl_ts, ver, _ in valid_files
            ]
            return VersionResult(hit=len(versions) > 0, key=base_key, versions=versions)

    def purge(self) -> PurgeResult:
        """Delete all cached `.zst` files across all subdirectories and reset size tracker."""
        with self.lock:
            deleted_count = 0
            freed_bytes = 0
            for p in self.root_dir.glob("*/*.zst"):
                if p.is_file():
                    try:
                        sz = p.stat().st_size
                        p.unlink(missing_ok=True)
                        deleted_count += 1
                        freed_bytes += sz
                    except OSError:
                        pass
            self._total_compressed_size = 0
            return PurgeResult(
                success=True, deleted_count=deleted_count, freed_bytes=freed_bytes
            )

    def set(self, key: str, entry: CacheEntry) -> StorageResult:
        """Compress and append a new immutable version of a cache entry.

        Never overwrites existing versions. Determines the next version as max(versions) + 1.
        """
        parsed = parse_versioned_key(key)
        if parsed is None:
            return StorageResult(
                success=False,
                key=key,
                message=f"Invalid cache key format: {key}",
            )

        base_key, _ = parsed
        raw_json_str = entry.model_dump_json()
        raw_json_bytes = raw_json_str.encode("utf-8")

        # 1. Single cache size check (uncompressed)
        if len(raw_json_bytes) > self.config.max_cache_size:
            return StorageResult(
                success=False,
                key=key,
                message=f"Exceeds max_cache_size ({len(raw_json_bytes)} > {self.config.max_cache_size})",
            )

        # Compress data using zstd level 3
        compressed_bytes = zstd.compress(raw_json_bytes, level=3)
        new_size = len(compressed_bytes)

        with self.lock:
            now = int(time.time())
            # Determine next version from all existing files before cleaning expired versions
            all_existing = self._find_files_by_key(base_key)
            existing_versions = [info[3] for info in all_existing]
            new_version = max(existing_versions) + 1 if existing_versions else 1

            # Clean expired files for this key
            self._find_and_clean_files(base_key, now)

            # Check total capacity & evict if necessary
            if (
                self._total_compressed_size + new_size
                > self.config.max_total_compressed_cache_size
            ):
                # Step A: Evict expired files across all keys
                all_files: list[tuple[Path, int, int, int, int]] = []
                for p in self.root_dir.glob("*/*.zst"):
                    if p.is_file() and not p.name.startswith(".tmp_"):
                        info = self._parse_cache_file_info(p)
                        if info is not None:
                            _, created_ts, ttl_ts, ver, sz = info
                            if ttl_ts <= now:
                                self._unlink_and_deduct(p, sz)
                            else:
                                all_files.append((p, created_ts, ttl_ts, ver, sz))

                # Step B: FIFO Eviction if still over capacity
                if (
                    self._total_compressed_size + new_size
                    > self.config.max_total_compressed_cache_size
                ):
                    # Sort by created_timestamp ascending (oldest first)
                    all_files.sort(key=lambda x: x[1])
                    for p, _, _, _, sz in all_files:
                        self._unlink_and_deduct(p, sz)
                        if (
                            self._total_compressed_size + new_size
                            <= self.config.max_total_compressed_cache_size
                        ):
                            break

                # If STILL exceeding after evicting everything
                if (
                    self._total_compressed_size + new_size
                    > self.config.max_total_compressed_cache_size
                ):
                    return StorageResult(
                        success=False,
                        key=base_key,
                        version=new_version,
                        message="Storage quota exceeded (max_total_compressed_cache_size)",
                    )

            # Atomic write via temporary file in the same directory
            sub_dir = self._get_sub_dir(base_key)
            target_path = (
                sub_dir
                / f"{base_key}_{entry.created_timestamp}_{entry.ttl_timestamp}_{new_version}.zst"
            )
            tmp_path = sub_dir / f".tmp_{os.getpid()}_{uuid.uuid4().hex}.zst"

            try:
                tmp_path.write_bytes(compressed_bytes)
                tmp_path.replace(target_path)
                self._total_compressed_size += new_size
                versioned_key_str = format_versioned_key(base_key, new_version)
                return StorageResult(
                    success=True, key=versioned_key_str, version=new_version
                )
            except Exception as e:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                return StorageResult(
                    success=False,
                    key=base_key,
                    version=new_version,
                    message=f"Failed to write file: {e}",
                )
