"""Shared todos_db exceptions."""

from __future__ import annotations


class HolderWriteRefused(ValueError):
    """A write targeted a structural holder slug.

    A holder is a todo with children grouped under it; the children own all state
    and artifacts, so the holder itself carries neither. Subclasses ``ValueError`` so
    existing ``except ValueError`` paths keep working, while the API layer can
    catch this specific type and surface a clean 409 instead of a 500.
    """


class HolderTransitionRefused(ValueError):
    """A holder transition was refused because the parent is past prepare.

    Grouping a child under a parent strips the parent to structure plus its
    frozen input artifact. A parent that already carries prepared (non-``input``)
    artifacts — a PRD, architecture, plan, or build output — must not be turned
    into a holder, since that would shred work-phase material. Subclasses
    ``ValueError`` so existing ``except ValueError`` paths keep working, while the
    API layer can catch this specific type and surface a clean 409.
    """
