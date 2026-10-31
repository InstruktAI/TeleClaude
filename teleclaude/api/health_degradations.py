"""The degraded components the health answer shows a caller, within that caller's reach."""

from __future__ import annotations

from datetime import datetime

from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution
from teleclaude.api_models_health import DegradationDTO
from teleclaude.core import command_handlers
from teleclaude.core.degradation import Degradation, DegradedComponent
from teleclaude.identity_reach import Reach, ReachResolutionError, resolve_reach

logger = get_logger(__name__)

PROJECT_DETAIL_WITHHELD = (
    "one or more projects are not serving; the project and the cause are shown to a caller whose reach admits the"
    " project, and are in the daemon log"
)


def degradations_within_reach(
    snapshot: tuple[Degradation, ...], identity: CallerIdentity
) -> tuple[DegradationDTO, ...]:
    """Show each degradation to the caller, with project details only where the caller's reach admits the project.

    A project-scoped entry names a project's path and the cause of its refusal, which are records about that
    project (`local/projects/teleclaude/spec/feature/identity/data-visibility`). A caller whose reach does not
    admit a project still learns that the component is degraded, from one entry that names no project and no
    cause and stands for every project withheld. Platform-level components carry no project detail and are
    shown unchanged.
    """
    shown = [DegradationDTO.from_degradation(entry) for entry in snapshot if not entry.component.project_scoped]
    project_entries = [entry for entry in snapshot if entry.component.project_scoped]
    if project_entries:
        reach = _reach_of(identity)
        projects = command_handlers.registered_projects_by_path()
        withheld: dict[DegradedComponent, datetime] = {}
        for entry in project_entries:
            project = projects.get(entry.subject or "")
            if reach is not None and reach.admits(
                project.subject if project else None, project.owner if project else None, None
            ):
                shown.append(DegradationDTO.from_degradation(entry))
            else:
                withheld[entry.component] = min(entry.since, withheld.get(entry.component, entry.since))
        shown.extend(
            DegradationDTO(component=component, reason=PROJECT_DETAIL_WITHHELD, since=since)
            for component, since in withheld.items()
        )
    return tuple(sorted(shown, key=lambda dto: dto.since))


def _reach_of(identity: CallerIdentity) -> Reach | None:
    """The caller's reach, or None when it cannot be resolved reliably: project details are then withheld."""
    try:
        return resolve_reach(caller_for_role_resolution(identity))
    except ReachResolutionError:
        logger.error("Health degradations withheld: the caller's reach could not be resolved", exc_info=True)
        return None
