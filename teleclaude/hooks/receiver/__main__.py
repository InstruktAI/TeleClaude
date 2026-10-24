#!/usr/bin/env python3
"""Entry point for teleclaude.hooks.receiver — executable via direct script invocation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Agent CLIs invoke this file by path, so sys.path[0] is this directory and the
# directory holding the teleclaude package is absent. Deriving that directory from
# __file__ needs no import, which is what lets the package import below resolve.
_PACKAGE_PARENT = Path(__file__).resolve().parents[3]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.append(str(_PACKAGE_PARENT))

_VENV_DIR_NAME = ".venv"
_VENV_PYTHON_RELATIVE = Path("bin") / "python3"


def _reexec_under_project_venv() -> None:
    """Re-execute direct entry under the project interpreter when needed."""
    # Each checkout owns its environment, including the prepared links in worktrees.
    # Select it before project imports: PATH may name a dependency-free Python.
    venv_dir = _PACKAGE_PARENT / _VENV_DIR_NAME
    venv_python = venv_dir / _VENV_PYTHON_RELATIVE
    if venv_python.is_file() and Path(sys.prefix).resolve() != venv_dir.resolve():
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


def _print_help_and_exit_if_requested() -> None:
    """Serve CLI help without importing the config-dependent receiver package."""
    if not any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        return

    from teleclaude.hooks.receiver_args import (  # noqa: PLC0415 - entry seam: select the checkout interpreter before importing project dependencies
        build_receiver_arg_parser,
    )

    build_receiver_arg_parser().print_help()
    raise SystemExit(0)


def _run_receiver_main() -> None:
    """Import and execute the hook receiver entry point."""
    _print_help_and_exit_if_requested()
    from teleclaude.hooks.receiver.run import (  # noqa: PLC0415 - entry seam: help and the venv re-exec run before the receiver loads
        main,
    )

    main()


if __name__ == "__main__":
    _reexec_under_project_venv()
    _run_receiver_main()
