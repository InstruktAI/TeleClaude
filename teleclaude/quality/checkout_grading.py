"""Decide which code grades an execution root and isolate subject-checkout grading."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path

from teleclaude.git_tree import tree_read_environment
from teleclaude.paths import MACHINE_CONFIG_PATH, REPO_ROOT, ConfigFileName
from teleclaude.project_root import worktree_home_root
from teleclaude.quality.selection import QualityCheckFamily
from teleclaude.runtime.command_runner import run_process_group_command

_TELECLAUDE_PACKAGE_MARKER = Path("teleclaude") / "__init__.py"

_UV_EXECUTABLE = "uv"
_UV_RUN_SUBCOMMAND = "run"
_UV_DIRECTORY_FLAG = "--directory"
_UV_QUIET_FLAG = "--quiet"
_PYTHON_EXECUTABLE = "python"
_PYTHON_SAFE_PATH_FLAG = "-P"
_ALL_FLAG = "--all"
_GUARDRAILS_ENTRY_SCRIPT = Path("tools") / "lint" / "checkout_guardrails.py"
_GUARDRAILS_ENTRY_ROOT_FLAG = "--root"
_GUARDRAILS_CONTENT_ROOT_FLAG = "--content-root"
_GUARDRAILS_PLATFORM_HOME_SUBJECT_FLAG = "--platform-home-subject"
_GUARDRAILS_FAMILY_FLAG = "--family"
_GUARDRAILS_FULL_RUN_FLAG = "--full-run"
_ENTRY_OPERATION_FLAG = "--operation"
_ENTRY_OPTION_TERMINATOR = "--"

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


class CheckoutGradingOperation(StrEnum):
    """Closed set of operations the installed entry can run under subject code."""

    GUARDRAILS = "guardrails"
    STAGED_DECLARATIONS = "staged-declarations"


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


@contextmanager
def subject_checkout_grading_environment(
    execution_root: Path,
    *,
    base_env: Mapping[str, str] | None = None,
) -> Iterator[dict[str, str]]:
    """Yield the isolated child environment used for grading a subject checkout."""
    child_env = dict(base_env) if base_env is not None else dict(os.environ)  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    child_env[_ENV_TELEC_INVOCATION_CWD] = str(execution_root)
    child_env[_ENV_UV_NO_SYNC] = _ENV_UV_NO_SYNC_VALUE
    if worktree_home_root(execution_root) is not None:
        child_env.pop(_ENV_TELECLAUDE_HOME, None)
        yield child_env
        return

    with tempfile.TemporaryDirectory() as scratch_home:
        shutil.copy2(MACHINE_CONFIG_PATH, Path(scratch_home) / ConfigFileName.MACHINE)
        child_env[_ENV_TELECLAUDE_HOME] = scratch_home
        yield child_env


def run_subject_checkout_guardrails(
    execution_root: Path,
    files: list[str] | None,
    child_env: Mapping[str, str],
    *,
    content_root: Path | None = None,
    platform_home_subject: bool = False,
    check_families: frozenset[QualityCheckFamily] = frozenset(QualityCheckFamily),
    full_run: bool = False,
) -> int:
    """Run the installed entry that verifies and grades the subject checkout."""
    targets = [_ALL_FLAG] if files is None else files
    arguments: list[str] = []
    if content_root is not None:
        arguments.extend([_GUARDRAILS_CONTENT_ROOT_FLAG, str(content_root)])
    if platform_home_subject:
        arguments.append(_GUARDRAILS_PLATFORM_HOME_SUBJECT_FLAG)
    for family in sorted(check_families):
        arguments.extend([_GUARDRAILS_FAMILY_FLAG, family.value])
    if full_run:
        arguments.append(_GUARDRAILS_FULL_RUN_FLAG)
    arguments.extend(targets)
    return _run_subject_checkout_entry(execution_root, child_env, arguments)


def run_subject_checkout_declarations(
    execution_root: Path,
    declaration_paths: list[str],
    child_env: Mapping[str, str],
) -> int:
    """Run staged declaration validation under the subject checkout's schema."""
    arguments = [
        _ENTRY_OPERATION_FLAG,
        CheckoutGradingOperation.STAGED_DECLARATIONS.value,
        _ENTRY_OPTION_TERMINATOR,
        *declaration_paths,
    ]
    return _run_subject_checkout_entry(execution_root, child_env, arguments)


def _run_subject_checkout_entry(
    execution_root: Path,
    child_env: Mapping[str, str],
    arguments: list[str],
) -> int:
    """Run the installation-supplied entry under the selected checkout's code."""
    entry_env = tree_read_environment(execution_root, base_environment=child_env)
    entry_env[_ENV_PYTHONPATH] = str(execution_root)
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
    ]
    command.extend(arguments)
    return run_process_group_command(command, execution_root, entry_env).exit_code


__all__ = [
    "CheckoutGradingDecision",
    "CheckoutGradingOperation",
    "CheckoutGradingReason",
    "CheckoutGradingRunner",
    "resolve_checkout_grading_decision",
    "run_subject_checkout_declarations",
    "run_subject_checkout_guardrails",
    "subject_checkout_grading_environment",
]
