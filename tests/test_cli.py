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

    # 9. Purge default (expired only) -> 0 active entries deleted
    code = cli(["purge", "--dir", cache_dir])
    assert code == 0
    captured = capsys.readouterr()
    purge_default_out = json.loads(captured.out)
    assert purge_default_out["success"] is True
    assert purge_default_out["deleted_count"] == 0
    assert purge_default_out["all"] is False

    # 10. Purge --all -> deletes remaining active entries
    code_all = cli(["purge", "--dir", cache_dir, "--all"])
    assert code_all == 0
    captured = capsys.readouterr()
    purge_all_out = json.loads(captured.out)
    assert purge_all_out["success"] is True
    assert purge_all_out["deleted_count"] == 1
    assert purge_all_out["all"] is True


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


def test_cli_set_with_long_json_payload_and_file(tmp_path: Path, capsys) -> None:
    import time

    now = int(time.time())
    cache_dir = str(tmp_path / "cli_cache_long_json")

    # Long payload > 300 bytes (exceeds single POSIX filename component limits if treated as path)
    long_stdout = "x" * 500
    payload = {
        "type": "command",
        "name": "big_output",
        "dir": "/tmp",
        "args": ["run", "--flag", "val"],
        "created_timestamp": now,
        "ttl": 300,
        "ttl_timestamp": now + 300,
        "stdout": long_stdout,
        "stderr": "",
        "success": True,
    }
    json_str = json.dumps(payload)
    assert len(json_str) > 500

    # 1. Direct string should succeed without OSError
    code = cli(["set", "--dir", cache_dir, "--json", json_str])
    assert code == 0
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert res["success"] is True

    # 2. File path should also succeed
    file_path = tmp_path / "payload.json"
    file_path.write_text(json_str, encoding="utf-8")
    code2 = cli(["set", "--dir", cache_dir, "--json", str(file_path)])
    assert code2 == 0
    captured = capsys.readouterr()
    res2 = json.loads(captured.out)
    assert res2["success"] is True
    assert res2["version"] == 2


def test_cli_logging(tmp_path: Path, capsys) -> None:
    cache_dir = tmp_path / "cli_cache_logging"
    log_file = cache_dir / "logs" / "cachemcp.log"

    # 1. Run command with default logging
    code = cli(
        [
            "set",
            "--dir",
            str(cache_dir),
            "--type",
            "cmd",
            "--name",
            "echo",
            "--cmd-dir",
            "/tmp",
            "--stdout",
            "logged",
        ]
    )
    assert code == 0
    capsys.readouterr()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").strip()
    assert len(content) > 0
    record = json.loads(content.splitlines()[-1])
    assert record["tool"] == "set"
    assert "duration_ms" in record

    # 2. Run command with --no-log
    line_count_before = len(content.splitlines())
    code_no_log = cli(
        [
            "--no-log",
            "exist",
            "--dir",
            str(cache_dir),
            "--type",
            "cmd",
            "--name",
            "echo",
            "--cmd-dir",
            "/tmp",
        ]
    )
    assert code_no_log == 0
    capsys.readouterr()

    content_after = log_file.read_text(encoding="utf-8").strip()
    line_count_after = len(content_after.splitlines())
    assert line_count_after == line_count_before
