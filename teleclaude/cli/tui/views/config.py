"""Interactive configuration view with guided setup and inline env editing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches, WrongType
from textual.events import Key, Paste
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _SUBTABS,
    AdapterSectionProjection,
    ConfigTuiOutcome,
    ConfigTuiRowAction,
    Subtab,
    observe_config_tui,
    project_adapter_sections,
)
from teleclaude.cli.tui.views.config_editing import ConfigContentEditingMixin
from teleclaude.cli.tui.views.config_operations import (
    ConfigOperationFailed,
    ConfigOperations,
    EditorViewAnswer,
    EnvVarStatus,
    ValidationResult,
)
from teleclaude.cli.tui.views.config_render import ConfigContentRenderMixin
from teleclaude.config.operation_answers import EditorFieldAnswer
from teleclaude.config.operation_requests import ConfigFailureKind
from teleclaude.config_subjects import ConfigSubjectKind

__all__ = ["ConfigContent", "ConfigView"]


@dataclass(frozen=True)
class PersonRow:
    """The identity fields the People list presents."""

    slug: str
    name: str
    role: str | None
    email: str | None


_TAB_ROOTS: dict[Subtab, tuple[str, ...]] = {
    Subtab.INFRA: ("computer", "daemon", "redis", "chiptunes"),
    Subtab.ADAPTERS: ("telegram", "discord", "whatsapp"),
    Subtab.PROVIDERS: ("backup", "email"),
    Subtab.SUMMARIZER: ("summarizer",),
    Subtab.TTS_STT: ("stt", "tts"),
    Subtab.PEOPLE: (),
    Subtab.ENV: (),
}
_PERSON_CACHE_KEY = "person:{slug}"
_STATUS_TEMPLATE = "{prefix}: {error}"
_LOAD_MACHINE_FAILED = "Failed to load machine configuration"
_LOAD_ENV_FAILED = "Failed to load env vars"
_LOAD_PEOPLE_FAILED = "Failed to load people"
_LOAD_SECRETS_FAILED = "Failed to load personal secrets"
_API_ATTRIBUTE = "api"
_LOAD_GROUP = "config-load"
_SECRETS_GROUP = "config-secrets"
_VALIDATE_GROUP = "config-validate"
_DAEMON_UNAVAILABLE = "The daemon is not reachable."
_PERSON_NAME_ID = "identity.name"
_PERSON_ROLE_ID = "identity.role"
_PERSON_EMAIL_ID = "identity.email"
_FIELD_PATH_SEPARATOR = "."


def _editor_value(editor: EditorViewAnswer, identity: str) -> object:
    field = next((item for item in editor.fields if item.identity == identity), None)
    return field.value if field is not None else None


def _person_row(slug: str, editor: EditorViewAnswer) -> PersonRow:
    name = _editor_value(editor, _PERSON_NAME_ID)
    role = _editor_value(editor, _PERSON_ROLE_ID)
    email = _editor_value(editor, _PERSON_EMAIL_ID)
    return PersonRow(
        slug=slug,
        name=name if isinstance(name, str) else slug,
        role=role if isinstance(role, str) else None,
        email=email if isinstance(email, str) else None,
    )


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
        """Return the mounted content widget when available."""
        if not self.is_attached:
            return None
        try:
            return self.query_one("#config-content", ConfigContent)
        except (NoMatches, WrongType):
            return None

    def _sync_from_content(self) -> None:
        """Mirror tab state back from the content widget."""
        content = self._content_or_none()
        if content is None:
            return
        self.active_subtab = content.active_subtab
        self.active_adapter_tab = content.active_adapter_tab

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Limit adapter tab movement to relevant subviews."""
        del parameters
        if action in ("next_adapter_tab", "prev_adapter_tab"):
            content = self._content_or_none()
            if content is not None and content.is_on_enum_field:
                return True
            return self.active_subtab == _SUBTABS.index(Subtab.ADAPTERS)
        return True

    def watch_active_subtab(self, _value: int) -> None:
        """Propagate subtab changes to the inner content widget."""
        self._sync_content()
        if self.is_attached:
            self.app.refresh_bindings()

    def watch_active_adapter_tab(self, _value: int) -> None:
        """Propagate adapter tab changes to the inner content widget."""
        self._sync_content()
        if self.is_attached:
            self.app.refresh_bindings()

    def compose(self) -> ComposeResult:
        """Compose the scrollable configuration content."""
        scroll = VerticalScroll(id="config-scroll")
        scroll.can_focus = False
        with scroll:
            yield ConfigContent(id="config-content")

    def on_mount(self) -> None:
        """Load configuration data once the widget is mounted."""
        self._refresh_content()

    def on_focus(self) -> None:
        """Refresh bindings and clear any focus border decoration."""
        self.styles.border = ("none", "transparent")
        self.app.refresh_bindings()

    def on_click(self) -> None:
        """Focus the widget when it is clicked."""
        self.focus()

    def on_config_content_subtab_selected(self, msg: ConfigContent.SubtabSelected) -> None:
        """Sync the outer subtab index from a click inside the content."""
        self.active_subtab = msg.idx

    def on_config_content_adapter_tab_selected(self, msg: ConfigContent.AdapterTabSelected) -> None:
        """Sync the outer adapter tab index from a click inside the content."""
        self.active_adapter_tab = msg.idx

    @property
    def paste_safe(self) -> bool:
        """Accept paste/key bursts only while an inline field is being edited."""
        content = self._content_or_none()
        return content is not None and content.is_editing

    def on_paste(self, event: Paste) -> None:
        """Insert pasted text into the active edit buffer; ignore otherwise."""
        content = self._content_or_none()
        if content is None or not content.is_editing:
            return
        content.append_edit_text(event.text)
        event.stop()

    def on_key(self, event: Key) -> None:
        """Forward editing keystrokes or list reordering keys to the content widget."""
        content = self._content_or_none()
        if content is None:
            return

        if not content.is_editing:
            if event.key == "left_square_bracket":
                content.reorder_reflected_list(-1)
                event.stop()
                return
            if event.key == "right_square_bracket":
                content.reorder_reflected_list(1)
                event.stop()
                return
            return

        if event.key == "backspace":
            content.backspace_edit()
            event.stop()
            return
        if event.key == "ctrl+u":
            content.clear_personal_secret_or_edit_buffer()
            event.stop()
            return
        if event.character and event.is_printable:
            content.append_edit_character(event.character)
            event.stop()

    def _refresh_content(self) -> None:
        """Ask the content widget to reload its underlying config data."""
        content = self.query_one("#config-content", ConfigContent)
        content.refresh_data()

    def _sync_content(self) -> None:
        """Push the current tab state into the content widget."""
        content = self.query_one("#config-content", ConfigContent)
        content.active_subtab = self.active_subtab
        content.active_adapter_tab = self.active_adapter_tab

    def action_run_validation(self) -> None:
        """Run config validation for the current content."""
        content = self.query_one("#config-content", ConfigContent)
        content.run_validation()

    def action_refresh_config(self) -> None:
        """Reload config data from disk."""
        self._refresh_content()

    def action_cursor_up(self) -> None:
        """Move the config cursor up."""
        content = self.query_one("#config-content", ConfigContent)
        content.move_cursor(-1)

    def action_cursor_down(self) -> None:
        """Move the config cursor down."""
        content = self.query_one("#config-content", ConfigContent)
        content.move_cursor(1)

    def action_activate(self) -> None:
        """Activate the currently selected field or row."""
        content = self.query_one("#config-content", ConfigContent)
        content.activate_current()
        self._sync_from_content()

    def action_cancel(self) -> None:
        """Cancel the active edit, expansion, or guided mode step."""
        content = self.query_one("#config-content", ConfigContent)
        if content.is_editing:
            content.cancel_edit()
        elif content.is_person_expanded:
            content.collapse_person()
        elif content.guided_mode:
            content.toggle_guided_mode()
            self._sync_from_content()

    def action_toggle_guided_mode(self) -> None:
        """Toggle guided mode on the content widget."""
        content = self.query_one("#config-content", ConfigContent)
        content.toggle_guided_mode()
        self._sync_from_content()

    def action_next_subtab(self) -> None:
        """Switch to the next config subtab."""
        self.active_subtab = (self.active_subtab + 1) % len(_SUBTABS)
        self._sync_content()

    def action_prev_subtab(self) -> None:
        """Switch to the previous config subtab."""
        self.active_subtab = (self.active_subtab - 1) % len(_SUBTABS)
        self._sync_content()

    def action_next_adapter_tab(self) -> None:
        """Advance to the next adapter tab or enum value."""
        content = self._content_or_none()
        if content is not None and content.is_on_enum_field:
            content.cycle_enum_field(1)
            return
        if self.active_subtab == _SUBTABS.index(Subtab.ADAPTERS):
            self.active_adapter_tab = (self.active_adapter_tab + 1) % len(_ADAPTER_TABS)
            self._sync_content()

    def action_prev_adapter_tab(self) -> None:
        """Move to the previous adapter tab or enum value."""
        content = self._content_or_none()
        if content is not None and content.is_on_enum_field:
            content.cycle_enum_field(-1)
            return
        if self.active_subtab == _SUBTABS.index(Subtab.ADAPTERS):
            self.active_adapter_tab = (self.active_adapter_tab - 1) % len(_ADAPTER_TABS)
            self._sync_content()


class ConfigContent(
    ConfigContentEditingMixin,
    ConfigContentRenderMixin,
    TelecMixin,
    Widget,
):
    """Renders guided config sections with inline env editing."""

    DEFAULT_CSS = """
    ConfigContent {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    class SubtabSelected(Message):
        """Posted when a config subtab is selected by mouse."""

        def __init__(self, idx: int) -> None:
            super().__init__()
            self.idx = idx

    class AdapterTabSelected(Message):
        """Posted when an adapter card is selected by mouse."""

        def __init__(self, idx: int) -> None:
            super().__init__()
            self.idx = idx

    active_subtab = reactive(0, layout=True)
    active_adapter_tab = reactive(0, layout=True)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._env_data: list[EnvVarStatus] = []
        self._people_data: list[PersonRow] = []
        self._validation_results: list[ValidationResult] = []
        self._adapter_sections: list[AdapterSectionProjection] = []
        self._outside_scope: tuple[str, ...] = ()
        self._cursor_by_context: dict[str, int] = {}
        self._editing_var_name: str | None = None
        self._edit_buffer = ""
        self._status_message = ""
        self._status_is_error = False
        self._guided_mode = False
        self._guided_step_index = 0
        self._tab_click_regions: list[tuple[int, int, int, int]] = []  # (row, x_start, x_end, subtab_idx)
        self._row_click_map: dict[int, tuple[ConfigTuiRowAction, Any]] = {}  # {content_row: action_tuple}
        self._expanded_person: str | None = None
        self._person_field_cursor: int = 0
        self._machine_editor: EditorViewAnswer | None = None
        self._machine_revision: str | None = None
        self._people: dict[str, EditorViewAnswer] = {}
        self._write_lock = asyncio.Lock()
        self._load_pending = True
        self._list_element_idx: int = 0
        self._reflected_cache: dict[Subtab | str, list[EditorFieldAnswer]] = {}

    @property
    def reflected_fields(self) -> list[EditorFieldAnswer]:
        """Return the owner-supplied fields for the active configuration tab."""
        tab = _SUBTABS[self.active_subtab]
        cached = self._reflected_cache.get(tab)
        if cached is not None:
            return cached
        editor = self._machine_editor
        if editor is None:
            return []
        render_cycle_id = str(uuid4())
        observe_config_tui(ConfigTuiOutcome.RENDER_REQUESTED, render_cycle_id=render_cycle_id, subtab=tab.value)
        roots = _TAB_ROOTS[tab]
        fields = [field for field in editor.fields if field.identity.split(_FIELD_PATH_SEPARATOR, 1)[0] in roots]
        observe_config_tui(
            ConfigTuiOutcome.RENDERED,
            render_cycle_id=render_cycle_id,
            field_paths=[field.identity for field in fields],
        )
        self._reflected_cache[tab] = fields
        return fields

    @property
    def guided_mode(self) -> bool:
        """Whether guided setup mode is active."""
        return self._guided_mode

    @property
    def is_editing(self) -> bool:
        """Whether an env var or person field is being edited."""
        return self._editing_var_name is not None

    @property
    def is_person_expanded(self) -> bool:
        """Whether a person's details are currently expanded."""
        return self._expanded_person is not None

    @property
    def person_reflected_fields(self) -> list[EditorFieldAnswer]:
        """Return the selected person's owner-supplied editor fields."""
        if self._expanded_person is None:
            return []
        cache_key = _PERSON_CACHE_KEY.format(slug=self._expanded_person)
        cached = self._reflected_cache.get(cache_key)
        if cached is not None:
            return cached
        editor = self._people.get(self._expanded_person)
        fields = list(editor.fields) if editor is not None else []
        self._reflected_cache[cache_key] = fields
        return fields

    @property
    def person_editable_fields(self) -> list[str]:
        """Return the identities of the selected person's supplied editor fields."""
        return [field.identity for field in self.person_reflected_fields]

    def _operations(self) -> ConfigOperations | None:
        """The daemon requests of this tab, or None while the TUI has not connected to the daemon."""
        api = getattr(self.app, _API_ATTRIBUTE, None)
        if api is None or not api.is_connected:
            return None
        return ConfigOperations(api)

    def refresh_data(self) -> None:
        """Ask the daemon for the machine configuration, environment state, and people, and show them."""
        operations = self._operations()
        if operations is None:
            self._load_pending = True
            return
        self._load_pending = False
        self.run_worker(self._load_snapshot(operations), exclusive=True, group=_LOAD_GROUP)

    def load_when_connected(self) -> None:
        """Load the first snapshot once the TUI has connected to the daemon."""
        if self._load_pending:
            self.refresh_data()

    async def _load_snapshot(self, operations: ConfigOperations) -> None:
        """Read the subjects this tab shows, each failure reported where it happened."""
        try:
            machine = await operations.editor(ConfigSubjectKind.COMPUTER)
            self._machine_editor = machine
            self._machine_revision = machine.revision
            self._outside_scope = tuple(machine.outside_scope)
        except Exception as exc:
            self._machine_editor = None
            self._machine_revision = None
            self._outside_scope = ()
            self._report_failure(_LOAD_MACHINE_FAILED, exc)

        try:
            statuses = await operations.environment_variables()
            self._env_data = [status for status in statuses if status.info.adapter not in self._outside_scope]
        except Exception as exc:
            self._env_data = []
            self._report_failure(_LOAD_ENV_FAILED, exc)

        self._adapter_sections = project_adapter_sections(self._env_data)
        await self._load_people(operations)
        self._reflected_cache.clear()
        self._clamp_current_cursor()

        if self._guided_mode:
            self._apply_guided_step()
            self._auto_advance_completed_steps()

        self.refresh(layout=True)

    async def _load_people(self, operations: ConfigOperations) -> None:
        """Read the people the operator may see: all of them for an administrator, else their own."""
        self._people = {}
        self._people_data = []
        try:
            try:
                slugs = await operations.list_instances(ConfigSubjectKind.PERSON)
            except ConfigOperationFailed as refusal:
                if refusal.kind is not ConfigFailureKind.REFUSED:
                    raise
                own_slug = await operations.own_person_slug()
                if own_slug is None:
                    raise
                slugs = [own_slug]
            editors = await asyncio.gather(*(operations.editor(ConfigSubjectKind.PERSON, slug) for slug in slugs))
        except Exception as exc:
            self._report_failure(_LOAD_PEOPLE_FAILED, exc)
            return
        self._people = dict(zip(slugs, editors, strict=True))
        self._people_data = [_person_row(slug, editor) for slug, editor in self._people.items()]
        if self._expanded_person is not None:
            self._reflected_cache.pop(_PERSON_CACHE_KEY.format(slug=self._expanded_person), None)

    def load_expanded_person_secrets(self) -> None:
        """Refresh the expanded person's owner-supplied fields and secret inventory."""
        operations = self._operations()
        slug = self._expanded_person
        if operations is None or slug is None:
            return
        self.run_worker(self._reload_person_editor(operations, slug), exclusive=True, group=_SECRETS_GROUP)

    async def _reload_person_editor(self, operations: ConfigOperations, slug: str) -> None:
        try:
            self._people[slug] = await operations.editor(ConfigSubjectKind.PERSON, slug)
            self._people_data = [_person_row(person.slug, self._people[person.slug]) for person in self._people_data]
        except Exception as exc:
            self._report_failure(_LOAD_SECRETS_FAILED, exc)
        self._reflected_cache.pop(_PERSON_CACHE_KEY.format(slug=slug), None)
        self.refresh(layout=True)

    def _report_failure(self, prefix: str, error: Exception) -> None:
        """Show a failed request in the status line: the daemon's refusal as it worded it, else the failure."""
        self._status_message = _STATUS_TEMPLATE.format(prefix=prefix, error=error)
        self._status_is_error = True

    def run_validation(self) -> None:
        """Run the full config validation suite and surface the summary."""
        operations = self._operations()
        if operations is None:
            self._status_message = _DAEMON_UNAVAILABLE
            self._status_is_error = True
            self.refresh(layout=True)
            return
        self.run_worker(self._validate(operations), exclusive=True, group=_VALIDATE_GROUP)

    async def _validate(self, operations: ConfigOperations) -> None:
        try:
            self._validation_results = await operations.validate()
            passed = sum(1 for result in self._validation_results if result.passed)
            self._status_message = f"Validation complete: {passed}/{len(self._validation_results)} checks passed"
            self._status_is_error = passed != len(self._validation_results)
        except Exception as exc:
            self._validation_results = []
            self._status_message = f"Validation failed: {exc}"
            self._status_is_error = True
        self.refresh(layout=True)

    def _current_context_key(self) -> str:
        """Return the cursor context key for the active subtab."""
        tab = _SUBTABS[self.active_subtab]
        if tab == Subtab.ADAPTERS:
            return f"adapter:{_ADAPTER_TABS[self.active_adapter_tab]}"
        return tab

    def _get_active_adapter_section(self) -> AdapterSectionProjection | None:
        """Return the adapter section for the active adapter tab."""
        if not self._adapter_sections:
            return None
        idx = max(0, min(self.active_adapter_tab, len(self._adapter_sections) - 1))
        return self._adapter_sections[idx]

    def _selectable_env_rows(self) -> list[EnvVarStatus]:
        """Return the env rows available for the active subtab."""
        tab = _SUBTABS[self.active_subtab]
        if tab == Subtab.ADAPTERS:
            section = self._get_active_adapter_section()
            if section is None:
                return []
            return section.env_statuses
        if tab == Subtab.ENV:
            return self._env_data
        return []

    def _current_cursor(self) -> int:
        """Return the cursor position for the active context."""
        return self._cursor_by_context.get(self._current_context_key(), 0)

    def _set_current_cursor(self, index: int) -> None:
        """Persist the cursor position for the active context."""
        self._cursor_by_context[self._current_context_key()] = index

    def _clamp_current_cursor(self) -> None:
        """Clamp the cursor to the available rows in the active context."""
        tab = _SUBTABS[self.active_subtab]
        if tab == Subtab.PEOPLE:
            count = len(self._people_data)
            if count:
                self._set_current_cursor(max(0, min(self._current_cursor(), count - 1)))
            else:
                self._set_current_cursor(0)
            self._person_field_cursor = max(0, min(self._person_field_cursor, len(self.person_editable_fields) - 1))
            return
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            count = len(self.reflected_fields)
            if count:
                self._set_current_cursor(max(0, min(self._current_cursor(), count - 1)))
            else:
                self._set_current_cursor(0)
            return
        rows = self._selectable_env_rows()
        if not rows:
            self._set_current_cursor(0)
            return
        cursor = self._current_cursor()
        self._set_current_cursor(max(0, min(cursor, len(rows) - 1)))

    def _current_selected_env(self) -> EnvVarStatus | None:
        """Return the currently selected env row, if any."""
        rows = self._selectable_env_rows()
        if not rows:
            return None
        cursor = self._current_cursor()
        if cursor < 0 or cursor >= len(rows):
            return None
        return rows[cursor]
