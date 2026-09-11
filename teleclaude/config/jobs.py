"""Configuration-owned composition of published and project-local jobs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from teleclaude.config.loader import load_global_config, load_project_config
from teleclaude.config.schema import JobScheduleConfig, is_agent_job, job_identity
from teleclaude.context_selector import resolve_snippet_meta
from teleclaude.paths import GLOBAL_CONFIG_PATH, ConfigFileName

_WHEN_FIELD: Final = "when"
_AGENT_FIELD: Final = "agent"
_ENABLED_FIELD: Final = "enabled"


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


def load_effective_jobs(project_root: Path) -> tuple[EffectiveJob, ...]:
    """Return the validated local and subscribed declarations for one project."""
    target_root = project_root.expanduser().resolve()
    published_root = GLOBAL_CONFIG_PATH.parent
    published = load_global_config().jobs
    local = load_project_config(target_root / ConfigFileName.OVERLAY).jobs
    local_pointers = {_execution_pointer(declaration) for declaration in local}
    published_by_pointer = _index_by_pointer(
        declaration for declaration in published if _execution_pointer(declaration) in local_pointers
    )
    effective: list[EffectiveJob] = []
    for declaration in local:
        pointer = _execution_pointer(declaration)
        inherited = published_by_pointer.get(pointer)
        resolved = _overlay(inherited, declaration) if inherited else declaration
        _validate_complete(resolved, target_root)
        if not resolved.enabled:
            continue
        origin_root = published_root if inherited else target_root
        effective.append(
            EffectiveJob(
                identity=job_identity(pointer, resolved),
                declaration=resolved,
                origin=JobOrigin(root=origin_root, published=inherited is not None),
            )
        )
    _reject_identity_collisions(effective)
    return tuple(effective)


def _index_by_pointer(declarations: Iterable[JobScheduleConfig]) -> dict[str, JobScheduleConfig]:
    indexed: dict[str, JobScheduleConfig] = {}
    for declaration in declarations:
        pointer = _execution_pointer(declaration)
        if pointer in indexed:
            raise ValueError(f"duplicate published job execution pointer: {pointer}")
        indexed[pointer] = declaration
    return indexed


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
        raise ValueError(f"job declaration {_execution_pointer(declaration)} requires when")
    if is_agent_job(declaration):
        if not declaration.agent:
            raise ValueError(f"agent job {_execution_pointer(declaration)} requires candidates")
        metadata = resolve_snippet_meta(_execution_pointer(declaration), project_root=project_root)
        if metadata is None:
            raise ValueError(f"agent job names unknown procedure: {_execution_pointer(declaration)}")
        if metadata.snippet_type != "procedure":
            raise ValueError(f"agent job must name a procedure: {_execution_pointer(declaration)}")
        if metadata.delivered_by:
            raise ValueError(f"agent job names a pending procedure: {_execution_pointer(declaration)}")


def _reject_identity_collisions(jobs: list[EffectiveJob]) -> None:
    identities: dict[str, EffectiveJob] = {}
    for effective in jobs:
        prior = identities.get(effective.identity)
        if prior is not None and _execution_pointer(prior.declaration) != _execution_pointer(effective.declaration):
            raise ValueError(f"effective job identity collision: {effective.identity}")
        identities[effective.identity] = effective
