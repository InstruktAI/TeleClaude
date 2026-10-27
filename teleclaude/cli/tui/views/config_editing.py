"""Editing and guided-mode mixin for ConfigContent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _GUIDED_STEPS,
    _SUBTABS,
    AdapterSectionProjection,
    ConfigTuiOutcome,
    Subtab,
    observe_config_tui,
)
from teleclaude.cli.tui.views.config_operations import ConfigOperationFailed, ConfigOperations, EnvVarStatus
from teleclaude.config.operation_answers import (
    EditorFieldAnswer,
    EditorInputKind,
    EditorValueState,
    EditorViewAnswer,
)
from teleclaude.config.operation_requests import ConfigEditIntent, ConfigFailureKind
from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind

if TYPE_CHECKING:
    from teleclaude.cli.tui.views.config import PersonRow

_WRITE_GROUP = "config-write"
_STALE_REVISION_MESSAGE = "{label}: Changed elsewhere since it was read; reloaded."
_CLEARED = "Cleared {label}."
_KEPT = "Kept {label}."
_SAVED = "Saved {label}."
_SAVED_FIELD = "Saved {label} successfully."
_UPDATED = "Updated {label}."
_SAVE_FAILED = "Failed to save {label}: {error}"
_EDITING_STATUS = "Editing {label}. Enter saves, Esc cancels."
_EMPTY_TEXT = ""
_EDIT_LIST_SEPARATOR = ","
_CONFIG_SOURCE = "config"
_SECRET_PREFIX = "secrets."
_IDENTITY_PREFIX = "identity."
_OVERLAY_PREFIX = "overlay."
_JSON_MODE = "json"
_DAEMON_UNAVAILABLE = "The daemon is not reachable."

_REDIS_URL_ID = "redis.cluster.url"
type WriteAction = Callable[[ConfigOperations], Awaitable[None]]


def _is_write_only(field: EditorFieldAnswer) -> bool:
    return field.sensitive or field.identity.startswith(_SECRET_PREFIX)


class _RedisUrl(StrEnum):
    """How the Redis URL stands for guided setup: left to its default, waiting on a variable, or set."""

    DEFAULT = "default"
    UNRESOLVED = "unresolved"
    EXPLICIT = "explicit"


class ConfigContentEditingMixin:
    """Cursor movement, inline editing, and guided-mode logic for ConfigContent."""

    if TYPE_CHECKING:
        _adapter_sections: list[AdapterSectionProjection]
        _env_data: list[EnvVarStatus]
        _people_data: list[PersonRow]
        _people: dict[str, EditorViewAnswer]
        _machine_editor: EditorViewAnswer | None
        _machine_revision: str | None

        @property
        def person_reflected_fields(self) -> list[EditorFieldAnswer]: ...

        @property
        def reflected_fields(self) -> list[EditorFieldAnswer]: ...

    def move_cursor(self, delta: int) -> None:
        """Move the cursor within the active config section."""
        if self.is_editing:  # type: ignore[attr-defined]
            return
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            fields = self.reflected_fields  # type: ignore[attr-defined]
            if not fields:
                return
            next_cursor = max(0, min(self._current_cursor() + delta, len(fields) - 1))  # type: ignore[attr-defined]
            self._set_current_cursor(next_cursor)  # type: ignore[attr-defined]
            self._list_element_idx = 0  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return
        if tab == Subtab.PEOPLE:
            if self._expanded_person is not None:  # type: ignore[attr-defined]
                fields = self.person_reflected_fields
                self._person_field_cursor = max(  # type: ignore[attr-defined]
                    0,
                    min(
                        self._person_field_cursor + delta,
                        len(fields) - 1,
                    ),  # type: ignore[attr-defined]
                )
            elif self._people_data:  # type: ignore[attr-defined]
                next_cursor = max(
                    0,
                    min(self._current_cursor() + delta, len(self._people_data) - 1),  # type: ignore[attr-defined]
                )
                self._set_current_cursor(next_cursor)  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return
        rows = self._selectable_env_rows()  # type: ignore[attr-defined]
        if not rows:
            return
        next_cursor = max(0, min(self._current_cursor() + delta, len(rows) - 1))  # type: ignore[attr-defined]
        self._set_current_cursor(next_cursor)  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def activate_current(self) -> None:
        """Activate the current row, entering edit mode when appropriate."""
        if self._editing_var_name is not None:  # type: ignore[attr-defined]
            self.save_edit()
            return

        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            fields = self.reflected_fields  # type: ignore[attr-defined]
            if fields:
                cursor = self._current_cursor()  # type: ignore[attr-defined]
                f = fields[max(0, min(cursor, len(fields) - 1))]
                if f.input_kind is EditorInputKind.BOOLEAN:
                    self._save_editor_field(f.identity, ConfigEditIntent.REPLACE, not bool(f.value))
                elif f.choices:
                    self.cycle_enum_field(1)
                else:
                    self._begin_edit(f)
            return

        if tab == Subtab.PEOPLE:
            if self._expanded_person is None:  # type: ignore[attr-defined]
                if self._people_data:  # type: ignore[attr-defined]
                    cursor = self._current_cursor()  # type: ignore[attr-defined]
                    if 0 <= cursor < len(self._people_data):  # type: ignore[attr-defined]
                        selected_person = self._people_data[cursor]  # type: ignore[attr-defined]
                        self._expanded_person = selected_person.slug or selected_person.name  # type: ignore[attr-defined]
                        self._person_field_cursor = 0  # type: ignore[attr-defined]
                        self.load_expanded_person_secrets()  # type: ignore[attr-defined]
                        self._status_message = (
                            f"Expanded {self._expanded_person}. Press Esc to collapse / navigate to other people."  # type: ignore[attr-defined]
                        )
                        self._status_is_error = False  # type: ignore[attr-defined]
                        self.refresh(layout=True)  # type: ignore[attr-defined]
            else:
                fields = self.person_reflected_fields
                if fields:
                    f = fields[self._person_field_cursor]
                    if f.input_kind is EditorInputKind.BOOLEAN:
                        self._save_editor_field(f.identity, ConfigEditIntent.REPLACE, not bool(f.value))
                    elif f.choices:
                        self.cycle_enum_field(1)
                    else:
                        self._begin_edit(f)
            return

        selected = self._current_selected_env()  # type: ignore[attr-defined]
        if selected is not None:
            self._begin_edit(selected)

    def _begin_edit(self, field_or_status: EditorFieldAnswer | EnvVarStatus) -> None:
        """Enter editing mode using supplied field values and generic input metadata."""
        if isinstance(field_or_status, EditorFieldAnswer):
            field = field_or_status
            if not field.editable:
                self._status_message = field.description or _DAEMON_UNAVAILABLE  # type: ignore[attr-defined]
                self._status_is_error = True  # type: ignore[attr-defined]
                self.refresh(layout=True)  # type: ignore[attr-defined]
                return
            self._editing_var_name = field.identity  # type: ignore[attr-defined]
            value = _EMPTY_TEXT if _is_write_only(field) else field.value
            if isinstance(value, list):
                self._edit_buffer = _EDIT_LIST_SEPARATOR.join(str(item) for item in value)  # type: ignore[attr-defined]
            else:
                self._edit_buffer = str(value if value is not None else _EMPTY_TEXT)  # type: ignore[attr-defined]
            self._status_message = _EDITING_STATUS.format(label=field.label)  # type: ignore[attr-defined]
        else:
            self._editing_var_name = field_or_status.info.name  # type: ignore[attr-defined]
            self._edit_buffer = _EMPTY_TEXT  # type: ignore[attr-defined]
            self._status_message = _EDITING_STATUS.format(label=field_or_status.info.name)  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def collapse_person(self) -> None:
        """Collapse the expanded person details."""
        self._expanded_person = None  # type: ignore[attr-defined]
        self._status_message = ""  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def append_edit_character(self, char: str) -> None:
        """Append a printable character to the active edit buffer."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        self._edit_buffer = f"{self._edit_buffer}{char}"  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def append_edit_text(self, text: str) -> None:
        """Append pasted text to the active edit buffer, flattening newlines (values are single-line)."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        cleaned = " ".join(text.splitlines())
        if not cleaned:
            return
        self._edit_buffer = f"{self._edit_buffer}{cleaned}"  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def backspace_edit(self) -> None:
        """Delete the final character from the active edit buffer."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        self._edit_buffer = self._edit_buffer[:-1]  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def clear_edit_buffer(self) -> None:
        """Clear the active edit buffer."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def clear_personal_secret_or_edit_buffer(self) -> None:
        """Clear a write-only field explicitly, or clear an ordinary edit buffer."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        field_id = self._editing_var_name  # type: ignore[attr-defined]
        if _SUBTABS[self.active_subtab] == Subtab.ENV and field_id is not None:  # type: ignore[attr-defined]
            operation_id = str(uuid4())
            observe_config_tui(ConfigTuiOutcome.SAVE_REQUESTED, operation_id=operation_id, field_paths=[field_id])
            self._editing_var_name = None  # type: ignore[attr-defined]
            self._edit_buffer = _EMPTY_TEXT  # type: ignore[attr-defined]

            async def clear_environment(operations: ConfigOperations) -> None:
                await operations.set_environment(ConfigEnvironment.MACHINE, clear=[field_id])

            self._submit_write(
                operation_id=operation_id,
                field_paths=[field_id],
                label=field_id,
                success_message=_CLEARED.format(label=field_id),
                action=clear_environment,
            )
            return
        field = self._active_write_only_field()
        if field is None:
            self.clear_edit_buffer()
            return
        self._save_editor_field(field.identity, ConfigEditIntent.CLEAR, None)

    def save_edit(self) -> None:
        """Submit the entered value or explicit keep intent to the configuration owner."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        field_id = self._editing_var_name  # type: ignore[attr-defined]
        if field_id is None:
            return
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            fields = self.reflected_fields  # type: ignore[attr-defined]
        elif tab == Subtab.PEOPLE and self._expanded_person is not None:  # type: ignore[attr-defined]
            fields = self.person_reflected_fields  # type: ignore[attr-defined]
        else:
            field = self._edit_buffer  # type: ignore[attr-defined]
            self._editing_var_name = None  # type: ignore[attr-defined]
            self._edit_buffer = _EMPTY_TEXT  # type: ignore[attr-defined]
            if not field:
                self._status_message = _KEPT.format(label=field_id)  # type: ignore[attr-defined]
                self._status_is_error = False  # type: ignore[attr-defined]
                self.refresh(layout=True)  # type: ignore[attr-defined]
                return
            operation_id = str(uuid4())
            observe_config_tui(ConfigTuiOutcome.SAVE_REQUESTED, operation_id=operation_id, field_paths=[field_id])

            async def write_environment(operations: ConfigOperations) -> None:
                await operations.set_environment(ConfigEnvironment.MACHINE, values=[(field_id, field)])

            self._submit_write(
                operation_id=operation_id,
                field_paths=[field_id],
                label=field_id,
                success_message=_SAVED.format(label=field_id),
                action=write_environment,
            )
            return
        field = next((item for item in fields if item.identity == field_id), None)
        if field is None:
            return
        intent = ConfigEditIntent.REPLACE
        value: object = self._edit_buffer  # type: ignore[attr-defined]
        if _is_write_only(field) and not self._edit_buffer:  # type: ignore[attr-defined]
            intent = ConfigEditIntent.KEEP
            value = None
        self._save_editor_field(field.identity, intent, value)

    @property
    def is_on_enum_field(self) -> bool:
        """Whether left/right acts on the current field (choice, boolean, or list)."""
        if self.is_editing:  # type: ignore[attr-defined]
            return False
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        fields = (
            self.person_reflected_fields if tab == Subtab.PEOPLE and self._expanded_person else self.reflected_fields
        )  # type: ignore[attr-defined]
        if not fields:
            return False
        cursor = self._person_field_cursor if tab == Subtab.PEOPLE and self._expanded_person else self._current_cursor()  # type: ignore[attr-defined]
        field = fields[max(0, min(cursor, len(fields) - 1))]
        return (
            bool(field.choices)
            or field.input_kind is EditorInputKind.BOOLEAN
            or field.input_kind
            in (
                EditorInputKind.STRING_LIST,
                EditorInputKind.VALUE_LIST,
            )
        )

    def cycle_enum_field(self, direction: int) -> None:
        """Cycle the active boolean/choice field or focus a list element."""
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        fields = (
            self.person_reflected_fields if tab == Subtab.PEOPLE and self._expanded_person else self.reflected_fields
        )  # type: ignore[attr-defined]
        cursor = self._person_field_cursor if tab == Subtab.PEOPLE and self._expanded_person else self._current_cursor()  # type: ignore[attr-defined]
        if not fields:
            return
        field = fields[max(0, min(cursor, len(fields) - 1))]
        if field.input_kind is EditorInputKind.BOOLEAN:
            self._save_editor_field(field.identity, ConfigEditIntent.REPLACE, not bool(field.value))
            return
        if field.choices:
            current = str(field.value)
            index = field.choices.index(current) if current in field.choices else -1
            self._save_editor_field(
                field.identity,
                ConfigEditIntent.REPLACE,
                field.choices[(index + direction) % len(field.choices)],
            )
            return
        if field.input_kind in (EditorInputKind.STRING_LIST, EditorInputKind.VALUE_LIST):
            values = field.value if isinstance(field.value, list) else []
            if values:
                self._list_element_idx = (self._list_element_idx + direction) % len(values)  # type: ignore[attr-defined]
                self.refresh(layout=True)  # type: ignore[attr-defined]

    def reorder_reflected_list(self, direction: int) -> None:
        """Shift the focused list element left or right and submit the new order."""
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        fields = (
            self.person_reflected_fields if tab == Subtab.PEOPLE and self._expanded_person else self.reflected_fields
        )  # type: ignore[attr-defined]
        cursor = self._person_field_cursor if tab == Subtab.PEOPLE and self._expanded_person else self._current_cursor()  # type: ignore[attr-defined]
        if not fields:
            return
        field = fields[max(0, min(cursor, len(fields) - 1))]
        if field.input_kind not in (EditorInputKind.STRING_LIST, EditorInputKind.VALUE_LIST):
            return
        values = list(field.value) if isinstance(field.value, list) else []
        if not values:
            return
        index = self._list_element_idx  # type: ignore[attr-defined]
        next_index = (index + direction) % len(values)
        values[index], values[next_index] = values[next_index], values[index]
        self._list_element_idx = next_index  # type: ignore[attr-defined]
        self._save_editor_field(field.identity, ConfigEditIntent.REPLACE, values)

    def _save_editor_field(self, field_id: str, intent: ConfigEditIntent, value: object) -> None:
        """Submit a field ID, the revisions supplied by its owner, and explicit edit intent."""
        operation_id = str(uuid4())
        fields = (
            self.person_reflected_fields  # type: ignore[attr-defined]
            if field_id.startswith((_SECRET_PREFIX, _IDENTITY_PREFIX, _OVERLAY_PREFIX))
            else self.reflected_fields  # type: ignore[attr-defined]
        )
        field = next((item for item in fields if item.identity == field_id), None)
        if field is None:
            return
        self._editing_var_name = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        observe_config_tui(ConfigTuiOutcome.SAVE_REQUESTED, operation_id=operation_id, field_paths=[field_id])
        self._submit_write(
            operation_id=operation_id,
            field_paths=[field_id],
            label=field.label,
            success_message=_KEPT.format(label=field.label)
            if intent is ConfigEditIntent.KEEP
            else _SAVED_FIELD.format(label=field.label),
            action=self._field_edit_action(field, intent, value),
        )

    def _field_edit_action(self, field: EditorFieldAnswer, intent: ConfigEditIntent, value: object) -> WriteAction:
        is_person = field.identity.startswith((_IDENTITY_PREFIX, _OVERLAY_PREFIX, _SECRET_PREFIX))
        slug = self._expanded_person if is_person else None  # type: ignore[attr-defined]

        async def write(operations: ConfigOperations) -> None:
            editor = self._people.get(slug) if slug is not None else self._machine_editor  # type: ignore[attr-defined]
            if editor is None:
                raise ConfigOperationFailed(ConfigFailureKind.INVALID, _DAEMON_UNAVAILABLE)
            kind = ConfigSubjectKind.PERSON if slug is not None else ConfigSubjectKind.COMPUTER
            answer = await operations.edit_field(
                kind,
                slug,
                editor.revision,
                editor.editor_revision,
                field.identity,
                intent,
                value,
            )
            if slug is None:
                self._machine_editor = answer  # type: ignore[attr-defined]
                self._machine_revision = answer.revision  # type: ignore[attr-defined]
                self._outside_scope = tuple(answer.outside_scope)  # type: ignore[attr-defined]
            else:
                self._people[slug] = answer  # type: ignore[attr-defined]
            self._reflected_cache.clear()  # type: ignore[attr-defined]

        return write

    def _submit_write(
        self,
        *,
        operation_id: str,
        field_paths: list[str],
        label: str,
        success_message: str,
        action: WriteAction,
        source: str = _CONFIG_SOURCE,
    ) -> None:
        """Run one write on the daemon, in order after the writes before it, then show the subject as it now is."""
        operations = self._operations()  # type: ignore[attr-defined]
        if operations is None:
            self._status_message = _DAEMON_UNAVAILABLE  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return
        self.run_worker(  # type: ignore[attr-defined]
            self._perform_write(operations, operation_id, field_paths, label, success_message, action, source),
            exclusive=False,
            group=_WRITE_GROUP,
        )

    async def _perform_write(
        self,
        operations: ConfigOperations,
        operation_id: str,
        field_paths: list[str],
        label: str,
        success_message: str,
        action: WriteAction,
        source: str,
    ) -> None:
        async with self._write_lock:  # type: ignore[attr-defined]
            try:
                await action(operations)
            except ConfigOperationFailed as failure:
                observe_config_tui(
                    ConfigTuiOutcome.FAILED, operation_id=operation_id, field_paths=field_paths, source=source
                )
                stale = failure.kind is ConfigFailureKind.STALE_REVISION
                self._status_message = (  # type: ignore[attr-defined]
                    _STALE_REVISION_MESSAGE.format(label=label)
                    if stale
                    else _SAVE_FAILED.format(label=label, error=failure)
                )
                self._status_is_error = True  # type: ignore[attr-defined]
            except Exception as exc:
                observe_config_tui(
                    ConfigTuiOutcome.FAILED, operation_id=operation_id, field_paths=field_paths, source=source
                )
                self._status_message = _SAVE_FAILED.format(label=label, error=exc)  # type: ignore[attr-defined]
                self._status_is_error = True  # type: ignore[attr-defined]
            else:
                observe_config_tui(
                    ConfigTuiOutcome.SAVED, operation_id=operation_id, field_paths=field_paths, source=source
                )
                self._status_message = success_message  # type: ignore[attr-defined]
                self._status_is_error = False  # type: ignore[attr-defined]
            await self._load_snapshot(operations)  # type: ignore[attr-defined]

    def _active_write_only_field(self) -> EditorFieldAnswer | None:
        """Return the currently edited sensitive field, if any."""
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        fields = (
            self.person_reflected_fields  # type: ignore[attr-defined]
            if tab == Subtab.PEOPLE and self._expanded_person is not None  # type: ignore[attr-defined]
            else self.reflected_fields  # type: ignore[attr-defined]
        )
        return next(
            (
                field
                for field in fields
                if field.identity == self._editing_var_name and _is_write_only(field)  # type: ignore[attr-defined]
            ),
            None,
        )

    def cancel_edit(self) -> None:
        """Cancel the current env-var or person-field edit."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        var_name = self._editing_var_name  # type: ignore[attr-defined]
        self._editing_var_name = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        if var_name:
            self._status_message = f"Canceled edit for {var_name}"  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def toggle_guided_mode(self) -> None:
        """Toggle guided setup mode."""
        if self._guided_mode:  # type: ignore[attr-defined]
            self._guided_mode = False  # type: ignore[attr-defined]
            self._status_message = "Guided mode exited"  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return

        self._guided_mode = True  # type: ignore[attr-defined]
        self._guided_step_index = 0  # type: ignore[attr-defined]
        self._apply_guided_step()
        self._status_message = "Guided mode started"  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def _advance_guided_step(self) -> None:
        """Advance guided setup to the next incomplete step."""
        if not self._guided_mode:  # type: ignore[attr-defined]
            return
        if self._guided_step_index >= len(_GUIDED_STEPS) - 1:  # type: ignore[attr-defined]
            self._guided_mode = False  # type: ignore[attr-defined]
            self._status_message = "Guided setup complete"  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return

        self._guided_step_index += 1  # type: ignore[attr-defined]
        self._apply_guided_step()
        self._auto_advance_completed_steps()
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def _apply_guided_step(self) -> None:
        """Apply the active guided-step focus and cursor placement."""
        step = _GUIDED_STEPS[self._guided_step_index]  # type: ignore[attr-defined]
        self.active_subtab = _SUBTABS.index(step.subtab)  # type: ignore[attr-defined]
        if step.adapter_tab is not None:
            self.active_adapter_tab = _ADAPTER_TABS.index(step.adapter_tab)  # type: ignore[attr-defined]
        self._clamp_current_cursor()  # type: ignore[attr-defined]
        # Auto-position cursor on the first unset var so guidance expands
        if step.subtab in (Subtab.ADAPTERS, Subtab.ENV):
            rows = self._selectable_env_rows()  # type: ignore[attr-defined]
            for idx, status in enumerate(rows):
                if not status.is_set:
                    self._set_current_cursor(idx)  # type: ignore[attr-defined]
                    return

    def _auto_advance_completed_steps(self) -> None:
        """Skip over guided steps that are already satisfied."""
        while self._guided_mode and self._is_current_guided_step_complete():  # type: ignore[attr-defined]
            if self._guided_step_index >= len(_GUIDED_STEPS) - 1:  # type: ignore[attr-defined]
                self._guided_mode = False  # type: ignore[attr-defined]
                self._status_message = "Guided setup complete"  # type: ignore[attr-defined]
                self._status_is_error = False  # type: ignore[attr-defined]
                break
            self._guided_step_index += 1  # type: ignore[attr-defined]
            self._apply_guided_step()

    def _is_current_guided_step_complete(self) -> bool:
        """Return whether the active guided step is already complete."""
        step = _GUIDED_STEPS[self._guided_step_index]  # type: ignore[attr-defined]
        if step.subtab in (Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            # Non-blocking or immediately considered complete
            return True
        if step.subtab == Subtab.INFRA:
            redis_url = next(
                (field for field in self.reflected_fields if field.identity == _REDIS_URL_ID),  # type: ignore[attr-defined]
                None,
            )
            if redis_url is not None and redis_url.value_state is EditorValueState.UNRESOLVED:
                disposition = _RedisUrl.UNRESOLVED
                complete = False
            elif redis_url is None or redis_url.value_state is EditorValueState.DEFAULT:
                disposition = _RedisUrl.DEFAULT
                complete = False
            else:
                disposition = _RedisUrl.EXPLICIT
                complete = True
            observe_config_tui(
                ConfigTuiOutcome.GUIDED_COMPLETENESS,
                operation_id=str(uuid4()),
                step="infra",
                complete=complete,
                source=disposition,
            )
            return complete
        if step.subtab == Subtab.PEOPLE:
            # People step is complete with at least one admin-role person.
            return any(p.role == "admin" for p in self._people_data)  # type: ignore[attr-defined]
        if step.subtab == Subtab.ENV:
            return bool(self._env_data) and all(  # type: ignore[attr-defined]
                status.is_set for status in self._env_data
            )
        return False
