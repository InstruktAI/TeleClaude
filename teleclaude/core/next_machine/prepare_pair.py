"""Prepare-pair role lookup and orchestration script helpers."""

from __future__ import annotations

import os
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Literal, Protocol, cast

from teleclaude.core.next_machine._types import PreparePhase, StateValue
from teleclaude.core.next_machine.output_formatting import (
    ORCHESTRATOR_IDLE_INVARIANT,
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
    surviving_slot: PreparePairSlot,
    command: str,
    project: str,
    subfolder: str,
    message: str,
) -> str:
    """Format revive-first recovery for a dead prepare pair member.

    Revival ladder:
      1. ``telec sessions revive <tc_session_id>`` — works while the TC row
         exists. Returns the SAME session_id, so no re-stamp is needed; the
         pending message is sent directly to the existing slot.
      2. ``telec sessions revive <native_session_id> --agent <agent>`` — works
         even after the TC row is purged (closed > 7 days), as long as the
         agent's own transcript files survive. The API mints a NEW TC
         session_id (``sessions_actions_routes.py:166``), so the orchestrator
         must save the returned id, send the pending message to it, and
         atomically re-stamp the pair.
      3. Dispatch a fresh replacement via ``telec sessions run`` — same
         post-conditions as native revive: new id, send message, re-stamp.

    Both slots are passed through to the stamp command as inline literals so
    the orchestrator never has to look up the surviving slot.
    """
    escaped = message.replace('"', '\\"')
    if slot.lens == "A":
        stamp_args = f"--agent-a <new_id> --agent-b {surviving_slot.session_id}"
    else:
        stamp_args = f"--agent-a {surviving_slot.session_id} --agent-b <new_id>"
    native_revive_block = (
        f"If TC revive fails (row purged), try native revival:\n"
        f"telec sessions revive {slot.native_session_id} --agent {slot.agent}\n"
        f"Save the returned session_id as <new_id> (the API mints a fresh TC id).\n"
        if slot.native_session_id
        else (
            "(no native_session_id stored — slot predates the durability fix; "
            "skip native revival and go straight to fresh dispatch)\n"
        )
    )
    return (
        f"PAIR MEMBER RECOVERY: {slug}\n\n"
        f"{ORCHESTRATOR_IDLE_INVARIANT}\n\n"
        f"Execute in order:\n\n"
        f"OPTION 1 — TC revive (slot id intact):\n"
        f"telec sessions revive {slot.session_id}\n"
        f"If revive succeeds (same TC session_id returned), send the pending message and skip the stamp:\n"
        f'  telec sessions send {slot.session_id} "{escaped}"\n'
        f"  Then call telec todo prepare {slug}. STOP HERE.\n\n"
        f"OPTION 2 — native revive (TC row purged, native transcript survives):\n"
        f"{native_revive_block}"
        f"\n"
        f"OPTION 3 — fresh dispatch (native revive also failed):\n"
        f'telec sessions run --command "{command}" --args "{slug}" --project "{project}" '
        f'--agent "{slot.agent}" --mode "slow" --subfolder "{subfolder}"\n'
        f"Save the returned session_id as <new_id>.\n\n"
        f"For OPTION 2 or 3, after the new <new_id> is in hand:\n"
        f'  telec sessions send <new_id> "{escaped}"\n'
        f"  telec todo stamp {slug} {stamp_args}\n"
        f"  Then call telec todo prepare {slug}."
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
            surviving_slot=reviewer_slot,
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
    writer_slot: PreparePairSlot,
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
            surviving_slot=writer_slot,
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
