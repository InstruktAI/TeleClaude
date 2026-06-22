"""Shared slug utilities: validation, normalization, and uniqueness."""

from __future__ import annotations

import re
from collections.abc import Set as AbstractSet
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


def ensure_unique_slug(
    base_dir: Path,
    slug: str,
    *,
    reserved: AbstractSet[str] | None = None,
    exclude_dir: Path | None = None,
) -> str:
    """Return *slug* if free, otherwise append -2, -3, … until free.

    A slug is free when it is not in *reserved* (slugs already taken in memory,
    e.g. earlier in the same pass) and ``base_dir/slug`` does not exist —
    except ``exclude_dir`` (the caller's own existing folder, due to be renamed
    to the slug), which never counts as a collision.
    """
    reserved = reserved or frozenset()
    candidate = slug
    counter = 1
    while candidate in reserved or _folder_taken(base_dir / candidate, exclude_dir):
        counter += 1
        candidate = f"{slug}-{counter}"
    return candidate


def _folder_taken(target: Path, exclude_dir: Path | None) -> bool:
    """Whether *target* is occupied by a folder other than the caller's own ``exclude_dir``."""
    if exclude_dir is not None and target == exclude_dir:
        return False
    return target.exists()
