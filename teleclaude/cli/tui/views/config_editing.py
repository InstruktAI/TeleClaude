"""Editing and guided-mode mixin for ConfigContent."""

from __future__ import annotations

import os

from teleclaude.cli.config_handlers import EnvVarStatus, set_env_var
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _GUIDED_STEPS,
    _PERSON_EDITABLE_FIELDS,
    _SUBTABS,
    _VALID_ROLES,
)


class ConfigContentEditingMixin:
    """Cursor movement, inline editing, and guided-mode logic for ConfigContent."""

    def move_cursor(self, delta: int) -> None:
        if self.is_editing:  # type: ignore[attr-defined]
            return
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab == "people":
            if self._expanded_person is not None:  # type: ignore[attr-defined]
                self._person_field_cursor = max(  # type: ignore[attr-defined]
                    0,
                    min(self._person_field_cursor + delta, len(_PERSON_EDITABLE_FIELDS) - 1),  # type: ignore[attr-defined]
                )
            elif self._people_data:  # type: ignore[attr-defined]
                self._set_current_cursor(max(0, min(self._current_cursor() + delta, len(self._people_data) - 1)))  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return
        rows = self._selectable_env_rows()  # type: ignore[attr-defined]
        if not rows:
            return
        next_cursor = max(0, min(self._current_cursor() + delta, len(rows) - 1))  # type: ignore[attr-defined]
        self._set_current_cursor(next_cursor)  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def activate_current(self) -> None:
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
                        self.refresh(layout=True)  # type: ignore[attr-defined]
            else:
                person = next((p for p in self._people_data if p.name == self._expanded_person), None)  # type: ignore[attr-defined]
                if person is not None:
                    field = _PERSON_EDITABLE_FIELDS[self._person_field_cursor]  # type: ignore[attr-defined]
                    if field != "role":
                        self._begin_person_field_edit(person, field)
            return

        selected = self._current_selected_env()  # type: ignore[attr-defined]
        if selected is not None:
            self._begin_edit(selected)

    def _begin_edit(self, status: EnvVarStatus) -> None:
        self._editing_var_name = status.info.name  # type: ignore[attr-defined]
        self._edit_buffer = os.environ.get(status.info.name, "")  # type: ignore[attr-defined]
        self._status_message = f"Editing {status.info.name}. Enter saves, Esc cancels."  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def _cycle_person_role(self, person: object, direction: int = 1) -> None:
        from teleclaude.cli.config_handlers import get_global_config, save_global_config

        current = getattr(person, "role", "")
        idx = _VALID_ROLES.index(current) if current in _VALID_ROLES else -1
        next_role = _VALID_ROLES[(idx + direction) % len(_VALID_ROLES)]
        try:
            config = get_global_config()
            for p in config.people:
                if p.name == getattr(person, "name", ""):
                    p.role = next_role  # type: ignore[assignment]
                    break
            save_global_config(config)
            self._status_message = f"Role set to {next_role}"  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
        except Exception as exc:
            self._status_message = f"Failed to save role: {exc}"  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
        self.refresh_data()  # type: ignore[attr-defined]

    def _begin_person_field_edit(self, person: object, field: str) -> None:
        self._editing_person_field = field  # type: ignore[attr-defined]
        self._edit_buffer = str(getattr(person, field, "") or "")  # type: ignore[attr-defined]
        self._status_message = f"Editing {getattr(person, 'name', '')}.{field}. Enter saves, Esc cancels."  # type: ignore[attr-defined]
        self._status_is_error = False  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def _save_person_field(self) -> None:
        if self._editing_person_field is None or self._expanded_person is None:  # type: ignore[attr-defined]
            return
        from teleclaude.cli.config_handlers import get_global_config, save_global_config

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
                    setattr(p, field, value or None)
                    break
            save_global_config(config)
            self._status_message = f"Saved {person_name}.{field}"  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
        except Exception as exc:
            self._status_message = f"Failed to save: {exc}"  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]

        self._editing_person_field = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self.refresh_data()  # type: ignore[attr-defined]

    def collapse_person(self) -> None:
        self._expanded_person = None  # type: ignore[attr-defined]
        self._editing_person_field = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def append_edit_character(self, char: str) -> None:
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        self._edit_buffer = f"{self._edit_buffer}{char}"  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def backspace_edit(self) -> None:
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        self._edit_buffer = self._edit_buffer[:-1]  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def clear_edit_buffer(self) -> None:
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def save_edit(self) -> None:
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
        while self._guided_mode and self._is_current_guided_step_complete():  # type: ignore[attr-defined]
            if self._guided_step_index >= len(_GUIDED_STEPS) - 1:  # type: ignore[attr-defined]
                self._guided_mode = False  # type: ignore[attr-defined]
                self._status_message = "Guided setup complete"  # type: ignore[attr-defined]
                self._status_is_error = False  # type: ignore[attr-defined]
                break
            self._guided_step_index += 1  # type: ignore[attr-defined]
            self._apply_guided_step()

    def _is_current_guided_step_complete(self) -> bool:
        step = _GUIDED_STEPS[self._guided_step_index]  # type: ignore[attr-defined]
        if step.subtab == "adapters":
            section = next(
                (item for item in self._adapter_sections if item.key == step.adapter_tab),
                None,  # type: ignore[attr-defined]
            )
            return bool(section and section.status == "configured")
        if step.subtab == "people":
            return bool(self._people_data)  # type: ignore[attr-defined]
        if step.subtab == "notifications":
            return self._notification_projection.configured  # type: ignore[attr-defined]
        if step.subtab == "environment":
            return all(status.is_set for status in self._env_data) if self._env_data else False  # type: ignore[attr-defined]
        return False
