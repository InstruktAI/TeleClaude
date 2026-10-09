"""Editing and guided-mode mixin for ConfigContent."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, get_args
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from teleclaude.cli.config_handlers import (
    EnvVarStatus,
    PersonMcpSecretManagementError,
    clear_person_mcp_secret_value,
    get_global_config,
    get_person_config,
    replace_person_mcp_secret_value,
    save_global_config,
    save_person_config,
    set_env_var,
)
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _GUIDED_STEPS,
    _SUBTABS,
    AdapterSectionProjection,
    ConfigTuiOutcome,
    Subtab,
    observe_config_tui,
)
from teleclaude.cli.tui.views.reflection import ReflectedField, deserialize_value
from teleclaude.config._environment import mutate_environment_value
from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.machine import reload_config
from teleclaude.config.machine_config_mutation import set_machine_field
from teleclaude.config.validation import is_unresolved_placeholder


def _zero_value(annotation: Any) -> Any:
    """A schema-valid placeholder for a required field, by declared type."""
    for candidate in get_args(annotation) or (annotation,):
        if candidate is type(None):
            continue
        if candidate is str:
            return ""
        if candidate is bool:
            return False
        if candidate is int:
            return 0
        if candidate is float:
            return 0.0
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return _blank_model(candidate)
        return None
    return None


def _blank_model(model_type: type[BaseModel]) -> BaseModel:
    """Build a schema-valid instance with placeholders for every required field.

    Editing a multi-field credential submodel one leaf at a time would otherwise
    deadlock: the first single-leaf save is always partial. Seeding required
    siblings with type-zero placeholders keeps the submodel valid from the first
    save, leaving the placeholders visible for the human to complete.
    """
    values = {
        name: _zero_value(field_info.annotation)
        for name, field_info in model_type.model_fields.items()
        if field_info.is_required()
    }
    return model_type.model_validate(values)


def _instantiate_nested_config_model(annotation: Any) -> BaseModel:
    for candidate in get_args(annotation) or (annotation,):
        if candidate is type(None):
            continue
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return _blank_model(candidate)
    raise TypeError(f"Cannot instantiate nested config field for {annotation!r}")


class ConfigContentEditingMixin:
    """Cursor movement, inline editing, and guided-mode logic for ConfigContent."""

    if TYPE_CHECKING:
        _adapter_sections: list[AdapterSectionProjection]
        _env_data: list[EnvVarStatus]
        _people_data: list[PersonEntry]

        @property
        def person_reflected_fields(self) -> list[ReflectedField]: ...

        @property
        def reflected_fields(self) -> list[ReflectedField]: ...

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
                if f.field_type is bool:
                    self._save_reflected_field(f.key, not f.value)
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
                        self._status_message = (
                            f"Expanded {self._expanded_person}. Press Esc to collapse / navigate to other people."  # type: ignore[attr-defined]
                        )
                        self._status_is_error = False  # type: ignore[attr-defined]
                        self.refresh(layout=True)  # type: ignore[attr-defined]
            else:
                fields = self.person_reflected_fields
                if fields:
                    f = fields[self._person_field_cursor]
                    if f.field_type is bool:
                        self._save_reflected_field(f.key, not f.value)
                    elif f.choices:
                        self.cycle_enum_field(1)
                    else:
                        self._begin_edit(f)
            return

        selected = self._current_selected_env()  # type: ignore[attr-defined]
        if selected is not None:
            self._begin_edit(selected)

    def _begin_edit(self, field_or_status: Any) -> None:
        """Enter editing mode for reflected fields or env vars."""
        if isinstance(field_or_status, ReflectedField):
            if field_or_status.write_only and not field_or_status.secret_available:
                self._status_message = field_or_status.description or "Personal secret storage is unavailable."  # type: ignore[attr-defined]
                self._status_is_error = True  # type: ignore[attr-defined]
                self.refresh(layout=True)  # type: ignore[attr-defined]
                return
            self._editing_var_name = field_or_status.key  # type: ignore[attr-defined]
            val = "" if field_or_status.write_only else field_or_status.value
            if isinstance(val, list):
                self._edit_buffer = ",".join(val)  # type: ignore[attr-defined]
            else:
                self._edit_buffer = str(val if val is not None else "")  # type: ignore[attr-defined]
            self._status_message = f"Editing {field_or_status.name}. Enter saves, Esc cancels."  # type: ignore[attr-defined]
        else:
            self._editing_var_name = field_or_status.info.name  # type: ignore[attr-defined]
            # guard: direct-env-read - allowed: environment-file management
            self._edit_buffer = os.environ.get(field_or_status.info.name, "")  # type: ignore[attr-defined]
            self._status_message = f"Editing {field_or_status.info.name}. Enter saves, Esc cancels."  # type: ignore[attr-defined]
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
        """Clear a write-only personal secret, or clear an ordinary active buffer."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        field = self._active_personal_secret_field()
        if field is None:
            reflected = next(
                (candidate for candidate in self.reflected_fields if candidate.key == self._editing_var_name),
                None,  # type: ignore[attr-defined]
            )
            if reflected is not None and reflected.write_only and reflected.environment is not None:
                mutate_environment_value(reflected.environment.path, reflected.environment.name, None)
                self._editing_var_name = None  # type: ignore[attr-defined]
                self._edit_buffer = ""  # type: ignore[attr-defined]
                self.refresh_data()  # type: ignore[attr-defined]
                return
            self.clear_edit_buffer()
            return
        operation_id = str(uuid4())
        observe_config_tui(ConfigTuiOutcome.SAVE_REQUESTED, operation_id=operation_id, field_paths=[field.key])
        try:
            clear_person_mcp_secret_value(self._expanded_person, field.name)  # type: ignore[attr-defined]
        except PersonMcpSecretManagementError:
            observe_config_tui(
                ConfigTuiOutcome.FAILED, operation_id=operation_id, field_paths=[field.key], source="config"
            )
            self._status_message = "Personal MCP secret management failed."  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return
        self._editing_var_name = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self._status_message = f"Cleared {field.name}."  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        observe_config_tui(ConfigTuiOutcome.SAVED, operation_id=operation_id, field_paths=[field.key], source="config")
        self.refresh_data()  # type: ignore[attr-defined]

    def save_edit(self) -> None:
        """Persist the current env-var or reflected field edit."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        var_name = self._editing_var_name  # type: ignore[attr-defined]
        if var_name is None:
            return

        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            self._save_reflected_field(var_name, self._edit_buffer)  # type: ignore[attr-defined]
            return
        if tab == Subtab.PEOPLE and self._expanded_person is not None:  # type: ignore[attr-defined]
            self._save_reflected_field(var_name, self._edit_buffer)  # type: ignore[attr-defined]
            return

        try:
            target_path = set_env_var(var_name, self._edit_buffer)  # type: ignore[attr-defined]
        except Exception as exc:
            self._status_message = f"Failed to save {var_name}: {exc}"  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return

        self._editing_var_name = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self._status_message = f"Saved {var_name} to {target_path}"  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        self.refresh_data()  # type: ignore[attr-defined]

    @property
    def is_on_enum_field(self) -> bool:
        """Whether left/right acts on the current field (enum, list, or bool)."""
        if self.is_editing:  # type: ignore[attr-defined]
            return False
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            fields = self.reflected_fields  # type: ignore[attr-defined]
            if not fields:
                return False
            cursor = self._current_cursor()  # type: ignore[attr-defined]
            f = fields[max(0, min(cursor, len(fields) - 1))]
            return bool(f.choices) or f.field_type is bool or f.field_type in (list[str], list)
        if tab == Subtab.PEOPLE and self._expanded_person is not None:  # type: ignore[attr-defined]
            fields = self.person_reflected_fields
            if not fields:
                return False
            f = fields[self._person_field_cursor]  # type: ignore[attr-defined]
            return bool(f.choices) or f.field_type is bool or f.field_type in (list[str], list)
        return False

    def cycle_enum_field(self, direction: int) -> None:
        """Cycle the active enum/list/bool field in the requested direction."""
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab == Subtab.PEOPLE and self._expanded_person is not None:  # type: ignore[attr-defined]
            fields = self.person_reflected_fields
            cursor = self._person_field_cursor  # type: ignore[attr-defined]
        else:
            fields = self.reflected_fields  # type: ignore[attr-defined]
            cursor = self._current_cursor()  # type: ignore[attr-defined]

        if fields:
            f = fields[max(0, min(cursor, len(fields) - 1))]

            # Booleans toggle between True/False.
            if f.field_type is bool:
                self._save_reflected_field(f.key, not f.value)
                return

            # If it's a Literal/Enum
            if f.choices:
                current_val = str(f.value)
                idx = f.choices.index(current_val) if current_val in f.choices else -1
                next_val = f.choices[(idx + direction) % len(f.choices)]
                self._save_reflected_field(f.key, next_val)
                return

            # If it's a list/array
            elif f.field_type in (list[str], list):
                items = f.value or []
                if items:
                    self._list_element_idx = (self._list_element_idx + direction) % len(items)  # type: ignore[attr-defined]
                    self.refresh(layout=True)  # type: ignore[attr-defined]
                return

    def reorder_reflected_list(self, direction: int) -> None:
        """Shift the focused list element left (-1) or right (1)."""
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab == Subtab.PEOPLE and self._expanded_person is not None:  # type: ignore[attr-defined]
            fields = self.person_reflected_fields
            cursor = self._person_field_cursor  # type: ignore[attr-defined]
        else:
            fields = self.reflected_fields  # type: ignore[attr-defined]
            cursor = self._current_cursor()  # type: ignore[attr-defined]

        if fields:
            f = fields[max(0, min(cursor, len(fields) - 1))]
            if f.field_type in (list[str], list):
                items = list(f.value or [])
                if not items:
                    return

                idx = self._list_element_idx  # type: ignore[attr-defined]
                new_idx = (idx + direction) % len(items)

                # Swap elements
                items[idx], items[new_idx] = items[new_idx], items[idx]
                self._list_element_idx = new_idx  # type: ignore[attr-defined]

                self._save_reflected_field(f.key, items)

    def _save_reflected_field(self, key: str, raw_value: Any) -> None:
        """Parse, validate, and write a reflected field value back to its source."""
        operation_id = str(uuid4())
        observe_config_tui(ConfigTuiOutcome.SAVE_REQUESTED, operation_id=operation_id, field_paths=[key])
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab == Subtab.PEOPLE and self._expanded_person is not None:  # type: ignore[attr-defined]
            fields = self.person_reflected_fields
        else:
            fields = self.reflected_fields  # type: ignore[attr-defined]

        f = next((field for field in fields if field.key == key), None)
        if f is None:
            return

        if f.write_only and f.environment is not None:
            if not str(raw_value).strip():
                self._editing_var_name = None  # type: ignore[attr-defined]
                self._edit_buffer = ""  # type: ignore[attr-defined]
                self.refresh(layout=True)  # type: ignore[attr-defined]
                return
            set_env_var(f.environment.name, str(raw_value), f.environment.path)
            self._editing_var_name = None  # type: ignore[attr-defined]
            self._edit_buffer = ""  # type: ignore[attr-defined]
            self.refresh_data()  # type: ignore[attr-defined]
            return

        if f.write_only:
            try:
                self._save_personal_secret(f, str(raw_value), operation_id)
            except PersonMcpSecretManagementError:
                observe_config_tui(
                    ConfigTuiOutcome.FAILED,
                    operation_id=operation_id,
                    field_paths=[key],
                    source="config",
                )
                self._status_message = "Personal MCP secret management failed."  # type: ignore[attr-defined]
                self._status_is_error = True  # type: ignore[attr-defined]
                self.refresh(layout=True)  # type: ignore[attr-defined]
            return

        try:
            deserialized = deserialize_value(raw_value, f.field_type, f.choices)

            if f.environment is not None:
                # ${VAR}-backed field: persist to .env, leave the placeholder in config.yml.
                set_env_var(f.environment.name, str(deserialized), f.environment.path)
                if f.owning_source == "machine":
                    reload_config()
            elif f.owning_source == "machine":
                result = set_machine_field(tuple(key.split(".")), deserialized)
                self._raw_config = dict(result.raw)  # type: ignore[attr-defined]
            elif f.owning_source == "global":
                global_config = get_global_config()
                person_key = self._expanded_person  # type: ignore[attr-defined]
                for p in global_config.people:
                    if (p.slug or p.name) == person_key:
                        key_without_prefix = key.split(".", 1)[1]
                        if ":" in key_without_prefix:
                            parent, child = key_without_prefix.split(":", 1)
                            raw_parent = getattr(p, parent, None)
                            if not isinstance(raw_parent, dict):
                                raw_parent = {}
                                setattr(p, parent, raw_parent)
                            raw_parent[child] = deserialized
                        else:
                            # Editing the name updates the display field only; the
                            # slug and the workspace folder are immutable.
                            setattr(p, key_without_prefix, deserialized)
                        break
                save_global_config(global_config)
            elif f.owning_source == "per-person":
                person_key = self._expanded_person  # type: ignore[attr-defined]
                person_config = get_person_config(person_key)

                key_without_prefix = key.split(".", 1)[1]
                parts = key_without_prefix.split(".")

                obj = person_config
                for part in parts[:-1]:
                    val = getattr(obj, part)
                    if val is None:
                        field_info = type(obj).model_fields[part]
                        val = _instantiate_nested_config_model(field_info.annotation)
                        setattr(obj, part, val)
                    obj = val

                setattr(obj, parts[-1], deserialized)

                # A nested optional submodel (e.g. a credential block) is instantiated
                # on demand above; refuse to persist it while a required sibling is
                # still unset, rather than writing a structurally invalid overlay.
                try:
                    type(person_config).model_validate(person_config.model_dump())
                except ValidationError as exc:
                    self._status_message = (
                        f"Cannot save {f.name} yet: {exc.error_count()} required field(s) still missing."  # type: ignore[attr-defined]
                    )
                    self._status_is_error = True  # type: ignore[attr-defined]
                    return

                save_person_config(person_key, person_config)
            self._editing_var_name = None  # type: ignore[attr-defined]
            self._edit_buffer = ""  # type: ignore[attr-defined]
            self._status_message = f"Saved {f.name} successfully."  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
            observe_config_tui(
                ConfigTuiOutcome.SAVED,
                operation_id=operation_id,
                field_paths=[key],
                source="environment" if f.env_var else "config",
            )
            self.refresh_data()  # type: ignore[attr-defined]

        except Exception as exc:
            observe_config_tui(
                ConfigTuiOutcome.FAILED,
                operation_id=operation_id,
                field_paths=[key],
                source="environment" if f.env_var else "config",
            )
            self._status_message = f"Failed to save {f.name}: {exc}"  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]

    def _active_personal_secret_field(self) -> ReflectedField | None:
        """Return the currently edited write-only personal secret field, if any."""
        if self._expanded_person is None:  # type: ignore[attr-defined]
            return None
        return next(
            (
                field
                for field in self.person_reflected_fields
                if field.key == self._editing_var_name and field.write_only  # type: ignore[attr-defined]
            ),
            None,
        )

    def _save_personal_secret(self, field: ReflectedField, value: str, operation_id: str) -> None:
        """Keep or replace a personal secret without placing its prior value in UI state."""
        if value:
            replace_person_mcp_secret_value(self._expanded_person, field.name, value)  # type: ignore[attr-defined]
            outcome = f"Updated {field.name}."
        else:
            outcome = f"Kept {field.name}."
        self._editing_var_name = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self._status_message = outcome  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        observe_config_tui(ConfigTuiOutcome.SAVED, operation_id=operation_id, field_paths=[field.key], source="config")
        self.refresh_data()  # type: ignore[attr-defined]

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
            redis = self._raw_config.get("redis", {})  # type: ignore[attr-defined]
            redis_url = redis.get("url") if isinstance(redis, dict) else None
            if redis_url is None:
                disposition = "default"
                complete = False
            elif is_unresolved_placeholder(redis_url):
                disposition = "unresolved"
                complete = False
            else:
                disposition = "explicit"
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
