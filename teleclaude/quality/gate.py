"""Native lint gate shared by command and integration callers."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.git import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import REPO_ROOT
from teleclaude.quality.checkout_grading import (
    CheckoutGradingDecision,
    resolve_checkout_grading_decision,
    run_subject_checkout_lint,
)
from teleclaude.quality.lint import LintRunner
from teleclaude.runtime.command_runner import run_process_group_command
from teleclaude.session_identity import get_session_id

logger = get_logger(__name__)

_SUBJECT_MISMATCH_TEMPLATE = "Quality gate refused to evaluate {subject_sha}: execution root HEAD is {execution_head}."
_HEAD_READ_FAILURES = (BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError)
_QUALITY_GATE_SUBJECT_UNAVAILABLE_EVENT = "quality_gate_subject_unavailable"
_QUALITY_GATE_CHECKOUT_GRADING_EVENT = "quality_gate_checkout_grading"
_MAKE_EXECUTABLE = "make"
_MAKE_FORMAT_TARGET = "format"
_MAKE_LINT_TARGET = "lint"
_MAKE_VARIABLE_TEMPLATE = "{key}={value}"
_FILES_FROM_ARGUMENT_TEMPLATE = "FILES_FROM={files_from}"
_NATIVE_LINT_FAILURE_TEMPLATE = "Native lint failed with exit code {exit_code}."
_GUARDRAILS_FAILURE_TEMPLATE = "Guardrails failed with exit code {exit_code}."
_DELEGATED_LINT_FAILURE_TEMPLATE = "{execution_root}'s own telec code lint exited {exit_code}."
_DELEGATED_GUARDRAILS_FAILURE_TEMPLATE = (
    "{execution_root}'s own guardrail lane (tools/lint/checkout_guardrails.py) exited {exit_code}."
)
_FAILURE_REASON_SEPARATOR = " "
_UTF8 = "utf-8"
_EMPTY_BYTES = b""
_NUL_BYTE = b"\0"
_DEFAULT_FAILURE_EXIT_CODE = 1


class LintGateOutcome(StrEnum):
    """Closed result states for a native lint gate invocation."""

    PASSED = "passed"
    FAILED = "failed"


class QualityGateLeg(StrEnum):
    """Independently selectable quality checks for a sealed commit."""

    NATIVE = "native"
    GUARDRAILS = "guardrails"


@dataclass(frozen=True)
class LintGateResult:
    """The optional subject and independent exit statuses observed by one lint gate."""

    outcome: LintGateOutcome
    subject_sha: str | None
    execution_head: str | None
    native_exit_code: int | None
    guardrails_exit_code: int | None
    failure_reason: str | None = None
    delegated_exit_code: int | None = None

    @property
    def exit_code(self) -> int:
        """Return a delegated checkout's own exit status first, else the existing CLI precedence."""
        if self.delegated_exit_code not in (None, 0):
            return self.delegated_exit_code
        if self.guardrails_exit_code not in (None, 0):
            return self.guardrails_exit_code
        if self.native_exit_code not in (None, 0):
            return self.native_exit_code
        return 0 if self.outcome is LintGateOutcome.PASSED else 1


def read_head_sha(execution_root: Path) -> str | None:
    """Read an execution checkout's committed subject through GitPython."""
    try:
        return Repo(execution_root).head.commit.hexsha
    except _HEAD_READ_FAILURES as exc:
        logger.error(_QUALITY_GATE_SUBJECT_UNAVAILABLE_EVENT, root=str(execution_root), error=str(exc))
        return None


def run_lint_gate(
    project_root: Path,
    execution_root: Path,
    subject_sha: str | None,
    files: list[str] | None,
    format_scoped: bool,
    child_env: Mapping[str, str] | None,
    selection: frozenset[QualityGateLeg] = frozenset(QualityGateLeg),
    *,
    request_subject_checkout_grading: bool = False,
) -> LintGateResult:
    """Run selected lint checks, optionally bound to a committed subject.

    When ``subject_sha`` is set, the execution checkout's HEAD must match it
    before grading. Callers without a selected commit pass ``None`` and grade
    the execution checkout without reading HEAD. Integration's final-content
    validation binds a subject; pre-commit callers do not have one yet.

    ``request_subject_checkout_grading`` is off by default: the legs run in this
    process against ``execution_root``. When enabled, grading is handed to
    ``execution_root``'s own code when it is a TeleClaude checkout other than the
    running installation: its own ``telec code lint`` for a full leg selection, or
    an installed entry that starts its own guardrail lane alone
    (``tools/lint/checkout_guardrails.py``) for a guardrails-only selection. A
    ``quality_gate_checkout_grading`` record is emitted naming which code graded it.
    """
    execution_head = None
    if subject_sha is not None:
        execution_head = read_head_sha(execution_root)
        if execution_head != subject_sha:
            return LintGateResult(
                outcome=LintGateOutcome.FAILED,
                subject_sha=subject_sha,
                execution_head=execution_head,
                native_exit_code=None,
                guardrails_exit_code=None,
                failure_reason=_SUBJECT_MISMATCH_TEMPLATE.format(
                    subject_sha=subject_sha, execution_head=execution_head
                ),
            )

    if not request_subject_checkout_grading:
        native_exit_code, guardrails_exit_code = _run_in_process_legs(
            execution_root, files, format_scoped, child_env, selection
        )
        return _build_in_process_result(subject_sha, execution_head, native_exit_code, guardrails_exit_code)

    decision = resolve_checkout_grading_decision(execution_root)
    # The guardrail lane is the only leg that needs the graded checkout's own code
    # (gate.run_make_target's native leg is already a cwd-scoped `make lint` subprocess
    # that imports no installed `teleclaude`). A native-only selection has no caller
    # today and is not delegated either: it runs in-process below, exactly as today.
    if decision is CheckoutGradingDecision.SUBJECT_CHECKOUT and QualityGateLeg.GUARDRAILS in selection:
        include_native = QualityGateLeg.NATIVE in selection
        delegated_exit_code = run_subject_checkout_lint(execution_root, files, include_native=include_native)
        result = LintGateResult(
            outcome=LintGateOutcome.PASSED if delegated_exit_code == 0 else LintGateOutcome.FAILED,
            subject_sha=subject_sha,
            execution_head=execution_head,
            native_exit_code=None,
            guardrails_exit_code=None,
            delegated_exit_code=delegated_exit_code,
            failure_reason=_delegated_lint_failure_reason(
                execution_root, delegated_exit_code, include_native=include_native
            ),
        )
    else:
        native_exit_code, guardrails_exit_code = _run_in_process_legs(
            execution_root, files, format_scoped, child_env, selection
        )
        result = _build_in_process_result(subject_sha, execution_head, native_exit_code, guardrails_exit_code)
    _log_checkout_grading(execution_root, decision, selection, result.exit_code)
    return result


def _run_in_process_legs(
    execution_root: Path,
    files: list[str] | None,
    format_scoped: bool,
    child_env: Mapping[str, str] | None,
    selection: frozenset[QualityGateLeg],
) -> tuple[int | None, int | None]:
    """Run the native and guardrails legs in this process, exactly as before."""
    run_native = QualityGateLeg.NATIVE in selection
    run_guardrails = QualityGateLeg.GUARDRAILS in selection
    if run_native and format_scoped and files is not None:
        run_make_target(_MAKE_FORMAT_TARGET, execution_root, files=files, child_env=child_env)

    native_exit_code = (
        run_make_target(_MAKE_LINT_TARGET, execution_root, files=files, child_env=child_env) if run_native else None
    )
    guardrails_exit_code: int | None = None
    if run_guardrails:
        guardrails_exit_code = 0
        try:
            LintRunner(project_root=execution_root).run(files=files, run_all=files is None)
        except SystemExit as exc:
            guardrails_exit_code = _system_exit_code(exc)
    return native_exit_code, guardrails_exit_code


def _build_in_process_result(
    subject_sha: str | None,
    execution_head: str | None,
    native_exit_code: int | None,
    guardrails_exit_code: int | None,
) -> LintGateResult:
    outcome = (
        LintGateOutcome.PASSED
        if native_exit_code in (None, 0) and guardrails_exit_code in (None, 0)
        else LintGateOutcome.FAILED
    )
    return LintGateResult(
        outcome=outcome,
        subject_sha=subject_sha,
        execution_head=execution_head,
        native_exit_code=native_exit_code,
        guardrails_exit_code=guardrails_exit_code,
        failure_reason=_lint_failure_reason(native_exit_code, guardrails_exit_code),
    )


def _delegated_lint_failure_reason(execution_root: Path, exit_code: int, *, include_native: bool) -> str | None:
    if exit_code == 0:
        return None
    template = _DELEGATED_LINT_FAILURE_TEMPLATE if include_native else _DELEGATED_GUARDRAILS_FAILURE_TEMPLATE
    return template.format(execution_root=execution_root, exit_code=exit_code)


def _log_checkout_grading(
    execution_root: Path,
    decision: CheckoutGradingDecision,
    selection: frozenset[QualityGateLeg],
    exit_code: int,
) -> None:
    logger.info(
        _QUALITY_GATE_CHECKOUT_GRADING_EVENT,
        execution_root=str(execution_root),
        code_root=str(REPO_ROOT),
        runner=decision.runner,
        reason=decision.reason,
        selection=sorted(selection),
        exit_code=exit_code,
        session_id=get_session_id(),
    )


def run_make_target(
    target: str,
    execution_root: Path,
    *,
    files: list[str] | None = None,
    variables: Mapping[str, str] | None = None,
    child_env: Mapping[str, str] | None = None,
) -> int:
    """Run one native Make target with optional NUL-delimited file scope."""
    command = [_MAKE_EXECUTABLE, target]
    if variables:
        command.extend(_MAKE_VARIABLE_TEMPLATE.format(key=key, value=value) for key, value in variables.items())
    if files is None:
        return run_process_group_command(command, execution_root, child_env).exit_code
    with _nul_file(files) as files_from:
        command.append(_FILES_FROM_ARGUMENT_TEMPLATE.format(files_from=files_from))
        return run_process_group_command(command, execution_root, child_env).exit_code


@contextmanager
def _nul_file(files: list[str]) -> Iterator[str]:
    handle = tempfile.NamedTemporaryFile(delete=False)
    try:
        with handle:
            handle.write(_EMPTY_BYTES.join(path.encode(_UTF8) + _NUL_BYTE for path in files))
        yield handle.name
    finally:
        Path(handle.name).unlink(missing_ok=True)


def _system_exit_code(exc: SystemExit) -> int:
    return exc.code if isinstance(exc.code, int) else _DEFAULT_FAILURE_EXIT_CODE


def _lint_failure_reason(native_exit_code: int | None, guardrails_exit_code: int | None) -> str | None:
    """Describe every failing lint leg with its terminal status."""
    reasons: list[str] = []
    if native_exit_code not in (None, 0):
        reasons.append(_NATIVE_LINT_FAILURE_TEMPLATE.format(exit_code=native_exit_code))
    if guardrails_exit_code not in (None, 0):
        reasons.append(_GUARDRAILS_FAILURE_TEMPLATE.format(exit_code=guardrails_exit_code))
    return _FAILURE_REASON_SEPARATOR.join(reasons) or None


__all__ = [
    "LintGateOutcome",
    "LintGateResult",
    "QualityGateLeg",
    "read_head_sha",
    "run_lint_gate",
    "run_make_target",
]
