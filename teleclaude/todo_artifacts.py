"""Helpers for logical todo artifact names."""

from __future__ import annotations


def artifact_display_filename(artifact_name: str) -> str:
    """Return the user-facing artifact name without inventing a file extension."""
    return artifact_name
