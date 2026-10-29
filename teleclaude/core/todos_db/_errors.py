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


class ContractUnderExecutionRefused(ValueError):
    """A prepare-artifact write was refused because the todo's contract is under execution.

    The todo's stored lifecycle phase is a work-lane phase, so the contract the work
    lane is executing against must not change underneath it. ``phase`` carries the
    stored phase for the refusal detail. Subclasses ``ValueError`` so existing
    ``except ValueError`` paths keep working, while the API layer can catch this
    specific type and surface a clean 409.
    """

    def __init__(self, slug: str, phase: str) -> None:
        self.slug = slug
        self.phase = phase
        super().__init__(f"Cannot write artifact: the contract of todo {slug!r} is under execution (phase {phase})")


class HolderTransitionRefused(ValueError):
    """A holder transition was refused because the parent is past prepare.

    Grouping a child under a parent strips the parent's `todo_state`. A parent
    whose `lifecycle_phase` has reached `prepared` or a work-lane phase must not
    become a holder, since that would shred its build/review/finalize tracking.
    Subclasses ``ValueError`` so existing ``except ValueError`` paths keep
    working, while the API layer can catch this specific type and surface a
    clean 409.
    """


class GroupCycleRefused(ValueError):
    """A todo cannot be grouped beneath itself or one of its descendants."""


class GroupDependencyConflict(ValueError):
    """A todo cannot depend on a holder in its effective group chain."""

    def __init__(self, slug: str, holder: str) -> None:
        self.slug = slug
        self.holder = holder
        super().__init__(
            f"todo '{slug}' cannot depend on holder '{holder}': group membership and an after dependency "
            "on the same holder are mutually exclusive"
        )


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
