from pathlib import Path

import pytest

from cache_mcp.models import CacheEntry, compute_cache_key, normalize_dir

# Table-Driven tests for normalize_dir
NORMALIZE_DIR_TEST_CASES = [
    ("current_dir", ".", str(Path.cwd())),
    ("trailing_slash", "/tmp/", str(Path("/tmp").resolve())),
    ("double_slash", "/tmp//", str(Path("/tmp").resolve())),
]


@pytest.mark.parametrize("name,input_path,expected", NORMALIZE_DIR_TEST_CASES)
def test_normalize_dir(name: str, input_path: str, expected: str) -> None:
    assert normalize_dir(input_path) == expected


# Table-Driven tests for compute_cache_key determinism and collision avoidance
CACHE_KEY_TEST_CASES = [
    (
        "empty_args_explicit_vs_default",
        {"type": "cmd", "name": "ls", "dir": "/tmp", "args": [], "stdin": None},
        {"type": "cmd", "name": "ls", "dir": "/tmp", "args": None, "stdin": None},
        True,  # keys should be equal
    ),
    (
        "path_trailing_slash_normalization",
        {"type": "cmd", "name": "ls", "dir": "/tmp", "args": ["-la"]},
        {"type": "cmd", "name": "ls", "dir": "/tmp/", "args": ["-la"]},
        True,  # keys should be equal
    ),
    (
        "stdin_null_vs_literal_null_string",
        {"type": "cmd", "name": "cat", "dir": "/tmp", "stdin": None},
        {"type": "cmd", "name": "cat", "dir": "/tmp", "stdin": "null"},
        False,  # keys must NOT be equal
    ),
    (
        "delimiter_like_characters_in_args",
        {"type": "cmd", "name": "echo", "dir": "/tmp", "args": ["a__k__b", "c"]},
        {"type": "cmd", "name": "echo", "dir": "/tmp", "args": ["a", "b__k__c"]},
        False,  # keys must NOT be equal (no delimiter collision)
    ),
    (
        "arg_order_matters",
        {"type": "cmd", "name": "echo", "dir": "/tmp", "args": ["1", "2"]},
        {"type": "cmd", "name": "echo", "dir": "/tmp", "args": ["2", "1"]},
        False,  # keys must NOT be equal
    ),
    (
        "different_type_same_name",
        {"type": "command", "name": "run", "dir": "/tmp"},
        {"type": "mcp", "name": "run", "dir": "/tmp"},
        False,  # keys must NOT be equal
    ),
]


@pytest.mark.parametrize("case_name,params1,params2,should_match", CACHE_KEY_TEST_CASES)
def test_compute_cache_key(
    case_name: str,
    params1: dict,
    params2: dict,
    should_match: bool,
) -> None:
    k1 = compute_cache_key(**params1)
    k2 = compute_cache_key(**params2)
    assert len(k1) == 64
    assert len(k2) == 64
    if should_match:
        assert k1 == k2
    else:
        assert k1 != k2


# Table-Driven tests for CacheEntry serialization and deserialization
CACHE_ENTRY_TEST_CASES = [
    (
        "full_entry",
        {
            "type": "command",
            "name": "git",
            "args": ["status", "--short"],
            "dir": "/tmp",
            "start_timestamp": 100,
            "end_timestamp": 105,
            "created_timestamp": 105,
            "ttl": 300,
            "ttl_timestamp": 405,
            "description": "git status check",
            "stdin": None,
            "stdout": "M file.txt",
            "stderr": "",
            "success": True,
            "status_code": 0,
            "status_string": "OK",
        },
    ),
    (
        "minimal_entry_with_defaults",
        {
            "type": "mcp",
            "name": "calc",
            "dir": "/tmp",
            "created_timestamp": 201,
            "ttl": 60,
            "ttl_timestamp": 261,
            "stdout": "42",
            "stderr": "",
            "success": True,
        },
    ),
]


@pytest.mark.parametrize("case_name,data", CACHE_ENTRY_TEST_CASES)
def test_cache_entry_model(case_name: str, data: dict) -> None:
    entry = CacheEntry(**data)
    json_str = entry.model_dump_json()
    restored = CacheEntry.model_validate_json(json_str)
    assert restored.model_dump() == entry.model_dump()


KEY_VALIDATION_CASES = [
    ("valid_sha256", "a" * 64, True),
    ("valid_alphanumeric_short", "test_key_1", True),
    ("valid_with_hyphen", "my-cache-key", True),
    ("invalid_path_traversal", "../secret", False),
    ("invalid_hidden_dot", ".hidden", False),
    ("invalid_slash", "foo/bar", False),
    ("invalid_single_char", "a", False),
    ("invalid_too_long", "a" * 65, False),
    ("invalid_special_chars", "key@name", False),
]


@pytest.mark.parametrize("case_name,key,expected", KEY_VALIDATION_CASES)
def test_is_valid_cache_key(case_name: str, key: str, expected: bool) -> None:
    from cache_mcp.models import is_valid_cache_key

    assert is_valid_cache_key(key) is expected


VERSIONED_KEY_CASES = [
    ("unversioned_base", "abc_123", ("abc_123", None)),
    ("versioned_int", "abc_123@1", ("abc_123", 1)),
    ("versioned_high_int", "abc_123@42", ("abc_123", 42)),
    ("versioned_latest", "abc_123@latest", ("abc_123", "latest")),
    ("invalid_zero_version", "abc_123@0", None),
    ("invalid_negative_version", "abc_123@-1", None),
    ("invalid_alpha_version", "abc_123@v1", None),
    ("invalid_double_at", "abc_123@1@2", None),
    ("invalid_base_key", "../bad@1", None),
]


@pytest.mark.parametrize("case_name,key,expected", VERSIONED_KEY_CASES)
def test_parse_versioned_key(
    case_name: str, key: str, expected: tuple[str, int | str | None] | None
) -> None:
    from cache_mcp.models import format_versioned_key, parse_versioned_key

    res = parse_versioned_key(key)
    assert res == expected
    if expected is not None:
        base, ver = expected
        assert format_versioned_key(base, ver) == (key if ver is not None else base)
