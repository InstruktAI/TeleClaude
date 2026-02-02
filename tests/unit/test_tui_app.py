"""Unit tests for TUI app WebSocket event handling."""

from unittest.mock import MagicMock

import pytest

from teleclaude.cli.models import (
    ProjectsInitialData,
    ProjectsInitialEvent,
    ProjectWithTodosInfo,
    RefreshData,
    RefreshEvent,
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
