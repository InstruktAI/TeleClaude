"""Configuration-owned composition of published and project-local jobs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, TypedDict, cast

from teleclaude.config.job_scope import JobScope
from teleclaude.config.loader import load_declared_project_config, load_global_config
from teleclaude.config.schema import JobScheduleConfig, is_agent_job
from teleclaude.context_selector import resolve_snippet_meta
from teleclaude.paths import GLOBAL_CONFIG_PATH

_WHEN_FIELD: Final = "when"
_AGENT_FIELD: Final = "agent"
_ENABLED_FIELD: Final = "enabled"
_NAME_FIELD: Final = "name"
_UNPUBLISHED_SUBSCRIPTION_ERROR: Final = "job '{name}' is not published"
_LOCAL_JOB_POINTER_ERROR: Final = "local job '{name}' requires exactly one execution pointer"
_SUBSCRIPTION_POINTER_ERROR: Final = "job '{name}' subscription cannot change its published execution pointer"
_JOB_WHEN_ERROR: Final = "job '{name}' requires when"
_AGENT_CANDIDATES_ERROR: Final = "agent job '{name}' requires candidates"
_UNKNOWN_PROCEDURE_ERROR: Final = "agent job '{name}' names unknown procedure: {pointer}"
_NON_PROCEDURE_ERROR: Final = "agent job '{name}' must name a procedure: {pointer}"
_PENDING_PROCEDURE_ERROR: Final = "agent job '{name}' names a pending procedure: {pointer}"


@dataclass(frozen=True)
class JobOrigin:
    """The configuration root that owns a job declaration's execution target."""

    root: Path
    published: bool


@dataclass(frozen=True)
class EffectiveJob:
    """One enabled, complete job ready for a project's runner pass."""

    identity: str
    declaration: JobScheduleConfig
    origin: JobOrigin


@dataclass(frozen=True)
class VisibleJob:
    """One job a project can see, with its relationship to that project."""

    name: str
    scope: JobScope
    declaration: JobScheduleConfig


class SubscriptionChange(StrEnum):
    """The result of changing one project's subscription to a published job."""

    SUBSCRIBED = "subscribed"
    ACTIVATED = "activated"
    DEACTIVATED = "deactivated"
    UNCHANGED = "unchanged"
    NOT_SUBSCRIBED = "not_subscribed"


class RawJobEntry(TypedDict, total=False):
    """One raw jobs-array entry preserved for the config resource engine."""

    name: str
    category: object
    enabled: bool
    when: object
    script: object
    job: object
    agent: object
    thinking_mode: object
    timeout: object


@dataclass(frozen=True)
class SubscriptionPlan:
    """The subscription outcome and optional replacement jobs array."""

    change: SubscriptionChange
    jobs: tuple[RawJobEntry, ...] | None = None


def load_effective_jobs(project_root: Path) -> tuple[EffectiveJob, ...]:
    """Return the validated local and subscribed declarations for one project."""
    target_root = project_root.expanduser().resolve()
    published_root = GLOBAL_CONFIG_PATH.parent
    published = load_global_config().jobs
    declared_project = load_declared_project_config(target_root)
    local = declared_project.jobs if declared_project is not None else []
    published_by_name = _index_by_name(published)
    effective: list[EffectiveJob] = []
    for declaration in local:
        inherited = published_by_name.get(declaration.name)
        if inherited is not None:
            if _has_execution_pointer(declaration) and (
                _execution_pointer(declaration) != _execution_pointer(inherited)
            ):
                raise ValueError(_SUBSCRIPTION_POINTER_ERROR.format(name=declaration.name))
            resolved = _overlay(inherited, declaration)
        else:
            if not _has_exactly_one_execution_pointer(declaration):
                raise ValueError(_LOCAL_JOB_POINTER_ERROR.format(name=declaration.name))
            resolved = declaration
        _validate_complete(resolved, target_root)
        if not resolved.enabled:
            continue
        origin_root = published_root if inherited else target_root
        effective.append(
            EffectiveJob(
                identity=resolved.name,
                declaration=resolved,
                origin=JobOrigin(root=origin_root, published=inherited is not None),
            )
        )
    return tuple(effective)


def load_visible_jobs(project_root: Path) -> tuple[VisibleJob, ...]:
    """Return effective project jobs followed by published jobs not subscribed to."""
    effective = load_effective_jobs(project_root)
    visible = [
        VisibleJob(
            name=job.identity,
            scope=JobScope.SUBSCRIBED if job.origin.published else JobScope.LOCAL,
            declaration=job.declaration,
        )
        for job in effective
    ]
    effective_names = {job.name for job in visible}
    visible.extend(
        VisibleJob(name=declaration.name, scope=JobScope.AVAILABLE, declaration=declaration)
        for declaration in load_global_config().jobs
        if declaration.name not in effective_names
    )
    return tuple(visible)


def plan_job_subscription(
    jobs: Sequence[Mapping[str, object]],
    published: Sequence[JobScheduleConfig],
    name: str,
    enabled: bool,
) -> SubscriptionPlan:
    """Plan a published-job subscription change without mutating either input."""
    if not any(declaration.name == name for declaration in published):
        raise ValueError(_UNPUBLISHED_SUBSCRIPTION_ERROR.format(name=name))

    copied_jobs = [cast(RawJobEntry, dict(entry)) for entry in jobs]
    entry_index = next(
        (index for index, entry in enumerate(copied_jobs) if entry.get(_NAME_FIELD) == name),
        None,
    )
    if entry_index is None:
        if not enabled:
            return SubscriptionPlan(SubscriptionChange.NOT_SUBSCRIBED)
        copied_jobs.append({_NAME_FIELD: name})
        return SubscriptionPlan(SubscriptionChange.SUBSCRIBED, tuple(copied_jobs))

    current_entry = copied_jobs[entry_index]
    currently_enabled = current_entry.get(_ENABLED_FIELD, True) is not False
    if currently_enabled is enabled:
        return SubscriptionPlan(SubscriptionChange.UNCHANGED)

    updated_entry = cast(RawJobEntry, dict(current_entry))
    updated_entry[_ENABLED_FIELD] = enabled
    copied_jobs[entry_index] = updated_entry
    change = SubscriptionChange.ACTIVATED if enabled else SubscriptionChange.DEACTIVATED
    return SubscriptionPlan(change, tuple(copied_jobs))


def _index_by_name(declarations: Iterable[JobScheduleConfig]) -> dict[str, JobScheduleConfig]:
    indexed: dict[str, JobScheduleConfig] = {}
    for declaration in declarations:
        indexed[declaration.name] = declaration
    return indexed


def _has_execution_pointer(declaration: JobScheduleConfig) -> bool:
    return any(pointer and pointer.strip() for pointer in (declaration.script, declaration.job))


def _has_exactly_one_execution_pointer(declaration: JobScheduleConfig) -> bool:
    return sum(bool(pointer and pointer.strip()) for pointer in (declaration.script, declaration.job)) == 1


def _execution_pointer(declaration: JobScheduleConfig) -> str:
    pointer = declaration.job if is_agent_job(declaration) else declaration.script
    if pointer is None:
        raise ValueError("job declaration has no execution pointer")
    return pointer.strip()


def _overlay(base: JobScheduleConfig, override: JobScheduleConfig) -> JobScheduleConfig:
    updates = {field: getattr(override, field) for field in override.model_fields_set if field not in {"job", "script"}}
    return base.model_copy(update=updates)


def _validate_complete(declaration: JobScheduleConfig, project_root: Path) -> None:
    if not declaration.enabled:
        return
    if _WHEN_FIELD not in declaration.model_fields_set or declaration.when is None:
        raise ValueError(_JOB_WHEN_ERROR.format(name=declaration.name))
    if is_agent_job(declaration):
        if not declaration.agent:
            raise ValueError(_AGENT_CANDIDATES_ERROR.format(name=declaration.name))
        pointer = _execution_pointer(declaration)
        metadata = resolve_snippet_meta(pointer, project_root=project_root)
        if metadata is None:
            raise ValueError(_UNKNOWN_PROCEDURE_ERROR.format(name=declaration.name, pointer=pointer))
        if metadata.snippet_type != "procedure":
            raise ValueError(_NON_PROCEDURE_ERROR.format(name=declaration.name, pointer=pointer))
        if metadata.delivered_by:
            raise ValueError(_PENDING_PROCEDURE_ERROR.format(name=declaration.name, pointer=pointer))
