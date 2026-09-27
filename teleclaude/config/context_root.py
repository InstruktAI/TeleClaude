"""Declaration-driven resolution of an invocation context root."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple, cast

import yaml

from teleclaude.config.migrations import resolve_read_subject
from teleclaude.config.migrations._runner import upcast_for_read
from teleclaude.config.schema import ConfigKind
from teleclaude.paths import ConfigFileName

_UTF8 = "utf-8"
_KIND_FIELD = "kind"
_INVALID_DECLARATION = "Invalid configuration declaration in {path}"
_RAW_DECLARATION_READ_FAILURE = "Failed to read {subject} declaration {path}: {error}"
_RAW_DECLARATION_MAPPING_FAILURE = "{subject_capitalized} declaration must be a mapping: {path}"


class ContextRoot(NamedTuple):
    """An anchoring configuration declaration and its root directory."""

    path: Path
    kind: ConfigKind


def resolve_context_root(start: Path) -> ContextRoot | None:
    """Return the nearest anchoring declaration, or no context root."""
    current = start.expanduser().resolve()
    if current.is_file():
        current = current.parent
    while True:
        marker = current / ConfigFileName.OVERLAY
        if marker.is_file():
            kind = load_declared_config_kind(marker)
            if kind is ConfigKind.COMPANY:
                return None
            return ContextRoot(path=current, kind=kind)
        if current.parent == current:
            return None
        current = current.parent


def load_declared_config_kind(path: Path) -> ConfigKind:
    """Read a root's declared configuration tier from its in-memory migrated view."""
    payload: object = yaml.safe_load(path.read_text(encoding=_UTF8)) or {}
    if not isinstance(payload, Mapping):
        raise ValueError(_INVALID_DECLARATION.format(path=path))
    subject = resolve_read_subject(path, payload)
    if subject is None:
        raise ValueError(_INVALID_DECLARATION.format(path=path))
    raw = upcast_for_read(path, payload, subject=subject)
    if not isinstance(raw, dict):
        raise ValueError(_INVALID_DECLARATION.format(path=path))
    value = raw.get(_KIND_FIELD)
    try:
        return ConfigKind(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(_INVALID_DECLARATION.format(path=path)) from exc


def load_raw_declaration(path: Path, *, subject: str) -> Mapping[object, object]:
    """Read a declaration mapping in its current in-memory shape without validation."""
    try:
        payload = yaml.safe_load(path.read_text(encoding=_UTF8)) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(_RAW_DECLARATION_READ_FAILURE.format(subject=subject, path=path, error=exc)) from exc
    if not isinstance(payload, Mapping):
        raise ValueError(_RAW_DECLARATION_MAPPING_FAILURE.format(subject_capitalized=subject.capitalize(), path=path))
    return cast(Mapping[object, object], upcast_for_read(path, payload))
