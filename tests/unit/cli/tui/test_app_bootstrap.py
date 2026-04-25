"""Tests for TelecApp bootstrap merge behavior."""

# guard: no-companion

from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.api_models import (
    AgentAvailabilityDTO,
    ComputerDTO,
    JobDTO,
    ProjectDTO,
    ProjectWithTodosDTO,
    SessionDTO,
    TuiBootstrapDataDTO,
    TuiBootstrapDTO,
    TuiBootstrapErrorDTO,
)
from teleclaude.cli.tui.app import TelecApp, _AppMediaState, _AppRuntimeState


@pytest.mark.unit
def test_merge_bootstrap_message_preserves_current_projects_when_project_pillar_fails() -> None:
    """A partial bootstrap response must merge successes without clearing failed pillars."""
    app = object.__new__(TelecApp)
    app._runtime_state = _AppRuntimeState()
    app._media_state = _AppMediaState()

    current_project = ProjectWithTodosDTO(
        computer="MozBook",
        name="app",
        path="/repo/app",
        description="Application",
        todos=[],
    )
    current_session = SessionDTO(
        session_id="sess-old",
        title="Old",
        status="active",
        computer="MozBook",
        project_path="/repo/app",
    )
    updated_session = current_session.model_copy(update={"title": "Updated"})
    availability = {
        "codex": AgentAvailabilityDTO(agent="codex", available=True, status="available"),
    }

    widgets = {
        "#sessions-view": SimpleNamespace(
            _computers=[ComputerDTO(name="MozBook", status="online", user=None, host=None, is_local=True)],
            _projects=[ProjectDTO(computer="MozBook", name="app", path="/repo/app", description="Application")],
            _sessions=[current_session],
            _availability=availability,
        ),
        "#preparation-view": SimpleNamespace(_projects_with_todos=[current_project]),
        "#jobs-view": SimpleNamespace(_jobs=[JobDTO(name="daily", type="agent", status="never")]),
        "#telec-footer": SimpleNamespace(
            tts_enabled=True,
            chiptunes_loaded=True,
            chiptunes_playback="playing",
            chiptunes_playing=True,
            chiptunes_track="theme",
            chiptunes_sid_path="/music/theme.sid",
            chiptunes_pending_command_id="",
            chiptunes_pending_action="",
        ),
    }
    app.query_one = lambda selector, *_args: widgets[selector]

    message = app._merge_bootstrap_message(
        TuiBootstrapDTO(
            requested=["projects", "sessions"],
            data=TuiBootstrapDataDTO(sessions=[updated_session]),
            errors=[TuiBootstrapErrorDTO(pillar="projects", message="temporary")],
        )
    )

    assert message.projects_with_todos == [current_project]
    assert message.projects == [ProjectDTO(computer="MozBook", name="app", path="/repo/app", description="Application")]
    assert message.sessions == [updated_session]
    assert message.tts_enabled is True
    assert message.chiptunes_playing is True
