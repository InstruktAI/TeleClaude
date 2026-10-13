"""Editing and guided-mode mixin for ConfigContent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any, get_args
from uuid import uuid4

from pydantic import BaseModel

from teleclaude.cli.config_handlers import EnvVarStatus
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _GUIDED_STEPS,
    _SUBTABS,
    AdapterSectionProjection,
    ConfigTuiOutcome,
    Subtab,
    observe_config_tui,
)
from teleclaude.cli.tui.views.config_operations import ConfigOperationFailed, ConfigOperations
from teleclaude.cli.tui.views.reflection import ReflectedField, deserialize_value
from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.person_resource import OVERLAY_PATCH_KEY, SETTINGS_SECTION
from teleclaude.config.subject_operations import ConfigFailureKind
from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind

_WRITE_GROUP = "config-write"
_IDENTITY_PREFIX = "identity"
_OVERLAY_PREFIX = "overlay"
_MACHINE_SOURCE = "machine"
_GLOBAL_SOURCE = "global"
_PERSON_SOURCE = "per-person"
_NESTED_SEPARATOR = ":"
_KEY_SEPARATOR = "."
_STALE_REVISION_MESSAGE = "{label}: Changed elsewhere since it was read; reloaded."
_CLEARED = "Cleared {label}."
_KEPT = "Kept {label}."
_SAVED = "Saved {label}."
_SAVED_FIELD = "Saved {label} successfully."
_UPDATED = "Updated {label}."
_SAVE_FAILED = "Failed to save {label}: {error}"
_CONFIG_SOURCE = "config"
_ENVIRONMENT_SOURCE = "environment"
_JSON_MODE = "json"
_DAEMON_UNAVAILABLE = "The daemon is not reachable."

type WriteAction = Callable[[ConfigOperations], Awaitable[None]]
type PatchBody = dict[str, object]  # guard: loose-dict - RFC 7386 merge patch


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


_REDIS_URL_KEY = "redis.url"
_NOT_READ = "the configuration has not been read from the daemon yet"
_NO_PERSON = ""
_MISSING_DEFAULT = object()


def _default_for(path: tuple[str, ...]) -> object:
    """The schema default of a machine field, or the sentinel when the schema declares none."""
    current: object = DEFAULT_CONFIG
    for segment in path:
        if not isinstance(current, dict) or segment not in current:
            return _MISSING_DEFAULT
        current = current[segment]
    return current


def _nested_patch(parts: list[str], value: object) -> PatchBody:
    """The merge patch that sets one leaf at a nested path."""
    patch: PatchBody = {parts[-1]: value.value if isinstance(value, Enum) else value}
    for part in reversed(parts[:-1]):
        patch = {part: patch}
    return patch


def _machine_patch(path: tuple[str, ...], value: object) -> PatchBody:
    """The merge patch for one machine field: an edit back to the schema default removes the field (UC-14)."""
    default = _default_for(path)
    return _nested_patch(list(path), None if default is not _MISSING_DEFAULT and value == default else value)


def _covered_by_reference(path: str, referenced: set[str]) -> bool:
    """Whether a stored environment reference sits at the path or beneath it."""
    return any(reference == path or reference.startswith(f"{path}{_KEY_SEPARATOR}") for reference in referenced)


def _overlay_patch(overlay: BaseModel, parts: list[str], value: object, referenced: set[str]) -> PatchBody:
    """The merge patch for one overlay field; an unset submodel is written whole with its required siblings seeded.

    A sibling whose stored value is an environment reference (`referenced` holds their paths) is never seeded,
    so a stored reference is not replaced by a placeholder.
    """
    patch: PatchBody = {}
    cursor = patch
    node: BaseModel | None = overlay
    for depth, part in enumerate(parts[:-1]):
        child = getattr(node, part, None) if node is not None else None
        if child is None and node is not None:
            child = _instantiate_nested_config_model(type(node).model_fields[part].annotation)
            parent_path = _KEY_SEPARATOR.join(parts[: depth + 1])
            seeded = {
                key: item
                for key, item in child.model_dump(mode=_JSON_MODE, exclude_none=True).items()
                if not _covered_by_reference(f"{parent_path}{_KEY_SEPARATOR}{key}", referenced)
            }
            cursor[part] = seeded
            cursor = seeded
        else:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
        node = child if isinstance(child, BaseModel) else None
    cursor[parts[-1]] = value.value if isinstance(value, Enum) else value
    return patch


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
            # The stored value is never shown or loaded; submitting nothing leaves it unchanged.
            self._edit_buffer = ""  # type: ignore[attr-defined]
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
        """Clear a stored value as a deliberate action, or clear an ordinary active buffer."""
        if not self.is_editing:  # type: ignore[attr-defined]
            return
        name = self._editing_var_name  # type: ignore[attr-defined]
        target = self._clear_target()
        if name is None or target is None:
            self.clear_edit_buffer()
            return
        label, action = target
        operation_id = str(uuid4())
        observe_config_tui(ConfigTuiOutcome.SAVE_REQUESTED, operation_id=operation_id, field_paths=[name])
        self._editing_var_name = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self._submit_write(
            operation_id=operation_id,
            field_paths=[name],
            label=label,
            success_message=_CLEARED.format(label=label),
            action=action,
        )

    def _clear_target(self) -> tuple[str, WriteAction] | None:
        """The label and the daemon request that removes the stored value the active edit is of."""
        name = self._editing_var_name  # type: ignore[attr-defined]
        field = self._active_write_only_field()
        if field is not None:
            return field.name, self._field_clear_action(field)
        if _SUBTABS[self.active_subtab] == Subtab.ENV and name is not None:  # type: ignore[attr-defined]
            return name, lambda operations: operations.set_environment(ConfigEnvironment.MACHINE, clear=[name])
        return None

    def _field_clear_action(self, f: ReflectedField) -> WriteAction:
        """Remove a write-only field's value where it lives: its environment variable, or the field itself."""
        if f.environment is None:
            return self._field_write_action(f, f.key, None)
        environment = f.environment
        instance = self._expanded_person if environment.owner is ConfigEnvironment.PERSON else None  # type: ignore[attr-defined]
        return lambda operations: operations.set_environment(
            environment.owner, instance=instance, clear=[environment.name]
        )

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

        value = self._edit_buffer  # type: ignore[attr-defined]
        self._editing_var_name = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        if not value:
            self._status_message = _KEPT.format(label=var_name)  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return
        operation_id = str(uuid4())
        observe_config_tui(ConfigTuiOutcome.SAVE_REQUESTED, operation_id=operation_id, field_paths=[var_name])
        self._submit_write(
            operation_id=operation_id,
            field_paths=[var_name],
            label=var_name,
            success_message=_SAVED.format(label=var_name),
            action=lambda operations: operations.set_environment(ConfigEnvironment.MACHINE, values=[(var_name, value)]),
        )

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
        """Parse a reflected field value and write it through the daemon to the subject that owns it."""
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

        if f.write_only:
            self._save_write_only_field(f, str(raw_value), operation_id)
            return

        try:
            deserialized = deserialize_value(raw_value, f.field_type, f.choices)
            action = self._field_write_action(f, key, deserialized)
        except Exception as exc:
            observe_config_tui(
                ConfigTuiOutcome.FAILED, operation_id=operation_id, field_paths=[key], source=_CONFIG_SOURCE
            )
            self._status_message = _SAVE_FAILED.format(label=f.name, error=exc)  # type: ignore[attr-defined]
            self._status_is_error = True  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return
        self._editing_var_name = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        self._submit_write(
            operation_id=operation_id,
            field_paths=[key],
            label=f.name,
            success_message=_SAVED_FIELD.format(label=f.name),
            action=action,
            source=_ENVIRONMENT_SOURCE if f.env_var else _CONFIG_SOURCE,
        )

    def _save_write_only_field(self, f: ReflectedField, value: str, operation_id: str) -> None:
        """Replace a sensitive or personal secret value, or keep it when nothing was entered; never read it back."""
        self._editing_var_name = None  # type: ignore[attr-defined]
        self._edit_buffer = ""  # type: ignore[attr-defined]
        if not value.strip():
            self._status_message = _KEPT.format(label=f.name)  # type: ignore[attr-defined]
            self._status_is_error = False  # type: ignore[attr-defined]
            self.refresh(layout=True)  # type: ignore[attr-defined]
            return
        self._submit_write(
            operation_id=operation_id,
            field_paths=[f.key],
            label=f.name,
            success_message=_UPDATED.format(label=f.name),
            action=self._field_write_action(f, f.key, deserialize_value(value, f.field_type, f.choices)),
        )

    def _field_write_action(self, f: ReflectedField, key: str, value: Any) -> WriteAction:
        """The daemon request that writes a field's value to the subject that owns the field."""
        if f.environment is not None:
            # A reference-backed field keeps its reference in the document; the value goes to the environment.
            environment = f.environment
            instance = self._expanded_person if environment.owner is ConfigEnvironment.PERSON else None  # type: ignore[attr-defined]
            return lambda operations: operations.set_environment(
                environment.owner, instance=instance, values=[(environment.name, str(value))]
            )
        if f.owning_source == _MACHINE_SOURCE:
            return self._machine_patch_action(_machine_patch(tuple(key.split(_KEY_SEPARATOR)), value))
        return self._person_patch_action(self._person_patch(key, value))

    def _machine_patch_action(self, patch: PatchBody) -> WriteAction:
        async def write(operations: ConfigOperations) -> None:
            revision = self._machine_revision  # type: ignore[attr-defined]
            if revision is None:
                raise ConfigOperationFailed(ConfigFailureKind.INVALID, _NOT_READ)
            await operations.patch(ConfigSubjectKind.COMPUTER, None, revision, patch)

        return write

    def _person_patch_action(self, patch: PatchBody) -> WriteAction:
        slug = self._expanded_person  # type: ignore[attr-defined]

        async def write(operations: ConfigOperations) -> None:
            snapshot = self._people.get(slug) if slug is not None else None  # type: ignore[attr-defined]
            if slug is None or snapshot is None:
                raise ConfigOperationFailed(ConfigFailureKind.INVALID, _NOT_READ)
            await operations.patch(ConfigSubjectKind.PERSON, slug, snapshot.revision, patch)

        return write

    def _person_patch(self, key: str, value: Any) -> PatchBody:
        """The merge patch for one person field: an identity field, or an overlay field with its submodels seeded."""
        prefix, _, remainder = key.partition(_KEY_SEPARATOR)
        parts = remainder.replace(_NESTED_SEPARATOR, _KEY_SEPARATOR).split(_KEY_SEPARATOR)
        if prefix == _IDENTITY_PREFIX:
            return _nested_patch(parts, value)
        slug = self._expanded_person or _NO_PERSON  # type: ignore[attr-defined]
        snapshot = self._people.get(slug)  # type: ignore[attr-defined]
        referenced = snapshot.references_under(SETTINGS_SECTION) if snapshot is not None else {}
        # The envelope addresses the overlay alone, so `name` cannot be taken for the identity entry's.
        return {OVERLAY_PATCH_KEY: _overlay_patch(self._person_overlay_model(slug), parts, value, set(referenced))}  # type: ignore[attr-defined]

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

    def _active_write_only_field(self) -> ReflectedField | None:
        """Return the currently edited write-only field, if any."""
        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        fields = (
            self.person_reflected_fields  # type: ignore[attr-defined]
            if tab == Subtab.PEOPLE and self._expanded_person is not None  # type: ignore[attr-defined]
            else self.reflected_fields  # type: ignore[attr-defined]
        )
        return next((field for field in fields if field.key == self._editing_var_name and field.write_only), None)  # type: ignore[attr-defined]

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
            reference = self._machine_references.get(_REDIS_URL_KEY)  # type: ignore[attr-defined]
            if reference is not None and not reference.has_value:
                disposition = _RedisUrl.UNRESOLVED
                complete = False
            elif redis_url is None:
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
