"""Declaration-driven resolution of an invocation context root."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import yaml

from teleclaude.config.advancement import advance_context_config
from teleclaude.config.schema import ConfigKind
from teleclaude.paths import ConfigFileName

_UTF8 = "utf-8"
_KIND_FIELD = "kind"
_INVALID_DECLARATION = "Invalid configuration declaration in {path}"


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
            kind = _load_kind(marker)
            if kind is ConfigKind.COMPANY:
                return None
            return ContextRoot(path=current, kind=kind)
        if current.parent == current:
            return None
        current = current.parent


def _load_kind(path: Path) -> ConfigKind:
    raw = yaml.safe_load(path.read_text(encoding=_UTF8))
    if isinstance(raw, dict) and _KIND_FIELD not in raw:
        advance_context_config(path, path.parent)
        raw = yaml.safe_load(path.read_text(encoding=_UTF8))
    if not isinstance(raw, dict):
        raise ValueError(_INVALID_DECLARATION.format(path=path))
    value = raw.get(_KIND_FIELD)
    try:
        return ConfigKind(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(_INVALID_DECLARATION.format(path=path)) from exc
