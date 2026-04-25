"""Prepare-pair role lookup and orchestration script helpers."""

from __future__ import annotations

import os
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Literal, Protocol, cast

from teleclaude.core.next_machine._types import PreparePhase, StateValue
from teleclaude.core.next_machine.output_formatting import (
    HumanApprovalScript,
    PairTurnScript,
    format_human_approval_script,
    format_pair_turn_script,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.session_status import compute_agent_status
from teleclaude.types.todos import PreparePairSlot

if TYPE_CHECKING:
    from teleclaude.core.db import Db

PrepareLens = Literal["A", "B"]


class _ListSessions(Protocol):
    def __call__(self, *, include_closed: bool) -> Awaitable[object]:
        """Return session rows from the runtime DB."""
        ...


DEFAULT_PREPARE_PAIR_AGENTS: dict[PrepareLens, str] = {"A": "claude", "B": "codex"}
PRODUCTION_ROLES: dict[PreparePhase, tuple[PrepareLens, PrepareLens]] = {
    PreparePhase.TRIANGULATION: ("A", "B"),
    PreparePhase.TEST_SPEC_BUILD: ("A", "B"),
    PreparePhase.PLAN_DRAFTING: ("B", "A"),
}
REVIEW_ROLES: dict[PreparePhase, tuple[PrepareLens, PrepareLens]] = {
    PreparePhase.REQUIREMENTS_REVIEW: ("A", "B"),
    PreparePhase.TEST_SPEC_REVIEW: ("A", "B"),
    PreparePhase.PLAN_REVIEW: ("B", "A"),
}


def prepare_pair_agent_mapping() -> dict[PrepareLens, str]:
    """Return the policy-configured prepare-pair lens to agent mapping."""
    return {
        "A": os.getenv("TELECLAUDE_PREPARE_PAIR_A_AGENT", DEFAULT_PREPARE_PAIR_AGENTS["A"]),
        "B": os.getenv("TELECLAUDE_PREPARE_PAIR_B_AGENT", DEFAULT_PREPARE_PAIR_AGENTS["B"]),
    }


def _pair_slot(state: dict[str, StateValue], lens: PrepareLens) -> PreparePairSlot | None:
    """Return a stored prepare pair slot by lens."""
    pair = StateWriter(state).state.prepare_pair
    if pair is None:
        return None
    slots: dict[PrepareLens, PreparePairSlot | None] = {"A": pair.slot_a, "B": pair.slot_b}
    return slots[lens]


def pair_writer_reviewer_slots(
    state: dict[str, StateValue],
    phase: PreparePhase,
    roles: dict[PreparePhase, tuple[PrepareLens, PrepareLens]],
) -> tuple[PreparePairSlot, PreparePairSlot] | None:
    """Return writer/reviewer slots for a pair-owned phase."""
    role_pair = roles.get(phase)
    if role_pair is None:
        return None
    writer = _pair_slot(state, role_pair[0])
    reviewer = _pair_slot(state, role_pair[1])
    if writer is None or reviewer is None:
        return None
    return writer, reviewer


async def pair_members_idle(db: Db, slot_a: PreparePairSlot, slot_b: PreparePairSlot) -> bool:
    """Return True when both stored pair sessions are live and idle."""
    sessions = await db.list_sessions(include_closed=False)
    target_ids = {slot_a.session_id, slot_b.session_id}
    statuses: dict[str, str] = {}
    for session in sessions:
        session_id = getattr(session, "session_id", "")
        if session_id not in target_ids:
            continue
        statuses[session_id] = compute_agent_status(
            last_activity=getattr(session, "last_activity", None),
            last_input_at=getattr(session, "last_message_sent_at", None),
            last_agent_stop_at=getattr(session, "last_agent_stop_at", None),
        )
    return statuses.get(slot_a.session_id) == "idle" and statuses.get(slot_b.session_id) == "idle"


async def pair_slot_alive(db: object, slot: PreparePairSlot) -> bool:
    """Return whether a stored pair slot currently maps to a live session."""
    list_sessions = getattr(db, "list_sessions", None)
    if not callable(list_sessions):
        return True
    sessions_obj = await cast(_ListSessions, list_sessions)(include_closed=False)
    if not isinstance(sessions_obj, list):
        return True
    return any(getattr(session, "session_id", "") == slot.session_id for session in sessions_obj)


def format_pair_recovery_script(
    *,
    slug: str,
    slot: PreparePairSlot,
    command: str,
    project: str,
    subfolder: str,
    message: str,
) -> str:
    """Format revive-first recovery for a dead prepare pair member."""
    escaped = message.replace('"', '\\"')
    return (
        f"PAIR MEMBER RECOVERY: {slug}\n\n"
        f"Execute in order:\n\n"
        f"telec sessions revive {slot.session_id}\n"
        f'If revive succeeds, send: telec sessions send {slot.session_id} "{escaped}"\n\n'
        f"If revive fails, dispatch a replacement:\n"
        f'telec sessions run --command "{command}" --args "{slug}" --project "{project}" '
        f'--agent "{slot.agent}" --mode "slow" --subfolder "{subfolder}"\n'
        f"Save the returned session_id and update prepare_pair slot {slot.lens} to that new session_id.\n"
        f"Then call telec todo prepare {slug}."
    )


async def format_pair_write_or_recovery_script(
    *,
    db: object,
    slug: str,
    writer_slot: PreparePairSlot,
    reviewer_slot: PreparePairSlot,
    command: str,
    project: str,
    subfolder: str,
    message: str,
    next_step: str,
) -> str:
    """Format a writer turn or revive-first recovery when the writer is dead."""
    if not await pair_slot_alive(db, writer_slot):
        return format_pair_recovery_script(
            slug=slug,
            slot=writer_slot,
            command=command,
            project=project,
            subfolder=subfolder,
            message=message,
        )
    return format_pair_write_turn_script(
        slug=slug,
        writer_slot=writer_slot,
        reviewer_slot=reviewer_slot,
        message=message,
        next_step=next_step,
    )


async def format_pair_review_or_recovery_script(
    *,
    db: object,
    slug: str,
    reviewer_slot: PreparePairSlot,
    command: str,
    project: str,
    subfolder: str,
    message: str,
    next_step: str,
) -> str:
    """Format a review turn or revive-first recovery when the reviewer is dead."""
    if not await pair_slot_alive(db, reviewer_slot):
        return format_pair_recovery_script(
            slug=slug,
            slot=reviewer_slot,
            command=command,
            project=project,
            subfolder=subfolder,
            message=message,
        )
    return format_pair_review_turn_script(
        slug=slug,
        reviewer_slot=reviewer_slot,
        message=message,
        next_step=next_step,
    )


def format_pair_member_send_script(
    *,
    slug: str,
    session_id: str,
    message: str,
    next_step: str,
) -> str:
    """Format a direct send to an existing prepare pair member."""
    return format_pair_turn_script(
        PairTurnScript(
            slug=slug,
            turn="continuation",
            session_id=session_id,
            message=message,
            next_step=next_step,
        )
    )


def format_pair_write_turn_script(
    *,
    slug: str,
    writer_slot: PreparePairSlot,
    reviewer_slot: PreparePairSlot,
    message: str,
    next_step: str,
) -> str:
    """Format a write turn where only the writer is messaged."""
    return format_pair_turn_script(
        PairTurnScript(
            slug=slug,
            turn="write",
            session_id=writer_slot.session_id,
            reviewer_session_id=reviewer_slot.session_id,
            message=message,
            next_step=next_step,
        )
    )


def format_pair_review_turn_script(
    *,
    slug: str,
    reviewer_slot: PreparePairSlot,
    message: str,
    next_step: str,
) -> str:
    """Format a review turn where the reviewer is explicitly messaged."""
    return format_pair_turn_script(
        PairTurnScript(
            slug=slug,
            turn="review",
            session_id=reviewer_slot.session_id,
            message=message,
            next_step=next_step,
        )
    )


def format_requirements_human_approval_script(slug: str) -> str:
    """Format the restart-safe human approval pause instruction."""
    return format_human_approval_script(HumanApprovalScript(slug=slug))
