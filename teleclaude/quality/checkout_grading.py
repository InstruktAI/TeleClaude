"""Decide whether an execution root is a TeleClaude checkout other than the running
installation, and run the selected checks in that checkout's own code, in a separate
process against a fresh scratch home, returning the exit status: its own
``telec code lint`` for a full leg selection, or an installed entry that starts its
own guardrail lane alone for a guardrails-only selection.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from enum import StrEnum
from pathlib import Path

from teleclaude.paths import MACHINE_CONFIG_PATH, REPO_ROOT, ConfigFileName
from teleclaude.runtime.command_runner import run_process_group_command

_TELECLAUDE_PACKAGE_MARKER = Path("teleclaude") / "__init__.py"

_UV_EXECUTABLE = "uv"
_UV_RUN_SUBCOMMAND = "run"
_UV_DIRECTORY_FLAG = "--directory"
_UV_QUIET_FLAG = "--quiet"
_PYTHON_EXECUTABLE = "python"
_PYTHON_MODULE_FLAG = "-m"
_PYTHON_SAFE_PATH_FLAG = "-P"
_TELEC_MODULE = "teleclaude.cli.telec"
_CODE_SUBCOMMAND = "code"
_LINT_SUBCOMMAND = "lint"
_ALL_FLAG = "--all"
_GUARDRAILS_ENTRY_SCRIPT = Path("tools") / "lint" / "checkout_guardrails.py"
_GUARDRAILS_ENTRY_ROOT_FLAG = "--root"

_ENV_TELECLAUDE_HOME = "TELECLAUDE_HOME"
_ENV_TELEC_INVOCATION_CWD = "TELEC_INVOCATION_CWD"
_ENV_UV_NO_SYNC = "UV_NO_SYNC"
_ENV_UV_NO_SYNC_VALUE = "1"
_ENV_PYTHONPATH = "PYTHONPATH"


class CheckoutGradingRunner(StrEnum):
    """Which code grades an execution root: the running installation, or itself."""

    INSTALLED = "installed"
    SUBJECT_CHECKOUT = "subject_checkout"


class CheckoutGradingReason(StrEnum):
    """Why a runner was selected."""

    INSTALLATION = "installation"
    NOT_TELECLAUDE_CHECKOUT = "not_teleclaude_checkout"
    SUBJECT_CHECKOUT = "subject_checkout"


class CheckoutGradingDecision(StrEnum):
    """Which code grades an execution root, and why.

    A closed vocabulary instead of an independent (runner, reason) pair: the
    runner and its reason can never disagree, because each member carries
    exactly one of each.
    """

    INSTALLED_INSTALLATION = "installed_installation"
    INSTALLED_NOT_TELECLAUDE_CHECKOUT = "installed_not_teleclaude_checkout"
    SUBJECT_CHECKOUT = "subject_checkout"

    @property
    def runner(self) -> CheckoutGradingRunner:
        """Return the runner this decision selects."""
        if self is CheckoutGradingDecision.SUBJECT_CHECKOUT:
            return CheckoutGradingRunner.SUBJECT_CHECKOUT
        return CheckoutGradingRunner.INSTALLED

    @property
    def reason(self) -> CheckoutGradingReason:
        """Return why this decision selects its runner."""
        return _DECISION_REASONS[self]


_DECISION_REASONS: dict[CheckoutGradingDecision, CheckoutGradingReason] = {
    CheckoutGradingDecision.INSTALLED_INSTALLATION: CheckoutGradingReason.INSTALLATION,
    CheckoutGradingDecision.INSTALLED_NOT_TELECLAUDE_CHECKOUT: CheckoutGradingReason.NOT_TELECLAUDE_CHECKOUT,
    CheckoutGradingDecision.SUBJECT_CHECKOUT: CheckoutGradingReason.SUBJECT_CHECKOUT,
}


def resolve_checkout_grading_decision(execution_root: Path) -> CheckoutGradingDecision:
    """Select the runner for grading ``execution_root``."""
    resolved_root = execution_root.resolve()
    if resolved_root == REPO_ROOT:
        return CheckoutGradingDecision.INSTALLED_INSTALLATION
    if not (resolved_root / _TELECLAUDE_PACKAGE_MARKER).is_file():
        return CheckoutGradingDecision.INSTALLED_NOT_TELECLAUDE_CHECKOUT
    return CheckoutGradingDecision.SUBJECT_CHECKOUT


def run_subject_checkout_lint(execution_root: Path, files: list[str] | None, *, include_native: bool) -> int:
    """Run the selected checks in ``execution_root``'s own code, against a fresh scratch home.

    ``include_native`` selects the checkout's own ``telec code lint`` (both legs).
    Without it, only the guardrail lane is requested: that command always runs
    both legs and refuses outright for a caller without the code capability
    (`handlers/code.py` ``_require_code_capability``), so a guardrails-only
    caller is started instead through an installed entry script that runs
    nothing but the graded checkout's own guardrail lane.
    """
    with tempfile.TemporaryDirectory() as scratch_home:
        shutil.copy2(MACHINE_CONFIG_PATH, Path(scratch_home) / ConfigFileName.MACHINE)
        targets = [_ALL_FLAG] if files is None else files
        child_env = dict(os.environ)  # guard: direct-env-read - allowed: child-process environment construction
        child_env[_ENV_TELECLAUDE_HOME] = scratch_home
        child_env[_ENV_TELEC_INVOCATION_CWD] = str(execution_root)
        child_env[_ENV_UV_NO_SYNC] = _ENV_UV_NO_SYNC_VALUE
        if include_native:
            # The graded checkout's rules have to run as that checkout's own code in a
            # separate interpreter with its own home; this runs that checkout's own
            # `telec code lint` module, started with `uv run --directory <root>`, the
            # lever the checkout's own wrapper also uses.
            command = [
                _UV_EXECUTABLE,
                _UV_RUN_SUBCOMMAND,
                _UV_DIRECTORY_FLAG,
                str(execution_root),
                _UV_QUIET_FLAG,
                _PYTHON_EXECUTABLE,
                _PYTHON_MODULE_FLAG,
                _TELEC_MODULE,
                _CODE_SUBCOMMAND,
                _LINT_SUBCOMMAND,
                *targets,
            ]
        else:
            # The same separate interpreter and home are needed here too. The checkout's
            # `teleclaude` package is selected by placing its root first on the child's
            # PYTHONPATH (it outranks the editable-install finder), and the entry script
            # verifies the loaded package before it runs anything. `uv run --directory
            # <root>` supplies the checkout's own environment for that entry.
            command = [
                _UV_EXECUTABLE,
                _UV_RUN_SUBCOMMAND,
                _UV_DIRECTORY_FLAG,
                str(execution_root),
                _UV_QUIET_FLAG,
                _PYTHON_EXECUTABLE,
                _PYTHON_SAFE_PATH_FLAG,
                str(REPO_ROOT / _GUARDRAILS_ENTRY_SCRIPT),
                _GUARDRAILS_ENTRY_ROOT_FLAG,
                str(execution_root),
                *targets,
            ]
            child_env[_ENV_PYTHONPATH] = str(execution_root)
        return run_process_group_command(command, execution_root, child_env).exit_code


__all__ = [
    "CheckoutGradingDecision",
    "CheckoutGradingReason",
    "CheckoutGradingRunner",
    "resolve_checkout_grading_decision",
    "run_subject_checkout_lint",
]
