"""Unit tests for TUI app WebSocket event handling."""

from unittest.mock import MagicMock

import pytest

from teleclaude.cli.models import (
    ProjectsInitialData,
    ProjectsInitialEvent,
    ProjectWithTodosInfo,
    RefreshData,
    RefreshEvent,
    SessionInfo,
    SessionStartedEvent,
)
from teleclaude.cli.tui.app import TelecApp
from tests.conftest import MockAPIClient


def _make_app(api: MockAPIClient | None = None) -> TelecApp:
    """Create a TelecApp with a mock event loop so refresh_data executes."""
    app = TelecApp(api or MockAPIClient())
    loop = MagicMock()
    loop.run_until_complete = MagicMock(side_effect=lambda coro: coro.close())
    app._loop = loop
    return app


@pytest.mark.skip(
    reason="Tests reference pre-Textual curses API (views, _maybe_heal_ws, call_from_thread) — rewrite needed"
)
@pytest.mark.unit
class TestTelecAppWebSocketEvents:
    """Verify WebSocket event routing triggers refreshes."""

    def test_projects_initial_triggers_refresh(self):
        """projects_initial should trigger a refresh via _update_preparation_view."""
        app = _make_app()
        event = ProjectsInitialEvent(
            event="projects_initial",
            data=ProjectsInitialData(
                projects=[
                    ProjectWithTodosInfo(
                        computer="local",
                        name="TeleClaude",
                        path="/Users/Morriz/Workspace/InstruktAI/TeleClaude",
                        description=None,
                        todos=[],
                    )
                ],
                computer="local",
            ),
        )
        app._on_ws_event(event)
        app._process_ws_events()

        assert app._loop.run_until_complete.called

    def test_projects_updated_triggers_refresh(self):
        """projects_updated (unhandled type) should trigger a full refresh via else branch."""
        app = _make_app()
        event = RefreshEvent(event="projects_updated", data=RefreshData(computer="MozMini"))
        app._on_ws_event(event)
        app._process_ws_events()

        assert app._loop.run_until_complete.called

    def test_session_started_auto_selects_root_session(self, monkeypatch):
        """Root session_started events should auto-select newly started session."""
        app = _make_app()
        select_calls: list[tuple[str, str | None]] = []

        class DummySessionsView:
            def request_select_session(self, session_id: str, *, source: str | None = None) -> bool:
                select_calls.append((session_id, source))
                return True

        monkeypatch.setattr("teleclaude.cli.tui.app.SessionsView", DummySessionsView)
        app.views[1] = DummySessionsView()

        event = SessionStartedEvent(
            event="session_started",
            data=SessionInfo(
                session_id="sess-root",
                title="Root Session",
                status="active",
                tmux_session_name="tc_sess-root",
                initiator_session_id=None,
            ),
        )

        app._on_ws_event(event)
        app._process_ws_events()

        assert select_calls == [("sess-root", "system")]
        assert app._loop.run_until_complete.called

    def test_session_started_does_not_auto_select_ai_child(self, monkeypatch):
        """Child AI-to-AI session_started events should not hijack selection."""
        app = _make_app()
        select_calls: list[tuple[str, str | None]] = []

        class DummySessionsView:
            def request_select_session(self, session_id: str, *, source: str | None = None) -> bool:
                select_calls.append((session_id, source))
                return True

        monkeypatch.setattr("teleclaude.cli.tui.app.SessionsView", DummySessionsView)
        app.views[1] = DummySessionsView()

        event = SessionStartedEvent(
            event="session_started",
            data=SessionInfo(
                session_id="sess-child",
                title="Child Session",
                status="active",
                tmux_session_name="tc_sess-child",
                initiator_session_id="sess-parent",
            ),
        )

        app._on_ws_event(event)
        app._process_ws_events()

        assert select_calls == []
        assert app._loop.run_until_complete.called

    def test_ws_heal_refreshes_when_disconnected(self):
        """Disconnected WebSocket should trigger periodic refresh."""

        class DummyAPI(MockAPIClient):
            ws_connected = False

        app = _make_app(DummyAPI())
        app._last_ws_heal = 0.0
        refreshed = app._maybe_heal_ws(now=10.0)

        assert refreshed is True
        assert app._loop.run_until_complete.called

    def test_ws_heal_skips_when_connected(self):
        """Connected WebSocket should not trigger refresh."""

        class DummyAPI(MockAPIClient):
            ws_connected = True

        app = _make_app(DummyAPI())
        app._last_ws_heal = 0.0
        refreshed = app._maybe_heal_ws(now=10.0)

        assert refreshed is False
        assert not app._loop.run_until_complete.called

    def test_theme_drift_sets_refresh_request(self, monkeypatch):
        """Fallback probe should request refresh when mode drift is detected."""
        app = _make_app()
        app._last_theme_probe = 0.0
        monkeypatch.setattr("teleclaude.cli.tui.app.get_system_dark_mode", lambda: None)
        monkeypatch.setattr("teleclaude.cli.tui.app.get_current_mode", lambda: False)
        monkeypatch.setattr("teleclaude.cli.tui.app.is_dark_mode", lambda: True)

        app._poll_theme_drift(now=10.0)

        assert app._theme_refresh_requested is True

    def test_theme_drift_skips_when_probe_interval_not_elapsed(self, monkeypatch):
        """Probe should not run before interval elapses."""
        app = _make_app()
        app._last_theme_probe = 9.5
        monkeypatch.setattr("teleclaude.cli.tui.app.get_system_dark_mode", lambda: None)
        monkeypatch.setattr("teleclaude.cli.tui.app.get_current_mode", lambda: False)
        monkeypatch.setattr("teleclaude.cli.tui.app.is_dark_mode", lambda: True)

        app._poll_theme_drift(now=10.0)

        assert app._theme_refresh_requested is False

    def test_theme_drift_prefers_system_mode_probe(self, monkeypatch):
        """When available, drift probe should use system mode source first."""
        app = _make_app()
        app._last_theme_probe = 0.0
        monkeypatch.setattr("teleclaude.cli.tui.app.get_system_dark_mode", lambda: True)
        monkeypatch.setattr("teleclaude.cli.tui.app.get_current_mode", lambda: False)
        monkeypatch.setattr("teleclaude.cli.tui.app.is_dark_mode", lambda: False)

        app._poll_theme_drift(now=10.0)

        assert app._theme_refresh_requested is True
