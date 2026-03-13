"""Interactive configuration view with guided setup and inline env editing."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.config_handlers import EnvVarStatus, ValidationResult, get_person_config
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _SUBTABS,
    AdapterSectionProjection,
    NotificationProjection,
    project_adapter_sections,
)
from teleclaude.cli.tui.views.config_editing import ConfigContentEditingMixin
from teleclaude.cli.tui.views.config_render import ConfigContentRenderMixin
from teleclaude.config.schema import PersonEntry

__all__ = ["ConfigContent", "ConfigView"]


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
        scrollbar-size: 0 0;
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
            content = self._content_or_none()
            if content is not None and content.is_on_enum_field:
                return True
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
        content = self._content_or_none()
        if content is not None and content.is_on_enum_field:
            content.cycle_enum_field(1)
            return
        if self.active_subtab == 0:
            self.active_adapter_tab = (self.active_adapter_tab + 1) % len(_ADAPTER_TABS)
            self._sync_content()

    def action_prev_adapter_tab(self) -> None:
        content = self._content_or_none()
        if content is not None and content.is_on_enum_field:
            content.cycle_enum_field(-1)
            return
        if self.active_subtab == 0:
            self.active_adapter_tab = (self.active_adapter_tab - 1) % len(_ADAPTER_TABS)
            self._sync_content()


class ConfigContent(ConfigContentEditingMixin, ConfigContentRenderMixin, TelecMixin, Widget):
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
        self._row_click_map: dict[int, tuple[str, Any]] = {}  # {content_row: action_tuple}
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

    @property
    def is_on_enum_field(self) -> bool:
        from teleclaude.cli.tui.views._config_constants import _PERSON_EDITABLE_FIELDS, _SUBTABS

        tab = _SUBTABS[self.active_subtab]
        return (
            tab == "people"
            and self._expanded_person is not None
            and not self.is_editing
            and _PERSON_EDITABLE_FIELDS[self._person_field_cursor] == "role"
        )

    def cycle_enum_field(self, direction: int) -> None:
        if not self.is_on_enum_field:
            return
        person = next((p for p in self._people_data if p.name == self._expanded_person), None)
        if person is not None:
            self._cycle_person_role(person, direction)

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
        from teleclaude.cli.tui.views._config_constants import _ADAPTER_TABS, _SUBTABS

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
        from teleclaude.cli.tui.views._config_constants import _SUBTABS

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
        from teleclaude.cli.tui.views._config_constants import _PERSON_EDITABLE_FIELDS, _SUBTABS

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
