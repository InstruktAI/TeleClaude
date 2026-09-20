"""Converge a repository root's installed TeleClaude plumbing to its declaration."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import resolve_capabilities
from teleclaude.checkpoint_model import load_checkpoint_model
from teleclaude.git import GitCommandError
from teleclaude.project_manifest import load_registered_roots
from teleclaude.project_setup.git_filters import GitFilterDisposition, ensure_git_filters
from teleclaude.project_setup.hooks import HookConvergenceOutcome, install_code_hooks

logger = get_logger(__name__)

_ROOT_FINISHED_EVENT = "plumbing_convergence_root_finished"
_RUN_STARTED_EVENT = "plumbing_convergence_run_started"
_RUN_FINISHED_EVENT = "plumbing_convergence_run_finished"
_REGISTRY_READ_FAILED_EVENT = "plumbing_convergence_registry_read_failed"
_ROOT_OPERATIONAL_FAILURE_EVENT = "plumbing_convergence_root_operational_failure"
_ROOT_ARGUMENT_REQUIRED = "A project root is required."
_HOOK_RESULT = "{hook_name}: {outcome}"
_FILTER_RESULT = "filter-driver: {disposition}"
_ROOT_RESULT = "{project_root}: {outcome}"


class PlumbingConvergenceOutcome(StrEnum):
    """Closed terminal outcomes for one root's plumbing convergence."""

    CONVERGED = "converged"
    UNCHANGED = "unchanged"
    NOT_ADOPTED = "not_adopted"
    TEMPLATE_MISSING = "template_missing"
    DECLARATION_ERROR = "declaration_error"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class PlumbingConvergenceRunOutcome(StrEnum):
    """Closed terminal outcomes for one registered-root convergence run."""

    COMPLETED = "completed"
    FAILED = "failed"


class PlumbingOperationalFailure(Exception):
    """A filesystem or Git failure while converging one adopted root."""


@dataclass(frozen=True)
class PlumbingConvergenceResult:
    """The observed outcome of converging one registered repository root."""

    project_root: Path
    outcome: PlumbingConvergenceOutcome
    hook_results: dict[str, HookConvergenceOutcome]
    filter_disposition: GitFilterDisposition | None


@dataclass(frozen=True)
class PlumbingConvergenceRunResult:
    """The terminal summary for convergence across every registered root."""

    run_id: str
    root_count: int
    results: tuple[PlumbingConvergenceResult, ...]
    outcome: PlumbingConvergenceRunOutcome


_FAILED_ROOT_OUTCOMES = frozenset(
    {
        PlumbingConvergenceOutcome.DECLARATION_ERROR,
        PlumbingConvergenceOutcome.FAILED,
        PlumbingConvergenceOutcome.TEMPLATE_MISSING,
    },
)


def _has_executable_maintenance(project_root: Path) -> bool:
    """Return whether the root's effective bindings resolve a maintenance action."""
    model = load_checkpoint_model(str(project_root))
    return any(action_id in model.maintenance for binding in model.bindings for action_id in binding.actions)


def _record_root_result(
    result: PlumbingConvergenceResult,
    *,
    run_id: str | None,
) -> PlumbingConvergenceResult:
    """Emit the one terminal observation record for a root convergence attempt."""
    logger.info(
        _ROOT_FINISHED_EVENT,
        project_root=str(result.project_root),
        run_id=run_id,
        outcome=result.outcome,
        hook_results=result.hook_results,
        filter_disposition=result.filter_disposition,
    )
    return result


def converge_plumbing(project_root: Path, *, run_id: str | None = None) -> PlumbingConvergenceResult:
    """Converge one adopted root's hooks and docs filter driver."""
    try:
        capabilities = resolve_capabilities(project_root)
    except ValueError:
        return _record_root_result(
            PlumbingConvergenceResult(
                project_root=project_root,
                outcome=PlumbingConvergenceOutcome.DECLARATION_ERROR,
                hook_results={},
                filter_disposition=None,
            ),
            run_id=run_id,
        )

    if not capabilities.is_target:
        return _record_root_result(
            PlumbingConvergenceResult(
                project_root=project_root,
                outcome=PlumbingConvergenceOutcome.NOT_ADOPTED,
                hook_results={},
                filter_disposition=None,
            ),
            run_id=run_id,
        )

    try:
        filter_disposition = ensure_git_filters(project_root, enabled=capabilities.docs)
        hook_results = install_code_hooks(project_root) if _has_executable_maintenance(project_root) else {}
    except (GitCommandError, OSError) as exc:
        raise PlumbingOperationalFailure from exc
    outcome = (
        PlumbingConvergenceOutcome.TEMPLATE_MISSING
        if HookConvergenceOutcome.TEMPLATE_MISSING in hook_results.values()
        else PlumbingConvergenceOutcome.CONVERGED
        if HookConvergenceOutcome.WRITTEN in hook_results.values()
        else PlumbingConvergenceOutcome.UNCHANGED
    )
    return _record_root_result(
        PlumbingConvergenceResult(
            project_root=project_root,
            outcome=outcome,
            hook_results=hook_results,
            filter_disposition=filter_disposition,
        ),
        run_id=run_id,
    )


def _failed_root_result(project_root: Path, *, run_id: str) -> PlumbingConvergenceResult:
    """Record an unexpected present-root failure without ending the fleet run."""
    return _record_root_result(
        PlumbingConvergenceResult(
            project_root=project_root,
            outcome=PlumbingConvergenceOutcome.FAILED,
            hook_results={},
            filter_disposition=None,
        ),
        run_id=run_id,
    )


def _unavailable_root_result(project_root: Path, *, run_id: str) -> PlumbingConvergenceResult:
    """Record a registry root that is unavailable on this machine."""
    return _record_root_result(
        PlumbingConvergenceResult(
            project_root=project_root,
            outcome=PlumbingConvergenceOutcome.UNAVAILABLE,
            hook_results={},
            filter_disposition=None,
        ),
        run_id=run_id,
    )


def _run_outcome(results: tuple[PlumbingConvergenceResult, ...]) -> PlumbingConvergenceRunOutcome:
    """Derive the run result after every registered root reaches a terminal state."""
    if any(result.outcome in _FAILED_ROOT_OUTCOMES for result in results):
        return PlumbingConvergenceRunOutcome.FAILED
    return PlumbingConvergenceRunOutcome.COMPLETED


def _record_run_result(result: PlumbingConvergenceRunResult) -> PlumbingConvergenceRunResult:
    """Emit the one terminal observation record for a registered-root run."""
    unavailable_roots = [
        str(item.project_root) for item in result.results if item.outcome is PlumbingConvergenceOutcome.UNAVAILABLE
    ]
    not_adopted_roots = [
        str(item.project_root) for item in result.results if item.outcome is PlumbingConvergenceOutcome.NOT_ADOPTED
    ]
    failed_roots = [str(item.project_root) for item in result.results if item.outcome in _FAILED_ROOT_OUTCOMES]
    logger.info(
        _RUN_FINISHED_EVENT,
        run_id=result.run_id,
        root_count=result.root_count,
        outcome=result.outcome,
        converged_count=sum(item.outcome is PlumbingConvergenceOutcome.CONVERGED for item in result.results),
        unchanged_count=sum(item.outcome is PlumbingConvergenceOutcome.UNCHANGED for item in result.results),
        unavailable_roots=unavailable_roots,
        not_adopted_roots=not_adopted_roots,
        failed_roots=failed_roots,
    )
    return result


def converge_registered_roots() -> PlumbingConvergenceRunResult:
    """Converge plumbing for every root in the machine-local project registry."""
    run_id = uuid4().hex
    try:
        registered_roots = load_registered_roots(strict=True)
    except RuntimeError:
        logger.exception(_REGISTRY_READ_FAILED_EVENT, run_id=run_id, root_count=0)
        logger.info(_RUN_STARTED_EVENT, run_id=run_id, root_count=0)
        return _record_run_result(
            PlumbingConvergenceRunResult(
                run_id=run_id,
                root_count=0,
                results=(),
                outcome=PlumbingConvergenceRunOutcome.FAILED,
            ),
        )

    logger.info(_RUN_STARTED_EVENT, run_id=run_id, root_count=len(registered_roots))
    results: list[PlumbingConvergenceResult] = []
    for registered_root in registered_roots:
        if not registered_root.is_present:
            results.append(_unavailable_root_result(registered_root.path, run_id=run_id))
            continue
        try:
            results.append(converge_plumbing(registered_root.path, run_id=run_id))
        except PlumbingOperationalFailure:
            logger.exception(
                _ROOT_OPERATIONAL_FAILURE_EVENT,
                project_root=str(registered_root.path),
                run_id=run_id,
            )
            results.append(_failed_root_result(registered_root.path, run_id=run_id))

    terminal_results = tuple(results)
    return _record_run_result(
        PlumbingConvergenceRunResult(
            run_id=run_id,
            root_count=len(registered_roots),
            results=terminal_results,
            outcome=_run_outcome(terminal_results),
        ),
    )


def main() -> None:
    """Run single-root convergence for installation carriers."""
    if len(sys.argv) != 2:
        raise SystemExit(_ROOT_ARGUMENT_REQUIRED)
    result = converge_plumbing(Path(sys.argv[1]))
    for hook_name, outcome in result.hook_results.items():
        print(_HOOK_RESULT.format(hook_name=hook_name, outcome=outcome))
    if result.filter_disposition is not None:
        print(_FILTER_RESULT.format(disposition=result.filter_disposition))
    print(_ROOT_RESULT.format(project_root=result.project_root, outcome=result.outcome))
    if result.outcome in _FAILED_ROOT_OUTCOMES:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
