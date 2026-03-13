#!/usr/bin/env python3
"""Entry point for teleclaude.hooks.receiver — executable via direct script invocation."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_main_repo_root(start: Path) -> Path:
    """Resolve the main git repository root, even when invoked from a worktree.

    In a worktree, .git is a file containing 'gitdir: <path>' pointing to
    main_repo/.git/worktrees/<name>. This reads that file to find the main repo.
    Pure filesystem — no subprocess, no external deps.
    """
    current = start
    while current != current.parent:
        git_path = current / ".git"
        if git_path.is_dir():
            return current
        if git_path.is_file():
            try:
                content = git_path.read_text().strip()
            except OSError:
                return current
            if content.startswith("gitdir:"):
                gitdir = Path(content.split(":", 1)[1].strip())
                if not gitdir.is_absolute():
                    gitdir = (current / gitdir).resolve()
                # gitdir = main_repo/.git/worktrees/<name> — find the .git ancestor
                for parent in gitdir.parents:
                    if parent.name == ".git":
                        return parent.parent
            return current
        current = current.parent
    return start


# Bootstrap: resolve main repo root (worktree-safe), then re-exec under the
# project venv when needed. Agent CLIs call this hook from arbitrary directories
# where PATH may resolve python3 to system Python (missing project deps).
_REPO_ROOT = _resolve_main_repo_root(Path(__file__).resolve().parents[3])
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python3"
if _VENV_PYTHON.is_file() and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), *sys.argv])

# Ensure local hooks utils and TeleClaude package are importable
sys.path.append(str(_REPO_ROOT / "teleclaude" / "hooks"))
sys.path.append(str(_REPO_ROOT))

from teleclaude.hooks.receiver import main

if __name__ == "__main__":
    main()
