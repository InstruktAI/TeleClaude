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
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.config_handlers import EnvVarStatus, ValidationResult, get_person_config, set_env_var
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.config_components.guidance import get_guidance_for_env
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, get_neutral_color
from teleclaude.config.schema import PersonEntry

_SUBTABS = ("adapters", "people", "notifications", "environment")
_PERSON_EDITABLE_FIELDS = ("email", "role", "username")
_VALID_ROLES = ("admin", "member", "contributor", "newcomer")
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


def _normal_style() -> Style:
    """Normal text style — adapts to dark/light mode."""
    return Style(color=get_neutral_color("highlight"))


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
        scroll = VerticalScroll(id="config-scroll")
        scroll.can_focus = False
        with scroll:
            yield ConfigContent(id="config-content")

    def on_mount(self) -> None:
        self._refresh_content()

    def on_focus(self) -> None:
        self.styles.border = ("none", "transparent")
        self.app.refresh_bindings()

    def on_click(self) -> None:
        self.focus()

    def on_config_content_subtab_selected(self, msg: ConfigContent.SubtabSelected) -> None:
        self.active_subtab = msg.idx

    def on_config_content_adapter_tab_selected(self, msg: ConfigContent.AdapterTabSelected) -> None:
        self.active_adapter_tab = msg.idx

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
        content = self.query_one("#config-content", ConfigContent)
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
        elif content.is_person_expanded:
            content.collapse_person()
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

    class SubtabSelected(Message):
        def __init__(self, idx: int) -> None:
            super().__init__()
            self.idx = idx

    class AdapterTabSelected(Message):
        def __init__(self, idx: int) -> None:
            super().__init__()
            self.idx = idx

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
        self._tab_click_regions: list[tuple[int, int, int, int]] = []  # (row, x_start, x_end, subtab_idx)
        self._row_click_map: dict[int, tuple] = {}  # {content_row: action_tuple}
        self._expanded_person: str | None = None
        self._person_field_cursor: int = 0
        self._editing_person_field: str | None = None

    @property
    def guided_mode(self) -> bool:
        return self._guided_mode

    @property
    def is_editing(self) -> bool:
        return self._editing_var_name is not None or self._editing_person_field is not None

    @property
    def is_person_expanded(self) -> bool:
        return self._expanded_person is not None

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
        tab = _SUBTABS[self.active_subtab]
        if tab == "people":
            count = len(self._people_data)
            if count:
                self._set_current_cursor(max(0, min(self._current_cursor(), count - 1)))
            else:
                self._set_current_cursor(0)
            self._person_field_cursor = max(0, min(self._person_field_cursor, len(_PERSON_EDITABLE_FIELDS) - 1))
            return
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
        tab = _SUBTABS[self.active_subtab]
        if tab == "people":
            if self._expanded_person is not None:
                self._person_field_cursor = max(0, min(self._person_field_cursor + delta, len(_PERSON_EDITABLE_FIELDS) - 1))
            elif self._people_data:
                self._set_current_cursor(max(0, min(self._current_cursor() + delta, len(self._people_data) - 1)))
            self.refresh(layout=True)
            return
        rows = self._selectable_env_rows()
        if not rows:
            return
        next_cursor = max(0, min(self._current_cursor() + delta, len(rows) - 1))
        self._set_current_cursor(next_cursor)
        self.refresh(layout=True)

    def activate_current(self) -> None:
        if self._editing_person_field is not None:
            self._save_person_field()
            return
        if self._editing_var_name is not None:
            self.save_edit()
            return

        tab = _SUBTABS[self.active_subtab]
        if tab == "people":
            if self._expanded_person is None:
                if self._people_data:
                    cursor = self._current_cursor()
                    if 0 <= cursor < len(self._people_data):
                        self._expanded_person = self._people_data[cursor].name
                        self._person_field_cursor = 0
                        self.refresh(layout=True)
            else:
                person = next((p for p in self._people_data if p.name == self._expanded_person), None)
                if person is not None:
                    field = _PERSON_EDITABLE_FIELDS[self._person_field_cursor]
                    if field == "role":
                        self._cycle_person_role(person)
                    else:
                        self._begin_person_field_edit(person, field)
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

    def _cycle_person_role(self, person: PersonEntry) -> None:
        from teleclaude.cli.config_handlers import get_global_config, save_global_config

        current = person.role
        idx = _VALID_ROLES.index(current) if current in _VALID_ROLES else -1
        next_role = _VALID_ROLES[(idx + 1) % len(_VALID_ROLES)]
        try:
            config = get_global_config()
            for p in config.people:
                if p.name == person.name:
                    p.role = next_role  # type: ignore[assignment]
                    break
            save_global_config(config)
            self._status_message = f"Role set to {next_role}"
            self._status_is_error = False
        except Exception as exc:
            self._status_message = f"Failed to save role: {exc}"
            self._status_is_error = True
        self.refresh_data()

    def _begin_person_field_edit(self, person: PersonEntry, field: str) -> None:
        self._editing_person_field = field
        self._edit_buffer = str(getattr(person, field, "") or "")
        self._status_message = f"Editing {person.name}.{field}. Enter saves, Esc cancels."
        self._status_is_error = False
        self.refresh(layout=True)

    def _save_person_field(self) -> None:
        if self._editing_person_field is None or self._expanded_person is None:
            return
        from teleclaude.cli.config_handlers import get_global_config, save_global_config

        field = self._editing_person_field
        value = self._edit_buffer
        person_name = self._expanded_person

        if field == "role" and value not in _VALID_ROLES:
            self._status_message = f"Invalid role. Valid: {', '.join(_VALID_ROLES)}"
            self._status_is_error = True
            self.refresh(layout=True)
            return

        try:
            config = get_global_config()
            for p in config.people:
                if p.name == person_name:
                    setattr(p, field, value or None)
                    break
            save_global_config(config)
            self._status_message = f"Saved {person_name}.{field}"
            self._status_is_error = False
        except Exception as exc:
            self._status_message = f"Failed to save: {exc}"
            self._status_is_error = True

        self._editing_person_field = None
        self._edit_buffer = ""
        self.refresh_data()

    def collapse_person(self) -> None:
        self._expanded_person = None
        self._editing_person_field = None
        self._edit_buffer = ""
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
        if self._editing_person_field is not None:
            field = self._editing_person_field
            self._editing_person_field = None
            self._edit_buffer = ""
            self._status_message = f"Canceled edit for {field}"
            self._status_is_error = False
            self.refresh(layout=True)
            return
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
        row = result.plain.count("\n")
        x = 0
        for idx, tab in enumerate(tabs):
            style = _TAB_ACTIVE if idx == active else _TAB_INACTIVE
            label = f" {tab} "
            self._tab_click_regions.append((row, x, x + len(label), idx))
            result.append(label, style=style)
            x += len(label)
            if idx < len(tabs) - 1:
                result.append(" ", style=_DIM)
                x += 1
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
            card_style = Style(reverse=True) if selected else _normal_style()
            row = result.plain.count("\n")
            self._row_click_map[row] = ("adapter_tab", idx)
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
            row_style = Style(reverse=True) if selected else _normal_style()
            prefix = "▶" if selected else " "

            row = result.plain.count("\n")
            self._row_click_map[row] = ("env_row", status.info.name)

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

        cursor = self._current_cursor()
        for idx, person in enumerate(self._people_data):
            selected = idx == cursor
            prefix = "▶" if selected else " "
            row_style = Style(reverse=True) if selected else _normal_style()

            row = result.plain.count("\n")
            self._row_click_map[row] = ("person_select", person.name)

            result.append(f"  {prefix} {person.name}", style=row_style)
            result.append(f" ({person.role})", style=_DIM)
            if person.email:
                result.append(f" <{person.email}>", style=_DIM)
            result.append("\n")

            if selected and self._expanded_person == person.name:
                for field_idx, field in enumerate(_PERSON_EDITABLE_FIELDS):
                    field_selected = field_idx == self._person_field_cursor
                    field_prefix = "▶" if field_selected else " "
                    field_row_style = Style(reverse=True) if field_selected else _DIM

                    field_row = result.plain.count("\n")
                    self._row_click_map[field_row] = ("person_field", field)

                    if self._editing_person_field == field:
                        result.append(f"      {field_prefix} {field} = {self._edit_buffer}█\n", style=field_row_style)
                        result.append("          Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
                    elif field == "role":
                        value = str(getattr(person, field, "") or "")
                        result.append(f"      {field_prefix} ", style=_DIM)
                        result.append("role: ", style=_DIM)
                        for opt in _VALID_ROLES:
                            opt_style = _TAB_ACTIVE if opt == value else _TAB_INACTIVE
                            result.append(f" {opt} ", style=opt_style)
                        if field_selected:
                            result.append("  ↵ cycle", style=_DIM)
                        result.append("\n")
                    else:
                        value = str(getattr(person, field, "") or "")
                        icon = "✔" if value else "○"
                        icon_style = _OK if value else _DIM
                        result.append(f"      {field_prefix} {icon} ", style=icon_style)
                        result.append(f"{field}: ", style=_DIM)
                        result.append(f"{value or '(not set)'}\n", style=field_row_style)

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
            row_style = Style(reverse=True) if selected else _normal_style()
            prefix = "▶" if selected else " "

            row = result.plain.count("\n")
            self._row_click_map[row] = ("env_row", status.info.name)

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


    def render(self) -> Text:
        self._tab_click_regions = []
        self._row_click_map = {}
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

        return result

    def on_click(self, event: object) -> None:
        x = getattr(event, "x", -1)
        y = getattr(event, "y", -1)

        for row, x_start, x_end, subtab_idx in self._tab_click_regions:
            if y == row and x_start <= x < x_end:
                self.post_message(self.SubtabSelected(subtab_idx))
                return

        action = self._row_click_map.get(y)
        if action is None:
            return

        action_type = action[0]
        if action_type == "adapter_tab":
            self.post_message(self.AdapterTabSelected(action[1]))
        elif action_type == "env_row":
            env_name = action[1]
            rows = self._selectable_env_rows()
            for i, status in enumerate(rows):
                if status.info.name == env_name:
                    self._set_current_cursor(i)
                    self._begin_edit(status)
                    break
        elif action_type == "person_select":
            person_name = action[1]
            if self._editing_person_field is not None:
                self._editing_person_field = None
                self._edit_buffer = ""
            for i, p in enumerate(self._people_data):
                if p.name == person_name:
                    self._set_current_cursor(i)
                    if self._expanded_person == person_name:
                        self._expanded_person = None
                    else:
                        self._expanded_person = person_name
                        self._person_field_cursor = 0
                    self.refresh(layout=True)
                    break
        elif action_type == "person_field":
            field = action[1]
            for field_idx, f in enumerate(_PERSON_EDITABLE_FIELDS):
                if f == field:
                    self._person_field_cursor = field_idx
                    person = next((p for p in self._people_data if p.name == self._expanded_person), None)
                    if person is not None:
                        if field == "role":
                            self._cycle_person_role(person)
                        else:
                            self._begin_person_field_edit(person, field)
                    break

    def watch_active_subtab(self, _value: int) -> None:
        self._clamp_current_cursor()
        self.refresh(layout=True)

    def watch_active_adapter_tab(self, _value: int) -> None:
        self._clamp_current_cursor()
        self.refresh(layout=True)
