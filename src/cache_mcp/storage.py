import os
import time
import uuid
from compression import zstd
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from cache_mcp.lock import FileLock
from cache_mcp.models import CacheEntry, Config, is_valid_cache_key


@dataclass
class StorageResult:
    success: bool
    key: str | None = None
    message: str | None = None


@dataclass
class GetResult:
    hit: bool
    key: str
    data: CacheEntry | None = None
    reason: str | None = None


@dataclass
class DeleteResult:
    hit: bool
    deleted: bool
    key: str


@dataclass
class PurgeResult:
    success: bool
    deleted_count: int
    freed_bytes: int
    message: str | None = None


class CacheStorage:
    """Core storage engine managing compressed cache files on disk.

    Architecture & Invariants:
        - Sharding: Two-level directory structure using first 2 chars of SHA-256 key (`<dir>/<key[:2]>/`).
          Prevents filesystem performance degradation when thousands of cache files accumulate.
        - File Naming Scheme: `<key>_<created_timestamp>_<ttl_timestamp>.zst`. Embeds temporal metadata
          directly in filenames, enabling fast timestamp extraction during eviction without reading or
          decompressing file contents.
        - Compression: Standard library `compression.zstd` at default Level 3, striking optimal CPU/ratio balance.
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
        """Scan all .zst files on startup to initialize the in-memory size ledger.

        Why in-memory tracking:
            Scanning the filesystem on every write operation would incur unacceptable I/O latency
            as cache sizes grow. Performing a single scan on startup and incrementally tracking
            byte deltas on mutations provides O(1) size checks.
        """
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
    def _parse_cache_file_info(path: Path) -> tuple[int, int, int] | None:
        """Parse (created_timestamp, ttl_timestamp, file_size) from a cache file.

        Only supports standard format: `<key>_<created_timestamp>_<ttl_timestamp>.zst`.
        Returns None if parsing fails or path is inaccessible.
        """
        try:
            parts = path.stem.rsplit("_", maxsplit=2)
            size = path.stat().st_size
            match parts:
                case [_, created_str, ttl_str]:
                    return int(created_str), int(ttl_str), size
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

    def _find_files_by_key(self, key: str) -> list[tuple[Path, int, int, int]]:
        """Find all files starting with <key>_ in <key[:2]>.

        Returns:
            List of (Path, created_timestamp, ttl_timestamp, file_size).
        """
        sub = self.root_dir / key[:2]
        if not sub.exists():
            return []
        results = []
        prefix = f"{key}_"
        for p in sub.iterdir():
            if p.is_file() and p.name.startswith(prefix) and p.name.endswith(".zst"):
                info = self._parse_cache_file_info(p)
                if info is not None:
                    results.append((p, info[0], info[1], info[2]))
        return results

    def get(self, key: str) -> GetResult:
        """Retrieve and decompress cached record by key.

        Invariants:
            - Duplicate cleanup: If multiple files share the key prefix, older files
              are discarded immediately, maintaining exactly one canonical file.
            - Lazy eviction: If the latest file is expired (`ttl_timestamp <= now`),
              it is deleted on the fly and reported as a cache miss (`hit=False`).
        """
        if not is_valid_cache_key(key):
            return GetResult(hit=False, key=key, reason="invalid_key")

        with self.lock:
            files = self._find_files_by_key(key)
            if not files:
                return GetResult(hit=False, key=key, reason="miss")

            # Sort by ttl_timestamp descending (latest first)
            files.sort(key=lambda x: x[2], reverse=True)
            latest_path, _, latest_ttl, latest_size = files[0]

            # Remove older duplicates
            for old_path, _, _, old_size in files[1:]:
                self._unlink_and_deduct(old_path, old_size)

            now = int(time.time())
            # Lazy eviction if expired
            if latest_ttl <= now:
                self._unlink_and_deduct(latest_path, latest_size)
                return GetResult(hit=False, key=key, reason="expired")

            # Read and decompress
            try:
                compressed_data = latest_path.read_bytes()
                decompressed_data = zstd.decompress(compressed_data)
                entry = CacheEntry.model_validate_json(
                    decompressed_data.decode("utf-8")
                )
                return GetResult(hit=True, key=key, data=entry)
            except (zstd.ZstdError, ValidationError, UnicodeDecodeError) as e:
                return GetResult(hit=False, key=key, reason=f"corrupt: {e}")
            except OSError as e:
                return GetResult(hit=False, key=key, reason=f"io_error: {e}")
            except Exception as e:
                return GetResult(hit=False, key=key, reason=f"unknown_error: {e}")

    def exist(self, key: str) -> bool:
        """Check whether a non-expired cache entry exists for the given key.

        This avoids reading file contents and decompressing zstd data by inspecting
        the metadata encoded in the filename (`<key>_<created_ts>_<ttl_ts>.zst`).
        """
        if not is_valid_cache_key(key):
            return False

        with self.lock:
            files = self._find_files_by_key(key)
            if not files:
                return False

            # Sort by ttl_timestamp descending (latest first)
            files.sort(key=lambda x: x[2], reverse=True)
            latest_path, _, latest_ttl, latest_size = files[0]

            # Clean up older duplicates if any
            for old_path, _, _, old_size in files[1:]:
                self._unlink_and_deduct(old_path, old_size)

            now = int(time.time())
            # Lazy eviction if expired
            if latest_ttl <= now:
                self._unlink_and_deduct(latest_path, latest_size)
                return False

            return True

    def delete(self, key: str) -> DeleteResult:
        """Delete all cached files matching the specified key."""
        if not is_valid_cache_key(key):
            return DeleteResult(hit=False, deleted=False, key=key)

        with self.lock:
            files = self._find_files_by_key(key)
            if not files:
                return DeleteResult(hit=False, deleted=False, key=key)

            deleted_any = False
            for p, _, _, size in files:
                if self._unlink_and_deduct(p, size):
                    deleted_any = True
            return DeleteResult(hit=True, deleted=deleted_any, key=key)

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
        """Compress and atomically store a cache entry with FIFO eviction support.

        Steps:
            1. Validate uncompressed JSON size <= max_cache_size.
            2. Compress with zstd level 3.
            3. Acquire exclusive flock (10s timeout).
            4. Remove existing versions of the same key.
            5. If adding new entry exceeds max_total_compressed_cache_size:
               a. Evict expired entries.
               b. Evict valid entries in FIFO order (oldest `created_timestamp` first).
               c. If still exceeding (e.g. single entry > max_total_compressed_cache_size), fail.
            6. Atomically write to `.tmp_<pid>_<uuid>.zst` and rename to target path.
        """
        if not is_valid_cache_key(key):
            return StorageResult(
                success=False,
                key=key,
                message=f"Invalid cache key format: {key}",
            )

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
            # 2. Remove existing versions of the same key
            existing = self._find_files_by_key(key)
            for p, _, _, sz in existing:
                self._unlink_and_deduct(p, sz)

            now = int(time.time())

            # 3. Check total capacity & evict if necessary
            if (
                self._total_compressed_size + new_size
                > self.config.max_total_compressed_cache_size
            ):
                # Step A: Evict expired files
                all_files: list[
                    tuple[Path, int, int, int]
                ] = []  # (path, created_ts, ttl_ts, size)
                for p in self.root_dir.glob("*/*.zst"):
                    if p.is_file() and not p.name.startswith(".tmp_"):
                        info = self._parse_cache_file_info(p)
                        if info is not None:
                            created_ts, ttl_ts, sz = info
                            if ttl_ts <= now:
                                self._unlink_and_deduct(p, sz)
                            else:
                                all_files.append((p, created_ts, ttl_ts, sz))

                # Step B: FIFO Eviction if still over capacity
                if (
                    self._total_compressed_size + new_size
                    > self.config.max_total_compressed_cache_size
                ):
                    # Sort by created_timestamp ascending (oldest first)
                    all_files.sort(key=lambda x: x[1])
                    for p, _, _, sz in all_files:
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
                        key=key,
                        message="Storage quota exceeded (max_total_compressed_cache_size)",
                    )

            # 4. Atomic write via temporary file in the same directory
            sub_dir = self._get_sub_dir(key)
            target_path = (
                sub_dir / f"{key}_{entry.created_timestamp}_{entry.ttl_timestamp}.zst"
            )
            tmp_path = sub_dir / f".tmp_{os.getpid()}_{uuid.uuid4().hex}.zst"

            try:
                tmp_path.write_bytes(compressed_bytes)
                tmp_path.replace(target_path)
                self._total_compressed_size += new_size
                return StorageResult(success=True, key=key)
            except Exception as e:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                return StorageResult(
                    success=False, key=key, message=f"Failed to write file: {e}"
                )
