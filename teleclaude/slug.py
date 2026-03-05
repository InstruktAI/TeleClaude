"""Shared slug utilities: validation, normalization, and uniqueness."""

from __future__ import annotations

import re
from pathlib import Path

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_slug(slug: str) -> None:
    """Validate slug format; raise ValueError if invalid."""
    slug = slug.strip()
    if not slug:
        raise ValueError("Slug is required")
    if not SLUG_PATTERN.match(slug):
        raise ValueError("Invalid slug. Use lowercase letters, numbers, and hyphens only")


def normalize_slug(text: str) -> str:
    """Convert arbitrary text to a valid slug.

    Lowercases, replaces non-alphanumeric runs with hyphens, collapses
    consecutive hyphens, and strips leading/trailing hyphens.
    """
    lowered = text.lower()
    slugified = re.sub(r"[^a-z0-9]+", "-", lowered)
    slugified = re.sub(r"-+", "-", slugified).strip("-")
    return slugified


def ensure_unique_slug(base_dir: Path, slug: str) -> str:
    """Return *slug* if ``base_dir/slug`` does not exist, otherwise append -2, -3, … until free."""
    if not (base_dir / slug).exists():
        return slug
    counter = 2
    while (base_dir / f"{slug}-{counter}").exists():
        counter += 1
    return f"{slug}-{counter}"
