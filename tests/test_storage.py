import time
from pathlib import Path

import pytest

from cache_mcp.models import CacheEntry, Config
from cache_mcp.storage import CacheStorage


def make_entry(
    name: str = "test",
    stdout: str = "output",
    ttl: int = 300,
    created_ts: int | None = None,
) -> CacheEntry:
    now = created_ts if created_ts is not None else int(time.time())
    return CacheEntry(
        type="command",
        name=name,
        args=["arg1"],
        dir="/tmp",
        start_timestamp=now - 1,
        end_timestamp=now,
        created_timestamp=now,
        ttl=ttl,
        ttl_timestamp=now + ttl,
        stdout=stdout,
        stderr="",
        success=True,
        status_code=0,
        status_string="OK",
    )


# Table-Driven tests for basic storage operations (get, set, exist, delete, purge)
STORAGE_BASIC_CASES = [
    ("set_and_get_success", "key1", make_entry(stdout="hello 1"), True),
    ("get_nonexistent_key", "nonexistent", None, False),
    ("delete_existing_key", "key2", make_entry(stdout="hello 2"), True),
]


@pytest.mark.parametrize("case_name,key,entry,should_exist", STORAGE_BASIC_CASES)
def test_storage_basic(
    tmp_path: Path,
    case_name: str,
    key: str,
    entry: CacheEntry | None,
    should_exist: bool,
) -> None:
    config = Config(
        dir=tmp_path / "cache",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=10 * 1024 * 1024,
    )
    storage = CacheStorage(config)

    if entry is not None:
        set_res = storage.set(key, entry)
        assert set_res.success is True

    if case_name == "delete_existing_key":
        del_res = storage.delete(key)
        assert del_res.hit is True
        assert del_res.deleted is True
        assert storage.exist(key) is False
    else:
        assert storage.exist(key) is should_exist
        get_res = storage.get(key)
        assert get_res.hit is should_exist
        if should_exist and entry is not None:
            assert get_res.data is not None
            assert get_res.data.stdout == entry.stdout


# Table-Driven tests for Eviction & Quota limits
CAPACITY_TEST_CASES = [
    (
        "single_file_exceeds_max_cache_size",
        {"max_cache_size": 50, "max_total": 10000},
        make_entry(stdout="A" * 100),
        False,  # Expect rejected
        "Exceeds max_cache_size",
    ),
    (
        "fifo_eviction_when_total_capacity_exceeded",
        {
            "max_cache_size": 10000,
            "max_total": 400,
        },  # allows 2 items (~163 bytes each), 3rd triggers eviction
        make_entry(stdout="item"),
        True,  # Expect success via FIFO eviction
        None,
    ),
]


@pytest.mark.parametrize(
    "case_name,limits,entry,expected_success,expected_err_substr", CAPACITY_TEST_CASES
)
def test_storage_capacity_and_eviction(
    tmp_path: Path,
    case_name: str,
    limits: dict,
    entry: CacheEntry,
    expected_success: bool,
    expected_err_substr: str | None,
) -> None:
    config = Config(
        dir=tmp_path / "cache",
        max_ttl=3600,
        max_cache_size=limits["max_cache_size"],
        max_total_compressed_cache_size=limits["max_total"],
    )
    storage = CacheStorage(config)

    if case_name == "fifo_eviction_when_total_capacity_exceeded":
        # Insert 3 entries, older should be evicted to make room
        k1 = "k_old"
        k2 = "k_mid"
        k3 = "k_new"
        base_time = int(time.time())
        res1 = storage.set(k1, make_entry(stdout="old_data", created_ts=base_time - 20))
        assert res1.success is True
        time.sleep(0.01)
        res2 = storage.set(k2, make_entry(stdout="mid_data", created_ts=base_time - 10))
        assert res2.success is True
        time.sleep(0.01)
        res3 = storage.set(k3, make_entry(stdout="new_data", created_ts=base_time))
        assert res3.success is True

        # Total capacity was small (~400 bytes), so k1 should have been evicted, but k3 must exist
        assert storage.exist(k3) is True
        assert storage.exist(k2) is True
        assert storage.exist(k1) is False
        assert storage.total_compressed_size <= config.max_total_compressed_cache_size
    else:
        res = storage.set("test_key", entry)
        assert res.success is expected_success
        if expected_err_substr:
            assert res.message is not None
            assert expected_err_substr in res.message


def test_lazy_eviction_on_expired(tmp_path: Path) -> None:
    config = Config(
        dir=tmp_path / "cache",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=1024 * 1024,
    )
    storage = CacheStorage(config)
    expired_entry = make_entry(
        ttl=1, created_ts=int(time.time()) - 10
    )  # expired 9s ago
    set_res = storage.set("expired_key", expired_entry)
    assert set_res.success is True

    # Accessing expired key should result in cache miss and file deletion
    get_res = storage.get("expired_key")
    assert get_res.hit is False
    assert storage.exist("expired_key") is False


def test_purge(tmp_path: Path) -> None:
    config = Config(
        dir=tmp_path / "cache",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=1024 * 1024,
    )
    storage = CacheStorage(config)
    storage.set("p1", make_entry())
    storage.set("p2", make_entry())
    assert storage.total_compressed_size > 0

    purge_res = storage.purge()
    assert purge_res.success is True
    assert purge_res.deleted_count == 2
    assert purge_res.freed_bytes > 0
    assert storage.total_compressed_size == 0


def test_storage_invalid_key(tmp_path: Path) -> None:
    config = Config(
        dir=tmp_path / "cache",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=1024 * 1024,
    )
    storage = CacheStorage(config)
    invalid_key = "../traversal"

    assert storage.exist(invalid_key) is False
    get_res = storage.get(invalid_key)
    assert get_res.hit is False
    assert get_res.reason == "invalid_key"

    del_res = storage.delete(invalid_key)
    assert del_res.hit is False
    assert del_res.deleted is False

    set_res = storage.set(invalid_key, make_entry())
    assert set_res.success is False
    assert "Invalid cache key" in (set_res.message or "")


def test_storage_corrupted_file(tmp_path: Path) -> None:
    config = Config(
        dir=tmp_path / "cache",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=1024 * 1024,
    )
    storage = CacheStorage(config)
    key = "valid_corrupt_key"
    storage.set(key, make_entry())

    # Find the written file and overwrite with garbage
    sub_dir = storage.root_dir / key[:2]
    written_files = list(sub_dir.glob(f"{key}_*.zst"))
    assert len(written_files) == 1
    written_files[0].write_bytes(b"not valid zstd data")

    get_res = storage.get(key)
    assert get_res.hit is False
    assert get_res.reason is not None
    assert "corrupt" in get_res.reason


def test_storage_immutable_versioning(tmp_path: Path) -> None:
    config = Config(
        dir=tmp_path / "cache",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=10 * 1024 * 1024,
    )
    storage = CacheStorage(config)
    key = "imm_key"

    res1 = storage.set(key, make_entry(stdout="v1"))
    assert res1.success is True
    assert res1.version == 1
    assert res1.key == f"{key}@1"

    res2 = storage.set(key, make_entry(stdout="v2"))
    assert res2.success is True
    assert res2.version == 2
    assert res2.key == f"{key}@2"

    res3 = storage.set(key, make_entry(stdout="v3"))
    assert res3.success is True
    assert res3.version == 3
    assert res3.key == f"{key}@3"

    # Default get -> latest (v3)
    get_latest = storage.get(key)
    assert get_latest.hit is True
    assert get_latest.version == 3
    assert get_latest.data is not None and get_latest.data.stdout == "v3"

    # get with @latest
    get_at_latest = storage.get(f"{key}@latest")
    assert get_at_latest.hit is True
    assert get_at_latest.version == 3
    assert get_at_latest.data is not None and get_at_latest.data.stdout == "v3"

    # get specific version
    get_v1 = storage.get(f"{key}@1")
    assert get_v1.hit is True
    assert get_v1.version == 1
    assert get_v1.data is not None and get_v1.data.stdout == "v1"

    get_v2 = storage.get(key, version=2)
    assert get_v2.hit is True
    assert get_v2.version == 2
    assert get_v2.data is not None and get_v2.data.stdout == "v2"

    # get non-existent version
    get_v99 = storage.get(f"{key}@99")
    assert get_v99.hit is False
    assert get_v99.reason == "miss"

    # exist checks
    assert storage.exist(key) is True
    assert storage.exist(f"{key}@latest") is True
    assert storage.exist(f"{key}@1") is True
    assert storage.exist(key, version=2) is True
    assert storage.exist(f"{key}@99") is False

    # version list
    ver_res = storage.version(key)
    assert ver_res.hit is True
    assert len(ver_res.versions) == 3
    assert [v.version for v in ver_res.versions] == [1, 2, 3]
    assert [v.key for v in ver_res.versions] == [f"{key}@1", f"{key}@2", f"{key}@3"]


def test_storage_lazy_eviction_mixed_versions(tmp_path: Path) -> None:
    config = Config(
        dir=tmp_path / "cache",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=10 * 1024 * 1024,
    )
    storage = CacheStorage(config)
    key = "mixed_key"
    base_time = int(time.time())

    # v1 is expired 10 seconds ago
    storage.set(key, make_entry(stdout="v1_expired", ttl=1, created_ts=base_time - 11))
    # v2 is active
    storage.set(key, make_entry(stdout="v2_active", ttl=600, created_ts=base_time))

    # Accessing key should lazily evict v1, return v2
    get_res = storage.get(key)
    assert get_res.hit is True
    assert get_res.version == 2
    assert get_res.data is not None and get_res.data.stdout == "v2_active"

    # v1 was evicted
    assert storage.exist(f"{key}@1") is False

    # version list should now only contain v2
    ver_res = storage.version(key)
    assert ver_res.hit is True
    assert len(ver_res.versions) == 1
    assert ver_res.versions[0].version == 2


def test_storage_delete_specific_and_all_versions(tmp_path: Path) -> None:
    config = Config(
        dir=tmp_path / "cache",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=10 * 1024 * 1024,
    )
    storage = CacheStorage(config)
    key = "del_test"

    storage.set(key, make_entry(stdout="v1"))
    storage.set(key, make_entry(stdout="v2"))
    storage.set(key, make_entry(stdout="v3"))

    # Delete specific version 2
    del_v2 = storage.delete(key, version=2)
    assert del_v2.hit is True
    assert del_v2.deleted is True
    assert del_v2.version == 2
    assert del_v2.deleted_count == 1
    assert storage.exist(f"{key}@2") is False
    assert storage.exist(f"{key}@1") is True
    assert storage.exist(f"{key}@3") is True

    # Delete latest version (v3)
    del_latest = storage.delete(f"{key}@latest")
    assert del_latest.hit is True
    assert del_latest.deleted is True
    assert del_latest.version == 3
    assert storage.exist(f"{key}@3") is False
    assert storage.exist(f"{key}@1") is True

    # Delete all remaining versions
    del_all = storage.delete(key)
    assert del_all.hit is True
    assert del_all.deleted is True
    assert del_all.deleted_count == 1  # remaining v1
    assert storage.exist(key) is False
