"""Tests for TelecApp bootstrap merge behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.screen import ModalScreen, Screen
from textual.widget import Widget

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


class _Timer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def _mount_bootstrap_widgets(
    app: TelecApp,
    *,
    current_project: ProjectWithTodosDTO,
    current_session: SessionDTO,
    availability: dict[str, AgentAvailabilityDTO] | None = None,
) -> None:
    widgets = {
        "#sessions-view": SimpleNamespace(
            _computers=[ComputerDTO(name="MozBook", status="online", user=None, host=None, is_local=True)],
            _projects=[
                ProjectDTO(
                    computer=current_project.computer,
                    name=current_project.name,
                    path=current_project.path,
                    description=current_project.description,
                )
            ],
            _sessions=[current_session],
            _availability=availability or {},
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

    _mount_bootstrap_widgets(
        app,
        current_project=current_project,
        current_session=current_session,
        availability=availability,
    )

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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_subset_refresh_does_not_clear_unrelated_pending_retry() -> None:
    """A successful computer-only refresh must not cancel a pending projects retry."""
    app = object.__new__(TelecApp)
    app._runtime_state = _AppRuntimeState()
    app._media_state = _AppMediaState()
    timers: list[_Timer] = []

    def set_timer(_delay: float, _callback: object) -> _Timer:
        timer = _Timer()
        timers.append(timer)
        return timer

    async def get_tui_bootstrap(_pillars: object) -> TuiBootstrapDTO:
        return TuiBootstrapDTO(
            requested=["computers"],
            data=TuiBootstrapDataDTO(
                computers=[ComputerDTO(name="MozBook", status="online", user=None, host=None, is_local=True)]
            ),
        )

    app.set_timer = set_timer
    app.api = SimpleNamespace(get_tui_bootstrap=get_tui_bootstrap)
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
    _mount_bootstrap_widgets(app, current_project=current_project, current_session=current_session)

    app._schedule_bootstrap_retry(["projects"])
    projects_timer = app._runtime_state.bootstrap_retry_timer

    await app._build_data_refresh_message(0.0, ["computers"])

    assert app._runtime_state.bootstrap_pending_pillars == {"projects"}
    assert app._runtime_state.bootstrap_retry_timer is projects_timer
    assert projects_timer is not None
    assert projects_timer.stopped is False


@pytest.mark.unit
def test_open_modal_makes_input_surface_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pushed popup counts as an input surface, so control-surface guards stand down."""
    app = object.__new__(TelecApp)
    modal = object.__new__(ModalScreen)
    monkeypatch.setattr(TelecApp, "screen", property(lambda _self: modal))
    monkeypatch.setattr(TelecApp, "focused", property(lambda _self: None))

    assert app._input_surface_active() is True


@pytest.mark.unit
def test_bare_control_surface_is_not_input_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """No popup and a non-input focus means bindings may fire — guard stays armed."""
    app = object.__new__(TelecApp)
    base_screen = object.__new__(Screen)
    monkeypatch.setattr(TelecApp, "screen", property(lambda _self: base_screen))
    monkeypatch.setattr(TelecApp, "focused", property(lambda _self: Widget()))

    assert app._input_surface_active() is False
