import concurrent.futures
import random
import time
from pathlib import Path

import pytest

from cache_mcp.models import CacheEntry, Config
from cache_mcp.storage import CacheStorage


def _make_entry(key: str, worker_id: int, seq: int) -> CacheEntry:
    now = int(time.time())
    return CacheEntry(
        type="command",
        name="test_worker",
        args=[f"worker_{worker_id}", f"seq_{seq}"],
        dir="/tmp",
        start_timestamp=now - 1,
        end_timestamp=now,
        created_timestamp=now,
        ttl=300,
        ttl_timestamp=now + 300,
        stdout=f"output from worker {worker_id} seq {seq}",
        stderr="",
        success=True,
        status_code=0,
        status_string="OK",
    )


# Table-Driven test cases for storage concurrency
STORAGE_CONCURRENCY_CASES = [
    (
        "concurrent_writes_same_key",
        {
            "num_workers": 8,
            "iterations": 15,
            "keys": ["contested_key"],
            "max_total": 10 * 1024 * 1024,
            "mode": "write_only",
        },
    ),
    (
        "concurrent_read_write_delete_mix",
        {
            "num_workers": 10,
            "iterations": 25,
            "keys": [f"mix_key_{i}" for i in range(5)],
            "max_total": 10 * 1024 * 1024,
            "mode": "mixed",
        },
    ),
    (
        "concurrent_eviction_under_tight_capacity",
        {
            "num_workers": 6,
            "iterations": 10,
            "keys": [f"flood_key_{i}" for i in range(15)],
            # Tight capacity: each entry is ~180B compressed, capacity 600B (~3 items)
            "max_total": 600,
            "mode": "write_flood",
        },
    ),
]


@pytest.mark.parametrize("case_name,params", STORAGE_CONCURRENCY_CASES)
def test_storage_concurrency_stress(
    tmp_path: Path, case_name: str, params: dict
) -> None:
    config = Config(
        dir=tmp_path / "concurrent_cache",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=params["max_total"],
    )
    storage = CacheStorage(config)
    num_workers: int = params["num_workers"]
    iterations: int = params["iterations"]
    keys: list[str] = params["keys"]
    mode: str = params["mode"]

    errors: list[str] = []

    def worker_task(worker_id: int) -> None:
        try:
            for seq in range(iterations):
                target_key = random.choice(keys)
                if mode == "write_only" or mode == "write_flood":
                    entry = _make_entry(target_key, worker_id, seq)
                    res = storage.set(target_key, entry)
                    if not res.success and "max_total" not in (res.message or ""):
                        errors.append(
                            f"Worker {worker_id} set failed unexpectedly: {res.message}"
                        )
                elif mode == "mixed":
                    op = random.random()
                    if op < 0.5:
                        # Write
                        entry = _make_entry(target_key, worker_id, seq)
                        storage.set(target_key, entry)
                    elif op < 0.85:
                        # Read
                        get_res = storage.get(target_key)
                        if get_res.hit and get_res.data is not None:
                            # Verify integrity: data must not be corrupted
                            assert get_res.data.type == "command"
                            assert get_res.data.name == "test_worker"
                            assert "output from worker" in get_res.data.stdout
                    else:
                        # Delete
                        storage.delete(target_key)
        except Exception as e:
            errors.append(f"Worker {worker_id} crashed with exception: {e}")

    # Launch threads in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_task, w) for w in range(num_workers)]
        concurrent.futures.wait(futures)

    # Assert no worker raised unhandled exceptions or data corruption
    assert len(errors) == 0, f"Concurrency errors encountered: {errors}"

    # Final consistency checks
    if mode == "write_only":
        # Shared key must exist and be valid
        res = storage.get("contested_key")
        assert res.hit is True
        assert res.data is not None
        assert "output from worker" in res.data.stdout
    elif mode == "write_flood":
        # Disk usage must never exceed max_total_compressed_cache_size
        assert storage.total_compressed_size <= config.max_total_compressed_cache_size
