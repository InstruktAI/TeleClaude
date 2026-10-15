"""Single-claim responsibilities: what an activation of a driver procedure does with a request and with a notice.

``local/projects/teleclaude/design/architecture/procedure-activation`` (Single-claim responsibilities). A driver
procedure that declares ``session: single-claim`` has sessions that each serve one claim of one item. The platform tells
the two inputs apart by the declared data of the event's type: an event whose data carries a reservation key is a request,
every other event about the item is a notice.

* A request starts or wakes a driver only when its key is the item's current launch reservation and the item has no
  holder; any other request is ``not delivered`` as a ``stale request``.
* A notice goes only to the open session bound to the item whose session is the item's holder, and never starts or revives
  one; with no such holder it is ``not delivered`` with the reason ``no holder``.

The item is read through the store of the project the event's home names, never by backend name or procedure identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.core.db import db
from teleclaude.core.db_models import ProcedureEventDeliveryOutcome
from teleclaude.core.workflow_machine.publication import driver_initialization
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.entry_declarations import SessionMode
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.types.claim_change import workflow_record_of
from teleclaude.types.procedure_delivery import NotDeliveredReason

RESERVATION_KEY_FIELD = "reservation_key"
SLUG_FIELD = "slug"
PROJECT_FIELD = "project_path"


def is_single_claim(procedure_id: str) -> bool:
    """Whether the procedure's current published declaration is a single-claim driver."""
    workflow = driver_initialization(procedure_id).declarations
    return (
        workflow is not None and workflow.workflow is not None and workflow.workflow.session is SessionMode.SINGLE_CLAIM
    )


@dataclass(frozen=True)
class ItemFacts:
    """What the activation needs to know of the item: who holds it and which launch reservation stands."""

    holder: str
    launch_key: str


@dataclass(frozen=True)
class EventFacts:
    """What an event says about the item and whether it is a request: its slug and the reservation key it carries."""

    slug: str
    request_key: str
    project_path: str = ""

    @property
    def is_request(self) -> bool:
        """A request is an event whose data carries a reservation key."""
        return bool(self.request_key)


def event_facts(event_json: str) -> EventFacts:
    """The item an event is about and the reservation key it carries, read from the event\'s declared data."""
    event = ReceivedEvent.model_validate_json(event_json)
    data = event.data
    slug = str(data.get(SLUG_FIELD) or "")
    if not slug and event.subject is not None:
        slug = event.subject.identity
    return EventFacts(
        slug=slug,
        request_key=str(data.get(RESERVATION_KEY_FIELD) or ""),
        project_path=str(data.get(PROJECT_FIELD) or ""),
    )


async def read_item_facts(folder: Path, slug: str) -> ItemFacts | None:
    """The item\'s holder and standing reservation, read through the store of the project the home names."""
    if not slug:
        return None
    store = await get_workflow_store(str(folder))
    raw = await store.read_state(slug)
    if raw is None:
        return None
    launch = workflow_record_of(raw).launch
    return ItemFacts(holder=str(raw.get("active_runner") or ""), launch_key=launch.key if launch is not None else "")


def judge(facts: EventFacts, item: ItemFacts | None, bound_session_id: str) -> NotDeliveredReason | None:
    """The reason an activation delivers nothing, or None when it qualifies.

    ``bound_session_id`` is the open session bound to the item for the procedure and home, empty when none.
    """
    if facts.is_request:
        stands = item is not None and not item.holder and item.launch_key == facts.request_key
        return None if stands else NotDeliveredReason.STALE_REQUEST
    holds = item is not None and bool(item.holder) and item.holder == bound_session_id
    return None if holds else NotDeliveredReason.NO_HOLDER


async def entitled_to_request(session_id: str, slug: str, key: str) -> bool:
    """Whether an activation assigned to the session carries a request event for this item with this key."""
    rows = await db.list_session_procedure_activations(
        session_id=session_id,
        outcomes=(ProcedureEventDeliveryOutcome.PENDING, ProcedureEventDeliveryOutcome.DELIVERED),
    )
    for row in rows:
        facts = event_facts(row.event_json)
        if facts.slug == slug and facts.request_key == key:
            return True
    return False
