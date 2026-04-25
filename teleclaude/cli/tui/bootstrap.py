"""Helpers for TUI bootstrap retries and partial-state merging."""

from __future__ import annotations

from dataclasses import dataclass

from teleclaude.api_models import ProjectDTO, ProjectWithTodosDTO, TuiBootstrapDTO, TuiBootstrapPillar

BOOTSTRAP_PILLARS: tuple[TuiBootstrapPillar, ...] = (
    "computers",
    "projects",
    "sessions",
    "availability",
    "jobs",
    "settings",
    "chiptunes",
)
BOOTSTRAP_INITIAL_RETRY_DELAY_S = 1.0
BOOTSTRAP_MAX_RETRY_DELAY_S = 60.0

_PILLAR_FIELDS: dict[TuiBootstrapPillar, str] = {
    "computers": "computers",
    "projects": "projects_with_todos",
    "sessions": "sessions",
    "availability": "availability",
    "jobs": "jobs",
    "settings": "settings",
    "chiptunes": "chiptunes",
}


@dataclass
class BootstrapRetryState:
    """Stateful exponential backoff for missing bootstrap pillars."""

    initial_delay_s: float = BOOTSTRAP_INITIAL_RETRY_DELAY_S
    max_delay_s: float = BOOTSTRAP_MAX_RETRY_DELAY_S
    next_delay_s: float | None = None

    def consume_delay(self) -> float:
        """Return the current delay and advance to the next capped delay."""
        delay = self.next_delay_s if self.next_delay_s is not None else self.initial_delay_s
        self.next_delay_s = min(delay * 2, self.max_delay_s)
        return delay

    def reset(self) -> None:
        """Reset backoff after a complete bootstrap."""
        self.next_delay_s = None


def projects_from_projects_with_todos(projects: list[ProjectWithTodosDTO]) -> list[ProjectDTO]:
    """Return plain project DTOs for SessionsView."""
    return [
        ProjectDTO(
            computer=project.computer,
            name=project.name,
            path=project.path,
            description=project.description,
        )
        for project in projects
    ]


def failed_bootstrap_pillars(
    response: TuiBootstrapDTO,
    *,
    requested: list[TuiBootstrapPillar] | tuple[TuiBootstrapPillar, ...],
) -> list[TuiBootstrapPillar]:
    """Return requested pillars that should be retried."""
    failed = {error.pillar for error in response.errors if error.retryable}
    missing = {pillar for pillar in requested if getattr(response.data, _PILLAR_FIELDS[pillar]) is None}
    return [pillar for pillar in requested if pillar in failed or pillar in missing]
