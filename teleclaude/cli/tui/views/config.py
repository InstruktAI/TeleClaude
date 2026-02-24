"""Configuration view with sub-tabs for adapters, people, environment, and validation."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.config_handlers import EnvVarStatus, ValidationResult
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR
from teleclaude.config.schema import PersonEntry

_SUBTABS = ("adapters", "people", "notifications", "environment", "validate")
_ADAPTER_TABS = ("telegram", "discord", "ai_keys", "whatsapp")

# Styles
_NORMAL = Style(color="#d0d0d0")
_DIM = Style(color="#727578")
_OK = Style(color="#5faf5f")
_FAIL = Style(color="#d75f5f")
_SEP = Style(color=CONNECTOR_COLOR)
_TAB_ACTIVE = Style(bold=True, reverse=True)
_TAB_INACTIVE = Style(color="#808080")


class ConfigView(Widget, can_focus=True):
    """Configuration tab with sub-tabs matching old TUI layout.

    Sub-tabs: Adapters | People | Notifications | Environment | Validate
    Adapters has further sub-tabs: Telegram | Discord | AI Keys | WhatsApp
    """

    DEFAULT_CSS = """
    ConfigView {
        width: 100%;
        height: 1fr;
    }
    ConfigView VerticalScroll {
        width: 100%;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("v", "run_validation", "Validate"),
        Binding("r", "refresh_config", "Refresh", key_display="↻"),
        Binding("tab", "next_subtab", "Tab", key_display="⇥", group=Binding.Group("Tabs", compact=True)),
        Binding("shift+tab", "prev_subtab", "Back", key_display="⇤", group=Binding.Group("Tabs", compact=True)),
        Binding(
            "left",
            "prev_adapter_tab",
            "Prev",
            key_display="←",
            group=Binding.Group("Adapters", compact=True),
            show=False,
        ),
        Binding(
            "right",
            "next_adapter_tab",
            "Next",
            key_display="→",
            group=Binding.Group("Adapters", compact=True),
            show=False,
        ),
    ]

    active_subtab = reactive(0)
    active_adapter_tab = reactive(0)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("next_adapter_tab", "prev_adapter_tab"):
            return self.active_subtab == 0
        return True

    def watch_active_subtab(self, value: int) -> None:
        self._sync_content()
        if self.is_attached:
            self.app.refresh_bindings()

    def watch_active_adapter_tab(self, value: int) -> None:
        self._sync_content()
        if self.is_attached:
            self.app.refresh_bindings()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="config-scroll"):
            yield ConfigContent(id="config-content")

    def on_mount(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        content = self.query_one("#config-content", ConfigContent)
        content.refresh_data()

    def _sync_content(self) -> None:
        content = self.query_one("#config-content", ConfigContent)
        content.active_subtab = self.active_subtab
        content.active_adapter_tab = self.active_adapter_tab

    def action_run_validation(self) -> None:
        self.active_subtab = 4  # Switch to validate tab
        content = self.query_one("#config-content", ConfigContent)
        content.active_subtab = 4
        content.run_validation()

    def action_refresh_config(self) -> None:
        self._refresh_content()

    def action_next_subtab(self) -> None:
        self.active_subtab = (self.active_subtab + 1) % len(_SUBTABS)
        self._sync_content()

    def action_prev_subtab(self) -> None:
        self.active_subtab = (self.active_subtab - 1) % len(_SUBTABS)
        self._sync_content()

    def action_next_adapter_tab(self) -> None:
        if self.active_subtab == 0:
            self.active_adapter_tab = (self.active_adapter_tab + 1) % len(_ADAPTER_TABS)
            self._sync_content()

    def action_prev_adapter_tab(self) -> None:
        if self.active_subtab == 0:
            self.active_adapter_tab = (self.active_adapter_tab - 1) % len(_ADAPTER_TABS)
            self._sync_content()


class ConfigContent(TelecMixin, Widget):
    """Renders configuration sections as styled text with sub-tab navigation."""

    DEFAULT_CSS = """
    ConfigContent {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    active_subtab = reactive(0, layout=True)
    active_adapter_tab = reactive(0, layout=True)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._env_data: list[EnvVarStatus] = []
        self._env_by_adapter: dict[str, list[EnvVarStatus]] = {}
        self._people_data: list[PersonEntry] = []
        self._validation_results: list[ValidationResult] = []

    def refresh_data(self) -> None:
        from teleclaude.cli.config_handlers import check_env_vars, list_people

        try:
            self._env_data = check_env_vars()
            self._env_by_adapter = {}
            for status in self._env_data:
                adapter = status.info.adapter
                if adapter not in self._env_by_adapter:
                    self._env_by_adapter[adapter] = []
                self._env_by_adapter[adapter].append(status)
        except Exception:
            self._env_data = []
            self._env_by_adapter = {}
        try:
            self._people_data = list_people()
        except Exception:
            self._people_data = []
        self.refresh(layout=True)

    def run_validation(self) -> None:
        from teleclaude.cli.config_handlers import validate_all

        try:
            self._validation_results = validate_all()
        except Exception:
            self._validation_results = []
        self.refresh(layout=True)

    def _render_tab_bar(self, result: Text, tabs: tuple[str, ...], active: int) -> None:
        """Render a horizontal tab bar."""
        for i, tab in enumerate(tabs):
            style = _TAB_ACTIVE if i == active else _TAB_INACTIVE
            result.append(f" {tab} ", style=style)
            if i < len(tabs) - 1:
                result.append(" ", style=_DIM)
        result.append("\n")

    def _render_adapters(self, result: Text) -> None:
        """Render adapter sub-tabs with env var details."""
        # Adapter sub-tab bar
        result.append("\n")
        self._render_tab_bar(result, _ADAPTER_TABS, self.active_adapter_tab)
        result.append("\n")

        adapter_name = _ADAPTER_TABS[self.active_adapter_tab]
        statuses = self._env_by_adapter.get(adapter_name, [])

        if not statuses:
            # Check for vars using alternative names
            alt_names = {"ai_keys": "ai", "whatsapp": "whatsapp"}
            alt = alt_names.get(adapter_name, adapter_name)
            statuses = self._env_by_adapter.get(alt, [])

        if not statuses:
            result.append(f"  No environment variables registered for {adapter_name}\n", style=_DIM)
            return

        for status in statuses:
            if status.is_set:
                result.append("  \u2714 ", style=_OK)
            else:
                result.append("  \u2718 ", style=_FAIL)
            result.append(f"{status.info.name}", style=_NORMAL)
            result.append(f"  {status.info.description}\n", style=_DIM)
            if status.info.example:
                result.append(f"      Example: {status.info.example}\n", style=_DIM)

    def _render_people(self, result: Text) -> None:
        result.append("\n")
        if self._people_data:
            for person in self._people_data:
                result.append(f"  {person.name}", style=_NORMAL)
                result.append(f" ({person.role})", style=_DIM)
                email = getattr(person, "email", None)
                if email:
                    result.append(f" <{email}>", style=_DIM)
                result.append("\n")
        else:
            result.append("  (No people configured)\n", style=_DIM)

    def _render_notifications(self, result: Text) -> None:
        result.append("\n")
        result.append("  (Not implemented yet)\n", style=_DIM)

    def _render_environment(self, result: Text) -> None:
        result.append("\n")
        for status in self._env_data:
            if status.is_set:
                result.append("  \u2714 ", style=_OK)
            else:
                result.append("  \u2718 ", style=_FAIL)
            result.append(f"{status.info.name}", style=_NORMAL)
            result.append(f" ({status.info.adapter})\n", style=_DIM)

        if not self._env_data:
            result.append("  (Could not load env vars)\n", style=_DIM)

    def _render_validate(self, result: Text) -> None:
        result.append("\n")
        if self._validation_results:
            passed = sum(1 for v in self._validation_results if v.passed)
            total = len(self._validation_results)
            summary_style = _OK if passed == total else _FAIL
            result.append(f"  {passed}/{total} checks passed\n\n", style=summary_style)

            for vr in self._validation_results:
                if vr.passed:
                    result.append("  \u2714 ", style=_OK)
                else:
                    result.append("  \u2718 ", style=_FAIL)
                result.append(f"{vr.area}\n", style=_NORMAL)
                for err in vr.errors:
                    result.append(f"      Error: {err}\n", style=_FAIL)
                for sug in vr.suggestions:
                    result.append(f"      Tip: {sug}\n", style=_DIM)
        else:
            result.append("  Press 'v' to run validation\n", style=_DIM)

    def render(self) -> Text:
        result = Text()

        # Main sub-tab bar
        self._render_tab_bar(result, _SUBTABS, self.active_subtab)
        result.append("-" * 60 + "\n", style=_SEP)

        # Render active sub-tab content
        tab = _SUBTABS[self.active_subtab]
        if tab == "adapters":
            self._render_adapters(result)
        elif tab == "people":
            self._render_people(result)
        elif tab == "notifications":
            self._render_notifications(result)
        elif tab == "environment":
            self._render_environment(result)
        elif tab == "validate":
            self._render_validate(result)

        return result

    def watch_active_subtab(self, _value: int) -> None:
        self.refresh(layout=True)

    def watch_active_adapter_tab(self, _value: int) -> None:
        self.refresh(layout=True)
