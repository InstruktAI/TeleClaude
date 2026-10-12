"""Editability tiers for machine-config Pydantic fields.

A field's tier declares what reaches humans: ``internal`` (the default),
``public``, or ``tui``. The tier is the single authority for the public config
surface — the generated ``templates/config.yml`` sample and the config TUI render
set are consequences of these markers, never independent sources. See
``local/projects/teleclaude/policy/config-public-surface``.

The marker is read from a Pydantic ``FieldInfo``'s ``json_schema_extra["tier"]``. A field with no marker is
``internal``. ``effective_tier`` resolves a leaf's tier by inheritance: the leaf's
own tier when declared, else the nearest ancestor container's tier, else the
``internal`` default — so a container marked ``tui`` lifts its unmarked leaves into
view without a marker on every one.

Two more section-level declarations live beside the tier. A section's **scope**
(``local``, the default, or ``master``) says whether the section is meaningful on
every computer or only on the master; and an ``enabled`` flag may declare that it
does not govern its section (``governs_section`` false), for a flag whose meaning
is not the section's switch. The configuration reader derives each section's
effective ``enabled`` from these declarations alone.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic.fields import FieldInfo

TIER_METADATA_KEY = "tier"
SCOPE_METADATA_KEY = "scope"
GOVERNS_SECTION_METADATA_KEY = "governs_section"

# A container field whose members are themselves structured carries this marker
# with the reason its body is not walked. The schema walker refuses to skip such
# a field silently: either it is governed leaf-by-leaf, or it says here why it
# is not. An unmarked container of structures is an error, not a leaf.
UNGOVERNED_BODY_METADATA_KEY = "ungoverned_body"


class Tier(StrEnum):
    """Editability tier of a config field. ``INTERNAL`` is the default."""

    INTERNAL = "internal"
    PUBLIC = "public"
    TUI = "tui"


class Scope(StrEnum):
    """Where a machine-config section is meaningful. ``LOCAL`` is the default."""

    LOCAL = "local"
    MASTER = "master"


def pydantic_field_tier(field_info: FieldInfo) -> Tier | None:
    """Return the explicit tier declared on a pydantic field, or None."""
    extra = field_info.json_schema_extra
    if isinstance(extra, dict):
        raw = extra.get(TIER_METADATA_KEY)
        if raw is not None:
            return Tier(str(raw))
    return None


def pydantic_field_scope(field_info: FieldInfo) -> Scope | None:
    """Return the explicit scope declared on a pydantic field, or None."""
    extra = field_info.json_schema_extra
    if isinstance(extra, dict):
        raw = extra.get(SCOPE_METADATA_KEY)
        if raw is not None:
            return Scope(str(raw))
    return None


def pydantic_field_governs_section(field_info: FieldInfo) -> bool:
    """Whether an ``enabled`` field is its section's switch; true unless it declares otherwise."""
    extra = field_info.json_schema_extra
    return not (isinstance(extra, dict) and extra.get(GOVERNS_SECTION_METADATA_KEY) is False)


def pydantic_field_ungoverned_body(field_info: FieldInfo) -> str | None:
    """Return the reason a field's structured body is deliberately operator-authored."""
    extra = field_info.json_schema_extra
    reason = extra.get(UNGOVERNED_BODY_METADATA_KEY) if isinstance(extra, dict) else None
    return reason if isinstance(reason, str) else None


def effective_tier(explicit: Tier | None, inherited: Tier) -> Tier:
    """Resolve a leaf's effective tier: its own when declared, else the inherited."""
    return explicit if explicit is not None else inherited


def effective_scope(explicit: Scope | None, inherited: Scope) -> Scope:
    """Resolve a leaf's effective scope: its own when declared, else the inherited."""
    return explicit if explicit is not None else inherited


def renders_in_tui(tier: Tier) -> bool:
    """Whether a leaf at this effective tier is rendered by the config TUI."""
    return tier is Tier.TUI


def in_public_sample(tier: Tier) -> bool:
    """Whether a leaf at this effective tier belongs in the generated sample."""
    return tier in (Tier.PUBLIC, Tier.TUI)
