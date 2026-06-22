"""Editing and guided-mode mixin for ConfigContent."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, get_args

from pydantic import BaseModel, ValidationError

from teleclaude.cli.config_handlers import (
    EnvVarStatus,
    get_global_config,
    get_person_config,
    save_global_config,
    save_person_config,
    save_raw_machine_config,
    set_env_var,
)
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _GUIDED_STEPS,
    _SUBTABS,
    AdapterSectionProjection,
    Subtab,
)
from teleclaude.cli.tui.views.reflection import ReflectedField, deserialize_value
from teleclaude.config import DEFAULT_CONFIG, config
from teleclaude.config._coerce import as_bool
from teleclaude.config.schema import PersonEntry
from teleclaude.config.validation import missing_required_fields, validated_sections


def _apply_field_to_global_config(key: str, deserialized: Any) -> None:
    parts = key.split(".")
    # Special case for summarizer cloud models
    if (
        len(parts) == 3
        and parts[0] == "summarizer"
        and parts[1] in ("openai", "anthropic", "google")
        and parts[2] == "model"
    ):
        provider = parts[1]
        if config.summarizer is not None:
            config.summarizer.models[provider] = deserialized
        return

    # Standard traversal, descending list indices, dict members, and attributes alike.
    obj = config
    for part in parts[:-1]:
        obj = _descend(obj, part)
    _assign(obj, parts[-1], deserialized)


def _descend(node: Any, part: str) -> Any:
    if isinstance(node, list):
        return node[int(part)]
    if isinstance(node, dict):
        return node[part]
    return getattr(node, part)


def _assign(node: Any, part: str, value: Any) -> None:
    if isinstance(node, list):
        node[int(part)] = value
    elif isinstance(node, dict):
        node[part] = value
    else:
        setattr(node, part, value)


_NO_DEFAULT = object()


def _default_for_key(key: str) -> Any:
    """The DEFAULT_CONFIG value for a dotted key, or a sentinel when none exists."""
    node: Any = DEFAULT_CONFIG
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return _NO_DEFAULT
    return node


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

    def _apply_field_to_raw_config(self, key: str, deserialized: object) -> None:
        """Write a non-env field into config.yml, dropping it when it equals its default.

        Persisting only deviations keeps config.yml sparse; the loader re-fills
        defaults on read, so the dropped value still renders via the default.
        """
        path = key.split(".")
        if deserialized == _default_for_key(key) and self._prune_raw_key(path):
            return
        node = self._raw_config  # type: ignore[attr-defined]
        for part in path[:-1]:
            if isinstance(node, list):
                node = node[int(part)]
                continue
            child = node.get(part)
            if not isinstance(child, (dict, list)):
                child = {}
                node[part] = child
            node = child
        _assign(node, path[-1], deserialized)

    def _prune_raw_key(self, path: list[str]) -> bool:
        """Remove a dotted dict key from the raw config, pruning emptied parents.

        Returns True when the key is handled (absent or removed); False when the
        path crosses a non-dict node, in which case the caller writes it normally.
        """
        node = self._raw_config  # type: ignore[attr-defined]
        chain: list[tuple[dict[str, Any], str]] = []  # guard: loose-dict - raw YAML config tree
        for part in path[:-1]:
            if not isinstance(node, dict):
                return False
            if part not in node:
                return True  # ancestor absent: default was never stored
            chain.append((node, part))
            node = node[part]
        if not isinstance(node, dict):
            return False
        node.pop(path[-1], None)
        for container, part in reversed(chain):
            if isinstance(container[part], dict) and not container[part]:
                container.pop(part)
            else:
                break
        return True

    def _section_write_block_reason(self, key: str, deserialized: object) -> str | None:
        """Reason to refuse persisting this edit, or None if it may be written.

        Integrity gate: never persist a config section that is enabled while its
        required fields are missing. Reuses the same validator the daemon runs at
        startup so the two surfaces cannot disagree.
        """
        if "." not in key:
            return None
        section_name, field_name = key.split(".", 1)
        if section_name not in validated_sections():
            return None
        section = dict(self._raw_config.get(section_name) or {})  # type: ignore[attr-defined]
        section[field_name] = deserialized
        if not as_bool(section.get("enabled", False)):
            return None  # disabled (or being disabled) never blocks
        missing = missing_required_fields(section_name, section)
        if missing:
            return f"{section_name} is enabled but not configured: fill {', '.join(missing)} (or disable it)."
        return None

    def _save_reflected_field(self, key: str, raw_value: Any) -> None:
        """Parse, validate, and write a reflected field value back to its source."""
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab == Subtab.PEOPLE and self._expanded_person is not None:  # type: ignore[attr-defined]
            fields = self.person_reflected_fields
        else:
            fields = self.reflected_fields  # type: ignore[attr-defined]

        f = next((field for field in fields if field.key == key), None)
        if f is None:
            return

        try:
            deserialized = deserialize_value(raw_value, f.field_type, f.choices)

            if f.env_var:
                # ${VAR}-backed field: persist to .env, leave the placeholder in config.yml.
                set_env_var(f.env_var, str(deserialized))
            elif f.owning_source == "machine":
                block_reason = self._section_write_block_reason(key, deserialized)
                if block_reason is not None:
                    self._status_message = block_reason  # type: ignore[attr-defined]
                    self._status_is_error = True  # type: ignore[attr-defined]
                    return
                # Update the sparse raw tree (drops values equal to their default).
                self._apply_field_to_raw_config(key, deserialized)
                # Update global config singleton for live consistency.
                _apply_field_to_global_config(key, deserialized)
                # Persist the sparse raw tree; the loader re-fills defaults on read.
                save_raw_machine_config(self._raw_config)  # type: ignore[attr-defined]
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
            self.refresh_data()  # type: ignore[attr-defined]

        except Exception as exc:
            self._status_message = f"Failed to save {f.name}: {exc}"  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]

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
