#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path


def _stamp_path(project_root: Path) -> Path:
    digest = hashlib.sha1(str(project_root).encode("utf-8")).hexdigest()
    return Path("/tmp") / f"teleclaude-sync-{digest}.stamp"


def _iter_agent_master_paths(project_root: Path) -> list[Path]:
    skip_dirs = {
        ".git",
        ".agents",
        "agents",
        "dist",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
    }
    matches: list[Path] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        if "AGENTS.master.md" in files:
            matches.append(Path(root) / "AGENTS.master.md")
    return matches


def _is_newer(path: Path, *, since: float) -> bool:
    try:
        return path.stat().st_mtime > since
    except FileNotFoundError:
        return False


def _dir_changed(root: Path, *, since: float) -> bool:
    if not root.exists():
        return False
    for current, _, files in os.walk(root):
        for name in files:
            if _is_newer(Path(current) / name, since=since):
                return True
    return False


def _should_sync(project_root: Path, *, since: float, repo_root: Path) -> bool:
    if project_root == repo_root:
        if _dir_changed(project_root / "agents", since=since):
            return True
        global_master = project_root / "agents" / "AGENTS.global.md"
        if _is_newer(global_master, since=since):
            return True
    if _dir_changed(project_root / ".agents", since=since):
        return True

    for master_path in _iter_agent_master_paths(project_root):
        if _is_newer(master_path, since=since):
            return True
        agents_path = master_path.parent / "AGENTS.md"
        claude_path = master_path.parent / "CLAUDE.md"
        if not agents_path.exists() or not claude_path.exists():
            return True
    return False


def _run(cmd: list[str], *, cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, env=os.environ.copy())


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-sync TeleClaude docs/agents when relevant files change.")
    parser.add_argument("--project-root", required=True, help="Project root to sync.")
    parser.add_argument("--force", action="store_true", help="Run sync regardless of changes.")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    stamp = _stamp_path(project_root)
    last_run = stamp.stat().st_mtime if stamp.exists() else 0.0

    if not args.force and not _should_sync(project_root, since=last_run, repo_root=repo_root):
        return 0

    _run(
        [
            "uv",
            "run",
            "--quiet",
            "scripts/sync_resources.py",
            "--warn-only",
            "--project-root",
            str(project_root),
        ],
        cwd=project_root,
    )
    _run(
        [
            "uv",
            "run",
            "--quiet",
            "scripts/distribute.py",
            "--project-root",
            str(project_root),
            "--deploy",
            "--warn-only",
        ],
        cwd=project_root,
    )
    stamp.touch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
