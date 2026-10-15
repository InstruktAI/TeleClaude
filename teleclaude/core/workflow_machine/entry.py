"""The entry verbs: start or attach to an item's driver, claim for it, and return its instruction.

``local/projects/teleclaude/spec/feature/workflow/item-acts`` is the contract. A session that does not
hold the item causes its driver to be started; the driver, an activated agent bound to the item, claims
for itself on its first call. A session that holds the item receives the instruction for its phase.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.constants import ARTIFACT_INPUT, WORKTREE_DIR
from teleclaude.core.db import db
from teleclaude.core.workflow_machine.caller import child_sessions_of, load_caller
from teleclaude.core.workflow_machine.dependencies import unmet_for_preparation, unmet_for_work
from teleclaude.core.workflow_machine.effects import reconcile_slug_supervised
from teleclaude.core.workflow_machine.heads import observe_item_supervised
from teleclaude.core.workflow_machine.instruction import InstructionFacts, render_instruction
from teleclaude.core.workflow_machine.lane import resolve_lane
from teleclaude.core.workflow_machine.ledger_log import render_log_entry
from teleclaude.core.workflow_machine.phase_reading import LaneFacts, PhaseReading, creative_snapshot, read_phase
from teleclaude.core.workflow_machine.publication import (
    PublicationError,
    WorkflowPublication,
    published_workflow_publication,
)
from teleclaude.core.workflow_machine.reasons import context_notes, reason_notes, record_reason
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ArtifactRevisionMismatch, ItemChange
from teleclaude.entry_declarations import EntryDeclarations, WorkflowDeclaration
from teleclaude.events.envelope import EventHomeRef, occurrence_id
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.references import TodoRef
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.procedure_delivery import BINDING_SECTION, BindingField
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY, LIFECYCLE_PHASE_STATE_KEY, TodoState
from teleclaude.types.workflow_record import (
    Act,
    ActStatus,
    DrivenPhase,
    EffectKind,
    EmittedEvent,
    InstructionOffer,
    LaunchReservation,
    LedgerEntry,
    NoteKind,
    PendingEffect,
    Phase,
)

logger = get_logger(__name__)


class EntryVerb(StrEnum):
    """The verbs that start or attach to a driver."""

    PREPARE = "prepare"
    WORK = "work"


class EntryRefusal(StrEnum):
    """The causes an entry verb refuses with; D11 of the item lifecycle names no others."""

    HELD = "{item} is held by session {session}"
    WAITING = "{item} is waiting on {person}"
    DRIVEN_BY = "{item} is in {phase}, which {verb} drives"
    NOT_DRIVEN = "{item} is in {phase}, which no entry verb drives"
    UNMET_DEPENDENCIES = "{item} has unmet dependencies: {dependencies}"
    REVISION_MOVED = "{item}: the intent body is at {actual}, not at the {expected} it was prepared at"
    UNKNOWN_ITEM = "no item {item} in this project"
    NO_DRIVER = "{item}: {reason}"
    CREATIVE_CHANGED = "{item}: its creative state changed while the verb ran; repeat the verb"
    NO_LAUNCH = "{item}: no driver start is awaiting a claim; the start this session was given was released"
    WRONG_RESERVATION = "{item}: this session was started for another request than the one awaiting a claim"
    NO_CHILD = "{item}: the phase {phase} dispatches no child"
    REASON_REQUIRED = (
        "{item} is ready: it is worked on only with a stated reason, from a session; "
        "repeat with `telec todo work {item} --reason <text>`"
    )
    ADMITTED = "{item} is admitted by the integrator at {sha}; the integrator delivers or parks it"
    READY_DOOR = "{item} is ready, which `telec todo work {item} --reason <text>` drives"
    HELD_NOTED = "{item} is held by session {session}; your reason is recorded as note {note}"


class EntryRefused(Exception):
    """An entry verb was refused for one named cause; nothing was written."""


class LaneNotResolved(Exception):
    """A phase was read before the entry resolved the creative lane and the integration head."""


class LaunchInProgress(Exception):
    """The driver start was requested and has not claimed yet; repeating the verb attaches to it."""


@dataclass(frozen=True)
class EntryRequest:
    """One entry call. The caller is a session, or empty for a person at a terminal."""

    project_root: str
    item: str
    verb: EntryVerb
    caller_session_id: str
    reservation: str = ""
    reason: str = ""
    wait_for_claim: bool = True
    lane: LaneFacts | None = None
    creative_snapshot: str = ""

    @property
    def resolved_lane(self) -> LaneFacts:
        """The lane facts the entry resolved before it decided; reading them earlier is a defect."""
        if self.lane is None:
            raise LaneNotResolved(self.item)
        return self.lane


@dataclass
class ReservationOutcome:
    """What the reservation write found: the note it names, the holder it met and whether the call was a retry."""

    note: str = ""
    held_by: str = ""
    retried: bool = False


@dataclass(frozen=True)
class EntryResult:
    """What an entry verb returns: the instruction text and the driver session it concerns."""

    text: str
    driver_session_id: str


REQUESTED_NOTE: Final = "{item}: a driver was requested."
REASON_NOTED: Final = " Your reason is recorded as note {note}."
RETRY_NOTE: Final = "{item}: this reason is already recorded as note {note} in this stamp's cycle; nothing was started."
LAUNCH_NOTE: Final = "{item}: a driver was requested; session {session} holds the claim."
CLAIM_NOTE: Final = "claimed"
NO_SESSION: Final = ""
TASK_LANE_LABEL: Final = "the task lane"
ATTACH_WAIT_SECONDS: Final = 120.0
ATTACH_POLL_SECONDS: Final = 0.5
LAUNCH_PENDING_TEMPLATE: Final = (
    "{item}: the driver start (reservation {key}) has not claimed yet; repeat the verb to attach."
)
OFFER_ACT: Final = "offer"
EFFECT_REQUEST: Final = "request"
EFFECT_WORKTREE: Final = "worktree"
EFFECT_ID_TEMPLATE: Final = "{key}:{name}"
RESERVATION_PARAM: Final = "reservation_key"
REQUESTED_BY_PARAM: Final = "requested_by"
DEPENDENCY_SEPARATOR: Final = ", "

_VERB_FOR_PHASE: Final[Mapping[Phase, EntryVerb]] = {
    Phase.PREPARATION: EntryVerb.PREPARE,
    Phase.PREPARED: EntryVerb.WORK,
    Phase.WORK: EntryVerb.WORK,
    Phase.READY: EntryVerb.WORK,
}
_DRIVEN_PHASE: Final[Mapping[Phase, DrivenPhase]] = {
    Phase.PREPARATION: DrivenPhase.PREPARATION,
    Phase.PREPARED: DrivenPhase.PREPARED,
    Phase.WORK: DrivenPhase.WORK,
    Phase.READY: DrivenPhase.READY,
}
_HELD_DRIVEN_PHASE: Final[Mapping[Phase, DrivenPhase]] = {
    Phase.PREPARATION: DrivenPhase.PREPARATION,
    Phase.PREPARED: DrivenPhase.WORK,
    Phase.WORK: DrivenPhase.WORK,
    Phase.READY: DrivenPhase.READY,
}
"""The driven phase whose scope governs the instruction: a prepared item is held as work from the claim."""
_REQUEST_EVENT: Final[Mapping[Phase, EmittedEvent]] = {
    Phase.PREPARATION: EmittedEvent.PREPARATION_REQUESTED,
    Phase.PREPARED: EmittedEvent.WORK_REQUESTED,
    Phase.WORK: EmittedEvent.WORK_REQUESTED,
    Phase.READY: EmittedEvent.WORK_REQUESTED,
}


def _refuse(refusal: EntryRefusal, **fields: str) -> EntryRefused:
    return EntryRefused(refusal.value.format(**fields))


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _unmet_dependencies(store: WorkflowStore, item: str, verb: EntryVerb) -> list[str]:
    """The dependencies the verb's gate has not cleared: prepared for preparation, delivered for work."""
    if verb is EntryVerb.PREPARE:
        return await unmet_for_preparation(store, item)
    return await unmet_for_work(store, item)


def _recheck_creative(request: EntryRequest, state_dict: Mapping[str, StateValue]) -> None:
    """Refuse a claim or a reservation when the creative section moved after the lane was resolved."""
    if creative_snapshot(state_dict) != request.creative_snapshot:
        raise _refuse(EntryRefusal.CREATIVE_CHANGED, item=request.item)


def _check_drivable(request: EntryRequest, state: TodoState, reading: PhaseReading, *, starting: bool = False) -> Phase:
    """The phase the verb may drive, or the one named cause for refusing.

    ``starting`` is the call that reserves a driver: on a ready item only that call states the reason.
    """
    phase = reading.phase
    if phase is Phase.WAITING:
        waiting = state.workflow.waiting
        raise _refuse(EntryRefusal.WAITING, item=request.item, person=waiting.person if waiting else NO_SESSION)
    if phase is None or phase not in _VERB_FOR_PHASE:
        shown = phase.value if phase is not None else TASK_LANE_LABEL
        raise _refuse(EntryRefusal.NOT_DRIVEN, item=request.item, phase=shown)
    if phase is Phase.READY:
        admitted = state.workflow.admitted
        if admitted is not None:
            raise _refuse(EntryRefusal.ADMITTED, item=request.item, sha=admitted.sha)
        if request.verb is not EntryVerb.WORK:
            raise _refuse(EntryRefusal.READY_DOOR, item=request.item)
        if starting and (not request.reason.strip() or not request.caller_session_id):
            raise _refuse(EntryRefusal.REASON_REQUIRED, item=request.item)
    if _VERB_FOR_PHASE[phase] is not request.verb:
        raise _refuse(EntryRefusal.DRIVEN_BY, item=request.item, phase=phase.value, verb=_VERB_FOR_PHASE[phase].value)
    return phase


async def _is_bound_driver(session_id: str, item: str, procedure_id: str, project_root: str) -> bool:
    """Whether the session is the agent procedure activation bound to this item of this project for the driver procedure.

    The binding names the subject, the procedure and the home it was activated under. An item of the same name in
    another project is a different item, so the home the binding records must be the home of this project.
    """
    if not session_id:
        return False
    session = await db.get_session(session_id)
    if session is None or session.job != procedure_id:
        return False
    binding = (session.origin_metadata or {}).get(BINDING_SECTION)
    if not isinstance(binding, dict):
        return False
    home = home_for_project_path(project_root)
    return (
        isinstance(home, EventHomeRef)
        and binding.get(BindingField.SUBJECT.value) == TodoRef(item).to_ref().to_token()
        and binding.get(BindingField.HOME.value) == home.to_token()
    )


def _driver_for(publication: WorkflowPublication, phase: Phase, item: str) -> tuple[str, WorkflowDeclaration]:
    try:
        declared, workflow = publication.driver_for(_DRIVEN_PHASE[phase])
    except PublicationError as error:
        raise _refuse(EntryRefusal.NO_DRIVER, item=item, reason=str(error)) from error
    return declared.procedure_id, workflow


async def _own_publication(session_id: str) -> WorkflowPublication | None:
    """The publication a driver was initialized under, from its session's stored invocation; None without one."""
    handover = await db.get_startup_handover(session_id) if session_id else None
    invocation = handover.intent.invocation if handover is not None else None
    if invocation is not None and invocation.workflow_publication:
        return WorkflowPublication.from_json(invocation.workflow_publication)
    return None


async def _publication_for(request: EntryRequest, holder: str | None, phase: Phase) -> tuple[WorkflowPublication, bool]:
    """The governing publication and whether the caller is the driver bound to this item under it.

    The holding driver, and the bound driver making its first claiming call, work under the publication they
    were initialized under; any other caller uses the current one.
    """
    own = await _own_publication(request.caller_session_id)
    if own is not None:
        try:
            procedure_id, _ = _driver_for(own, phase, request.item)
        except EntryRefused:
            procedure_id = NO_SESSION
        bound = bool(procedure_id) and await _is_bound_driver(
            request.caller_session_id, request.item, procedure_id, request.project_root
        )
        if holder == request.caller_session_id or bound:
            return own, bound
    return published_workflow_publication(), False


def _apply_claim(
    request: EntryRequest, item_id: str, branch: str, role: str, state_dict: dict[str, StateValue] | None
) -> ItemChange:
    """Claim the item for the calling driver inside the commit, or refuse."""
    if state_dict is None:
        raise _refuse(EntryRefusal.UNKNOWN_ITEM, item=request.item)
    _recheck_creative(request, state_dict)
    state = TodoState.model_validate(state_dict)
    reading = read_phase(state, request.resolved_lane)
    phase = _check_drivable(request, state, reading)
    holder = state.active_runner or None
    if holder is not None:
        raise _refuse(EntryRefusal.HELD, item=request.item, session=holder)
    launch = state.workflow.launch
    if launch is None:
        raise _refuse(EntryRefusal.NO_LAUNCH, item=request.item)
    if launch.key != request.reservation:
        raise _refuse(EntryRefusal.WRONG_RESERVATION, item=request.item)
    record = state.workflow.model_copy(deep=True)
    key = occurrence_id(request.project_root, item_id, Act.CLAIM.value, str(record.claim_epoch + 1))
    entry = LedgerEntry(
        seq=len(record.ledger) + 1,
        act=Act.CLAIM,
        key=key,
        epoch=record.claim_epoch + 1,
        at=_now(),
        role=role,
        session_id=request.caller_session_id,
        bound=branch if phase in (Phase.PREPARED, Phase.WORK) else NO_SESSION,
        text=CLAIM_NOTE,
    )
    record.ledger.append(entry)
    record.launch = None
    record.instruction_offer = None
    stale_stamp = phase is Phase.WORK and state.lifecycle_phase is LifecyclePhase.READY
    if stale_stamp:
        record.stamp = None
    effects: list[PendingEffect] = []
    if phase in (Phase.PREPARED, Phase.WORK):
        effects.append(
            PendingEffect(
                id=EFFECT_ID_TEMPLATE.format(key=key, name=EFFECT_WORKTREE),
                act_key=key,
                kind=EffectKind.ENSURE_WORKTREE,
            )
        )
    record.pending_effects.extend(effects)
    record.act_status[key] = ActStatus.IN_PROGRESS if effects else ActStatus.COMPLETE
    new_state: dict[str, StateValue] = {
        **state_dict,
        WORKFLOW_STATE_KEY: record.to_state(),
        ACTIVE_RUNNER_STATE_KEY: request.caller_session_id,
    }
    if phase is Phase.PREPARED or stale_stamp:
        new_state[LIFECYCLE_PHASE_STATE_KEY] = LifecyclePhase.WORK.value
    return ItemChange(state=new_state, log_entry=_claim_log(entry, request.item))


CLAIM_LOG_TEMPLATE: Final = (
    "\n### {at} — {role} · {session} · claim\n\n{item} claimed by {role} session {session}{branch}.\n"
)
CLAIM_LOG_BRANCH: Final = " on branch {branch}"


def _claim_log(entry: LedgerEntry, item: str) -> str:
    branch = CLAIM_LOG_BRANCH.format(branch=entry.bound) if entry.bound else NO_SESSION
    return CLAIM_LOG_TEMPLATE.format(at=entry.at, role=entry.role, session=entry.session_id, item=item, branch=branch)


def _apply_reservation(
    request: EntryRequest,
    item_id: str,
    phase: Phase,
    role: str,
    state_dict: dict[str, StateValue] | None,
    outcome: ReservationOutcome,
) -> ItemChange | None:
    """Record the launch reservation and the request notice in one write, or leave a pending one in place.

    On a ready item the call's reason is recorded in the same write, attributed to the calling session, and the write
    decides from the row as it is now whether the item is held, being started, admitted or free: a reason is never
    dropped because a holder appeared, and a true retry in the same stamp cycle starts nothing. ``outcome`` reports
    the note key, the holder that was found, and whether the call was a retry.
    """
    if state_dict is None:
        raise _refuse(EntryRefusal.UNKNOWN_ITEM, item=request.item)
    _recheck_creative(request, state_dict)
    state = TodoState.model_validate(state_dict)
    reading = read_phase(state, request.resolved_lane)
    _check_drivable(request, state, reading, starting=True)
    holder = state.active_runner or None
    if holder is not None and phase is not Phase.READY:
        raise _refuse(EntryRefusal.HELD, item=request.item, session=holder)
    record = state.workflow.model_copy(deep=True)
    log = NO_SESSION
    created = False
    if phase is Phase.READY:
        recorded = record_reason(
            record,
            project_root=request.project_root,
            item_id=item_id,
            session_id=request.caller_session_id,
            role=role,
            text=request.reason.strip(),
        )
        record = recorded.record.model_copy(deep=True)
        outcome.note = recorded.note.key
        created = recorded.created
        log = render_log_entry(recorded.note) if created else NO_SESSION
    if holder is not None:
        outcome.held_by = holder
        if not created:
            return None
        return ItemChange(state={**state_dict, WORKFLOW_STATE_KEY: record.to_state()}, log_entry=log)
    if phase is Phase.READY and not created and state.workflow.launch is None:
        outcome.retried = True
        return None
    if state.workflow.launch is not None:
        if not log:
            return ItemChange(state=state_dict)
        return ItemChange(state={**state_dict, WORKFLOW_STATE_KEY: record.to_state()}, log_entry=log)
    key = occurrence_id(request.project_root, item_id, EFFECT_REQUEST, str(record.claim_epoch), _now())
    record.launch = LaunchReservation(
        key=key,
        phase=phase,
        requested_at=_now(),
        requested_by=request.caller_session_id or NO_SESSION,
        effect_id=EFFECT_ID_TEMPLATE.format(key=key, name=EFFECT_REQUEST),
    )
    record.pending_effects.append(
        PendingEffect(
            id=EFFECT_ID_TEMPLATE.format(key=key, name=EFFECT_REQUEST),
            act_key=key,
            kind=EffectKind.EMIT_EVENT,
            event=_REQUEST_EVENT[phase],
            params={RESERVATION_PARAM: key, REQUESTED_BY_PARAM: request.caller_session_id or NO_SESSION},
        )
    )
    record.act_status[key] = ActStatus.IN_PROGRESS
    return ItemChange(state={**state_dict, WORKFLOW_STATE_KEY: record.to_state()}, log_entry=log)


_STAMPED_STORED: Final = frozenset(
    {LifecyclePhase.READY, LifecyclePhase.FINALIZE_READY, LifecyclePhase.REVIEW_APPROVED}
)
"""The stored phases whose reading depends on a stamp's commit being the integration head."""


async def _clear_stale_stamp(store: WorkflowStore, request: EntryRequest) -> None:
    """The holder's entry settles a stamp the head moved past: the stamp is cleared and work is stored, in one write."""

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            raise _refuse(EntryRefusal.UNKNOWN_ITEM, item=request.item)
        state = TodoState.model_validate(current)
        if state.active_runner != request.caller_session_id:
            raise _refuse(EntryRefusal.HELD, item=request.item, session=state.active_runner or NO_SESSION)
        if (
            read_phase(state, request.resolved_lane).phase is not Phase.WORK
            or state.lifecycle_phase not in _STAMPED_STORED
        ):
            return None
        record = state.workflow.model_copy(deep=True)
        record.stamp = None
        return ItemChange(
            state={
                **current,
                WORKFLOW_STATE_KEY: record.to_state(),
                LIFECYCLE_PHASE_STATE_KEY: LifecyclePhase.WORK.value,
            }
        )

    await store.commit_item_change(request.item, expect_digests={}, mutate=mutate, updated_by=request.caller_session_id)


async def _await_claim(store: WorkflowStore, request: EntryRequest) -> str:
    """The session that claimed, waiting within a bound for the started driver to do so."""
    deadline = asyncio.get_running_loop().time() + ATTACH_WAIT_SECONDS
    while True:
        raw = await store.read_state(request.item)
        if raw is not None:
            holder = TodoState.model_validate(raw).active_runner
            if holder:
                return holder
        if asyncio.get_running_loop().time() >= deadline:
            key = TodoState.model_validate(raw).workflow.launch if raw is not None else None
            raise LaunchInProgress(
                LAUNCH_PENDING_TEMPLATE.format(item=request.item, key=key.key if key else NO_SESSION)
            )
        await asyncio.sleep(ATTACH_POLL_SECONDS)


async def _claim(
    store: WorkflowStore, request: EntryRequest, item_id: str, branch: str, expected: Mapping[str, str]
) -> None:
    """The bound driver claims for itself, with the role the platform recorded for its session."""
    caller = await load_caller(request.caller_session_id)
    role = (caller.role if caller is not None else None) or NO_SESSION
    await store.commit_item_change(
        request.item,
        expect_digests=expected,
        mutate=lambda current, _digests: _apply_claim(request, item_id, branch, role, current),
        updated_by=request.caller_session_id,
    )
    await reconcile_slug_supervised(request.project_root, request.item)


async def _launch(
    store: WorkflowStore, request: EntryRequest, item_id: str, phase: Phase, expected: Mapping[str, str]
) -> EntryResult:
    """Record the launch reservation, then attach to the driver that claims for it."""
    caller = await load_caller(request.caller_session_id)
    role = (caller.role if caller is not None else None) or NO_SESSION
    outcome = ReservationOutcome()
    await store.commit_item_change(
        request.item,
        expect_digests=expected,
        mutate=lambda current, _digests: _apply_reservation(request, item_id, phase, role, current, outcome),
        updated_by=request.caller_session_id or None,
    )
    if outcome.held_by:
        raise _refuse(EntryRefusal.HELD_NOTED, item=request.item, session=outcome.held_by, note=outcome.note)
    if outcome.retried:
        return EntryResult(text=RETRY_NOTE.format(item=request.item, note=outcome.note), driver_session_id=NO_SESSION)
    await reconcile_slug_supervised(request.project_root, request.item)
    suffix = REASON_NOTED.format(note=outcome.note) if outcome.note else NO_SESSION
    if not request.wait_for_claim:
        return EntryResult(text=REQUESTED_NOTE.format(item=request.item) + suffix, driver_session_id=NO_SESSION)
    started = await _await_claim(store, request)
    return EntryResult(text=LAUNCH_NOTE.format(item=request.item, session=started) + suffix, driver_session_id=started)


async def _offer_instruction(
    store: WorkflowStore, request: EntryRequest, item_id: str
) -> tuple[str, list[LedgerEntry]]:
    """Record the offer an instruction for a held ready item prints, and the reason notes it lists, in one write.

    The offer names the highest reason note this transaction read, so a reason noted afterwards has a higher position
    than any offer already printed and the release presenting that offer's key is refused.
    """
    offered: list[tuple[str, list[LedgerEntry]]] = []

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            raise _refuse(EntryRefusal.UNKNOWN_ITEM, item=request.item)
        state = TodoState.model_validate(current)
        if state.active_runner != request.caller_session_id:
            raise _refuse(EntryRefusal.HELD, item=request.item, session=state.active_runner or NO_SESSION)
        if read_phase(state, request.resolved_lane).phase is not Phase.READY:
            raise _refuse(EntryRefusal.NOT_DRIVEN, item=request.item, phase=state.lifecycle_phase.value)
        record = state.workflow.model_copy(deep=True)
        upto = max((note.seq for note in reason_notes(record)), default=0)
        notes = context_notes(record)
        key = occurrence_id(request.project_root, item_id, OFFER_ACT, str(record.claim_epoch), str(upto), _now())
        record.instruction_offer = InstructionOffer(key=key, upto_seq=upto, epoch=record.claim_epoch)
        offered.append((key, notes))
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: record.to_state()})

    await store.commit_item_change(request.item, expect_digests={}, mutate=mutate, updated_by=request.caller_session_id)
    return offered[-1]


async def _instruct(
    store: WorkflowStore,
    request: EntryRequest,
    item_id: str,
    publication: WorkflowPublication,
    workflow: WorkflowDeclaration,
    phase: Phase,
    branch: str,
) -> EntryResult:
    """The instruction for the holding driver of the phase."""
    children = await child_sessions_of(request.caller_session_id)
    offer_key = NO_SESSION
    reasons: list[tuple[str, bool, str]] = []
    if phase is Phase.READY:
        offer_key, notes = await _offer_instruction(store, request, item_id)
        reasons = [(note.session_id, note.note_kind is NoteKind.REASON, note.text) for note in notes]
    worktree = (
        str(Path(request.project_root) / WORKTREE_DIR / request.item)
        if phase in (Phase.PREPARED, Phase.WORK)
        else NO_SESSION
    )
    driven = _HELD_DRIVEN_PHASE[phase]
    child = publication.child_of(workflow, driven)
    text = render_instruction(
        InstructionFacts(
            item=request.item,
            phase=Phase.WORK if phase is Phase.PREPARED else phase,
            session_id=request.caller_session_id,
            branch=branch,
            worktree=worktree,
            child_sessions=children,
            reasons=reasons,
            offer_key=offer_key,
        ),
        workflow,
        driven,
        child.declarations if child is not None else None,
    )
    return EntryResult(text=text, driver_session_id=request.caller_session_id)


async def enter(request: EntryRequest) -> EntryResult:
    """Run one entry verb for an item."""
    store = await get_workflow_store(request.project_root)
    request = replace(request, project_root=str(store.project_root))
    raw = await store.read_state(request.item)
    item_id = store.resolve_store_address_sync(request.item)
    if raw is None or item_id is None:
        raise _refuse(EntryRefusal.UNKNOWN_ITEM, item=request.item)
    state = TodoState.model_validate(raw)
    holder = state.active_runner or None
    request = replace(
        request,
        lane=await resolve_lane(store, request.project_root, request.item, raw, state),
        creative_snapshot=creative_snapshot(raw),
    )
    reading = read_phase(state, request.resolved_lane)
    other_holder = holder is not None and holder != request.caller_session_id
    noting = (
        other_holder
        and reading.phase is Phase.READY
        and bool(request.reason.strip())
        and bool(request.caller_session_id)
    )
    if other_holder and not noting:
        raise _refuse(EntryRefusal.HELD, item=request.item, session=holder or NO_SESSION)
    if holder == request.caller_session_id and reading.phase is Phase.WORK and state.lifecycle_phase in _STAMPED_STORED:
        await _clear_stale_stamp(store, request)
        raw = await store.read_state(request.item) or raw
        state = TodoState.model_validate(raw)
        reading = read_phase(state, request.resolved_lane)
    phase = _check_drivable(request, state, reading)
    unmet = await _unmet_dependencies(store, request.item, request.verb)
    if unmet and holder is None:
        raise _refuse(EntryRefusal.UNMET_DEPENDENCIES, item=request.item, dependencies=DEPENDENCY_SEPARATOR.join(unmet))
    await observe_item_supervised(request.project_root, request.item)
    publication, bound = await _publication_for(request, holder, phase)
    _, workflow = _driver_for(publication, phase, request.item)
    branch = request.item
    expected = request.resolved_lane.expected_digests
    if phase is Phase.PREPARED and state.workflow.prepared is not None:
        expected = {**expected, ARTIFACT_INPUT: state.workflow.prepared.revision}
    if holder is None or noting:
        try:
            if noting or not bound:
                return await _launch(store, request, item_id, phase, expected)
            await _claim(store, request, item_id, branch, expected)
        except ArtifactRevisionMismatch as mismatch:
            if mismatch.name == ARTIFACT_INPUT and phase is Phase.PREPARED:
                raise _refuse(
                    EntryRefusal.REVISION_MOVED, item=request.item, actual=mismatch.actual, expected=mismatch.expected
                ) from mismatch
            raise _refuse(EntryRefusal.CREATIVE_CHANGED, item=request.item) from mismatch
    return await _instruct(store, request, item_id, publication, workflow, phase, branch)


@dataclass(frozen=True)
class ChildPlan:
    """The child a holding driver starts, from the declarations the driver was initialized under."""

    procedure_id: str
    arguments: str
    declarations: EntryDeclarations
    subfolder: str


async def plan_child(project_root: str, item: str, caller_session_id: str) -> ChildPlan:
    """Resolve the child launch for the caller, who must hold the item."""
    store = await get_workflow_store(project_root)
    raw = await store.read_state(item)
    if raw is None:
        raise _refuse(EntryRefusal.UNKNOWN_ITEM, item=item)
    state = TodoState.model_validate(raw)
    holder = state.active_runner or None
    if holder != caller_session_id:
        raise _refuse(EntryRefusal.HELD, item=item, session=holder or NO_SESSION)
    phase = read_phase(state, await resolve_lane(store, project_root, item, raw, state)).phase
    if phase is None or phase not in _VERB_FOR_PHASE:
        raise _refuse(EntryRefusal.NOT_DRIVEN, item=item, phase=phase.value if phase else NO_SESSION)
    publication = await _own_publication(caller_session_id) or published_workflow_publication()
    _, workflow = _driver_for(publication, phase, item)
    driven = _HELD_DRIVEN_PHASE[phase]
    child = publication.child_of(workflow, driven)
    if child is None:
        raise _refuse(EntryRefusal.NO_CHILD, item=item, phase=driven.value)
    subfolder = f"{WORKTREE_DIR}/{item}" if phase in (Phase.PREPARED, Phase.WORK) else NO_SESSION
    return ChildPlan(
        procedure_id=child.procedure_id,
        arguments=item,
        declarations=child.declarations,
        subfolder=subfolder,
    )
