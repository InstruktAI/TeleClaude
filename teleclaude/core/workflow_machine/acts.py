"""The sealed act command's engine: one authenticated act becomes one atomic commit with its pending effects.

``local/projects/teleclaude/spec/feature/workflow/item-acts`` is the contract. The caller's facts and the
facts that need other stores (the claiming group, the person's authority, the child sessions) are resolved
before the commit; the commit itself re-checks the holder, the phase and the artifact revisions inside the
writer lock, so a decision made on a stale read is refused rather than applied.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.constants import ARTIFACT_INPUT
from teleclaude.core.next_machine.create import creative_incomplete
from teleclaude.core.roles import RoleName
from teleclaude.core.workflow_machine.act_types import BOUND_SEPARATOR, ActRefused, ActRequest, ActResult, Refusal
from teleclaude.core.workflow_machine.authority import configured_person, has_project_authority
from teleclaude.core.workflow_machine.caller import CallerFacts, child_sessions_of, in_claiming_group, load_caller
from teleclaude.core.workflow_machine.effects import reconcile_slug_supervised
from teleclaude.core.workflow_machine.heads import observe_item_supervised
from teleclaude.core.workflow_machine.phase_reading import PhaseReading, read_phase
from teleclaude.core.workflow_machine.stamp_run import run_stamp
from teleclaude.core.workflow_machine.vocabulary import ACT_PERFORMERS, Performer
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ArtifactRevisionMismatch, ItemChange
from teleclaude.events.envelope import occurrence_id
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import LIFECYCLE_PHASE_STATE_KEY, TodoState
from teleclaude.types.workflow_record import (
    Act,
    ActStatus,
    EffectKind,
    EmittedEvent,
    LaunchReservation,
    LedgerEntry,
    PendingEffect,
    Phase,
    PreparedRecord,
    StampRecord,
    WaitedPhase,
    WaitingRecord,
    WorkflowRecord,
)

logger = get_logger(__name__)

LOG_HEADER_TEMPLATE: Final = "\n### {at} — {role} · {session} · {act}{bound}\n\n"
LOG_BOUND_TEMPLATE: Final = " ({bound})"
LOG_TEXT_TEMPLATE: Final = "{text}\n"
EFFECT_ID_TEMPLATE: Final = "{key}:{name}"
SESSION_PARAM: Final = "session_id"
PERSON_PARAM: Final = "person"
WAITED_PHASE_PARAM: Final = "waited_phase"
RESERVATION_PARAM: Final = "reservation_key"
EFFECT_RELEASE: Final = "release"
EFFECT_END_CHILD: Final = "end-child"
EFFECT_WAITING: Final = "waiting"
WAIT_PARAM: Final = "wait"
EFFECT_READY: Final = "ready"
SHA_PARAM: Final = "sha"
READY_AT_PARAM: Final = "ready_at"
EFFECT_REQUEST: Final = "request"
NO_SESSION: Final = ""
DIGEST_LENGTH: Final = 16
ARGUMENT_TEXT: Final = "text"
ARGUMENT_SHA: Final = "--sha"
ARGUMENT_REVISION: Final = "--revision"
ARGUMENT_PERSON: Final = "--person"
ARGUMENT_FINDING: Final = "--finding"
ARTIFACT_INPUT_LABEL: Final = "intent body"


@dataclass(frozen=True)
class _Facts:
    """What the act needs from other stores, resolved before the commit."""

    caller: CallerFacts
    item_id: str
    holder: str | None
    in_group: bool
    child_sessions: tuple[str, ...]
    person_slug: str
    person_email: str
    person_authorized: bool
    waiting_digest: str


@dataclass(frozen=True)
class _EffectSpec:
    name: str
    kind: EffectKind
    event: EmittedEvent | None = None
    params: Mapping[str, str] | None = None


@dataclass(frozen=True)
class _Decision:
    """What an act changes: the bound object, the new phase and record, and the effects it commits."""

    bound: str
    text: str = ""
    phase: LifecyclePhase | None = None
    record: Callable[[WorkflowRecord], WorkflowRecord] | None = None
    effects: tuple[_EffectSpec, ...] = ()
    expect_digests: Mapping[str, str] | None = None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:DIGEST_LENGTH]


def _content_digest(request: ActRequest) -> str:
    """The identity of what one invocation asks for, from the request alone, calling session included."""
    parts = (
        request.caller_session_id,
        request.sha,
        request.revision,
        request.person,
        request.finding_key,
        request.wait,
        request.text,
    )
    return _digest(BOUND_SEPARATOR.join(parts))


def _callers_claim(request: ActRequest, record: WorkflowRecord) -> str:
    """The epoch of the latest claim the calling session itself made; none for a session that never claimed."""
    epochs = [
        entry.epoch
        for entry in record.ledger
        if entry.act is Act.CLAIM and entry.session_id == request.caller_session_id
    ]
    return str(max(epochs, default=0))


def _act_key(request: ActRequest, item_id: str, record: WorkflowRecord) -> str:
    """The identity of one invocation, stable across the item's later phases and other sessions' claims.

    The calling session, the claim it made and the request content name the invocation for as long as it can
    be repeated. A successor's claim leaves it unchanged; a session that claims again, as a revived driver
    does, starts a new one, so its repeated act is not swallowed as the earlier one. A decision's content
    names the wait it answers, so a repeat never binds to a later wait.
    """
    return occurrence_id(
        request.project_root,
        item_id,
        request.act.value,
        _callers_claim(request, record),
        _content_digest(request),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _refuse(refusal: Refusal, **fields: str) -> ActRefused:
    return ActRefused(refusal.value.format(**fields))


def _require(request: ActRequest, value: str, argument: str) -> str:
    if not value.strip():
        raise _refuse(Refusal.MISSING_ARGUMENT, act=request.act.value, argument=argument)
    return value


def _require_phase(request: ActRequest, reading: PhaseReading, allowed: tuple[Phase, ...]) -> Phase:
    phase = reading.phase
    if phase is None or phase not in allowed:
        shown = phase.value if phase is not None else LifecyclePhase.TASK_RUNNING.value
        raise _refuse(Refusal.WRONG_PHASE, act=request.act.value, phase=shown)
    return phase


def _release_effect(session_id: str) -> _EffectSpec:
    return _EffectSpec(EFFECT_RELEASE, EffectKind.RELEASE_CLAIM, params={SESSION_PARAM: session_id})


def _decide_note(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    text = _require(request, request.text, ARGUMENT_TEXT)
    bound = f"{facts.caller.session_id}{BOUND_SEPARATOR}{_digest(text)}"
    return _Decision(bound=bound, text=text)


def _decide_reviewed(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    _require_phase(request, reading, (Phase.WORK,))
    return _Decision(bound=_require(request, request.sha, ARGUMENT_SHA), text=request.text)


def _decide_finding(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    _require_phase(request, reading, (Phase.WORK,))
    sha = _require(request, request.sha, ARGUMENT_SHA)
    text = _require(request, request.text, ARGUMENT_TEXT)
    return _Decision(bound=f"{sha}{BOUND_SEPARATOR}{_digest(text)}", text=text)


def _decide_reply(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    _require_phase(request, reading, (Phase.WORK,))
    finding = _require(request, request.finding_key, ARGUMENT_FINDING)
    if not any(entry.act is Act.FINDING and entry.key == finding for entry in state.workflow.ledger):
        raise _refuse(Refusal.UNKNOWN_FINDING, act=request.act.value, finding=finding)
    text = _require(request, request.text, ARGUMENT_TEXT)
    return _Decision(bound=f"{finding}{BOUND_SEPARATOR}{_digest(text)}", text=text)


def _decide_prepared(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    _require_phase(request, reading, (Phase.PREPARATION,))
    revision = _require(request, request.revision, ARGUMENT_REVISION)
    prepared = PreparedRecord(revision=revision, session_id=facts.caller.session_id, at=_now())

    def record(current: WorkflowRecord) -> WorkflowRecord:
        updated = current.model_copy(deep=True)
        updated.prepared = prepared
        return updated

    return _Decision(
        bound=revision,
        text=request.text,
        phase=LifecyclePhase.PREPARED,
        record=record,
        effects=(_release_effect(facts.caller.session_id),),
        expect_digests={ARTIFACT_INPUT: revision},
    )


def _decide_waiting(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    waited = _require_phase(request, reading, (Phase.PREPARATION, Phase.WORK))
    person = _require(request, request.person, ARGUMENT_PERSON)
    question = _require(request, request.text, ARGUMENT_TEXT)
    if not facts.person_authorized:
        raise _refuse(Refusal.NO_AUTHORITY, act=request.act.value, person=person)
    waited_phase = WaitedPhase(waited.value)
    waiting = WaitingRecord(
        key=_act_key(request, facts.item_id, state.workflow),
        waited_phase=waited_phase,
        person=person,
        question_digest=_digest(question),
    )

    def record(current: WorkflowRecord) -> WorkflowRecord:
        updated = current.model_copy(deep=True)
        updated.waiting = waiting
        return updated

    return _Decision(
        bound=person,
        text=question,
        phase=LifecyclePhase.WAITING,
        record=record,
        effects=(
            _EffectSpec(
                EFFECT_WAITING,
                EffectKind.EMIT_EVENT,
                EmittedEvent.WAITING,
                {PERSON_PARAM: person, WAITED_PHASE_PARAM: waited_phase.value, WAIT_PARAM: waiting.key},
            ),
            _release_effect(facts.caller.session_id),
        ),
    )


_REQUEST_EVENT_FOR_WAITED_PHASE: Final[Mapping[WaitedPhase, EmittedEvent]] = {
    WaitedPhase.PREPARATION: EmittedEvent.PREPARATION_REQUESTED,
    WaitedPhase.WORK: EmittedEvent.WORK_REQUESTED,
}
_STORED_PHASE_FOR_WAITED_PHASE: Final[Mapping[WaitedPhase, LifecyclePhase]] = {
    WaitedPhase.PREPARATION: LifecyclePhase.PREPARATION,
    WaitedPhase.WORK: LifecyclePhase.WORK,
}


def _decide_decision(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    _require_phase(request, reading, (Phase.WAITING,))
    waiting = state.workflow.waiting
    if waiting is None or not facts.caller.is_persons_own_session(facts.person_email):
        person = waiting.person if waiting is not None else NO_SESSION
        raise _refuse(Refusal.DECISION_OWNER, act=request.act.value, person=person)
    if not request.wait:
        raise _refuse(Refusal.WAIT_REQUIRED, act=request.act.value)
    if (
        waiting.key != request.wait
        or waiting.person != facts.person_slug
        or waiting.question_digest != facts.waiting_digest
    ):
        raise _refuse(Refusal.WAIT_CHANGED, act=request.act.value, person=waiting.person)
    answer = _require(request, request.text, ARGUMENT_TEXT)
    reservation = LaunchReservation(
        key=_digest(f"{waiting.person}{BOUND_SEPARATOR}{waiting.question_digest}{BOUND_SEPARATOR}{_now()}"),
        phase=Phase(waiting.waited_phase.value),
        requested_at=_now(),
        requested_by=facts.caller.session_id,
        effect_id=EFFECT_ID_TEMPLATE.format(key=_act_key(request, facts.item_id, state.workflow), name=EFFECT_REQUEST),
    )

    def record(current: WorkflowRecord) -> WorkflowRecord:
        updated = current.model_copy(deep=True)
        updated.waiting = None
        updated.launch = reservation
        return updated

    return _Decision(
        bound=waiting.person,
        text=answer,
        phase=_STORED_PHASE_FOR_WAITED_PHASE[waiting.waited_phase],
        record=record,
        effects=(
            _EffectSpec(
                EFFECT_REQUEST,
                EffectKind.EMIT_EVENT,
                _REQUEST_EVENT_FOR_WAITED_PHASE[waiting.waited_phase],
                {RESERVATION_PARAM: reservation.key},
            ),
        ),
    )


def _decide_kickback(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    _require_phase(request, reading, (Phase.WORK,))
    reason = _require(request, request.text, ARGUMENT_TEXT)

    def record(current: WorkflowRecord) -> WorkflowRecord:
        updated = current.model_copy(deep=True)
        updated.prepared = None
        updated.stamp = None
        return updated

    ends = tuple(
        _EffectSpec(f"{EFFECT_END_CHILD}-{child}", EffectKind.END_SESSION, params={SESSION_PARAM: child})
        for child in facts.child_sessions
    )
    return _Decision(
        bound=_digest(reason),
        text=reason,
        phase=LifecyclePhase.PREPARATION,
        record=record,
        effects=(*ends, _release_effect(facts.caller.session_id)),
    )


def _decide_stamp(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    _require_phase(request, reading, (Phase.WORK,))
    sha = _require(request, request.sha, ARGUMENT_SHA)
    flight = state.workflow.stamp_in_flight
    if flight is None or flight.key != _act_key(request, facts.item_id, state.workflow):
        raise _refuse(Refusal.STAMP_SLOT_LOST, act=request.act.value)
    stamp = StampRecord(sha=sha, session_id=facts.caller.session_id, ready_at=_now())

    def record(current: WorkflowRecord) -> WorkflowRecord:
        updated = current.model_copy(deep=True)
        updated.stamp = stamp
        updated.stamp_in_flight = None
        return updated

    ends = tuple(
        _EffectSpec(f"{EFFECT_END_CHILD}-{child}", EffectKind.END_SESSION, params={SESSION_PARAM: child})
        for child in facts.child_sessions
    )
    return _Decision(
        bound=sha,
        text=request.text,
        phase=LifecyclePhase.READY,
        record=record,
        effects=(
            _EffectSpec(
                EFFECT_READY,
                EffectKind.EMIT_EVENT,
                EmittedEvent.READY,
                {SHA_PARAM: sha, READY_AT_PARAM: stamp.ready_at, SESSION_PARAM: facts.caller.session_id},
            ),
            *ends,
            _release_effect(facts.caller.session_id),
        ),
    )


def _decide_release(request: ActRequest, facts: _Facts, state: TodoState, reading: PhaseReading) -> _Decision:
    return _Decision(bound=facts.caller.session_id, effects=(_release_effect(facts.caller.session_id),))


_DECIDERS: Final[Mapping[Act, Callable[[ActRequest, _Facts, TodoState, PhaseReading], _Decision]]] = {
    Act.NOTE: _decide_note,
    Act.REVIEWED: _decide_reviewed,
    Act.FINDING: _decide_finding,
    Act.REPLY: _decide_reply,
    Act.PREPARED: _decide_prepared,
    Act.WAITING: _decide_waiting,
    Act.DECISION: _decide_decision,
    Act.KICKBACK: _decide_kickback,
    Act.STAMP: _decide_stamp,
    Act.RELEASE: _decide_release,
}


def _authorize(request: ActRequest, facts: _Facts) -> None:
    """Refuse an act whose performer is not the one the vocabulary names for it."""
    performer = ACT_PERFORMERS[request.act]
    caller = facts.caller
    allowed = {
        Performer.ANY_WRITER: True,
        Performer.HOLDER: facts.holder is not None and caller.session_id == facts.holder,
        Performer.HOLDER_OR_PLATFORM: facts.holder is not None and caller.session_id == facts.holder,
        Performer.HOLDER_OR_GROUP: facts.holder is not None and facts.in_group,
        Performer.BUILDER_IN_GROUP: facts.holder is not None and facts.in_group and caller.role == RoleName.BUILDER,
        Performer.OWNER_SESSION: True,
        Performer.CLAIMING_DRIVER: False,
        Performer.INTEGRATOR: False,
    }[performer]
    if performer in (Performer.CLAIMING_DRIVER, Performer.INTEGRATOR):
        raise _refuse(Refusal.NOT_PERFORMED_HERE, act=request.act.value)
    if not allowed:
        raise _refuse(Refusal.PERFORMER, act=request.act.value, performer=performer.value)


def _log_entry(entry: LedgerEntry) -> str:
    bound = LOG_BOUND_TEMPLATE.format(bound=entry.bound) if entry.bound else NO_SESSION
    header = LOG_HEADER_TEMPLATE.format(
        at=entry.at, role=entry.role or NO_SESSION, session=entry.session_id, act=entry.act.value, bound=bound
    )
    return header + (LOG_TEXT_TEMPLATE.format(text=entry.text) if entry.text else NO_SESSION)


async def _resolve_facts(store: WorkflowStore, request: ActRequest, state: TodoState) -> _Facts:
    """The facts an act needs from other stores, read before the commit."""
    item_id = store.resolve_store_address_sync(request.item)
    if item_id is None:
        raise _refuse(Refusal.UNKNOWN_ITEM, act=request.act.value, item=request.item)
    caller = await load_caller(request.caller_session_id)
    if caller is None:
        raise _refuse(Refusal.UNKNOWN_CALLER, act=request.act.value)
    holder = state.active_runner or None
    in_group = holder is not None and await in_claiming_group(caller.session_id, holder)
    waiting = state.workflow.waiting
    if request.act is Act.DECISION:
        person_slug = waiting.person if waiting is not None else NO_SESSION
    else:
        person_slug = request.person
    person = configured_person(person_slug) if person_slug else None
    return _Facts(
        caller=caller,
        item_id=item_id,
        holder=holder,
        in_group=in_group,
        child_sessions=await child_sessions_of(holder)
        if holder is not None and request.act in (Act.KICKBACK, Act.STAMP)
        else (),
        person_slug=person_slug,
        person_email=person.email if person is not None else NO_SESSION,
        person_authorized=person is not None and has_project_authority(person, request.project_root),
        waiting_digest=waiting.question_digest if waiting is not None else NO_SESSION,
    )


def _apply(
    request: ActRequest, facts: _Facts, state_dict: dict[str, StateValue] | None, outcome: list[str]
) -> ItemChange | None:
    """Decide the act against the state read inside the commit and build the change, or refuse.

    An invocation the item already recorded writes nothing: it resumes through its pending effects.
    """
    if state_dict is None:
        raise _refuse(Refusal.UNKNOWN_ITEM, act=request.act.value, item=request.item)
    state = TodoState.model_validate(state_dict)
    existing = _act_key(request, facts.item_id, state.workflow)
    if existing in state.workflow.act_status:
        outcome.append(existing)
        return None
    holder_now = state.active_runner or None
    if holder_now != facts.holder:
        raise _refuse(Refusal.HOLDER_CHANGED, act=request.act.value)
    reading = read_phase(state, integration_head=NO_SESSION, creative_incomplete=request.creative_incomplete)
    decision = _DECIDERS[request.act](request, facts, state, reading)
    record = state.workflow
    key = existing
    entry = LedgerEntry(
        seq=len(record.ledger) + 1,
        act=request.act,
        key=key,
        epoch=record.claim_epoch,
        at=_now(),
        role=facts.caller.role or NO_SESSION,
        session_id=facts.caller.session_id,
        bound=decision.bound,
        text=decision.text,
    )
    updated = decision.record(record) if decision.record is not None else record.model_copy(deep=True)
    updated.ledger.append(entry)
    for spec in decision.effects:
        updated.pending_effects.append(
            PendingEffect(
                id=EFFECT_ID_TEMPLATE.format(key=key, name=spec.name),
                act_key=key,
                kind=spec.kind,
                event=spec.event,
                params=dict(spec.params or {}),
            )
        )
    updated.act_status[key] = ActStatus.IN_PROGRESS if decision.effects else ActStatus.COMPLETE
    new_state: dict[str, StateValue] = {**state_dict, WORKFLOW_STATE_KEY: updated.to_state()}
    if decision.phase is not None:
        new_state[LIFECYCLE_PHASE_STATE_KEY] = decision.phase.value
    outcome.append(key)
    return ItemChange(state=new_state, log_entry=_log_entry(entry))


async def perform_act(request: ActRequest) -> ActResult:
    """Perform one act: authorize it, commit it atomically with its pending effects, then run the effects.

    An invocation the item already recorded is not decided again: it resumes through its pending effects.
    """
    store = await get_workflow_store(request.project_root)
    request = replace(request, project_root=str(store.project_root))
    raw = await store.read_state(request.item)
    if raw is None:
        raise _refuse(Refusal.UNKNOWN_ITEM, act=request.act.value, item=request.item)
    if request.act not in _DECIDERS:
        raise _refuse(Refusal.NOT_PERFORMED_HERE, act=request.act.value)
    state = TodoState.model_validate(raw)
    request = replace(
        request, creative_incomplete=await creative_incomplete(store, request.project_root, request.item, raw)
    )
    facts = await _resolve_facts(store, request, state)
    key = _act_key(request, facts.item_id, state.workflow)
    if key not in state.workflow.act_status:
        _authorize(request, facts)
        await observe_item_supervised(request.project_root, request.item)
        if request.act is Act.STAMP:
            key = await run_stamp(
                store, request, facts.caller.session_id, facts.item_id, key, partial(_commit, store, request, facts)
            )
        else:
            key = await _commit(store, request, facts)
    await reconcile_slug_supervised(request.project_root, request.item)
    return await _result(store, request, key)


async def _commit(store: WorkflowStore, request: ActRequest, facts: _Facts) -> str:
    """Commit the act and return the key the transaction recorded it under."""
    raw = await store.read_state(request.item)
    if raw is None:
        raise _refuse(Refusal.UNKNOWN_ITEM, act=request.act.value, item=request.item)
    current = TodoState.model_validate(raw)
    expected = _DECIDERS[request.act](
        request,
        facts,
        current,
        read_phase(current, integration_head=NO_SESSION, creative_incomplete=request.creative_incomplete),
    ).expect_digests

    recorded: list[str] = []

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        return _apply(request, facts, current, recorded)

    try:
        await store.commit_item_change(
            request.item, expect_digests=expected or {}, mutate=mutate, updated_by=request.caller_session_id
        )
    except ArtifactRevisionMismatch as mismatch:
        raise _refuse(
            Refusal.REVISION_MOVED,
            act=request.act.value,
            artifact=ARTIFACT_INPUT_LABEL,
            actual=mismatch.actual,
            expected=mismatch.expected,
        ) from mismatch
    return recorded[-1]


async def _result(store: WorkflowStore, request: ActRequest, key: str) -> ActResult:
    """What the item now records for the invocation: the phase afterwards and whether its effects finished."""
    refreshed = await store.read_state(request.item)
    if refreshed is None:
        raise _refuse(Refusal.UNKNOWN_ITEM, act=request.act.value, item=request.item)
    state = TodoState.model_validate(refreshed)
    status = state.workflow.act_status.get(key)
    if status is None:
        raise _refuse(Refusal.NOT_RECORDED, act=request.act.value)
    return ActResult(
        act_key=key,
        phase=read_phase(state, integration_head=NO_SESSION, creative_incomplete=request.creative_incomplete).phase,
        complete=status is ActStatus.COMPLETE,
        finding_key=key if request.act is Act.FINDING else NO_SESSION,
    )
