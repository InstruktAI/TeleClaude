#!/usr/bin/env python3
"""Entry point for teleclaude.hooks.receiver — executable via direct script invocation."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

if __package__:
    from ._repo_root import resolve_project_root
else:
    _repo_root_path = Path(__file__).with_name("_repo_root.py")
    _repo_root_spec = importlib.util.spec_from_file_location("_repo_root", _repo_root_path)
    if _repo_root_spec is None or _repo_root_spec.loader is None:
        raise RuntimeError(f"Unable to load repo-root helper from {_repo_root_path}")
    _repo_root_module = importlib.util.module_from_spec(_repo_root_spec)
    _repo_root_spec.loader.exec_module(_repo_root_module)
    resolve_project_root = _repo_root_module.resolve_project_root

# Bootstrap: resolve main repo root (worktree-safe), then re-exec under the
# project venv when needed. Agent CLIs call this hook from arbitrary directories
# where PATH may resolve python3 to system Python (missing project deps).
_REPO_ROOT = resolve_project_root(Path(__file__).resolve().parents[3])
_VENV_DIR = _REPO_ROOT / ".venv"
_VENV_PYTHON = _VENV_DIR / "bin" / "python3"
if _VENV_PYTHON.is_file() and Path(sys.prefix).resolve() != _VENV_DIR.resolve():
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), *sys.argv])

# Ensure local hooks utils and TeleClaude package are importable
sys.path.append(str(_REPO_ROOT / "teleclaude" / "hooks"))
sys.path.append(str(_REPO_ROOT))


def _run_receiver_main() -> None:
    """Import and execute the hook receiver entry point."""
    receiver_module = importlib.import_module("teleclaude.hooks.receiver")
    receiver_module.main()


if __name__ == "__main__":
    _run_receiver_main()
