import json
from pathlib import Path

from cache_mcp.main import cli


def test_cli_set_get_exist_version_delete_purge_flow(tmp_path: Path, capsys) -> None:
    cache_dir = str(tmp_path / "cli_cache")

    # 1. Set v1
    code = cli(
        [
            "set",
            "--dir",
            cache_dir,
            "--type",
            "cmd",
            "--name",
            "date",
            "--cmd-dir",
            "/tmp",
            "--stdout",
            "2026-01-01",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert res["success"] is True
    assert res["version"] == 1
    key_v1 = res["key"]
    base_key = key_v1.split("@")[0]

    # 2. Set v2
    code = cli(
        [
            "set",
            "--dir",
            cache_dir,
            "--type",
            "cmd",
            "--name",
            "date",
            "--cmd-dir",
            "/tmp",
            "--stdout",
            "2026-01-02",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert res["success"] is True
    assert res["version"] == 2

    # 3. Exist check
    code = cli(["exist", "--dir", cache_dir, "--key", base_key])
    assert code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["hit"] is True

    # 4. Version list
    code = cli(["version", "--dir", cache_dir, "--key", base_key])
    assert code == 0
    captured = capsys.readouterr()
    ver_out = json.loads(captured.out)
    assert ver_out["hit"] is True
    assert len(ver_out["versions"]) == 2
    assert [v["version"] for v in ver_out["versions"]] == [1, 2]

    # 5. Get default (latest -> v2)
    code = cli(["get", "--dir", cache_dir, "--key", base_key])
    assert code == 0
    captured = capsys.readouterr()
    get_out = json.loads(captured.out)
    assert get_out["hit"] is True
    assert get_out["version"] == 2
    assert get_out["data"]["stdout"] == "2026-01-02"

    # 6. Get specific version (v1) via --version
    code = cli(["get", "--dir", cache_dir, "--key", base_key, "--version", "1"])
    assert code == 0
    captured = capsys.readouterr()
    get_v1_out = json.loads(captured.out)
    assert get_v1_out["hit"] is True
    assert get_v1_out["version"] == 1
    assert get_v1_out["data"]["stdout"] == "2026-01-01"

    # 7. Get non-existent key
    code = cli(["get", "--dir", cache_dir, "--key", "unknown_key"])
    assert code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["hit"] is False

    # 8. Delete specific version 1
    code = cli(["delete", "--dir", cache_dir, "--key", base_key, "--version", "1"])
    assert code == 0
    captured = capsys.readouterr()
    del_out = json.loads(captured.out)
    assert del_out["deleted"] is True
    assert del_out["version"] == 1

    # Verify v1 is gone, v2 remains
    code = cli(["exist", "--dir", cache_dir, "--key", f"{base_key}@1"])
    assert code == 1
    capsys.readouterr()
    code = cli(["exist", "--dir", cache_dir, "--key", f"{base_key}@2"])
    assert code == 0
    capsys.readouterr()

    # 9. Purge
    code = cli(["purge", "--dir", cache_dir])
    assert code == 0
    captured = capsys.readouterr()
    purge_out = json.loads(captured.out)
    assert purge_out["success"] is True
    assert purge_out["deleted_count"] == 1


def test_cli_set_with_json_payload(tmp_path: Path, capsys) -> None:
    import time

    now = int(time.time())
    cache_dir = str(tmp_path / "cli_cache_json")
    payload = {
        "type": "command",
        "name": "git",
        "dir": "/tmp",
        "args": ["status"],
        "created_timestamp": now,
        "ttl": 300,
        "ttl_timestamp": now + 300,
        "stdout": "clean",
        "stderr": "",
        "success": True,
    }
    json_str = json.dumps(payload)

    code = cli(["set", "--dir", cache_dir, "--json", json_str])
    assert code == 0
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert res["success"] is True
    assert res["version"] == 1

    # Get by parameters
    code = cli(
        [
            "get",
            "--dir",
            cache_dir,
            "--type",
            "command",
            "--name",
            "git",
            "--cmd-dir",
            "/tmp",
            "--args",
            "status",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    get_res = json.loads(captured.out)
    assert get_res["hit"] is True
    assert get_res["data"]["stdout"] == "clean"
