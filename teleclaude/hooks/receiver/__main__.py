#!/usr/bin/env python3
"""Entry point for teleclaude.hooks.receiver — executable via direct script invocation."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# Agent CLIs invoke this file by path, so sys.path[0] is this directory and the
# directory holding the teleclaude package is absent. Deriving that directory from
# __file__ needs no import, which is what lets the package import below resolve.
_PACKAGE_PARENT = Path(__file__).resolve().parents[3]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.append(str(_PACKAGE_PARENT))

from teleclaude.project_root import resolve_project_root

# Resolve the main repo root (worktree-safe), then re-exec under the project venv when
# needed. PATH may resolve python3 to system Python, which lacks the project deps.
_REPO_ROOT = resolve_project_root(_PACKAGE_PARENT)
_VENV_DIR = _REPO_ROOT / ".venv"
_VENV_PYTHON = _VENV_DIR / "bin" / "python3"
if _VENV_PYTHON.is_file() and Path(sys.prefix).resolve() != _VENV_DIR.resolve():
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), *sys.argv])


def _run_receiver_main() -> None:
    """Import and execute the hook receiver entry point."""
    receiver_module = importlib.import_module("teleclaude.hooks.receiver")
    receiver_module.main()


if __name__ == "__main__":
    _run_receiver_main()
