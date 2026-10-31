"""Converge a repository root's installed TeleClaude plumbing to its declaration."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import resolve_capabilities
from teleclaude.checkpoint_model import load_checkpoint_model
from teleclaude.config.context_root import load_declared_config_kind
from teleclaude.config.loader import load_declared_project_config
from teleclaude.config.schema import ConfigKind
from teleclaude.core.reconciliation.config_schemas import (
    SchemaCopyDisposition,
    SchemaLinkDisposition,
    converge_project_schema_link,
    remove_stray_schema_copy,
)
from teleclaude.core.reconciliation.home_convergence import TemplateTargets, home_output_targets, project_targets
from teleclaude.core.reconciliation.template_installation import (
    HomeTemplateDisposition,
    HomeTemplateMaterializationConflict,
    HomeTemplateOutcome,
    InvalidTemplateEncodingError,
    UnresolvedPlaceholderError,
    apply_template_installation,
    plan_template_installation,
)
from teleclaude.git import GitCommandError
from teleclaude.logging_config import setup_logging
from teleclaude.paths import TELECLAUDE_HOME, ConfigFileName
from teleclaude.project_manifest import load_registered_roots
from teleclaude.project_setup.git_filters import GitFilterDisposition, ensure_git_filters
from teleclaude.project_setup.hooks import HookConvergenceOutcome, install_code_hooks
from teleclaude.runtime.config import require_own_checkout

logger = get_logger(__name__)

_ROOT_FINISHED_EVENT = "plumbing_convergence_root_finished"
_RUN_STARTED_EVENT = "plumbing_convergence_run_started"
_RUN_FINISHED_EVENT = "plumbing_convergence_run_finished"
_REGISTRY_READ_FAILED_EVENT = "plumbing_convergence_registry_read_failed"
_ROOT_OPERATIONAL_FAILURE_EVENT = "plumbing_convergence_root_operational_failure"
_ROOT_ARGUMENT_REQUIRED = "A project root is required."
_PLUMBING_ONLY_FLAG = "--plumbing-only"
_HOOK_RESULT = "{hook_name}: {outcome}"
_FILTER_RESULT = "filter-driver: {disposition}"
_OUTPUT_RESULT = "{path}: {disposition}"
_ROOT_RESULT = "{project_root}: {outcome} (schema-link: {schema_link}, schema-copy: {schema_copy})"
_RUN_RESULT = "Plumbing convergence {outcome}: {root_count} root(s)."


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
    schema_link: SchemaLinkDisposition | None = None
    schema_copy: SchemaCopyDisposition | None = None
    output_results: tuple[HomeTemplateOutcome, ...] = ()


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
        schema_link=result.schema_link,
        schema_copy=result.schema_copy,
        output_dispositions={str(item.target): item.disposition for item in result.output_results},
    )
    return result


def converge_plumbing(project_root: Path, *, run_id: str | None = None) -> PlumbingConvergenceResult:
    """Converge one adopted root's hooks, docs filter driver and schema link."""
    return _record_root_result(_converge_machine_plumbing(project_root), run_id=run_id)


def _converge_machine_plumbing(project_root: Path) -> PlumbingConvergenceResult:
    """Compare one root's installed plumbing against its declaration and close the gap."""
    require_own_checkout(project_root)
    try:
        capabilities = resolve_capabilities(project_root)
    except ValueError:
        return PlumbingConvergenceResult(
            project_root=project_root,
            outcome=PlumbingConvergenceOutcome.DECLARATION_ERROR,
            hook_results={},
            filter_disposition=None,
        )

    if not capabilities.is_target:
        return PlumbingConvergenceResult(
            project_root=project_root,
            outcome=PlumbingConvergenceOutcome.NOT_ADOPTED,
            hook_results={},
            filter_disposition=None,
        )

    try:
        filter_disposition = ensure_git_filters(project_root, enabled=capabilities.docs)
        hook_results = install_code_hooks(project_root) if _has_executable_maintenance(project_root) else {}
        schema_link = converge_project_schema_link(project_root)
        schema_copy = remove_stray_schema_copy(project_root)
    except (GitCommandError, OSError) as exc:
        raise PlumbingOperationalFailure from exc
    outcome = (
        PlumbingConvergenceOutcome.TEMPLATE_MISSING
        if HookConvergenceOutcome.TEMPLATE_MISSING in hook_results.values()
        else PlumbingConvergenceOutcome.CONVERGED
        if (
            HookConvergenceOutcome.WRITTEN in hook_results.values()
            or schema_link.disposition in (SchemaLinkDisposition.CREATED, SchemaLinkDisposition.REPOINTED)
            or schema_copy is SchemaCopyDisposition.REMOVED
        )
        else PlumbingConvergenceOutcome.UNCHANGED
    )
    return PlumbingConvergenceResult(
        project_root=project_root,
        outcome=outcome,
        hook_results=hook_results,
        filter_disposition=filter_disposition,
        schema_link=schema_link.disposition,
        schema_copy=schema_copy,
    )


def _declared_kind(root: Path) -> ConfigKind | None:
    """The tier a root's declaration names, or ``None`` when the root declares nothing."""
    marker = root / ConfigFileName.OVERLAY
    return load_declared_config_kind(marker) if marker.is_file() else None


def _deployment_output_targets(root: Path) -> TemplateTargets:
    """The masters a root's declaration owes: a project's enabled help desk, the tier homes' masters and desks."""
    kind = _declared_kind(root)
    if kind is ConfigKind.GLOBAL:
        return home_output_targets(root)
    if kind is ConfigKind.PROJECT:
        config = load_declared_project_config(root)
        if config is not None and config.help_desk.enabled:
            return project_targets(root, docs=False, help_desk=True)
    return ()


def _render_deployment_output(root: Path, targets: TemplateTargets) -> tuple[HomeTemplateOutcome, ...]:
    """Seed the targets' masters from their templates; an existing master is never rewritten."""
    plan = plan_template_installation(targets, values={}, environ=os.environ)  # fmt: skip  # guard: direct-env-read - allowed: configuration loading or interpolation
    return apply_template_installation(plan)


def _with_output(
    result: PlumbingConvergenceResult, outputs: tuple[HomeTemplateOutcome, ...]
) -> PlumbingConvergenceResult:
    """Fold a root's deployment output into its plumbing outcome; a failure outcome is never softened."""
    if result.outcome in _FAILED_ROOT_OUTCOMES:
        return replace(result, output_results=outputs)
    written = any(item.disposition is HomeTemplateDisposition.WRITTEN for item in outputs)
    converged = written or result.outcome is PlumbingConvergenceOutcome.CONVERGED
    outcome = PlumbingConvergenceOutcome.CONVERGED if converged else PlumbingConvergenceOutcome.UNCHANGED
    return replace(result, outcome=outcome, output_results=outputs)


def converge_root(project_root: Path, *, run_id: str | None = None) -> PlumbingConvergenceResult:
    """Converge one root's plumbing, then seed the masters its declaration owes.

    An existing master is left as it is; neither it nor a disabled desk's
    folder fails the root.
    """
    result = _converge_machine_plumbing(project_root)
    if result.outcome is PlumbingConvergenceOutcome.DECLARATION_ERROR:
        return _record_root_result(result, run_id=run_id)
    try:
        targets = _deployment_output_targets(project_root)
    except ValueError:
        return _record_root_result(replace(result, outcome=PlumbingConvergenceOutcome.DECLARATION_ERROR), run_id=run_id)
    if not targets:
        return _record_root_result(result, run_id=run_id)
    try:
        outputs = _render_deployment_output(project_root, targets)
    except (
        HomeTemplateMaterializationConflict,
        InvalidTemplateEncodingError,
        OSError,
        UnresolvedPlaceholderError,
    ) as exc:
        raise PlumbingOperationalFailure from exc
    return _record_root_result(_with_output(result, outputs), run_id=run_id)


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
        retained_schema_copy_roots=[
            str(item.project_root)
            for item in result.results
            if item.schema_copy in (SchemaCopyDisposition.RETAINED_TRACKED, SchemaCopyDisposition.RETAINED_FOREIGN)
        ],
        occupied_schema_link_roots=[
            str(item.project_root) for item in result.results if item.schema_link is SchemaLinkDisposition.OCCUPIED
        ],
    )
    return result


def _converge_fleet_root(root: Path, *, run_id: str) -> PlumbingConvergenceResult:
    """Converge one present root in a fleet run, recording an operational failure without ending the run."""
    require_own_checkout(root)
    try:
        return converge_root(root, run_id=run_id)
    except PlumbingOperationalFailure:
        logger.exception(_ROOT_OPERATIONAL_FAILURE_EVENT, project_root=str(root), run_id=run_id)
        return _failed_root_result(root, run_id=run_id)


def converge_registered_roots(home: Path = TELECLAUDE_HOME) -> PlumbingConvergenceRunResult:
    """Converge every root in the machine-local project registry, then the platform home's deployment output."""
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

    roots = [registered_root.path for registered_root in registered_roots]
    if _declared_kind(home) is ConfigKind.GLOBAL:
        roots.append(home)
    logger.info(_RUN_STARTED_EVENT, run_id=run_id, root_count=len(roots))
    results: list[PlumbingConvergenceResult] = []
    for registered_root in registered_roots:
        if not registered_root.is_present:
            results.append(_unavailable_root_result(registered_root.path, run_id=run_id))
            continue
        results.append(_converge_fleet_root(registered_root.path, run_id=run_id))
    if home in roots:
        results.append(_converge_fleet_root(home, run_id=run_id))

    terminal_results = tuple(results)
    return _record_run_result(
        PlumbingConvergenceRunResult(
            run_id=run_id,
            root_count=len(roots),
            results=terminal_results,
            outcome=_run_outcome(terminal_results),
        ),
    )


def _print_output_results(result: PlumbingConvergenceResult) -> None:
    """Report each deployment output a root's convergence wrote."""
    for output in result.output_results:
        if output.disposition is HomeTemplateDisposition.WRITTEN:
            print(_OUTPUT_RESULT.format(path=output.target, disposition=output.disposition))


def _print_root_line(result: PlumbingConvergenceResult) -> None:
    """Report one root's terminal outcome."""
    print(
        _ROOT_RESULT.format(
            project_root=result.project_root,
            outcome=result.outcome,
            schema_link=result.schema_link,
            schema_copy=result.schema_copy,
        ),
    )


def run_fleet_convergence() -> int:
    """Converge every registered root and the platform home, report each outcome, and answer the exit code."""
    run_result = converge_registered_roots()
    for root_result in run_result.results:
        _print_output_results(root_result)
        _print_root_line(root_result)
    print(_RUN_RESULT.format(outcome=run_result.outcome, root_count=run_result.root_count))
    return 1 if run_result.outcome is PlumbingConvergenceRunOutcome.FAILED else 0


def main() -> None:
    """Run fleet convergence, or one-root convergence for installers and maintenance.

    A root argument runs the whole act; ``--plumbing-only <root>`` runs the
    machine plumbing alone, for installers that render no deployment output.
    """
    setup_logging()
    arguments = sys.argv[1:]
    plumbing_only = arguments[:1] == [_PLUMBING_ONLY_FLAG]
    if plumbing_only:
        arguments = arguments[1:]
    if not arguments and not plumbing_only:
        exit_code = run_fleet_convergence()
        if exit_code:
            raise SystemExit(exit_code)
        return
    if len(arguments) != 1:
        raise SystemExit(_ROOT_ARGUMENT_REQUIRED)
    root = Path(arguments[0]).resolve()
    result = converge_plumbing(root) if plumbing_only else converge_root(root)
    for hook_name, outcome in result.hook_results.items():
        print(_HOOK_RESULT.format(hook_name=hook_name, outcome=outcome))
    if result.filter_disposition is not None:
        print(_FILTER_RESULT.format(disposition=result.filter_disposition))
    _print_output_results(result)
    _print_root_line(result)
    if result.outcome in _FAILED_ROOT_OUTCOMES:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
