"""Configuration view with settings forms."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Label


class ConfigView(Widget):
    """Configuration tab view.

    Displays settings in scrollable form layout.
    Settings are loaded from the API and saved via SettingsChanged messages.
    """

    DEFAULT_CSS = """
    ConfigView {
        width: 100%;
        height: 100%;
    }
    ConfigView VerticalScroll {
        width: 100%;
        height: 100%;
    }
    ConfigView Label {
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="config-scroll"):
            yield Label("Configuration", id="config-title")
            yield Label("Settings will be displayed here.", id="config-placeholder")

    def update_settings(self, settings: object) -> None:
        """Update view with current settings data.

        Full form implementation deferred to Phase 2 polish.
        """
        pass
