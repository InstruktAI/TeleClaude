"""Shared todos_db exceptions."""

from __future__ import annotations


class HolderWriteRefused(ValueError):
    """A write or removal targeted a structural holder slug.

    A holder is a todo with children grouped under it; it carries no `todo_state`,
    but its artifacts are preserved as frozen, read-only evidence — refused here.
    Subclasses ``ValueError`` so existing ``except ValueError`` paths keep working,
    while the API layer can catch this specific type and surface a clean 409
    instead of a 500 or a misleading 404.
    """
