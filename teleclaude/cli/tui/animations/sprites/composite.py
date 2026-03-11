"""Composite sprite type for layered rendering with per-layer color."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import NamedTuple


class SpriteLayer(NamedTuple):
    """One color layer of a composite sprite.

    At each cell position:
      - positive non-space char → rendered normally (fg = color)
      - negative non-space char → rendered inverted (bg = color, fg = sky)
      - space → transparent (layer does not contribute at this cell)
    """

    color: str | list[str] | None = "#ffffff"
    positive: list[str] | None = None
    negative: list[str] | None = None


_DEFAULT_SPEED_WEIGHTS: list[tuple[float, int]] = [(0.0, 10), (0.4, 30), (0.7, 50), (1.0, 10)]


@dataclass(frozen=True)
class CompositeSprite:
    """Multi-layer sprite with per-layer color declarations.

    Layers render back-to-front: layer 0 first, last layer on top.
    Within each layer, negative chars render before positive so that
    positive wins on overlap.

    z_weights: depth distribution as (z_level, weight) pairs.
    y_weights: vertical position as (y_lo, y_hi, weight) triples.
               Engine picks a weighted entry, then randomizes Y within
               [y_lo, y_hi]. Screen Y: 0=top row, 9=bottom (tab bar).
    speed_weights: speed distribution as (speed, weight) pairs.
                   The engine periodically picks a new target speed
                   and eases toward it. Direction is random 50/50.
    speed_fixed: optional (lo, hi) range — engine picks uniform(lo, hi)
                 once at spawn and speed stays constant. Sign encodes
                 direction. Mutually exclusive with non-default speed_weights.
    """

    layers: list[SpriteLayer]
    z_weights: list[tuple[int, int]] | None = field(default_factory=list)
    y_weights: list[tuple[int, int, int]] | None = field(default_factory=list)
    speed_weights: list[tuple[float, int]] | None = field(default_factory=lambda: list(_DEFAULT_SPEED_WEIGHTS))
    speed_fixed: tuple[float, float] | None = None
    theme: str | None = None  # "dark", "light", or None (both)

    def __post_init__(self) -> None:
        if self.speed_fixed is not None and self.speed_weights != list(_DEFAULT_SPEED_WEIGHTS):
            raise ValueError("speed_fixed and non-default speed_weights are mutually exclusive")

    def resolve_colors(self) -> CompositeSprite:
        """Return a copy with list colors resolved to a single random pick."""
        needs_resolve = any(isinstance(layer.color, list) for layer in self.layers)
        if not needs_resolve:
            return self
        resolved = []
        for layer in self.layers:
            if isinstance(layer.color, list):
                resolved.append(
                    SpriteLayer(color=random.choice(layer.color), positive=layer.positive, negative=layer.negative)
                )
            else:
                resolved.append(layer)
        return CompositeSprite(
            layers=resolved,
            z_weights=self.z_weights,
            y_weights=self.y_weights,
            speed_weights=self.speed_weights,
            speed_fixed=self.speed_fixed,
            theme=self.theme,
        )

    def tick(self, frame: int) -> CompositeSprite:
        """Static sprite -- returns self every frame."""
        return self


@dataclass(frozen=True)
class AnimatedSprite:
    """Animated sprite that cycles through frames.

    Each frame is either a list[str] (plain chars) or a CompositeSprite.
    tick(frame) returns the current renderable.

    speed_fixed: optional (lo, hi) range — engine picks uniform(lo, hi)
                 once at spawn and speed stays constant. Sign encodes
                 direction. Mutually exclusive with non-default speed_weights.
    y_offsets: per-frame Y offsets (cycles). Added to base Y each frame.
               Use for bobbing motion (e.g. butterfly: [0, -1, 0, 1]).
    """

    frames: list[list[str] | CompositeSprite]
    z_weights: list[tuple[int, int]] = field(default_factory=list)
    y_weights: list[tuple[int, int, int]] = field(default_factory=list)
    speed_weights: list[tuple[float, int]] = field(default_factory=lambda: list(_DEFAULT_SPEED_WEIGHTS))
    speed_fixed: tuple[float, float] | None = None
    theme: str | None = None  # "dark", "light", or None (both)
    y_offsets: list[int] | None = None

    def __post_init__(self) -> None:
        if self.speed_fixed is not None and self.speed_weights != list(_DEFAULT_SPEED_WEIGHTS):
            raise ValueError("speed_fixed and non-default speed_weights are mutually exclusive")

    def tick(self, frame: int) -> list[str] | CompositeSprite:
        return self.frames[frame % len(self.frames)]


@dataclass(frozen=True)
class SpriteGroup:
    """Population container with per-sprite count and weight.

    Each entry: (sprite, weight, (min_count, max_count)).
      - weight: occurrence fraction for runtime replacement (must sum to 1.0).
      - count: (min, max) entities to spawn of this type.
      - direction: None=random per entity, 1=right, -1=left for all entities.
      - theme: group-level theme filter. Overrides per-sprite theme when set.
    """

    entries: list[tuple[AnimatedSprite | CompositeSprite, float, tuple[int, int]]]
    direction: int | None = None
    theme: str | None = None  # "dark", "light", or None (both)

    def __post_init__(self) -> None:
        total = sum(w for _, w, _ in self.entries)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"SpriteGroup weights must sum to 1.0, got {total}")
        for _, _, (lo, hi) in self.entries:
            if lo < 0 or lo > hi:
                raise ValueError(f"SpriteGroup count range invalid: ({lo}, {hi})")

    def pick(self) -> AnimatedSprite | CompositeSprite:
        """Weighted random selection from the group."""
        r = random.random()
        cumulative = 0.0
        for sprite, weight, _ in self.entries:
            cumulative += weight
            if r < cumulative:
                return sprite
        return self.entries[-1][0]
