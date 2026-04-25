"""Tests for TUI bootstrap merge/retry helpers."""

from __future__ import annotations

import pytest

from teleclaude.api_models import (
    ComputerDTO,
    ProjectDTO,
    ProjectWithTodosDTO,
    TuiBootstrapDataDTO,
    TuiBootstrapDTO,
    TuiBootstrapErrorDTO,
)
from teleclaude.cli.tui.bootstrap import (
    BootstrapRetryState,
    failed_bootstrap_pillars,
    projects_from_projects_with_todos,
)


@pytest.mark.unit
def test_failed_bootstrap_pillars_returns_only_requested_failed_or_missing_pillars() -> None:
    """A retry after partial success should ask only for unresolved requested data."""
    response = TuiBootstrapDTO(
        requested=["computers", "projects", "sessions"],
        data=TuiBootstrapDataDTO(
            computers=[ComputerDTO(name="MozBook", status="online", user=None, host=None, is_local=True)],
        ),
        errors=[TuiBootstrapErrorDTO(pillar="projects", message="temporary")],
    )

    assert failed_bootstrap_pillars(response, requested=["computers", "projects", "sessions"]) == [
        "projects",
        "sessions",
    ]


@pytest.mark.unit
def test_bootstrap_retry_state_backs_off_to_one_minute_and_resets() -> None:
    """Retry cadence should back off but keep trying at least once per minute."""
    state = BootstrapRetryState(initial_delay_s=1.0, max_delay_s=60.0)

    delays = [state.consume_delay() for _ in range(8)]

    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
    state.reset()
    assert state.consume_delay() == 1.0


@pytest.mark.unit
def test_projects_from_projects_with_todos_strips_todo_payload_for_sessions_view() -> None:
    """SessionsView should receive plain projects while PreparationView keeps todo details."""
    project = ProjectWithTodosDTO(
        computer="MozBook",
        name="app",
        path="/repo/app",
        description="Application",
        todos=[],
    )

    assert projects_from_projects_with_todos([project]) == [
        ProjectDTO(computer="MozBook", name="app", path="/repo/app", description="Application")
    ]
