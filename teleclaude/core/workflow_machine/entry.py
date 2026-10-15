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
from teleclaude.core.workflow_machine.instruction import InstructionFacts, render_instruction
from teleclaude.core.workflow_machine.phase_reading import PhaseReading, read_phase
from teleclaude.core.workflow_machine.publication import (
    PublicationError,
    WorkflowPublication,
    published_workflow_publication,
)
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ArtifactRevisionMismatch, ItemChange
from teleclaude.entry_declarations import EntryDeclarations, WorkflowDeclaration
from teleclaude.events.envelope import occurrence_id
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
    LaunchReservation,
    LedgerEntry,
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


class EntryRefused(Exception):
    """An entry verb was refused for one named cause; nothing was written."""


class LaunchInProgress(Exception):
    """The driver start was requested and has not claimed yet; repeating the verb attaches to it."""


@dataclass(frozen=True)
class EntryRequest:
    """One entry call. The caller is a session, or empty for a person at a terminal."""

    project_root: str
    item: str
    verb: EntryVerb
    caller_session_id: str


@dataclass(frozen=True)
class EntryResult:
    """What an entry verb returns: the instruction text and the driver session it concerns."""

    text: str
    driver_session_id: str


LAUNCH_NOTE: Final = "{item}: a driver was requested; session {session} holds the claim."
CLAIM_NOTE: Final = "claimed"
NO_SESSION: Final = ""
ATTACH_WAIT_SECONDS: Final = 120.0
ATTACH_POLL_SECONDS: Final = 0.5
LAUNCH_PENDING_TEMPLATE: Final = (
    "{item}: the driver start (reservation {key}) has not claimed yet; repeat the verb to attach."
)
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
}
_DRIVEN_PHASE: Final[Mapping[Phase, DrivenPhase]] = {
    Phase.PREPARATION: DrivenPhase.PREPARATION,
    Phase.PREPARED: DrivenPhase.PREPARED,
    Phase.WORK: DrivenPhase.WORK,
}
_REQUEST_EVENT: Final[Mapping[Phase, EmittedEvent]] = {
    Phase.PREPARATION: EmittedEvent.PREPARATION_REQUESTED,
    Phase.PREPARED: EmittedEvent.WORK_REQUESTED,
    Phase.WORK: EmittedEvent.WORK_REQUESTED,
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


def _check_drivable(request: EntryRequest, state: TodoState, reading: PhaseReading) -> Phase:
    """The phase the verb may drive, or the one named cause for refusing."""
    phase = reading.phase
    if phase is Phase.WAITING:
        waiting = state.workflow.waiting
        raise _refuse(EntryRefusal.WAITING, item=request.item, person=waiting.person if waiting else NO_SESSION)
    if phase is None or phase not in _VERB_FOR_PHASE:
        shown = phase.value if phase is not None else LifecyclePhase.TASK_RUNNING.value
        raise _refuse(EntryRefusal.NOT_DRIVEN, item=request.item, phase=shown)
    if _VERB_FOR_PHASE[phase] is not request.verb:
        raise _refuse(EntryRefusal.DRIVEN_BY, item=request.item, phase=phase.value, verb=_VERB_FOR_PHASE[phase].value)
    return phase


async def _is_bound_driver(session_id: str, item: str, procedure_id: str) -> bool:
    """Whether the session is the agent procedure activation bound to this item for the driver procedure."""
    if not session_id:
        return False
    session = await db.get_session(session_id)
    if session is None or session.job != procedure_id:
        return False
    binding = (session.origin_metadata or {}).get(BINDING_SECTION)
    return isinstance(binding, dict) and binding.get(BindingField.SUBJECT.value) == item


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
        bound = bool(procedure_id) and await _is_bound_driver(request.caller_session_id, request.item, procedure_id)
        if holder == request.caller_session_id or bound:
            return own, bound
    return published_workflow_publication(), False


def _apply_claim(
    request: EntryRequest, item_id: str, branch: str, role: str, state_dict: dict[str, StateValue] | None
) -> ItemChange:
    """Claim the item for the calling driver inside the commit, or refuse."""
    if state_dict is None:
        raise _refuse(EntryRefusal.UNKNOWN_ITEM, item=request.item)
    state = TodoState.model_validate(state_dict)
    reading = read_phase(state, integration_head=NO_SESSION, creative_incomplete=False)
    phase = _check_drivable(request, state, reading)
    holder = state.active_runner or None
    if holder is not None:
        raise _refuse(EntryRefusal.HELD, item=request.item, session=holder)
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
    record.driver_cycle += 1
    record.launch = None
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
    if phase is Phase.PREPARED:
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
    request: EntryRequest, item_id: str, phase: Phase, state_dict: dict[str, StateValue] | None
) -> ItemChange:
    """Record the launch reservation and the request notice in one write, or leave a pending one in place."""
    if state_dict is None:
        raise _refuse(EntryRefusal.UNKNOWN_ITEM, item=request.item)
    state = TodoState.model_validate(state_dict)
    reading = read_phase(state, integration_head=NO_SESSION, creative_incomplete=False)
    _check_drivable(request, state, reading)
    holder = state.active_runner or None
    if holder is not None:
        raise _refuse(EntryRefusal.HELD, item=request.item, session=holder)
    if state.workflow.launch is not None:
        return ItemChange(state=state_dict)
    record = state.workflow.model_copy(deep=True)
    key = occurrence_id(request.project_root, item_id, EFFECT_REQUEST, str(record.claim_epoch), _now())
    record.launch = LaunchReservation(
        key=key, phase=phase, requested_at=_now(), requested_by=request.caller_session_id or NO_SESSION
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
    return ItemChange(state={**state_dict, WORKFLOW_STATE_KEY: record.to_state()})


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
    await store.commit_item_change(
        request.item,
        expect_digests=expected,
        mutate=lambda current, _digests: _apply_reservation(request, item_id, phase, current),
        updated_by=request.caller_session_id or None,
    )
    await reconcile_slug_supervised(request.project_root, request.item)
    started = await _await_claim(store, request)
    return EntryResult(text=LAUNCH_NOTE.format(item=request.item, session=started), driver_session_id=started)


async def _instruct(
    request: EntryRequest,
    publication: WorkflowPublication,
    workflow: WorkflowDeclaration,
    phase: Phase,
    branch: str,
) -> EntryResult:
    """The instruction for the holding driver of the phase."""
    children = await child_sessions_of(request.caller_session_id)
    worktree = (
        str(Path(request.project_root) / WORKTREE_DIR / request.item)
        if phase in (Phase.PREPARED, Phase.WORK)
        else NO_SESSION
    )
    text = render_instruction(
        InstructionFacts(
            item=request.item,
            phase=Phase.WORK if phase is Phase.PREPARED else phase,
            session_id=request.caller_session_id,
            branch=branch,
            worktree=worktree,
            child_sessions=children,
        ),
        workflow,
        publication.child_of(workflow).declarations,
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
    if holder is not None and holder != request.caller_session_id:
        raise _refuse(EntryRefusal.HELD, item=request.item, session=holder)
    phase = _check_drivable(request, state, read_phase(state, integration_head=NO_SESSION, creative_incomplete=False))
    unmet = await _unmet_dependencies(store, request.item, request.verb)
    if unmet and holder is None:
        raise _refuse(EntryRefusal.UNMET_DEPENDENCIES, item=request.item, dependencies=DEPENDENCY_SEPARATOR.join(unmet))
    publication, bound = await _publication_for(request, holder, phase)
    _, workflow = _driver_for(publication, phase, request.item)
    branch = request.item
    expected = (
        {ARTIFACT_INPUT: state.workflow.prepared.revision}
        if phase is Phase.PREPARED and state.workflow.prepared is not None
        else {}
    )
    if holder is None:
        try:
            if not bound:
                return await _launch(store, request, item_id, phase, expected)
            await _claim(store, request, item_id, branch, expected)
        except ArtifactRevisionMismatch as mismatch:
            raise _refuse(
                EntryRefusal.REVISION_MOVED, item=request.item, actual=mismatch.actual, expected=mismatch.expected
            ) from mismatch
    return await _instruct(request, publication, workflow, phase, branch)


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
    phase = read_phase(state, integration_head=NO_SESSION, creative_incomplete=False).phase
    if phase is None or phase not in _VERB_FOR_PHASE:
        raise _refuse(EntryRefusal.NOT_DRIVEN, item=item, phase=phase.value if phase else NO_SESSION)
    publication = await _own_publication(caller_session_id) or published_workflow_publication()
    _, workflow = _driver_for(publication, phase, item)
    subfolder = f"{WORKTREE_DIR}/{item}" if phase in (Phase.PREPARED, Phase.WORK) else NO_SESSION
    return ChildPlan(
        procedure_id=workflow.child,
        arguments=item,
        declarations=publication.child_of(workflow).declarations,
        subfolder=subfolder,
    )
