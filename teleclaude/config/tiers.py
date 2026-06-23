"""Editability tiers for machine-config fields.

A field's tier declares what reaches humans: ``internal`` (the default),
``public``, or ``tui``. The tier is the single authority for the public config
surface — the generated ``templates/config.yml`` sample and the config TUI render
set are consequences of these markers, never independent sources. See
``project/policy/config-public-surface``.

The marker is read from a dataclass ``field``'s ``metadata["tier"]`` and from a
pydantic ``FieldInfo``'s ``json_schema_extra["tier"]``. A field with no marker is
``internal``. ``effective_tier`` resolves a leaf's tier by inheritance: the leaf's
own tier when declared, else the nearest ancestor container's tier, else the
``internal`` default — so a container marked ``tui`` lifts its unmarked leaves into
view without a marker on every one.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum

from pydantic.fields import FieldInfo

TIER_METADATA_KEY = "tier"


class Tier(StrEnum):
    """Editability tier of a config field. ``INTERNAL`` is the default."""

    INTERNAL = "internal"
    PUBLIC = "public"
    TUI = "tui"


def dataclass_field_tier(field: dataclasses.Field[object]) -> Tier | None:
    """Return the explicit tier declared on a dataclass field, or None."""
    raw = field.metadata.get(TIER_METADATA_KEY) if field.metadata else None
    return Tier(raw) if raw is not None else None


def pydantic_field_tier(field_info: FieldInfo) -> Tier | None:
    """Return the explicit tier declared on a pydantic field, or None."""
    extra = field_info.json_schema_extra
    if isinstance(extra, dict):
        raw = extra.get(TIER_METADATA_KEY)
        if raw is not None:
            return Tier(str(raw))
    return None


def effective_tier(explicit: Tier | None, inherited: Tier) -> Tier:
    """Resolve a leaf's effective tier: its own when declared, else the inherited."""
    return explicit if explicit is not None else inherited


def renders_in_tui(tier: Tier) -> bool:
    """Whether a leaf at this effective tier is rendered by the config TUI."""
    return tier is Tier.TUI


def in_public_sample(tier: Tier) -> bool:
    """Whether a leaf at this effective tier belongs in the generated sample."""
    return tier in (Tier.PUBLIC, Tier.TUI)
