import time
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.types import CallToolResult

from cache_mcp.models import Config
from cache_mcp.server import create_mcp_server


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    return Config(
        dir=tmp_path / "cache_server",
        max_ttl=3600,
        max_cache_size=1024 * 1024,
        max_total_compressed_cache_size=10 * 1024 * 1024,
    )


# Table-Driven tests for MCPServer call_tool (get, set, exist, delete, purge)
TOOL_TEST_CASES = [
    (
        "roundtrip_via_args",
        {
            "type": "command",
            "name": "echo",
            "dir": "/tmp",
            "args": ["hello"],
            "stdout": "hello",
            "stderr": "",
            "success": True,
            "ttl": 300,
        },
        True,
    ),
    (
        "roundtrip_via_key",
        {
            "type": "mcp",
            "name": "fetch",
            "dir": "/tmp",
            "args": ["url"],
            "stdout": "data",
            "stderr": "",
            "success": True,
            "ttl": 300,
        },
        True,
    ),
]


@pytest.mark.parametrize("case_name,call_params,expect_success", TOOL_TEST_CASES)
def test_server_tools_roundtrip(
    test_config: Config, case_name: str, call_params: dict, expect_success: bool
) -> None:
    server = create_mcp_server(test_config)
    now = int(time.time())

    # 1. Call set via call_tool
    set_args: dict[str, Any] = {
        "type": call_params["type"],
        "name": call_params["name"],
        "dir": call_params["dir"],
        "ttl": call_params["ttl"],
        "stdout": call_params["stdout"],
        "stderr": call_params["stderr"],
        "success": call_params["success"],
        "args": call_params["args"],
    }
    if case_name == "roundtrip_via_args":
        set_args["start_timestamp"] = now - 1
        set_args["end_timestamp"] = now
    set_call_res = anyio.run(server.call_tool, "set", set_args)
    assert isinstance(set_call_res, CallToolResult)
    assert set_call_res.is_error is False
    set_res = set_call_res.structured_content
    assert set_res is not None
    assert set_res["success"] is expect_success
    cache_key = set_res["key"]
    assert cache_key is not None

    # 2. Call exist via call_tool
    if case_name == "roundtrip_via_key":
        exist_args = {"key": cache_key}
    else:
        exist_args = {
            "type": call_params["type"],
            "name": call_params["name"],
            "dir": call_params["dir"],
            "args": call_params["args"],
        }
    exist_call_res = anyio.run(server.call_tool, "exist", exist_args)
    assert isinstance(exist_call_res, CallToolResult)
    assert exist_call_res.is_error is False
    assert exist_call_res.structured_content is not None
    assert exist_call_res.structured_content["hit"] is True

    # 3. Call get via call_tool
    if case_name == "roundtrip_via_key":
        get_args = {"key": cache_key}
    else:
        get_args = {
            "type": call_params["type"],
            "name": call_params["name"],
            "dir": call_params["dir"],
            "args": call_params["args"],
        }
    get_call_res = anyio.run(server.call_tool, "get", get_args)
    assert isinstance(get_call_res, CallToolResult)
    assert get_call_res.is_error is False
    assert get_call_res.structured_content is not None
    assert get_call_res.structured_content["hit"] is True
    assert get_call_res.structured_content["data"]["stdout"] == call_params["stdout"]

    # 4. Call delete via call_tool
    del_call_res = anyio.run(server.call_tool, "delete", {"key": cache_key})
    assert isinstance(del_call_res, CallToolResult)
    assert del_call_res.is_error is False
    assert del_call_res.structured_content is not None
    assert del_call_res.structured_content["hit"] is True
    assert del_call_res.structured_content["deleted"] is True

    # 5. Verify deleted via call_tool
    exist_after_call = anyio.run(server.call_tool, "exist", {"key": cache_key})
    assert isinstance(exist_after_call, CallToolResult)
    assert exist_after_call.structured_content is not None
    assert exist_after_call.structured_content["hit"] is False


def test_server_purge_tool(test_config: Config) -> None:
    server = create_mcp_server(test_config)
    now = int(time.time())

    anyio.run(
        server.call_tool,
        "set",
        {
            "type": "cmd",
            "name": "test",
            "dir": "/tmp",
            "start_timestamp": now - 1,
            "end_timestamp": now,
            "ttl": 300,
            "stdout": "out",
            "stderr": "",
            "success": True,
        },
    )

    # Default purge does not delete active unexpired entry
    purge_default_res = anyio.run(server.call_tool, "purge", {})
    assert isinstance(purge_default_res, CallToolResult)
    assert purge_default_res.is_error is False
    assert purge_default_res.structured_content is not None
    assert purge_default_res.structured_content["success"] is True
    assert purge_default_res.structured_content["deleted_count"] == 0
    assert purge_default_res.structured_content["all"] is False

    # Purge with all=True purges all entries
    purge_all_res = anyio.run(server.call_tool, "purge", {"all": True})
    assert isinstance(purge_all_res, CallToolResult)
    assert purge_all_res.is_error is False
    assert purge_all_res.structured_content is not None
    assert purge_all_res.structured_content["success"] is True
    assert purge_all_res.structured_content["deleted_count"] == 1
    assert purge_all_res.structured_content["all"] is True
    assert purge_all_res.structured_content["freed_bytes"] > 0


def test_server_version_tool_and_versioned_calls(test_config: Config) -> None:
    server = create_mcp_server(test_config)
    set_args_base = {
        "type": "command",
        "name": "git",
        "dir": "/tmp",
        "ttl": 300,
        "stderr": "",
        "success": True,
    }

    # 1. Set version 1
    res1 = anyio.run(
        server.call_tool,
        "set",
        {**set_args_base, "stdout": "v1_output"},
    )
    assert isinstance(res1, CallToolResult)
    assert res1.structured_content is not None
    assert res1.structured_content["success"] is True
    assert res1.structured_content["version"] == 1
    v1_key = res1.structured_content["key"]

    # 2. Set version 2
    res2 = anyio.run(
        server.call_tool,
        "set",
        {**set_args_base, "stdout": "v2_output"},
    )
    assert isinstance(res2, CallToolResult)
    assert res2.structured_content is not None
    assert res2.structured_content["success"] is True
    assert res2.structured_content["version"] == 2
    v2_key = res2.structured_content["key"]

    # 3. Call version tool
    ver_call = anyio.run(
        server.call_tool,
        "version",
        {"type": "command", "name": "git", "dir": "/tmp"},
    )
    assert isinstance(ver_call, CallToolResult)
    assert ver_call.is_error is False
    assert ver_call.structured_content is not None
    assert ver_call.structured_content["hit"] is True
    versions = ver_call.structured_content["versions"]
    assert len(versions) == 2
    assert [v["version"] for v in versions] == [1, 2]

    # 4. Get latest version by default
    get_latest = anyio.run(
        server.call_tool,
        "get",
        {"type": "command", "name": "git", "dir": "/tmp"},
    )
    assert isinstance(get_latest, CallToolResult)
    assert get_latest.structured_content is not None
    assert get_latest.structured_content["hit"] is True
    assert get_latest.structured_content["version"] == 2
    assert get_latest.structured_content["data"]["stdout"] == "v2_output"

    # 5. Get specific version (v1) via explicit version parameter
    get_v1 = anyio.run(
        server.call_tool,
        "get",
        {"type": "command", "name": "git", "dir": "/tmp", "version": 1},
    )
    assert isinstance(get_v1, CallToolResult)
    assert get_v1.structured_content is not None
    assert get_v1.structured_content["hit"] is True
    assert get_v1.structured_content["version"] == 1
    assert get_v1.structured_content["data"]["stdout"] == "v1_output"

    # 6. Delete specific version 1
    del_v1 = anyio.run(
        server.call_tool,
        "delete",
        {"type": "command", "name": "git", "dir": "/tmp", "version": 1},
    )
    assert isinstance(del_v1, CallToolResult)
    assert del_v1.structured_content is not None
    assert del_v1.structured_content["deleted"] is True
    assert del_v1.structured_content["version"] == 1

    # Check v1 is deleted, v2 still exists
    exist_v1 = anyio.run(server.call_tool, "exist", {"key": v1_key})
    assert isinstance(exist_v1, CallToolResult)
    assert exist_v1.structured_content is not None
    assert exist_v1.structured_content["hit"] is False
    exist_v2 = anyio.run(server.call_tool, "exist", {"key": v2_key})
    assert isinstance(exist_v2, CallToolResult)
    assert exist_v2.structured_content is not None
    assert exist_v2.structured_content["hit"] is True
