"""Tier-driven generation of the public config sample (``templates/config.yml``).

The sample is a consequence of the field tiers, never an independent source of the
public surface. It is reconciled from ``TeleclaudeConfig``'s effective-tier tree
into the curated template via a ruamel round-trip that preserves the template's
comments, commented-out optionals, and seed bodies (voice catalogs, trusted-dir
example). A ``public``/``tui`` leaf absent from the sample is added from
``DEFAULT_CONFIG``; an ``internal`` leaf present in the sample is removed. See
``project/policy/config-public-surface``.

The walk descends into static dataclass sub-structs (e.g. ``WorkflowConfig``,
``DeploymentConfig``) and stops at scalars, enums, dicts, and lists — dynamic
containers (``tts.services``) carry per-install keys the schema cannot enumerate,
so their curated bodies are left untouched. A leaf the curated sample exposes as a
commented-out optional (``# host:``, ``# max_connections:``) counts as already
present, so reconciliation never uncomments the curated optional surface.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from ruamel.yaml import YAML

from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config._models import TeleclaudeConfig
from teleclaude.config.tiers import Tier, dataclass_field_tier, effective_tier, in_public_sample

_MISSING: Any = object()


def _nested_dataclass(annotation: Any) -> Any:
    """Return the nested dataclass type in an annotation, unwrapping ``Optional``.

    Returns ``None`` when the annotation is a scalar, enum, dict, or list — those are
    reconciled as leaves, not descended into.
    """
    candidates = get_args(annotation) if get_origin(annotation) in (Union, UnionType) else [annotation]
    for candidate in candidates:
        if candidate is type(None):
            continue
        if get_origin(candidate) in (dict, list):
            continue
        if isinstance(candidate, type) and dataclasses.is_dataclass(candidate):
            return candidate
    return None


def _iter_schema_leaves(
    struct_type: Any, inherited: Tier, prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Tier]]:
    """Return ``(dotted-path, effective-tier)`` for every static leaf under ``struct_type``."""
    leaves: list[tuple[tuple[str, ...], Tier]] = []
    hints = get_type_hints(struct_type)
    for field in dataclasses.fields(struct_type):
        eff = effective_tier(dataclass_field_tier(field), inherited)
        annotation = hints.get(field.name, field.type)
        nested = _nested_dataclass(annotation)
        path = (*prefix, field.name)
        if nested is not None:
            leaves.extend(_iter_schema_leaves(nested, eff, path))
        else:
            leaves.append((path, eff))
    return leaves


def _default_at(path: tuple[str, ...]) -> Any:
    """Return the ``DEFAULT_CONFIG`` value at ``path``, or ``_MISSING`` when absent."""
    cursor: Any = DEFAULT_CONFIG
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return _MISSING
        cursor = cursor[key]
    return cursor


def _parent_and_key(doc: Any, path: tuple[str, ...]) -> tuple[Any, str]:
    """Return the parent map holding ``path``'s leaf (or ``_MISSING``) and the leaf key."""
    cursor: Any = doc
    for key in path[:-1]:
        if not isinstance(cursor, dict) or key not in cursor:
            return _MISSING, path[-1]
        cursor = cursor[key]
    return (cursor if isinstance(cursor, dict) else _MISSING), path[-1]


def _comment_texts(node: Any) -> list[str]:
    """Collect every comment string attached to a ruamel ``CommentedMap``."""
    texts: list[str] = []
    ca = getattr(node, "ca", None)
    if ca is None:
        return texts
    sources = list(ca.comment or [])
    for item in ca.items.values():
        sources.extend(item)
    stack = list(sources)
    while stack:
        token = stack.pop()
        if token is None:
            continue
        if isinstance(token, list):
            stack.extend(token)
        else:
            value = getattr(token, "value", None)
            if isinstance(value, str):
                texts.append(value)
    return texts


def _key_is_commented(parent: Any, key: str) -> bool:
    """Whether ``key`` appears as a commented-out optional in ``parent``'s comments."""
    pattern = re.compile(rf"(?m)^\s*#\s*{re.escape(key)}\s*:")
    return any(pattern.search(text) for text in _comment_texts(parent))


def _ensure_path(doc: Any, path: tuple[str, ...], value: Any) -> None:
    """Set ``path`` to ``value``, creating intermediate maps as needed."""
    cursor: Any = doc
    for key in path[:-1]:
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[key] = nxt
        cursor = nxt
    cursor[path[-1]] = value


def _top_level_tiers() -> dict[str, Tier]:
    """Map each top-level ``TeleclaudeConfig`` field to its effective container tier."""
    return {
        f.name: effective_tier(dataclass_field_tier(f), Tier.INTERNAL) for f in dataclasses.fields(TeleclaudeConfig)
    }


def reconcile_sample(doc: dict[str, object]) -> bool:  # guard: loose-dict - ruamel round-trip YAML tree
    """Reconcile a loaded sample against the effective-tier tree in place; return whether it changed.

    A whole top-level section that maps to an ``internal`` field is dropped. Within the
    surviving ``public``/``tui`` sections a missing ``public``/``tui`` leaf (neither an
    active key nor a commented-out optional) is added from ``DEFAULT_CONFIG`` when a
    default exists, and an ``internal`` leaf present as an active key is removed. Dynamic
    dict/list bodies and commented optionals are preserved.
    """
    top_tiers = _top_level_tiers()
    changed = False

    for key in list(doc.keys()):
        tier = top_tiers.get(str(key))
        if tier is not None and not in_public_sample(tier):
            del doc[key]
            changed = True

    for path, tier in _iter_schema_leaves(TeleclaudeConfig, Tier.INTERNAL):
        if not in_public_sample(top_tiers.get(path[0], Tier.INTERNAL)):
            continue
        parent, key = _parent_and_key(doc, path)
        active = parent is not _MISSING and key in parent
        if in_public_sample(tier):
            if active:
                continue
            if parent is not _MISSING and _key_is_commented(parent, key):
                continue
            default = _default_at(path)
            if default is not _MISSING:
                _ensure_path(doc, path, default)
                changed = True
        elif active:
            del parent[key]
            changed = True
    return changed


def generate_sample_file(template_path: Path) -> bool:
    """Reconcile ``template_path`` against the field tiers in place; return whether it changed.

    Comment-preserving via ruamel round-trip. A no-op (and idempotent) when the
    sample already matches the tier map.
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    with open(template_path, encoding="utf-8") as f:
        doc = yaml.load(f)
    if not isinstance(doc, dict):
        return False
    if not reconcile_sample(doc):
        return False
    with open(template_path, "w", encoding="utf-8") as f:
        yaml.dump(doc, f)
    return True
