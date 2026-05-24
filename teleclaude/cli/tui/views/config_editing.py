"""Editing and guided-mode mixin for ConfigContent."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, get_origin

from teleclaude.cli.config_handlers import (
    EnvVarStatus,
    get_global_config,
    rename_person,
    save_global_config,
    set_env_var,
)
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _GUIDED_STEPS,
    _SUBTABS,
    _VALID_ROLES,
    get_allowed_values_for_field,
)
from teleclaude.config.schema import PersonEntry

if TYPE_CHECKING:
    from teleclaude.cli.tui.views._config_constants import AdapterSectionProjection


class ConfigContentEditingMixin:
    """Cursor movement, inline editing, and guided-mode logic for ConfigContent."""

    if TYPE_CHECKING:
        _adapter_sections: list[AdapterSectionProjection]
        _env_data: list[EnvVarStatus]
        _people_data: list[PersonEntry]

        @property
        def person_editable_fields(self) -> list[str]: ...

    def move_cursor(self, delta: int) -> None:
        """Move the cursor within the active config section."""
        if self.is_editing:  # type: ignore[attr-defined]
            return
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab == "people":
            if self._expanded_person is not None:  # type: ignore[attr-defined]
                self._person_field_cursor = max(  # type: ignore[attr-defined]
                    0,
                    min(
                        self._person_field_cursor + delta,
                        len(self.person_editable_fields) - 1,
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
        if self._editing_person_field is not None:  # type: ignore[attr-defined]
            self._save_person_field()
            return
        if self._editing_var_name is not None:  # type: ignore[attr-defined]
            self.save_edit()
            return

        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab == "people":
            if self._expanded_person is None:  # type: ignore[attr-defined]
                if self._people_data:  # type: ignore[attr-defined]
                    cursor = self._current_cursor()  # type: ignore[attr-defined]
                    if 0 <= cursor < len(self._people_data):  # type: ignore[attr-defined]
                        self._expanded_person = self._people_data[cursor].name  # type: ignore[attr-defined]
                        self._person_field_cursor = 0  # type: ignore[attr-defined]
                        self._status_message = (
                            f"Expanded {self._expanded_person}. Press Esc to collapse / navigate to other people."  # type: ignore[attr-defined]
                        )
                        self._status_is_error = False  # type: ignore[attr-defined]
                        self.refresh(layout=True)  # type: ignore[attr-defined]
            else:
                person = next(  # type: ignore[attr-defined]
                    (p for p in self._people_data if p.name == self._expanded_person),
                    None,
                )
                if person is not None:
                    field = self.person_editable_fields[self._person_field_cursor]  # type: ignore[attr-defined]
                    if get_allowed_values_for_field(field) is not None:
                        self._cycle_person_enum(person, field, 1)
                    else:
                        self._begin_person_field_edit(person, field)
            return

        selected = self._current_selected_env()  # type: ignore[attr-defined]
        if selected is not None:
            self._begin_edit(selected)

    def _begin_edit(self, status: EnvVarStatus) -> None:
        """Enter env-var editing mode for the provided status row."""
        self._editing_var_name = status.info.name  # type: ignore[attr-defined]
        self._edit_buffer = os.environ.get(status.info.name, "")  # type: ignore[attr-defined]
        self._status_message = f"Editing {status.info.name}. Enter saves, Esc cancels."  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def _cycle_person_enum(self, person: object, field_name: str, direction: int = 1) -> None:
        """Dynamically cycle any Literal/enum-backed field in the requested direction."""
        allowed_values = get_allowed_values_for_field(field_name)
        if not allowed_values:
            return

        current_val = None
        if ":" in field_name:
            parent, child = field_name.split(":", 1)
            raw_parent = getattr(person, parent, None) or {}
            current_val = raw_parent.get(child, allowed_values[0])
        else:
            current_val = getattr(person, field_name, allowed_values[0])

        idx = allowed_values.index(current_val) if current_val in allowed_values else -1
        next_val = allowed_values[(idx + direction) % len(allowed_values)]

        try:
            config = get_global_config()
            for p in config.people:
                if p.name == getattr(person, "name", ""):
                    if ":" in field_name:
                        parent, child = field_name.split(":", 1)
                        raw_parent = getattr(p, parent, None)
                        if not isinstance(raw_parent, dict):
                            raw_parent = {}
                            setattr(p, parent, raw_parent)
                        raw_parent[child] = next_val
                    else:
                        setattr(p, field_name, next_val)
                    break
            save_global_config(config)
            self._status_message = f"Set {field_name} to {next_val}"  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
        except Exception as exc:
            self._status_message = f"Failed to save {field_name}: {exc}"  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
        self.refresh_data()  # type: ignore[attr-defined]

    def _begin_person_field_edit(self, person: object, field: str) -> None:
        """Enter edit mode for a specific field on the expanded person."""
        self._editing_person_field = field  # type: ignore[attr-defined]
        if ":" in field:
            parent, child = field.split(":", 1)
            raw_parent = getattr(person, parent, {})
            val = raw_parent.get(child, "") if isinstance(raw_parent, dict) else ""
            self._edit_buffer = str(val or "")
        else:
            raw_val = getattr(person, field, None)
            if isinstance(raw_val, dict):
                # Editing a parent dictionary prompts to add a new skill key
                self._edit_buffer = ""
                person_name = getattr(person, "name", "")
                self._status_message = f"Add new key to {person_name}.{field}: Enter name of the key"  # type: ignore[attr-defined]
                self._status_is_error = False  # type: ignore[attr-defined]
                self.refresh(layout=True)  # type: ignore[attr-defined]
                return
            elif isinstance(raw_val, list):
                self._edit_buffer = json.dumps(raw_val)
            else:
                self._edit_buffer = str(raw_val or "")
        person_name = getattr(person, "name", "")
        self._status_message = f"Editing {person_name}.{field}. Enter saves, Esc cancels."  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def _save_person_field(self) -> None:
        """Persist the current person-field edit."""
        if self._editing_person_field is None or self._expanded_person is None:  # type: ignore[attr-defined]
            return

        field = self._editing_person_field  # type: ignore[attr-defined]
        value = self._edit_buffer  # type: ignore[attr-defined]
        person_name = self._expanded_person  # type: ignore[attr-defined]

        if field == "role" and value not in _VALID_ROLES:
            self._status_message = f"Invalid role. Valid: {', '.join(_VALID_ROLES)}"  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return

        try:
            config = get_global_config()
            for p in config.people:
                if p.name == person_name:
                    if ":" in field:
                        parent, child = field.split(":", 1)
                        raw_parent = getattr(p, parent, None)
                        if not isinstance(raw_parent, dict):
                            raw_parent = {}
                            setattr(p, parent, raw_parent)
                        raw_parent[child] = value
                    else:
                        if field == "name" and value != person_name:
                            rename_person(person_name, value)
                            self._expanded_person = value  # type: ignore[attr-defined]

                        # Detect if field is a dict or list to parse appropriately
                        current_val = getattr(p, field, None)
                        is_dict = isinstance(current_val, dict)

                        if not is_dict and field in PersonEntry.model_fields:
                            ann = PersonEntry.model_fields[field].annotation
                            is_dict = get_origin(ann) is dict or ann is dict

                        if is_dict:
                            # Adding a new key to the dict
                            if value.strip():
                                if current_val is None:
                                    current_val = {}
                                    setattr(p, field, current_val)
                                current_val[value.strip()] = "novice"
                        elif isinstance(current_val, list):
                            setattr(p, field, json.loads(value))
                        else:
                            setattr(p, field, value or None)
                    break
            save_global_config(config)
            self._status_message = f"Saved {self._expanded_person}.{field}"  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
        except Exception as exc:
            self._status_message = f"Failed to save: {exc}"  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]

        self._editing_person_field = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self.refresh_data()  # type: ignore[attr-defined]

    def collapse_person(self) -> None:
        """Collapse the expanded person details and exit person editing."""
        self._expanded_person = None  # type: ignore[attr-defined]
        self._editing_person_field = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def append_edit_character(self, char: str) -> None:
        """Append a printable character to the active edit buffer."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        self._edit_buffer = f"{self._edit_buffer}{char}"  # type: ignore[attr-defined]
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

    def save_edit(self) -> None:
        """Persist the current env-var edit."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        var_name = self._editing_var_name  # type: ignore[attr-defined]
        if var_name is None:
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

    def cancel_edit(self) -> None:
        """Cancel the current env-var or person-field edit."""
        if self._editing_person_field is not None:  # type: ignore[attr-defined]
            field = self._editing_person_field  # type: ignore[attr-defined]
            self._editing_person_field = None  # type: ignore[attr-defined]
            self._edit_buffer = ""  # type: ignore[attr-defined]
            self._status_message = f"Canceled edit for {field}"  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return
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
        if step.subtab in ("adapters", "environment"):
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
        if step.subtab == "adapters":
            # Adapter steps are non-blocking; we store by contract, validation is feedback only.
            return True
        if step.subtab == "people":
            # People step is complete if we have at least one person with 'admin' role.
            return any(p.role == "admin" for p in self._people_data)  # type: ignore[attr-defined]
        if step.subtab == "notifications":
            # Notifications are optional.
            return True
        if step.subtab == "environment":
            return bool(self._env_data) and all(  # type: ignore[attr-defined]
                status.is_set for status in self._env_data
            )
        return False
