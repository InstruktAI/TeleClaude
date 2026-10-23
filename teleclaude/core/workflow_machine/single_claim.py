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

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.constants import ARTIFACT_INPUT
from teleclaude.core.db import db
from teleclaude.core.db_models import ProcedureEventDeliveryOutcome
from teleclaude.core.models import Session
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.workflow_machine.admission import admitted_identity
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.core.workflow_store.types import ItemIdentity
from teleclaude.entry_declarations import EntryDeclarations, SessionMode
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.references import TodoRef
from teleclaude.types.claim_change import workflow_record_of
from teleclaude.types.procedure_delivery import BINDING_SECTION, BindingField, NotDeliveredReason
from teleclaude.types.workflow_record import Phase

RESERVATION_KEY_FIELD = "reservation_key"
SLUG_FIELD = "slug"
PROJECT_FIELD = "project_path"
ACTIVE_RUNNER_FIELD = "active_runner"
_EMPTY = ""
_INPUT_REVISION_UNREADABLE = "prepared_request_input_revision_unreadable"
logger = get_logger(__name__)


def declares_single_claim(declarations: EntryDeclarations | None) -> bool:
    """Whether the declarations one initialization captured declare a single-claim driver."""
    return (
        declarations is not None
        and declarations.workflow is not None
        and declarations.workflow.session is SessionMode.SINGLE_CLAIM
    )


class RecordedBinding(BaseModel):
    """The structured procedure binding persisted on a session when it was initialized."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    procedure: str = ""
    session_mode: str = ""


def recorded_binding(session: Session) -> RecordedBinding:
    """The binding recorded on the session at initialization; an empty one when it has none."""
    binding = (session.origin_metadata or {}).get(BINDING_SECTION)
    if not isinstance(binding, dict):
        return RecordedBinding()
    return RecordedBinding(
        procedure=str(binding.get(BindingField.PROCEDURE.value) or ""),
        session_mode=str(binding.get(BindingField.SESSION_MODE.value) or ""),
    )


def session_is_single_claim(session: Session) -> bool:
    """Whether the session was initialized in single-claim mode, by the mode recorded then and never reread."""
    return recorded_binding(session).session_mode == SessionMode.SINGLE_CLAIM.value


@dataclass(frozen=True)
class ItemFacts:
    """The holder/reservation and, for a prepared start, the recorded and currently observed input revisions."""

    identity: ItemIdentity
    holder: str
    launch_key: str
    launch_phase: Phase | None = None
    prepared_revision: str = _EMPTY
    current_input_revision: str | None = None


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
    """Read the existing holder/reservation and prepared-body evidence through the project store."""
    if not slug:
        return None
    store = await get_workflow_store(str(folder))
    raw = await store.read_state(slug)
    if raw is None:
        return None
    identity = await admitted_identity(store, slug)
    if identity is None:
        return None
    record = workflow_record_of(raw)
    launch = record.launch
    prepared_revision = record.prepared.revision if record.prepared is not None else _EMPTY
    current_input_revision: str | None = None
    if launch is not None and launch.phase is Phase.PREPARED:
        try:
            current_input_revision = await store.artifact_digest(slug, ARTIFACT_INPUT)
        except Exception:
            # An unreadable body cannot qualify a prepared start; preserve the failure in the native log.
            logger.warning(_INPUT_REVISION_UNREADABLE, slug=slug, project_path=str(folder), exc_info=True)
    return ItemFacts(
        identity=identity,
        holder=str(raw.get(ACTIVE_RUNNER_FIELD) or _EMPTY),
        launch_key=launch.key if launch is not None else _EMPTY,
        launch_phase=launch.phase if launch is not None else None,
        prepared_revision=prepared_revision,
        current_input_revision=current_input_revision,
    )


def judge(facts: EventFacts, item: ItemFacts | None, bound_session_id: str) -> NotDeliveredReason | None:
    """The reason an activation delivers nothing, or None when it qualifies.

    ``bound_session_id`` is the open session bound to the item for the procedure and home, empty when none.
    """
    if facts.is_request:
        stands = item is not None and not item.holder and item.launch_key == facts.request_key
        if stands and item is not None and item.launch_phase is Phase.PREPARED:
            stands = bool(item.prepared_revision) and item.current_input_revision == item.prepared_revision
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


async def started_session_for(item: str, key: str) -> str:
    """The open session bound to the item that a driver start for this reservation is starting, or empty when none is."""
    subject = TodoRef(item).to_ref().to_token()
    for session in await db.get_sessions_by_origin_metadata(BINDING_SECTION, BindingField.SUBJECT, subject):
        if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
            continue
        if await entitled_to_request(session.session_id, item, key):
            return session.session_id
    return ""
