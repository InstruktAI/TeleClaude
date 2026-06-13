"""Shared todos_db exceptions."""

from __future__ import annotations


class HolderWriteRefused(ValueError):
    """A write targeted a structural holder slug.

    A holder is a todo that has been split into children; the children own all
    state and artifacts, so the holder itself carries neither. Subclasses
    ``ValueError`` so existing ``except ValueError`` paths keep working, while
    the API layer can catch this specific type and surface a clean 409 instead
    of a 500.
    """
