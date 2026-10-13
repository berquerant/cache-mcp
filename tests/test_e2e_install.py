"""End-to-End tests for building and pip-installing cache-mcp package."""

import subprocess
import tempfile
from pathlib import Path


def test_e2e_wheel_build_and_pip_install() -> None:
    """Verify wheel build, pip install in clean venv, and CLI execution."""
    with tempfile.TemporaryDirectory() as tmpdir_name:
        tmp_path = Path(tmpdir_name)
        dist_dir = tmp_path / "dist"
        venv_dir = tmp_path / "venv"

        repo_root = Path(__file__).resolve().parent.parent

        # 1. Build wheel into isolated dist directory
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )

        wheel_files = list(dist_dir.glob("*.whl"))
        assert len(wheel_files) > 0, f"No .whl file found in {dist_dir}"
        wheel_file = wheel_files[0]

        # 2. Create clean virtual environment with pip
        subprocess.run(
            ["uv", "venv", "--seed", str(venv_dir)],
            check=True,
            capture_output=True,
        )

        pip_bin = venv_dir / "bin" / "pip"
        cli_bin = venv_dir / "bin" / "cache-mcp"

        # 3. Pip install the built wheel
        subprocess.run(
            [str(pip_bin), "install", str(wheel_file)],
            check=True,
            capture_output=True,
        )

        # 4. Verify cache-mcp --help runs outside the repo root
        res = subprocess.run(
            [str(cli_bin), "--help"],
            capture_output=True,
            text=True,
            cwd=tmpdir_name,
            check=False,
        )
        assert res.returncode == 0, f"cache-mcp --help failed: {res.stderr}"
        assert "Cache MCP Server" in res.stdout
        assert "--max-ttl" in res.stdout
        assert "--max-total-compressed-cache-size" in res.stdout
