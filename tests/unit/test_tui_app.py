"""Unit tests for TUI app WebSocket event handling."""

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


@pytest.mark.unit
class TestTelecAppWebSocketEvents:
    """Verify WebSocket event routing triggers refreshes."""

    def test_projects_initial_triggers_refresh(self):
        """projects_initial should trigger a refresh."""

        class DummyApp(TelecApp):
            def __init__(self, api):
                super().__init__(api)
                self.refresh_called = False

            async def refresh_data(self, *, include_todos: bool | None = None) -> None:
                self.refresh_called = True

        app = DummyApp(MockAPIClient())
        event = ProjectsInitialEvent(
            event="projects_initial",
            data=ProjectsInitialData(
                projects=[
                    ProjectWithTodosInfo(
                        computer="local",
                        name="TeleClaude",
                        path="/Users/Morriz/Documents/Workspace/InstruktAI/TeleClaude",
                        description=None,
                        todos=[],
                    )
                ],
                computer="local",
            ),
        )
        app._on_ws_event(event)
        app._process_ws_events()

        assert app.refresh_called is True

    def test_projects_updated_triggers_refresh(self):
        """projects_updated should trigger a refresh."""

        class DummyApp(TelecApp):
            def __init__(self, api):
                super().__init__(api)
                self.refresh_called = False

            async def refresh_data(self, *, include_todos: bool | None = None) -> None:
                self.refresh_called = True

        app = DummyApp(MockAPIClient())
        event = RefreshEvent(event="projects_updated", data=RefreshData(computer="MozMini"))
        app._on_ws_event(event)
        app._process_ws_events()

        assert app.refresh_called is True

    def test_ws_heal_refreshes_when_disconnected(self):
        """Disconnected WebSocket should trigger periodic refresh."""

        class DummyAPI(MockAPIClient):
            ws_connected = False

        class DummyApp(TelecApp):
            def __init__(self, api):
                super().__init__(api)
                self.refresh_called = False

            async def refresh_data(self, *, include_todos: bool | None = None) -> None:
                self.refresh_called = True

        app = DummyApp(DummyAPI())
        app._last_ws_heal = 0.0
        refreshed = app._maybe_heal_ws(now=10.0)

        assert refreshed is True
        assert app.refresh_called is True

    def test_ws_heal_skips_when_connected(self):
        """Connected WebSocket should not trigger refresh."""

        class DummyAPI(MockAPIClient):
            ws_connected = True

        class DummyApp(TelecApp):
            def __init__(self, api):
                super().__init__(api)
                self.refresh_called = False

            async def refresh_data(self, *, include_todos: bool | None = None) -> None:
                self.refresh_called = True

        app = DummyApp(DummyAPI())
        app._last_ws_heal = 0.0
        refreshed = app._maybe_heal_ws(now=10.0)

        assert refreshed is False
        assert app.refresh_called is False
