"""Current outcome and opaque checkpoint storage for scheduled jobs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Final

from jobs.base import JobResult
from teleclaude.file_transaction import FileTransaction, file_transaction
from teleclaude.paths import JOB_RUNS_DIR, safe_path_component

_INVALID_COMPONENT_ERROR = "Job result identity is not a safe path component"
_PATH_ESCAPE_ERROR = "Job result path resolves outside the state directory"
_JOB_RESULT_SUFFIX: Final[str] = ".json"
_JOB_RESULT_TERMINATOR: Final[str] = "\n"


def job_result_path(project_slug: str, job_name: str, *, root: Path = JOB_RUNS_DIR) -> Path:
    """Resolve the stable current-record path for one project and job."""
    if safe_path_component(project_slug) != project_slug or safe_path_component(job_name) != job_name:
        raise ValueError(_INVALID_COMPONENT_ERROR)
    resolved_root = root.resolve(strict=False)
    record_path = (resolved_root / project_slug / f"{job_name}{_JOB_RESULT_SUFFIX}").resolve(strict=False)
    try:
        record_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(_PATH_ESCAPE_ERROR) from exc
    return record_path


@contextmanager
def job_result_transaction(project_slug: str, job_name: str, *, root: Path = JOB_RUNS_DIR) -> Iterator[FileTransaction]:
    """Lock one job identity across report acceptance and record replacement."""
    path = job_result_path(project_slug, job_name, root=root)
    with file_transaction(path) as transaction:
        yield transaction


def load_job_result_in_transaction(transaction: FileTransaction) -> JobResult | None:
    """Read one current record while its lifecycle lock is held."""
    content = transaction.read_text()
    return JobResult.from_json(content) if content else None


def write_job_result(
    project_slug: str,
    job_name: str,
    result: JobResult,
    *,
    execution_session_id: str | None,
    root: Path = JOB_RUNS_DIR,
) -> Path:
    """Atomically replace the current outcome and apply its checkpoint decision."""
    with job_result_transaction(project_slug, job_name, root=root) as transaction:
        return write_job_result_in_transaction(
            transaction,
            result,
            execution_session_id=execution_session_id,
        )


def write_job_result_in_transaction(
    transaction: FileTransaction,
    result: JobResult,
    *,
    execution_session_id: str | None,
) -> Path:
    """Replace a current record while the caller holds its lifecycle lock."""
    previous = load_job_result_in_transaction(transaction)
    state = result.state
    if state is None and previous is not None:
        state = previous.state
    accepted = replace(result, session_id=execution_session_id, state=state)
    transaction.replace_text(accepted.to_json() + _JOB_RESULT_TERMINATOR)
    return transaction.path
