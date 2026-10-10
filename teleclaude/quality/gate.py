"""Native lint gate shared by command and integration callers."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.agent_artifacts import AGENT_ARTIFACT_ROOT_DIRNAME
from teleclaude.capabilities import DeclarationUnreadable, resolve_tier_permissions
from teleclaude.git import (
    BadName,
    GitCommandError,
    InvalidGitRepositoryError,
    NoSuchPathError,
    Repo,
    hook_free_environment,
)
from teleclaude.git_tree import TreeSource
from teleclaude.paths import REPO_ROOT
from teleclaude.quality.checkout_grading import (
    CheckoutGradingDecision,
    resolve_checkout_grading_decision,
    run_subject_checkout_guardrails,
    subject_checkout_grading_environment,
)
from teleclaude.quality.lint import LintRunner
from teleclaude.quality.native_slot import full_native_slot
from teleclaude.quality.selection import (
    GradingRoot,
    QualityCheckFamily,
    QualityGateLeg,
    resolve_repository_grading_root,
    select_grading_homes,
    select_quality_check_families,
    select_quality_gate_legs,
)
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
_DELEGATED_GUARDRAILS_FAILURE_TEMPLATE = (
    "{execution_root}'s own guardrail lane (tools/lint/checkout_guardrails.py) exited {exit_code}."
)
_FAILURE_REASON_SEPARATOR = " "
_UTF8 = "utf-8"
_EMPTY_BYTES = b""
_NUL_BYTE = b"\0"
_DEFAULT_FAILURE_EXIT_CODE = 1
_MARKDOWN_SUFFIX = ".md"
_ROOT_DECLARATION_MISSING = "The repository root has no readable declaration in the candidate tree or on disk."
_FORMAT_SELECTION_FAILURE_TEMPLATE = "native format selection failed: {error}"
_FORMAT_EXECUTION_FAILURE_TEMPLATE = "native format target failed for {home}: {error}"
_FORMAT_FAILURE_SEPARATOR = "; "
# These are failures of repository and declaration reads at the selection boundary.
_FORMAT_SELECTION_FAILURES = (
    BadName,
    DeclarationUnreadable,
    GitCommandError,
    InvalidGitRepositoryError,
    NoSuchPathError,
    OSError,
    ValueError,
    yaml.YAMLError,
)


class LintGateOutcome(StrEnum):
    """Closed result states for a native lint gate invocation."""

    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class LintGateResult:
    """The optional subject and independent exit statuses observed by one lint gate."""

    outcome: LintGateOutcome
    subject_sha: str | None
    execution_head: str | None
    native_exit_code: int | None
    guardrails_exit_code: int | None
    failure_reason: str | None = None

    @property
    def exit_code(self) -> int:
        """Return the guardrail status first, then the native status."""
        if self.guardrails_exit_code not in (None, 0):
            return self.guardrails_exit_code
        if self.native_exit_code not in (None, 0):
            return self.native_exit_code
        return 0 if self.outcome is LintGateOutcome.PASSED else 1


@dataclass(frozen=True)
class FormatGateOutcome:
    """The paths formatted and any grading homes whose native target failed."""

    failed_homes: tuple[Path, ...] = ()
    formatted_paths: tuple[str, ...] = ()
    failure_reason: str | None = None


def read_head_sha(execution_root: Path) -> str | None:
    """Read an execution checkout's committed subject through GitPython."""
    try:
        return Repo(execution_root).head.commit.hexsha
    except _HEAD_READ_FAILURES as exc:
        logger.error(_QUALITY_GATE_SUBJECT_UNAVAILABLE_EVENT, root=str(execution_root), error=str(exc))
        return None


def run_lint_gate(
    execution_root: Path,
    subject_sha: str | None,
    files: list[str] | None,
    format_scoped: bool,
    child_env: Mapping[str, str] | None,
    selection: frozenset[QualityGateLeg] = frozenset(QualityGateLeg),
    *,
    check_families: frozenset[QualityCheckFamily] = frozenset(QualityCheckFamily),
    full_run: bool = False,
    request_subject_checkout_grading: bool = False,
    content_root: Path | None = None,
    platform_home_subject: bool = False,
) -> LintGateResult:
    """Run selected lint checks, optionally bound to a committed subject.

    When ``subject_sha`` is set, the execution checkout's HEAD must match it
    before grading. Callers without a selected commit pass ``None`` and grade
    the execution checkout without reading HEAD. Integration's final-content
    validation binds a subject; pre-commit callers do not have one yet.

    ``request_subject_checkout_grading`` is off by default: the legs run in this
    process against ``execution_root``. When enabled, grading is handed to
    ``execution_root``'s own code when it is a TeleClaude checkout other than the
    running installation. The native leg runs that checkout's project-native lint
    under an isolated environment, and the guardrail lane runs through the installed
    entry (``tools/lint/checkout_guardrails.py``). A
    ``quality_gate_checkout_grading`` record names which code graded it.
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
            execution_root,
            files,
            format_scoped,
            child_env,
            selection,
            content_root,
            platform_home_subject,
            check_families,
            full_run,
        )
        return _build_in_process_result(subject_sha, execution_head, native_exit_code, guardrails_exit_code)

    decision = resolve_checkout_grading_decision(execution_root)
    # The guardrail lane is the only leg that loads first-party code. The native leg
    # runs the subject checkout's own project-native lint through its existing make target.
    # A native-only selection runs in-process, exactly as before.
    if decision is CheckoutGradingDecision.SUBJECT_CHECKOUT and QualityGateLeg.GUARDRAILS in selection:
        with subject_checkout_grading_environment(execution_root, base_env=child_env) as grading_env:
            native_exit_code, _ = _run_in_process_legs(
                execution_root,
                files,
                format_scoped,
                grading_env,
                selection & frozenset({QualityGateLeg.NATIVE}),
                check_families=check_families,
                full_run=full_run,
            )
            guardrails_exit_code = run_subject_checkout_guardrails(
                execution_root,
                files,
                grading_env,
                content_root=content_root,
                platform_home_subject=platform_home_subject,
                check_families=check_families,
                full_run=full_run,
            )
        result = LintGateResult(
            outcome=(
                LintGateOutcome.PASSED
                if native_exit_code in (None, 0) and guardrails_exit_code == 0
                else LintGateOutcome.FAILED
            ),
            subject_sha=subject_sha,
            execution_head=execution_head,
            native_exit_code=native_exit_code,
            guardrails_exit_code=guardrails_exit_code,
            failure_reason=_subject_checkout_failure_reason(execution_root, native_exit_code, guardrails_exit_code),
        )
    else:
        native_exit_code, guardrails_exit_code = _run_in_process_legs(
            execution_root,
            files,
            format_scoped,
            child_env,
            selection,
            content_root,
            platform_home_subject,
            check_families,
            full_run,
        )
        result = _build_in_process_result(subject_sha, execution_head, native_exit_code, guardrails_exit_code)
    _log_checkout_grading(execution_root, decision, selection, result)
    return result


def run_home_guardrail_gate(
    execution_root: Path,
    home_root: Path,
    selected_paths: list[str],
    tree_paths: list[str],
    child_env: Mapping[str, str] | None,
    *,
    check_families: frozenset[QualityCheckFamily] | None = None,
    content_root: Path | None = None,
    platform_home_subject: bool = False,
) -> LintGateResult | None:
    """Grade one home's changed and deletion-dependent files with its guardrails."""
    paths = set(selected_paths)
    paths.update(_home_validation_paths(tree_paths, home_root))
    ordered_paths = sorted(paths)
    if not ordered_paths:
        return None
    if check_families is None:
        validation_root = content_root if content_root is not None else execution_root
        home_permissions = resolve_tier_permissions(validation_root / home_root)
        check_families = select_quality_check_families(
            home_permissions.project_subscriptions,
            home_permissions,
        )
    if not check_families:
        return None
    return run_lint_gate(
        execution_root,
        None,
        ordered_paths,
        False,
        child_env,
        selection=frozenset({QualityGateLeg.GUARDRAILS}),
        check_families=check_families,
        request_subject_checkout_grading=True,
        content_root=content_root,
        platform_home_subject=platform_home_subject,
    )


def _home_validation_paths(tree_paths: list[str], home_root: Path) -> set[str]:
    """Select the existing Markdown and agent-artifact candidate set for a home."""
    selected: set[str] = set()
    for relative_path in tree_paths:
        path = Path(relative_path)
        try:
            home_path = path.relative_to(home_root)
        except ValueError:
            continue
        if home_path.suffix == _MARKDOWN_SUFFIX or AGENT_ARTIFACT_ROOT_DIRNAME in home_path.parts:
            selected.add(relative_path)
    return selected


def _run_in_process_legs(
    execution_root: Path,
    files: list[str] | None,
    format_scoped: bool,
    child_env: Mapping[str, str] | None,
    selection: frozenset[QualityGateLeg],
    content_root: Path | None = None,
    platform_home_subject: bool = False,
    check_families: frozenset[QualityCheckFamily] = frozenset(QualityCheckFamily),
    full_run: bool = False,
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
            LintRunner(
                project_root=execution_root,
                content_root=content_root,
                platform_home_subject=platform_home_subject,
                child_env=child_env,
                check_families=check_families,
            ).run(files=files, run_all=full_run or files is None)
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


def _subject_checkout_failure_reason(
    execution_root: Path,
    native_exit_code: int | None,
    guardrails_exit_code: int | None,
) -> str | None:
    reasons: list[str] = []
    native_reason = _lint_failure_reason(native_exit_code, None)
    if native_reason is not None:
        reasons.append(native_reason)
    if guardrails_exit_code not in (None, 0):
        reasons.append(
            _DELEGATED_GUARDRAILS_FAILURE_TEMPLATE.format(execution_root=execution_root, exit_code=guardrails_exit_code)
        )
    return _FAILURE_REASON_SEPARATOR.join(reasons) or None


def _log_checkout_grading(
    execution_root: Path,
    decision: CheckoutGradingDecision,
    selection: frozenset[QualityGateLeg],
    result: LintGateResult,
) -> None:
    logger.info(
        _QUALITY_GATE_CHECKOUT_GRADING_EVENT,
        execution_root=str(execution_root),
        code_root=str(REPO_ROOT),
        runner=decision.runner,
        reason=decision.reason,
        selection=sorted(selection),
        exit_code=result.exit_code,
        native_exit_code=result.native_exit_code,
        guardrails_exit_code=result.guardrails_exit_code,
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
        if target == _MAKE_LINT_TARGET:
            with full_native_slot(execution_root):
                return run_process_group_command(command, execution_root, child_env).exit_code
        return run_process_group_command(command, execution_root, child_env).exit_code
    with _nul_file(files) as files_from:
        command.append(_FILES_FROM_ARGUMENT_TEMPLATE.format(files_from=files_from))
        return run_process_group_command(command, execution_root, child_env).exit_code


def format_paths_for_commit_gate(repository_root: Path, relative_paths: list[str]) -> FormatGateOutcome:
    """Format each path set with the native leg selected for its grading home."""
    try:
        source = TreeSource.active_index(repository_root)
        grading_root: GradingRoot | None = resolve_repository_grading_root(repository_root, source)
        if grading_root is None:
            return FormatGateOutcome(
                failed_homes=(repository_root,),
                failure_reason=_ROOT_DECLARATION_MISSING,
            )
        selections = select_grading_homes(repository_root, relative_paths, source, grading_root)
        child_environment = hook_free_environment(repository_root)
    except _FORMAT_SELECTION_FAILURES as error:
        return FormatGateOutcome(
            failed_homes=(repository_root,),
            failure_reason=_FORMAT_SELECTION_FAILURE_TEMPLATE.format(error=error),
        )
    failed_homes: list[Path] = []
    formatted_paths: list[str] = []
    failure_reasons: list[str] = []
    for selection in selections:
        if QualityGateLeg.NATIVE not in selection.legs:
            continue
        formatted_paths.extend(selection.paths)
        try:
            exit_code = run_make_target(
                _MAKE_FORMAT_TARGET,
                selection.root,
                files=list(selection.paths),
                child_env=child_environment,
            )
        except OSError as error:
            failed_homes.append(selection.root)
            failure_reasons.append(_FORMAT_EXECUTION_FAILURE_TEMPLATE.format(home=selection.root, error=error))
            continue
        if exit_code != 0:
            failed_homes.append(selection.root)
    return FormatGateOutcome(
        tuple(failed_homes),
        tuple(formatted_paths),
        _FORMAT_FAILURE_SEPARATOR.join(failure_reasons) or None,
    )


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
    "FormatGateOutcome",
    "LintGateOutcome",
    "LintGateResult",
    "QualityCheckFamily",
    "QualityGateLeg",
    "format_paths_for_commit_gate",
    "read_head_sha",
    "run_lint_gate",
    "run_make_target",
    "select_quality_check_families",
    "select_quality_gate_legs",
]
