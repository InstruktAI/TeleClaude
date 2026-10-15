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
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.constants import ARTIFACT_INPUT
from teleclaude.core.roles import RoleName
from teleclaude.core.workflow_machine.act_types import ActRefused, ActRequest, ActResult, Refusal
from teleclaude.core.workflow_machine.authority import configured_person, has_project_authority
from teleclaude.core.workflow_machine.caller import CallerFacts, child_sessions_of, in_claiming_group, load_caller
from teleclaude.core.workflow_machine.effects import reconcile_slug_supervised
from teleclaude.core.workflow_machine.phase_reading import PhaseReading, read_phase
from teleclaude.core.workflow_machine.vocabulary import ACT_PERFORMERS, Performer
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ArtifactRevisionMismatch, ItemChange
from teleclaude.events.envelope import occurrence_id
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
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
EFFECT_REQUEST: Final = "request"
NO_SESSION: Final = ""
DIGEST_LENGTH: Final = 16
BOUND_SEPARATOR: Final = ":"
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
    person_email: str
    person_authorized: bool


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
    waiting = WaitingRecord(waited_phase=waited_phase, person=person, question_digest=_digest(question))

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
                {PERSON_PARAM: person, WAITED_PHASE_PARAM: waited_phase.value},
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
    answer = _require(request, request.text, ARGUMENT_TEXT)
    reservation = LaunchReservation(
        key=_digest(f"{waiting.person}{BOUND_SEPARATOR}{waiting.question_digest}{BOUND_SEPARATOR}{_now()}"),
        phase=Phase(waiting.waited_phase.value),
        requested_at=_now(),
        requested_by=facts.caller.session_id,
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
    person_slug = request.person or (state.workflow.waiting.person if state.workflow.waiting is not None else "")
    person = configured_person(person_slug) if person_slug else None
    return _Facts(
        caller=caller,
        item_id=item_id,
        holder=holder,
        in_group=in_group,
        child_sessions=await child_sessions_of(holder) if holder is not None and request.act is Act.KICKBACK else (),
        person_email=person.email if person is not None else NO_SESSION,
        person_authorized=person is not None and has_project_authority(person, request.project_root),
    )


def _apply(
    request: ActRequest, facts: _Facts, state_dict: dict[str, StateValue] | None, outcome: list[ActResult]
) -> ItemChange:
    """Decide the act against the state read inside the commit and build the change, or refuse."""
    if state_dict is None:
        raise _refuse(Refusal.UNKNOWN_ITEM, act=request.act.value, item=request.item)
    state = TodoState.model_validate(state_dict)
    holder_now = state.active_runner or None
    if holder_now != facts.holder:
        raise _refuse(Refusal.HOLDER_CHANGED, act=request.act.value)
    reading = read_phase(state, integration_head=NO_SESSION, creative_incomplete=False)
    decision = _DECIDERS[request.act](request, facts, state, reading)
    record = state.workflow
    key = occurrence_id(request.project_root, facts.item_id, request.act.value, decision.bound, str(record.claim_epoch))
    if key in record.act_status:
        outcome.append(
            ActResult(act_key=key, phase=reading.phase, complete=record.act_status[key] is ActStatus.COMPLETE)
        )
        return ItemChange(state=state_dict)
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
    new_phase = read_phase(TodoState.model_validate(new_state), integration_head=NO_SESSION, creative_incomplete=False)
    outcome.append(ActResult(act_key=key, phase=new_phase.phase, complete=not decision.effects, finding_key=key))
    return ItemChange(state=new_state, log_entry=_log_entry(entry))


async def perform_act(request: ActRequest) -> ActResult:
    """Perform one act: authorize it, commit it atomically with its pending effects, then run the effects."""
    store = await get_workflow_store(request.project_root)
    request = replace(request, project_root=str(store.project_root))
    raw = await store.read_state(request.item)
    if raw is None:
        raise _refuse(Refusal.UNKNOWN_ITEM, act=request.act.value, item=request.item)
    state = TodoState.model_validate(raw)
    if request.act not in _DECIDERS:
        raise _refuse(Refusal.NOT_PERFORMED_HERE, act=request.act.value)
    facts = await _resolve_facts(store, request, state)
    _authorize(request, facts)
    outcome: list[ActResult] = []
    expected = _DECIDERS[request.act](
        request, facts, state, read_phase(state, integration_head=NO_SESSION, creative_incomplete=False)
    ).expect_digests

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange:
        return _apply(request, facts, current, outcome)

    try:
        await store.commit_item_change(
            request.item,
            expect_digests=expected or {},
            mutate=mutate,
            updated_by=request.caller_session_id,
        )
    except ArtifactRevisionMismatch as mismatch:
        raise _refuse(
            Refusal.REVISION_MOVED,
            act=request.act.value,
            artifact=ARTIFACT_INPUT_LABEL,
            actual=mismatch.actual,
            expected=mismatch.expected,
        ) from mismatch
    await reconcile_slug_supervised(request.project_root, request.item)
    result = outcome[-1]
    refreshed = await store.read_state(request.item)
    if refreshed is None:
        return result
    status = workflow_record_of(refreshed).act_status.get(result.act_key)
    return ActResult(
        act_key=result.act_key,
        phase=result.phase,
        complete=status is not ActStatus.IN_PROGRESS,
        finding_key=result.act_key if request.act is Act.FINDING else NO_SESSION,
    )
