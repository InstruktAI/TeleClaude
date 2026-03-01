"""Interactive configuration view with guided setup and inline env editing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.events import Key
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.config_handlers import EnvVarStatus, ValidationResult, get_person_config, set_env_var
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.config_components.guidance import get_guidance_for_env
from teleclaude.cli.tui.theme import CONNECTOR_COLOR
from teleclaude.config.schema import PersonEntry

_SUBTABS = ("adapters", "people", "notifications", "environment", "validate")
_ADAPTER_TABS = ("telegram", "discord", "ai_keys", "whatsapp")
_ADAPTER_LABELS = {
    "telegram": "Telegram",
    "discord": "Discord",
    "ai_keys": "AI + Voice",
    "whatsapp": "WhatsApp",
}
_ADAPTER_ENV_KEYS = {
    "telegram": ("telegram",),
    "discord": ("discord",),
    "ai_keys": ("ai", "voice"),
    "whatsapp": ("whatsapp",),
}

# Styles
_NORMAL = Style(color="#d0d0d0")
_DIM = Style(color="#727578")
_OK = Style(color="#5faf5f")
_FAIL = Style(color="#d75f5f")
_WARN = Style(color="#d7af5f")
_INFO = Style(color="#87afd7")
_SEP = Style(color=CONNECTOR_COLOR)
_TAB_ACTIVE = Style(bold=True, reverse=True)
_TAB_INACTIVE = Style(color="#808080")

AdapterStatus = Literal["configured", "partial", "unconfigured"]


@dataclass(frozen=True)
class AdapterSectionProjection:
    """Computed adapter section state for rendering and guided flow."""

    key: str
    label: str
    env_statuses: list[EnvVarStatus]
    status: AdapterStatus
    configured_count: int
    total_count: int


@dataclass(frozen=True)
class NotificationProjection:
    """Summary of notification setup state."""

    configured: bool
    total_people: int
    people_with_subscriptions: int
    total_subscriptions: int
    next_action: str


@dataclass(frozen=True)
class GuidedStep:
    """Deterministic guided mode step."""

    subtab: str
    title: str
    adapter_tab: str | None = None


_GUIDED_STEPS: tuple[GuidedStep, ...] = (
    GuidedStep(subtab="adapters", adapter_tab="telegram", title="Configure Telegram"),
    GuidedStep(subtab="adapters", adapter_tab="discord", title="Configure Discord"),
    GuidedStep(subtab="adapters", adapter_tab="ai_keys", title="Configure AI + Voice"),
    GuidedStep(subtab="adapters", adapter_tab="whatsapp", title="Configure WhatsApp"),
    GuidedStep(subtab="people", title="Review People"),
    GuidedStep(subtab="notifications", title="Review Notifications"),
    GuidedStep(subtab="environment", title="Review Environment"),
    GuidedStep(subtab="validate", title="Run Validation"),
)


def classify_adapter_status(env_statuses: list[EnvVarStatus]) -> AdapterStatus:
    """Classify adapter setup status from env var state."""
    if not env_statuses:
        return "unconfigured"
    configured_count = sum(1 for status in env_statuses if status.is_set)
    if configured_count == 0:
        return "unconfigured"
    if configured_count == len(env_statuses):
        return "configured"
    return "partial"


def project_adapter_sections(env_data: list[EnvVarStatus]) -> list[AdapterSectionProjection]:
    """Build adapter section projections for the configured tab set."""
    sections: list[AdapterSectionProjection] = []
    for key in _ADAPTER_TABS:
        adapter_keys = _ADAPTER_ENV_KEYS[key]
        statuses = [status for status in env_data if status.info.adapter in adapter_keys]
        configured_count = sum(1 for status in statuses if status.is_set)
        sections.append(
            AdapterSectionProjection(
                key=key,
                label=_ADAPTER_LABELS.get(key, key),
                env_statuses=statuses,
                status=classify_adapter_status(statuses),
                configured_count=configured_count,
                total_count=len(statuses),
            )
        )
    return sections


def completion_summary(
    adapter_sections: list[AdapterSectionProjection],
    *,
    has_people: bool,
    notifications_configured: bool,
    environment_configured: bool,
) -> tuple[int, int]:
    """Return configured/total summary across adapter and core sections."""
    configured = sum(1 for section in adapter_sections if section.status == "configured")
    configured += int(has_people)
    configured += int(notifications_configured)
    configured += int(environment_configured)
    total = len(adapter_sections) + 3
    return configured, total


class ConfigView(Widget, can_focus=True):
    """Configuration tab with guided setup and inline edit behavior."""

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
        Binding("up", "cursor_up", "Up", key_display="↑", group=Binding.Group("Nav", compact=True), show=False),
        Binding("down", "cursor_down", "Down", key_display="↓", group=Binding.Group("Nav", compact=True), show=False),
        Binding("enter", "activate", "Select/Edit", key_display="↵"),
        Binding("escape", "cancel", "Cancel", key_display="Esc"),
        Binding("g", "toggle_guided_mode", "Guided"),
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

    def _content_or_none(self) -> ConfigContent | None:
        if not self.is_attached:
            return None
        try:
            return self.query_one("#config-content", ConfigContent)
        except Exception:
            return None

    def _sync_from_content(self) -> None:
        content = self._content_or_none()
        if content is None:
            return
        self.active_subtab = content.active_subtab
        self.active_adapter_tab = content.active_adapter_tab

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        content = self._content_or_none()
        if (
            content is not None
            and content.guided_mode
            and action
            in (
                "next_subtab",
                "prev_subtab",
                "next_adapter_tab",
                "prev_adapter_tab",
            )
        ):
            return False
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

    def on_key(self, event: Key) -> None:
        content = self._content_or_none()
        if content is None or not content.is_editing:
            return

        if event.key == "backspace":
            content.backspace_edit()
            event.stop()
            return
        if event.key == "ctrl+u":
            content.clear_edit_buffer()
            event.stop()
            return
        if event.character and event.is_printable:
            content.append_edit_character(event.character)
            event.stop()

    def _refresh_content(self) -> None:
        content = self.query_one("#config-content", ConfigContent)
        content.refresh_data()

    def _sync_content(self) -> None:
        content = self.query_one("#config-content", ConfigContent)
        content.active_subtab = self.active_subtab
        content.active_adapter_tab = self.active_adapter_tab

    def action_run_validation(self) -> None:
        self.active_subtab = 4
        content = self.query_one("#config-content", ConfigContent)
        content.active_subtab = 4
        content.run_validation()

    def action_refresh_config(self) -> None:
        self._refresh_content()

    def action_cursor_up(self) -> None:
        content = self.query_one("#config-content", ConfigContent)
        content.move_cursor(-1)

    def action_cursor_down(self) -> None:
        content = self.query_one("#config-content", ConfigContent)
        content.move_cursor(1)

    def action_activate(self) -> None:
        content = self.query_one("#config-content", ConfigContent)
        content.activate_current()
        self._sync_from_content()

    def action_cancel(self) -> None:
        content = self.query_one("#config-content", ConfigContent)
        if content.is_editing:
            content.cancel_edit()
        elif content.guided_mode:
            content.toggle_guided_mode()
            self._sync_from_content()

    def action_toggle_guided_mode(self) -> None:
        content = self.query_one("#config-content", ConfigContent)
        content.toggle_guided_mode()
        self._sync_from_content()

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
    """Renders guided config sections with inline env editing."""

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
        self._people_data: list[PersonEntry] = []
        self._validation_results: list[ValidationResult] = []
        self._adapter_sections: list[AdapterSectionProjection] = []
        self._notification_projection = NotificationProjection(
            configured=False,
            total_people=0,
            people_with_subscriptions=0,
            total_subscriptions=0,
            next_action="Add a person first, then configure subscriptions.",
        )
        self._cursor_by_context: dict[str, int] = {}
        self._editing_var_name: str | None = None
        self._edit_buffer = ""
        self._status_message = ""
        self._status_is_error = False
        self._guided_mode = False
        self._guided_step_index = 0

    @property
    def guided_mode(self) -> bool:
        return self._guided_mode

    @property
    def is_editing(self) -> bool:
        return self._editing_var_name is not None

    def refresh_data(self) -> None:
        from teleclaude.cli.config_handlers import check_env_vars, list_people

        try:
            self._env_data = check_env_vars()
        except Exception as exc:
            self._env_data = []
            self._status_message = f"Failed to load env vars: {exc}"
            self._status_is_error = True

        self._adapter_sections = project_adapter_sections(self._env_data)

        try:
            self._people_data = list_people()
        except Exception as exc:
            self._people_data = []
            self._status_message = f"Failed to load people: {exc}"
            self._status_is_error = True

        self._notification_projection = self._build_notification_projection()
        self._clamp_current_cursor()

        if self._guided_mode:
            self._apply_guided_step()
            self._auto_advance_completed_steps()

        self.refresh(layout=True)

    def run_validation(self) -> None:
        from teleclaude.cli.config_handlers import validate_all

        try:
            self._validation_results = validate_all()
            passed = sum(1 for result in self._validation_results if result.passed)
            self._status_message = f"Validation complete: {passed}/{len(self._validation_results)} checks passed"
            self._status_is_error = passed != len(self._validation_results)
        except Exception as exc:
            self._validation_results = []
            self._status_message = f"Validation failed: {exc}"
            self._status_is_error = True
        self.refresh(layout=True)

    def _build_notification_projection(self) -> NotificationProjection:
        if not self._people_data:
            return NotificationProjection(
                configured=False,
                total_people=0,
                people_with_subscriptions=0,
                total_subscriptions=0,
                next_action="Run: telec config people add --name <name> --email <email>",
            )

        people_with_subscriptions = 0
        total_subscriptions = 0
        for person in self._people_data:
            try:
                person_config = get_person_config(person.name)
            except Exception:
                continue
            count = len(person_config.subscriptions)
            if count > 0:
                people_with_subscriptions += 1
                total_subscriptions += count

        configured = total_subscriptions > 0
        if configured:
            next_action = "Use telec config validate after changing subscription settings."
        else:
            next_action = "Add subscriptions under ~/.teleclaude/people/<name>/teleclaude.yml"

        return NotificationProjection(
            configured=configured,
            total_people=len(self._people_data),
            people_with_subscriptions=people_with_subscriptions,
            total_subscriptions=total_subscriptions,
            next_action=next_action,
        )

    def _current_context_key(self) -> str:
        tab = _SUBTABS[self.active_subtab]
        if tab == "adapters":
            return f"adapter:{_ADAPTER_TABS[self.active_adapter_tab]}"
        return tab

    def _get_active_adapter_section(self) -> AdapterSectionProjection | None:
        if not self._adapter_sections:
            return None
        idx = max(0, min(self.active_adapter_tab, len(self._adapter_sections) - 1))
        return self._adapter_sections[idx]

    def _selectable_env_rows(self) -> list[EnvVarStatus]:
        tab = _SUBTABS[self.active_subtab]
        if tab == "adapters":
            section = self._get_active_adapter_section()
            if section is None:
                return []
            return section.env_statuses
        if tab == "environment":
            return self._env_data
        return []

    def _current_cursor(self) -> int:
        return self._cursor_by_context.get(self._current_context_key(), 0)

    def _set_current_cursor(self, index: int) -> None:
        self._cursor_by_context[self._current_context_key()] = index

    def _clamp_current_cursor(self) -> None:
        rows = self._selectable_env_rows()
        if not rows:
            self._set_current_cursor(0)
            return
        cursor = self._current_cursor()
        self._set_current_cursor(max(0, min(cursor, len(rows) - 1)))

    def _current_selected_env(self) -> EnvVarStatus | None:
        rows = self._selectable_env_rows()
        if not rows:
            return None
        cursor = self._current_cursor()
        if cursor < 0 or cursor >= len(rows):
            return None
        return rows[cursor]

    def move_cursor(self, delta: int) -> None:
        if self.is_editing:
            return
        rows = self._selectable_env_rows()
        if not rows:
            return
        next_cursor = max(0, min(self._current_cursor() + delta, len(rows) - 1))
        self._set_current_cursor(next_cursor)
        self.refresh(layout=True)

    def activate_current(self) -> None:
        if self.is_editing:
            self.save_edit()
            return

        if self._guided_mode:
            step = _GUIDED_STEPS[self._guided_step_index]
            if step.subtab in ("adapters", "environment"):
                selected = self._current_selected_env()
                if selected is not None and not selected.is_set:
                    self._begin_edit(selected)
                    return
            if step.subtab == "validate":
                self.run_validation()
                if self._is_current_guided_step_complete():
                    self._advance_guided_step()
                return
            self._advance_guided_step()
            return

        tab = _SUBTABS[self.active_subtab]
        if tab == "validate":
            self.run_validation()
            return

        selected = self._current_selected_env()
        if selected is not None:
            self._begin_edit(selected)

    def _begin_edit(self, status: EnvVarStatus) -> None:
        self._editing_var_name = status.info.name
        self._edit_buffer = os.environ.get(status.info.name, "")
        self._status_message = f"Editing {status.info.name}. Enter saves, Esc cancels."
        self._status_is_error = False
        self.refresh(layout=True)

    def append_edit_character(self, char: str) -> None:
        if not self.is_editing:
            return
        self._edit_buffer = f"{self._edit_buffer}{char}"
        self.refresh(layout=True)

    def backspace_edit(self) -> None:
        if not self.is_editing:
            return
        self._edit_buffer = self._edit_buffer[:-1]
        self.refresh(layout=True)

    def clear_edit_buffer(self) -> None:
        if not self.is_editing:
            return
        self._edit_buffer = ""
        self.refresh(layout=True)

    def save_edit(self) -> None:
        if not self.is_editing:
            return
        var_name = self._editing_var_name
        if var_name is None:
            return

        try:
            target_path = set_env_var(var_name, self._edit_buffer)
        except Exception as exc:
            self._status_message = f"Failed to save {var_name}: {exc}"
            self._status_is_error = True
            self.refresh(layout=True)
            return

        self._editing_var_name = None
        self._edit_buffer = ""
        self._status_message = f"Saved {var_name} to {target_path}"
        self._status_is_error = False
        self.refresh_data()

    def cancel_edit(self) -> None:
        if not self.is_editing:
            return
        var_name = self._editing_var_name
        self._editing_var_name = None
        self._edit_buffer = ""
        if var_name:
            self._status_message = f"Canceled edit for {var_name}"
            self._status_is_error = False
        self.refresh(layout=True)

    def toggle_guided_mode(self) -> None:
        if self._guided_mode:
            self._guided_mode = False
            self._status_message = "Guided mode exited"
            self._status_is_error = False
            self.refresh(layout=True)
            return

        self._guided_mode = True
        self._guided_step_index = 0
        self._apply_guided_step()
        self._auto_advance_completed_steps()
        self._status_message = "Guided mode started"
        self._status_is_error = False
        self.refresh(layout=True)

    def _advance_guided_step(self) -> None:
        if not self._guided_mode:
            return
        if self._guided_step_index >= len(_GUIDED_STEPS) - 1:
            self._guided_mode = False
            self._status_message = "Guided setup complete"
            self._status_is_error = False
            self.refresh(layout=True)
            return

        self._guided_step_index += 1
        self._apply_guided_step()
        self._auto_advance_completed_steps()
        self.refresh(layout=True)

    def _apply_guided_step(self) -> None:
        step = _GUIDED_STEPS[self._guided_step_index]
        self.active_subtab = _SUBTABS.index(step.subtab)
        if step.adapter_tab is not None:
            self.active_adapter_tab = _ADAPTER_TABS.index(step.adapter_tab)
        self._clamp_current_cursor()
        # Auto-position cursor on the first unset var so guidance expands
        if step.subtab in ("adapters", "environment"):
            rows = self._selectable_env_rows()
            for idx, status in enumerate(rows):
                if not status.is_set:
                    self._set_current_cursor(idx)
                    return

    def _auto_advance_completed_steps(self) -> None:
        while self._guided_mode and self._is_current_guided_step_complete():
            if self._guided_step_index >= len(_GUIDED_STEPS) - 1:
                self._guided_mode = False
                self._status_message = "Guided setup complete"
                self._status_is_error = False
                break
            self._guided_step_index += 1
            self._apply_guided_step()

    def _is_current_guided_step_complete(self) -> bool:
        step = _GUIDED_STEPS[self._guided_step_index]
        if step.subtab == "adapters":
            section = next((item for item in self._adapter_sections if item.key == step.adapter_tab), None)
            return bool(section and section.status == "configured")
        if step.subtab == "people":
            return bool(self._people_data)
        if step.subtab == "notifications":
            return self._notification_projection.configured
        if step.subtab == "environment":
            return all(status.is_set for status in self._env_data) if self._env_data else False
        if step.subtab == "validate":
            return bool(self._validation_results) and all(result.passed for result in self._validation_results)
        return False

    def _render_guidance(self, result: Text, env_name: str) -> None:
        """Render inline guidance block for the given env var."""
        guidance = get_guidance_for_env(env_name)
        if guidance is None:
            return
        result.append("      ┌─ Guidance\n", style=_SEP)
        for idx, step in enumerate(guidance.steps, 1):
            result.append(f"      │ {idx}. {step}\n", style=_DIM)
        if guidance.url:
            url_text = Text()
            url_text.append("      │ Link: ")
            url_text.append(guidance.url, style=Style(color="#87afd7", link=guidance.url))
            url_text.append("\n")
            result.append_text(url_text)
        if guidance.format_example:
            result.append("      │ Format: ", style=_DIM)
            result.append(f"{guidance.format_example}\n", style=Style(color="#87afd7", bold=True))
        if guidance.validation_hint:
            result.append(f"      │ Hint: {guidance.validation_hint}\n", style=_DIM)
        result.append("      └─\n", style=_SEP)

    def _render_tab_bar(self, result: Text, tabs: tuple[str, ...], active: int) -> None:
        for idx, tab in enumerate(tabs):
            style = _TAB_ACTIVE if idx == active else _TAB_INACTIVE
            result.append(f" {tab} ", style=style)
            if idx < len(tabs) - 1:
                result.append(" ", style=_DIM)
        result.append("\n")

    def _render_header(self, result: Text) -> None:
        env_complete = all(status.is_set for status in self._env_data) if self._env_data else True
        configured, total = completion_summary(
            self._adapter_sections,
            has_people=bool(self._people_data),
            notifications_configured=self._notification_projection.configured,
            environment_configured=env_complete,
        )
        summary_style = _OK if configured == total else _WARN
        result.append(f"Setup Progress: {configured}/{total} sections configured\n", style=summary_style)

        if self._guided_mode:
            step = _GUIDED_STEPS[self._guided_step_index]
            result.append(
                f"Guided Step {self._guided_step_index + 1}/{len(_GUIDED_STEPS)}: {step.title}\n",
                style=_INFO,
            )

        if self._status_message:
            status_style = _FAIL if self._status_is_error else _DIM
            result.append(f"{self._status_message}\n", style=status_style)

    def _status_style(self, status: AdapterStatus) -> Style:
        if status == "configured":
            return _OK
        if status == "partial":
            return _WARN
        return _FAIL

    def _render_adapters(self, result: Text) -> None:
        result.append("\n")
        result.append("  Adapter Cards\n", style=Style(bold=True))

        for idx, section in enumerate(self._adapter_sections):
            selected = idx == self.active_adapter_tab
            prefix = "▶" if selected else " "
            card_style = Style(reverse=True) if selected else _NORMAL
            result.append(f"  {prefix} {section.label:<11} ", style=card_style)
            result.append(section.status.upper(), style=self._status_style(section.status))
            result.append(f"  ({section.configured_count}/{section.total_count})\n", style=_DIM)

        section = self._get_active_adapter_section()
        if section is None:
            result.append("\n  No adapters available\n", style=_DIM)
            return

        result.append("\n")
        result.append(f"  {section.label} Variables\n", style=Style(bold=True))
        if not section.env_statuses:
            result.append("  No environment variables registered for this adapter\n", style=_DIM)
            return

        cursor = self._current_cursor()
        for idx, status in enumerate(section.env_statuses):
            selected = idx == cursor
            row_style = Style(reverse=True) if selected else _NORMAL
            prefix = "▶" if selected else " "

            if self._editing_var_name == status.info.name:
                result.append(f"  {prefix} {status.info.name} = {self._edit_buffer}\n", style=row_style)
                result.append("      Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
                continue

            icon = "✔" if status.is_set else "✖"
            icon_style = _OK if status.is_set else _FAIL
            result.append(f"  {prefix} {icon} ", style=icon_style)
            result.append(f"{status.info.name}\n", style=row_style)
            result.append(f"      {status.info.description}\n", style=_DIM)
            if selected:
                self._render_guidance(result, status.info.name)

    def _render_people(self, result: Text) -> None:
        result.append("\n")
        result.append("  People\n", style=Style(bold=True))
        if not self._people_data:
            result.append("  No people configured\n", style=_FAIL)
            result.append("  Next: telec config people add --name <name> --email <email>\n", style=_DIM)
            return

        for person in self._people_data:
            result.append(f"  • {person.name}", style=_NORMAL)
            result.append(f" ({person.role})", style=_DIM)
            if person.email:
                result.append(f" <{person.email}>", style=_DIM)
            result.append("\n")

    def _render_notifications(self, result: Text) -> None:
        projection = self._notification_projection
        result.append("\n")
        result.append("  Notifications\n", style=Style(bold=True))
        result.append(
            f"  People with subscriptions: {projection.people_with_subscriptions}/{projection.total_people}\n"
        )
        result.append(f"  Total subscriptions: {projection.total_subscriptions}\n", style=_DIM)
        status = "CONFIGURED" if projection.configured else "NEEDS ATTENTION"
        result.append(f"  Status: {status}\n", style=_OK if projection.configured else _WARN)
        result.append(f"  Next action: {projection.next_action}\n", style=_DIM)

    def _render_environment(self, result: Text) -> None:
        result.append("\n")
        result.append("  Environment Variables\n", style=Style(bold=True))

        if not self._env_data:
            result.append("  Could not load env vars\n", style=_FAIL)
            return

        cursor = self._current_cursor()
        for idx, status in enumerate(self._env_data):
            selected = idx == cursor
            row_style = Style(reverse=True) if selected else _NORMAL
            prefix = "▶" if selected else " "

            if self._editing_var_name == status.info.name:
                result.append(f"  {prefix} {status.info.name} = {self._edit_buffer}\n", style=row_style)
                result.append("      Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
                continue

            icon = "✔" if status.is_set else "✖"
            icon_style = _OK if status.is_set else _FAIL
            result.append(f"  {prefix} {icon} ", style=icon_style)
            result.append(f"{status.info.name}", style=row_style)
            result.append(f" ({status.info.adapter})\n", style=_DIM)
            if selected:
                self._render_guidance(result, status.info.name)

    def _render_validate(self, result: Text) -> None:
        result.append("\n")
        result.append("  Validation\n", style=Style(bold=True))

        if not self._validation_results:
            result.append("  Press 'v' or Enter to run validation\n", style=_DIM)
            return

        passed = sum(1 for item in self._validation_results if item.passed)
        total = len(self._validation_results)
        summary_style = _OK if passed == total else _FAIL
        result.append(f"  {passed}/{total} checks passed\n\n", style=summary_style)

        for validation in self._validation_results:
            icon = "✔" if validation.passed else "✖"
            icon_style = _OK if validation.passed else _FAIL
            result.append("  ")
            result.append(f"{icon} ", style=icon_style)
            result.append(f"{validation.area}\n", style=_NORMAL)
            for error in validation.errors:
                result.append(f"      Error: {error}\n", style=_FAIL)
            for suggestion in validation.suggestions:
                result.append(f"      Tip: {suggestion}\n", style=_DIM)

    def render(self) -> Text:
        result = Text()

        self._render_tab_bar(result, _SUBTABS, self.active_subtab)
        result.append("-" * 78 + "\n", style=_SEP)
        self._render_header(result)

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
        self._clamp_current_cursor()
        self.refresh(layout=True)

    def watch_active_adapter_tab(self, _value: int) -> None:
        self._clamp_current_cursor()
        self.refresh(layout=True)
