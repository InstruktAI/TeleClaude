"""Slug-addressed todo actions: freeze, unfreeze, and deliver.

Each action runs against the project's workflow store and answers with a
structured result. The CLI's local path and the daemon's routes both run these
functions, so a todo acted on from another computer is acted on by the same
rule as one acted on in place; the caller renders the result and decides
nothing about the todo's state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Self

from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.next_machine.marker_reconciliation import MarkerMoment, reconcile_lifecycle_markers
from teleclaude.core.todo_dependency_warnings import freeze_dependent_warnings, unfreeze_frozen_dep_warnings
from teleclaude.core.todos_db import get_todos_db
from teleclaude.core.todos_db._errors import DeliveryProvenanceRefused

_OUTCOME_FIELD = "outcome"
_DETAIL_FIELD = "detail"
_WARNINGS_FIELD = "warnings"
_RECONCILIATION_FAILED_DETAIL = "Delivery reconciliation failed for {slug}: {reason}"
_PROVENANCE_REFUSED_DETAIL = "Delivery refused for {slug}: --commit is required for {kind} todos."
_UNKNOWN_KIND = "unknown"
_NOT_AN_OBJECT_DETAIL = "slug action result must be a JSON object"


class SlugActionOutcome(StrEnum):
    """What a slug-addressed action did."""

    DONE = "done"
    NOT_FOUND = "not_found"
    REFUSED = "refused"


@dataclass(frozen=True)
class SlugActionResult:
    """The structured answer of a slug-addressed action."""

    outcome: SlugActionOutcome
    detail: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - JSON body of a route response
        """Serialize as the JSON body a route answers with."""
        return {_OUTCOME_FIELD: self.outcome.value, _DETAIL_FIELD: self.detail, _WARNINGS_FIELD: list(self.warnings)}

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Rebuild a result from a route's JSON body."""
        if not isinstance(data, dict):
            raise ValueError(_NOT_AN_OBJECT_DETAIL)
        detail = data.get(_DETAIL_FIELD)
        warnings = data.get(_WARNINGS_FIELD)
        return cls(
            outcome=SlugActionOutcome(str(data.get(_OUTCOME_FIELD))),
            detail=detail if isinstance(detail, str) else None,
            warnings=[item for item in warnings if isinstance(item, str)] if isinstance(warnings, list) else [],
        )


async def freeze_todo(project_root: Path, slug: str) -> SlugActionResult:
    """Move a todo to the icebox, warning about active todos it leaves waiting."""
    todos_db = await get_todos_db(project_root)
    if not await todos_db.freeze(slug):
        return SlugActionResult(outcome=SlugActionOutcome.NOT_FOUND)
    open_dependents = await todos_db.get_open_dependents(slug)
    return SlugActionResult(outcome=SlugActionOutcome.DONE, warnings=freeze_dependent_warnings(slug, open_dependents))


async def unfreeze_todo(project_root: Path, slug: str) -> SlugActionResult:
    """Return an iceboxed todo to the active list, warning about dependencies still iceboxed."""
    todos_db = await get_todos_db(project_root)
    if not await todos_db.unfreeze(slug):
        return SlugActionResult(outcome=SlugActionOutcome.NOT_FOUND)
    dependencies = await todos_db.get_deps_with_status(slug)
    return SlugActionResult(outcome=SlugActionOutcome.DONE, warnings=unfreeze_frozen_dep_warnings(slug, dependencies))


async def deliver_todo(project_root: Path, slug: str, commit: str | None) -> SlugActionResult:
    """Mark a todo delivered and clean up what its delivery leaves behind."""
    receipt = await asyncio.to_thread(reconcile_lifecycle_markers, project_root, slug, MarkerMoment.DELIVER)
    if not receipt.succeeded:
        return SlugActionResult(
            outcome=SlugActionOutcome.REFUSED,
            detail=_RECONCILIATION_FAILED_DETAIL.format(slug=slug, reason=receipt.reason),
        )
    todos_db = await get_todos_db(project_root)
    try:
        delivered = await todos_db.deliver(
            slug,
            reconciliation_receipt=receipt,
            reconciliation_root=project_root,
            commit=commit,
        )
    except DeliveryProvenanceRefused as exc:
        return SlugActionResult(
            outcome=SlugActionOutcome.REFUSED,
            detail=_PROVENANCE_REFUSED_DETAIL.format(slug=exc.slug, kind=exc.kind or _UNKNOWN_KIND),
        )
    if not delivered:
        return SlugActionResult(outcome=SlugActionOutcome.NOT_FOUND)
    await asyncio.to_thread(cleanup_delivered_slug, str(project_root), slug)
    return SlugActionResult(outcome=SlugActionOutcome.DONE)
