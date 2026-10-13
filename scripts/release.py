#!/usr/bin/env python3
"""Release script to bump version, update uv.lock, commit, tag, and push."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

SEMVER_REGEX = re.compile(
    r"^v?(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*)?(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?)$"
)


def validate_semver(version_str: str) -> str:
    """Validate that version_str is a valid SemVer string and return normalized version."""
    match = SEMVER_REGEX.match(version_str)
    if not match:
        raise ValueError(f"Invalid SemVer version string: '{version_str}'")
    return match.group("version")


def has_remote(remote_name: str = "origin") -> bool:
    """Check if git remote exists."""
    res = subprocess.run(["git", "remote"], capture_output=True, text=True, check=True)
    remotes = {line.strip() for line in res.stdout.splitlines() if line.strip()}
    return remote_name in remotes


def get_existing_tags() -> set[str]:
    """Get existing git tags from local repository and remote if reachable."""
    tags = set()
    # Local tags
    res = subprocess.run(
        ["git", "tag", "-l"], capture_output=True, text=True, check=True
    )
    for tag in res.stdout.splitlines():
        tag = tag.strip()
        if tag:
            tags.add(tag)

    # Remote tags if origin exists
    if has_remote("origin"):
        try:
            remote_res = subprocess.run(
                ["git", "ls-remote", "--tags", "origin"],
                capture_output=True,
                check=False,
                text=True,
                timeout=10,
            )
            if remote_res.returncode == 0:
                for line in remote_res.stdout.splitlines():
                    parts = line.strip().split("\t")
                    if len(parts) == 2:
                        ref = parts[1]
                        tag_name = ref.removeprefix("refs/tags/").removesuffix("^{}")
                        if tag_name:
                            tags.add(tag_name)
        except (subprocess.SubprocessError, OSError) as e:
            print(f"Warning: Failed to fetch remote tags: {e}", file=sys.stderr)

    return tags


def update_pyproject_version(
    pyproject_path: Path, new_version: str, dry_run: bool = False
) -> None:
    """Update version in pyproject.toml."""
    content = pyproject_path.read_text(encoding="utf-8")
    updated_content, count = re.subn(
        r'(^version\s*=\s*")[^"]+(")',
        rf"\g<1>{new_version}\g<2>",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if count == 0:
        raise RuntimeError(f"Could not find version field in {pyproject_path}")

    if dry_run:
        print(f"[DRY-RUN] Updated {pyproject_path} version to '{new_version}'")
    else:
        pyproject_path.write_text(updated_content, encoding="utf-8")
        print(f"Updated {pyproject_path} version to '{new_version}'")


def update_uv_lock(dry_run: bool = False) -> None:
    """Run `uv lock` to update uv.lock."""
    if dry_run:
        print("[DRY-RUN] Would run `uv lock`")
    else:
        print("Updating uv.lock...")
        subprocess.run(["uv", "lock"], check=True)


def commit_tag_and_push(
    version: str,
    dry_run: bool = False,
    no_push: bool = False,
    remote_name: str = "origin",
) -> None:
    """Stage, commit, tag, and push changes and tag to remote."""
    tag_name = f"v{version}"
    cmd_stage = ["git", "add", "pyproject.toml", "uv.lock"]
    cmd_commit = ["git", "commit", "-m", f"release: {tag_name}"]
    cmd_tag = ["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"]
    cmd_push_branch = ["git", "push", remote_name, "HEAD"]
    cmd_push_tag = ["git", "push", remote_name, tag_name]

    remote_available = has_remote(remote_name)

    if dry_run:
        print("[DRY-RUN] Executing git operations:")
        print(f"  {' '.join(cmd_stage)}")
        print(f"  {' '.join(cmd_commit)}")
        print(f"  {' '.join(cmd_tag)}")
        if not no_push and remote_available:
            print(f"  {' '.join(cmd_push_branch)}")
            print(f"  {' '.join(cmd_push_tag)}")
        elif not remote_available:
            print(
                f"  [Notice] Remote '{remote_name}' not found. Pushes would be skipped."
            )
        else:
            print("  [Notice] --no-push set. Pushes skipped.")
        return

    print("Staging modified version files...")
    subprocess.run(cmd_stage, check=True)

    print(f"Creating commit for release {tag_name}...")
    subprocess.run(cmd_commit, check=True)

    print(f"Creating tag {tag_name}...")
    subprocess.run(cmd_tag, check=True)

    if no_push:
        print("Skipping push as --no-push was set.")
    elif not remote_available:
        print(f"Notice: Git remote '{remote_name}' not configured. Skipped push.")
    else:
        print(f"Pushing current branch to {remote_name}...")
        subprocess.run(cmd_push_branch, check=True)
        print(f"Pushing tag {tag_name} to {remote_name}...")
        subprocess.run(cmd_push_tag, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Release new version: bump pyproject.toml, uv lock, commit, tag, and push."
    )
    parser.add_argument("version", help="New version string (e.g. 0.2.0 or v0.2.0)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform validation and show changes without modifying files or git state.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit and tag locally, but do not push to remote.",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote name to push to (default: origin).",
    )
    args = parser.parse_args()

    # 1. Validate SemVer
    try:
        version = validate_semver(args.version)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Target release version: v{version}")

    # 2. Check if version tag already exists
    existing_tags = get_existing_tags()
    if version in existing_tags or f"v{version}" in existing_tags:
        print(
            f"Error: Version tag '{version}' (or 'v{version}') already exists in git history!",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. Locate files
    root_dir = Path(__file__).resolve().parent.parent
    pyproject_path = root_dir / "pyproject.toml"
    if not pyproject_path.exists():
        print(f"Error: pyproject.toml not found at {pyproject_path}", file=sys.stderr)
        sys.exit(1)

    # 4. Check git status is clean before release (unless dry-run)
    status_res = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    )
    if not args.dry_run and status_res.stdout.strip():
        print(
            "Error: Git working tree is dirty. Please commit or stash changes before release.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.dry_run and status_res.stdout.strip():
        print(
            "[DRY-RUN] Notice: Git working tree is dirty (skipped failure in dry-run mode)."
        )

    # 5. Run full test & check suite
    print("Running make check-all (checks, mypy, pytest including E2E)...")
    check_cmd = ["make", "check-all"]
    if args.dry_run:
        print(f"[DRY-RUN] Would run: {' '.join(check_cmd)}")
    else:
        subprocess.run(check_cmd, check=True)

    # 6. Update files
    try:
        update_pyproject_version(pyproject_path, version, dry_run=args.dry_run)
        update_uv_lock(dry_run=args.dry_run)
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        print(f"Error updating project files: {e}", file=sys.stderr)
        sys.exit(1)

    # 7. Git commit, tag & push
    try:
        commit_tag_and_push(
            version,
            dry_run=args.dry_run,
            no_push=args.no_push,
            remote_name=args.remote,
        )
    except subprocess.SubprocessError as e:
        print(f"Error executing git operations: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Successfully released v{version}!")


if __name__ == "__main__":
    main()
