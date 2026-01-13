"""Unit tests for TUI app WebSocket event handling."""

import pytest

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

            async def refresh_data(self) -> None:
                self.refresh_called = True

        app = DummyApp(MockAPIClient())
        app._on_ws_event("projects_initial", {"projects": []})
        app._process_ws_events()

        assert app.refresh_called is True

    def test_projects_updated_triggers_refresh(self):
        """projects_updated should trigger a refresh."""

        class DummyApp(TelecApp):
            def __init__(self, api):
                super().__init__(api)
                self.refresh_called = False

            async def refresh_data(self) -> None:
                self.refresh_called = True

        app = DummyApp(MockAPIClient())
        app._on_ws_event("projects_updated", {"computer": "MozMini", "projects": []})
        app._process_ws_events()

        assert app.refresh_called is True
