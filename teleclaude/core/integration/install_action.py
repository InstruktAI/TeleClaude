"""Execute the base ``install`` maintenance action for the invoking root."""

from __future__ import annotations

import subprocess
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import resolve_capabilities
from teleclaude.runtime.command_runner import run_process_group_command

logger = get_logger(__name__)

_MAKE_EXECUTABLE = "make"
_INSTALL_TARGET = "install"
_MAKE_QUESTION_FLAG = "--question"
_MAKE_NO_BUILTIN_RULES_FLAG = "--no-builtin-rules"
# Exit status GNU make reserves for "could not run": no makefile, or no rule for the target.
_MAKE_ERROR_EXIT_CODE = 2
_INSTALL_DECISION_EVENT = "install_action_decision"
_NOTHING_TO_INSTALL = "Nothing to install: this root declares no install target."
_INSTALL_TARGET_REQUIRED = "This root subscribes code, so it must declare an install make target, and it declares none."
_MAKE_UNAVAILABLE = "Cannot decide whether this root declares an install target: {error}"
_SUCCEEDED = 0
_FAILED = 1


class InstallDecision(StrEnum):
    """What the installation action decided for a root."""

    INSTALL = "install"
    NOTHING_TO_INSTALL = "nothing_to_install"
    TARGET_REQUIRED = "target_required"
    UNDECIDABLE = "undecidable"


def declares_install_target(root: Path) -> bool:
    """Whether the root's make configuration declares an ``install`` target.

    The query asks make whether the target is up to date, which runs no recipe of
    the target itself; make reports an unknown target, or the absence of any
    makefile, through its reserved error status.
    """
    # The root's own build tool is the only authority on what it declares; no Python API answers that question.
    answer = subprocess.run(
        [_MAKE_EXECUTABLE, _MAKE_QUESTION_FLAG, _MAKE_NO_BUILTIN_RULES_FLAG, _INSTALL_TARGET],
        cwd=str(root),
        capture_output=True,
        check=False,
    )
    return answer.returncode != _MAKE_ERROR_EXIT_CODE


def run_install_action(root: Path) -> int:
    """Install the root when it declares an install target; report nothing to install otherwise."""
    try:
        declared = declares_install_target(root)
    except OSError as exc:
        _log_decision(root, InstallDecision.UNDECIDABLE, _FAILED)
        print(_MAKE_UNAVAILABLE.format(error=exc))
        return _FAILED
    if declared:
        exit_code = run_process_group_command([_MAKE_EXECUTABLE, _INSTALL_TARGET], root).exit_code
        _log_decision(root, InstallDecision.INSTALL, exit_code)
        return exit_code
    if resolve_capabilities(root).code:
        _log_decision(root, InstallDecision.TARGET_REQUIRED, _FAILED)
        print(_INSTALL_TARGET_REQUIRED)
        return _FAILED
    _log_decision(root, InstallDecision.NOTHING_TO_INSTALL, _SUCCEEDED)
    print(_NOTHING_TO_INSTALL)
    return _SUCCEEDED


def main() -> int:
    """Run the installation action for the command line's working root."""
    return run_install_action(Path.cwd().resolve())


def _log_decision(root: Path, decision: InstallDecision, exit_code: int) -> None:
    """Record the root, the decision and the resulting exit code."""
    logger.info(_INSTALL_DECISION_EVENT, project_root=str(root), decision=decision.value, exit_code=exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
