"""Editing and guided-mode mixin for ConfigContent."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, get_origin

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
    Subtab,
    get_allowed_values_for_field,
)
from teleclaude.cli.tui.views._project_actions import _resolve_config_path, _write_raw_config
from teleclaude.cli.tui.views.reflection import ReflectedField, deserialize_value
from teleclaude.config._coerce import as_bool
from teleclaude.config.adapter_validation import adapter_names, validate_adapter_config
from teleclaude.config.schema import PersonEntry

if TYPE_CHECKING:
    from teleclaude.cli.tui.views._config_constants import AdapterSectionProjection

# Reflected field keys prefixed with one of these map to that config.yml section.
_SECTION_PREFIXES = ("computer", "telegram", "discord", "whatsapp")
# Flat reflected keys that map to a (section, leaf) pair in config.yml.
_FLAT_CONFIG_KEYS = {
    "stt_enabled": ("stt", "enabled"),
    "stt_service_priority": ("stt", "service_priority"),
    "tts_enabled": ("tts", "enabled"),
    "tts_service_priority": ("tts", "service_priority"),
    # Summarizer subtab (local_base_url is env-backed and routed via env_var, not here).
    "local_enabled": ("summarizer", "local", "enabled"),
    "local_model": ("summarizer", "local", "model"),
    "provider_priority": ("summarizer", "provider_priority"),
    "openai_model": ("summarizer", "openai", "model"),
    "anthropic_model": ("summarizer", "anthropic", "model"),
    "google_model": ("summarizer", "google", "model"),
}


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

    def _begin_edit(self, field_or_status: Any) -> None:
        """Enter editing mode for reflected fields or env vars."""
        if isinstance(field_or_status, ReflectedField):
            self._editing_var_name = field_or_status.key  # type: ignore[attr-defined]
            val = field_or_status.value
            if isinstance(val, list):
                self._edit_buffer = ",".join(val)  # type: ignore[attr-defined]
            else:
                self._edit_buffer = str(val if val is not None else "")  # type: ignore[attr-defined]
            self._status_message = f"Editing {field_or_status.name}. Enter saves, Esc cancels."  # type: ignore[attr-defined]
        else:
            self._editing_var_name = field_or_status.info.name  # type: ignore[attr-defined]
            self._edit_buffer = os.environ.get(field_or_status.info.name, "")  # type: ignore[attr-defined]
            self._status_message = f"Editing {field_or_status.info.name}. Enter saves, Esc cancels."  # type: ignore[attr-defined]
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
            field = self.person_editable_fields[self._person_field_cursor]  # type: ignore[attr-defined]
            return get_allowed_values_for_field(field) is not None
        return False

    def cycle_enum_field(self, direction: int) -> None:
        """Cycle the active enum/list/bool field in the requested direction."""
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            fields = self.reflected_fields  # type: ignore[attr-defined]
            if fields:
                cursor = self._current_cursor()  # type: ignore[attr-defined]
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

        # Fallback to Person enum cycle
        person = next((p for p in self._people_data if p.name == self._expanded_person), None)  # type: ignore[attr-defined]
        if person is not None:
            field = self.person_editable_fields[self._person_field_cursor]  # type: ignore[attr-defined]
            self._cycle_person_enum(person, field, direction)

    def reorder_reflected_list(self, direction: int) -> None:
        """Shift the focused list element left (-1) or right (1)."""
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            fields = self.reflected_fields  # type: ignore[attr-defined]
            if fields:
                cursor = self._current_cursor()  # type: ignore[attr-defined]
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

    def _apply_field_to_raw_config(self, key: str, deserialized: object) -> None:
        """Write a non-env field value into its config.yml path (any nesting depth)."""
        if "." in key and key.split(".", 1)[0] in _SECTION_PREFIXES:
            path: tuple[str, ...] = tuple(key.split("."))
        elif key in _FLAT_CONFIG_KEYS:
            path = _FLAT_CONFIG_KEYS[key]
        else:
            return
        node = self._raw_config  # type: ignore[attr-defined]
        for part in path[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[path[-1]] = deserialized

    def _adapter_write_block_reason(self, key: str, deserialized: object) -> str | None:
        """Reason to refuse persisting this edit, or None if it may be written.

        Integrity gate: never persist an adapter section that is enabled while its
        required credentials are missing. Reuses the same validator the daemon
        runs at startup so the two surfaces cannot disagree.
        """
        if "." not in key:
            return None
        adapter, field_name = key.split(".", 1)
        if adapter not in adapter_names():
            return None
        section = dict(self._raw_config.get(adapter) or {})  # type: ignore[attr-defined]
        section[field_name] = deserialized
        if not as_bool(section.get("enabled", False)):
            return None  # disabled (or being disabled) never blocks
        missing = validate_adapter_config(adapter, section)
        if missing:
            return f"{adapter} is enabled but not configured: fill {', '.join(missing)} (or disable it)."
        return None

    def _save_reflected_field(self, key: str, raw_value: Any) -> None:
        """Parse, validate, and write a reflected field value back to config.yml or .env."""
        fields = self.reflected_fields  # type: ignore[attr-defined]
        f = next((field for field in fields if field.key == key), None)
        if f is None:
            return

        try:
            deserialized = deserialize_value(raw_value, f.field_type, f.choices)

            if f.env_var:
                # ${VAR}-backed field: persist to .env, leave the placeholder in config.yml.
                set_env_var(f.env_var, str(deserialized))
            else:
                block_reason = self._adapter_write_block_reason(key, deserialized)
                if block_reason is not None:
                    self._status_message = block_reason  # type: ignore[attr-defined]
                    self._status_is_error = True  # type: ignore[attr-defined]
                    return
                self._apply_field_to_raw_config(key, deserialized)
                config_path = _resolve_config_path()
                _write_raw_config(config_path, self._raw_config)  # type: ignore[attr-defined]

            self._editing_var_name = None  # type: ignore[attr-defined]
            self._edit_buffer = ""  # type: ignore[attr-defined]
            self._status_message = f"Saved {f.name} successfully."  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
            self.refresh_data()  # type: ignore[attr-defined]

        except Exception as exc:
            self._status_message = f"Failed to save {f.name}: {exc}"  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]

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
            # Redis is mandatory infrastructure; the step is not satisfied until it is set.
            return bool(os.environ.get("REDIS_URL"))
        if step.subtab == Subtab.PEOPLE:
            # People step is complete with at least one admin-role person.
            return any(p.role == "admin" for p in self._people_data)  # type: ignore[attr-defined]
        if step.subtab == Subtab.ENV:
            return bool(self._env_data) and all(  # type: ignore[attr-defined]
                status.is_set for status in self._env_data
            )
        return False
