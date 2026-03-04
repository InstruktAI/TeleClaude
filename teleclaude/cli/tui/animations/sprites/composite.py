"""Composite sprite type for layered rendering with per-layer color."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import NamedTuple, Optional


class SpriteLayer(NamedTuple):
    """One color layer of a composite sprite.

    At each cell position:
      - positive non-space char → rendered normally (fg = color)
      - negative non-space char → rendered inverted (bg = color, fg = sky)
      - space → transparent (layer does not contribute at this cell)
    """

    color: str = "#FFFFFF"
    positive: Optional[list[str]] = None
    negative: Optional[list[str]] = None


_DEFAULT_SPEED_WEIGHTS: list[tuple[float, int]] = [(0.0, 10), (0.4, 30), (0.7, 50), (1.0, 10)]


@dataclass(frozen=True)
class CompositeSprite:
    """Multi-layer sprite with per-layer color declarations.

    Layers render back-to-front: layer 0 first, last layer on top.
    Within each layer, negative chars render before positive so that
    positive wins on overlap.

    z_weights: depth distribution as (z_level, weight) pairs.
    y_weights: vertical lane distribution as (lane, weight) pairs.
               Lane 0 = top, 1 = middle, 2 = bottom.
    speed_weights: speed distribution as (speed, weight) pairs.
                   The engine periodically picks a new target speed
                   and eases toward it. Direction is random 50/50.
    """

    layers: list[SpriteLayer]
    z_weights: Optional[list[tuple[int, int]]] = field(default_factory=list)
    y_weights: Optional[list[tuple[int, int]]] = field(default_factory=list)
    speed_weights: Optional[list[tuple[float, int]]] = field(default_factory=lambda: list(_DEFAULT_SPEED_WEIGHTS))
    theme: Optional[str] = None  # "dark", "light", or None (both)

    def tick(self, frame: int) -> CompositeSprite:
        """Static sprite -- returns self every frame."""
        return self


@dataclass(frozen=True)
class AnimatedSprite:
    """Animated sprite that cycles through frames.

    Each frame is either a list[str] (plain chars) or a CompositeSprite.
    tick(frame) returns the current renderable.
    """

    frames: list[list[str] | CompositeSprite]
    z_weights: list[tuple[int, int]] = field(default_factory=list)
    y_weights: list[tuple[int, int]] = field(default_factory=list)
    speed_weights: list[tuple[float, int]] = field(default_factory=lambda: list(_DEFAULT_SPEED_WEIGHTS))
    theme: Optional[str] = None  # "dark", "light", or None (both)

    def tick(self, frame: int) -> list[str] | CompositeSprite:
        return self.frames[frame % len(self.frames)]


@dataclass(frozen=True)
class SpriteGroup:
    """Population container with per-sprite count and weight.

    Each entry: (sprite, weight, (min_count, max_count)).
      - weight: occurrence fraction for runtime replacement (must sum to 1.0).
      - count: (min, max) entities to spawn of this type.
    """

    entries: list[tuple[AnimatedSprite | CompositeSprite, float, tuple[int, int]]]

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
