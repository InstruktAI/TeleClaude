"""The degraded components the health answer shows a caller, within that caller's reach."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution
from teleclaude.api_models_health import DegradationDTO
from teleclaude.core.command_handlers._projects import registered_projects_by_path
from teleclaude.core.degradation import Degradation
from teleclaude.identity_reach import Reach, ReachResolutionError, resolve_reach

logger = get_logger(__name__)


def degradations_within_reach(
    snapshot: tuple[Degradation, ...], identity: CallerIdentity
) -> tuple[DegradationDTO, ...]:
    """Show each degradation the caller may see; a project-scoped one only where the caller's reach admits it.

    A project-scoped entry is a record about that project, so identity-owned admission decides whether it
    is shown at all (`local/projects/teleclaude/spec/feature/identity/data-visibility`): an entry the caller's
    reach does not admit is left out, indistinguishable from a project that serves. Platform-level components
    carry no project detail and are shown unchanged. Reads configuration and the project registry, so callers
    on a shared event loop run it on a worker thread.
    """
    shown = [DegradationDTO.from_degradation(entry) for entry in snapshot if not entry.component.project_scoped]
    project_entries = [entry for entry in snapshot if entry.component.project_scoped]
    if project_entries:
        reach = _reach_of(identity)
        projects = registered_projects_by_path() if reach is not None else {}
        for entry in project_entries:
            project = projects.get(entry.subject or "")
            if reach is not None and project is not None and reach.admits(project.subject, project.owner, None):
                shown.append(DegradationDTO.from_degradation(entry))
    return tuple(sorted(shown, key=lambda dto: dto.since))


def _reach_of(identity: CallerIdentity) -> Reach | None:
    """The caller's reach, or None when it cannot be resolved reliably: project entries are then left out."""
    try:
        return resolve_reach(caller_for_role_resolution(identity))
    except ReachResolutionError:
        logger.error("Health degradations withheld: the caller's reach could not be resolved", exc_info=True)
        return None
