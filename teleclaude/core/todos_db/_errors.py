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


class HolderTransitionRefused(ValueError):
    """A holder transition was refused because the parent is past prepare.

    Grouping a child under a parent strips the parent's `todo_state`. A parent
    whose `lifecycle_phase` has reached `prepared` or a work-lane phase must not
    become a holder, since that would shred its build/review/finalize tracking.
    Subclasses ``ValueError`` so existing ``except ValueError`` paths keep
    working, while the API layer can catch this specific type and surface a
    clean 409.
    """


class HolderReconciliationRefused(ValueError):
    """A holder transition was refused because documentation reconciliation failed safely.

    Subclasses ``ValueError`` so existing ``except ValueError`` paths keep
    working, while the API layer can catch this specific type and surface a
    clean 409.
    """


class DeliveryProvenanceRefused(ValueError):
    """A non-task todo delivery omitted its required delivery commit."""

    def __init__(self, slug: str, kind: str | None) -> None:
        self.slug = slug
        self.kind = kind
        super().__init__(f"delivery for {kind or 'unknown'} todo {slug!r} requires commit provenance")
