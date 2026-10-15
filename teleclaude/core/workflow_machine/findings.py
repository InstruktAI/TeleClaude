"""Findings the work driver recorded and the builder has not answered, and how they are supplied.

``local/projects/teleclaude/spec/feature/workflow/work-review-cycle`` is the contract. The builder is
supplied its unanswered findings at the start of each of its turns and when it stops, without having to
look. A finding supplied at a stop and still unanswered does not hold a later stop, but is supplied
again at the next turn start. The offer is recorded only after the response carrying it was written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from teleclaude.core.workflow_machine.act_types import BOUND_SEPARATOR
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Act, LedgerEntry, OfferedFinding, WorkflowRecord

HEADING_TEMPLATE: Final = "{item} has findings waiting for your reply:"
FINDING_TEMPLATE: Final = "- {key}: {text}"
REPLY_TEMPLATE: Final = "Answer each with `telec todo act {item} reply --finding <key> <what you did>`."
LINE_SEPARATOR: Final = "\n"


class SupplyBoundary(StrEnum):
    """The two places the builder is supplied its findings."""

    TURN_START = "turn_start"
    STOP = "stop"


@dataclass(frozen=True)
class ItemFindings:
    """The unanswered findings the builder has to be supplied, read from the item."""

    holder: str
    entries: tuple[LedgerEntry, ...]


@dataclass(frozen=True)
class FindingsSupply:
    """The text to supply and what the offer records once it was written."""

    project_root: str
    item: str
    session_id: str
    text: str
    keys: tuple[str, ...]


def unanswered(record: WorkflowRecord) -> tuple[LedgerEntry, ...]:
    """The findings of the ledger no reply has answered, in the order they were recorded."""
    answered = {entry.bound.split(BOUND_SEPARATOR, 1)[0] for entry in record.ledger if entry.act is Act.REPLY}
    return tuple(entry for entry in record.ledger if entry.act is Act.FINDING and entry.key not in answered)


async def read_findings(project_root: str, item: str, session_id: str, boundary: SupplyBoundary) -> ItemFindings | None:
    """The item's holder and the findings this boundary owes the session; None when the item is unknown."""
    store = await get_workflow_store(project_root)
    raw = await store.read_state(item)
    if raw is None:
        return None
    state = TodoState.model_validate(raw)
    entries = unanswered(state.workflow)
    if boundary is SupplyBoundary.STOP:
        offered = {offer.finding_key for offer in state.workflow.offered_findings if offer.session_id == session_id}
        entries = tuple(entry for entry in entries if entry.key not in offered)
    return ItemFindings(holder=state.active_runner or "", entries=entries)


def render_supply(item: str, entries: tuple[LedgerEntry, ...]) -> str:
    """The text that carries the findings to the builder."""
    lines = [HEADING_TEMPLATE.format(item=item)]
    lines.extend(FINDING_TEMPLATE.format(key=entry.key, text=entry.text) for entry in entries)
    lines.append(REPLY_TEMPLATE.format(item=item))
    return LINE_SEPARATOR.join(lines)


async def record_offered(supply: FindingsSupply) -> None:
    """Record that the session was offered these findings at a stop, after the response carrying them was written."""
    store = await get_workflow_store(supply.project_root)

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            return None
        record = workflow_record_of(current)
        known = {(offer.session_id, offer.finding_key) for offer in record.offered_findings}
        fresh = [key for key in supply.keys if (supply.session_id, key) not in known]
        if not fresh:
            return None
        updated = record.model_copy(deep=True)
        updated.offered_findings.extend(OfferedFinding(session_id=supply.session_id, finding_key=key) for key in fresh)
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()})

    await store.commit_item_change(supply.item, expect_digests={}, mutate=mutate, updated_by=supply.session_id)
