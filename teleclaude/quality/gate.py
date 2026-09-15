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
from teleclaude.quality.lint import LintRunner
from teleclaude.runtime.command_runner import run_process_group_command

logger = get_logger(__name__)

_SUBJECT_MISMATCH_TEMPLATE = "Quality gate refused to evaluate {subject_sha}: execution root HEAD is {execution_head}."
_HEAD_READ_FAILURES = (BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError)


class LintGateOutcome(StrEnum):
    """Closed result states for a native lint gate invocation."""

    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class LintGateResult:
    """The subject and independent exit statuses observed by one lint gate."""

    outcome: LintGateOutcome
    subject_sha: str
    execution_head: str | None
    native_exit_code: int | None
    guardrails_exit_code: int | None
    failure_reason: str | None = None

    @property
    def exit_code(self) -> int:
        """Return the existing CLI precedence: guardrails before native lint."""
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
        logger.error("quality_gate_subject_unavailable root=%s error=%s", execution_root, exc)
        return None


def run_lint_gate(
    project_root: Path,
    execution_root: Path,
    subject_sha: str,
    files: list[str] | None,
    format_scoped: bool,
    child_env: Mapping[str, str] | None,
) -> LintGateResult:
    """Run native lint and guardrails against the exact committed subject."""
    execution_head = read_head_sha(execution_root)
    if execution_head != subject_sha:
        return LintGateResult(
            outcome=LintGateOutcome.FAILED,
            subject_sha=subject_sha,
            execution_head=execution_head,
            native_exit_code=None,
            guardrails_exit_code=None,
            failure_reason=_SUBJECT_MISMATCH_TEMPLATE.format(subject_sha=subject_sha, execution_head=execution_head),
        )

    if format_scoped and files is not None:
        run_make_target("format", execution_root, files=files, child_env=child_env)

    native_exit_code = run_make_target("lint", execution_root, files=files, child_env=child_env)
    guardrails_exit_code = 0
    try:
        LintRunner(project_root=execution_root).run(files=files, run_all=files is None)
    except SystemExit as exc:
        guardrails_exit_code = _system_exit_code(exc)

    outcome = LintGateOutcome.PASSED if native_exit_code == 0 and guardrails_exit_code == 0 else LintGateOutcome.FAILED
    return LintGateResult(
        outcome=outcome,
        subject_sha=subject_sha,
        execution_head=execution_head,
        native_exit_code=native_exit_code,
        guardrails_exit_code=guardrails_exit_code,
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
    command = ["make", target]
    if variables:
        command.extend(f"{key}={value}" for key, value in variables.items())
    if files is None:
        return run_process_group_command(command, execution_root, child_env).exit_code
    with _nul_file(files) as files_from:
        command.append(f"FILES_FROM={files_from}")
        return run_process_group_command(command, execution_root, child_env).exit_code


@contextmanager
def _nul_file(files: list[str]) -> Iterator[str]:
    handle = tempfile.NamedTemporaryFile(delete=False)
    try:
        with handle:
            handle.write(b"".join(path.encode("utf-8") + b"\0" for path in files))
        yield handle.name
    finally:
        Path(handle.name).unlink(missing_ok=True)


def _system_exit_code(exc: SystemExit) -> int:
    return exc.code if isinstance(exc.code, int) else 1


__all__ = ["LintGateOutcome", "LintGateResult", "read_head_sha", "run_lint_gate", "run_make_target"]
