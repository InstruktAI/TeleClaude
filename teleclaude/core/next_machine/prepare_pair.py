"""Prepare-pair role lookup and orchestration script helpers."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import PreparePhase, StateValue
from teleclaude.core.next_machine.output_formatting import (
    ORCHESTRATOR_IDLE_INVARIANT,
    HumanApprovalScript,
    PairTurnScript,
    format_human_approval_script,
    format_pair_turn_script,
)
from teleclaude.core.next_machine.state_mutation import PreparePairManager, StateWriter
from teleclaude.core.session_status import compute_agent_status
from teleclaude.types.todos import PreparePairSlot

if TYPE_CHECKING:
    from teleclaude.core.db import Db
    from teleclaude.core.todos_db import TodosDb

PrepareLens = Literal["A", "B"]


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


async def resolve_pair_or_recover(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
    phase: PreparePhase,
    roles: dict[PreparePhase, tuple[PrepareLens, PrepareLens]],
) -> tuple[PreparePairSlot, PreparePairSlot] | None:
    """Return writer/reviewer slots; auto-recover from live sessions if state is empty.

    Resolution order:
      1. ``pair_writer_reviewer_slots`` — if state has both slots, return them.
      2. Auto-recovery — scan live sessions for this slug's worktree subdir,
         pick the newest session matching the configured A and B agents,
         re-stamp the pair programmatically (single-shot, no recursion),
         then return the recovered slots.
      3. ``None`` — no recovery candidate (both A and B sessions absent);
         the phase handler surfaces BLOCKED.

    Recovery is bounded: a single attempt per state-machine call. Once the
    pair is stamped, the state mutation persists and future calls take path 1.

    Contract: ``db.list_sessions`` is part of the Db protocol. Failures bubble
    up — silent-fail guards are not used; an infrastructure failure must not
    be confused with "no recoverable pair".
    """
    pair = pair_writer_reviewer_slots(state, phase, roles)
    if pair is not None:
        return pair

    agents = prepare_pair_agent_mapping()
    expected_subdir = f"{WORKTREE_DIR}/{slug}"
    sessions = await db.list_sessions(include_closed=False)

    slot_a: PreparePairSlot | None = None
    slot_b: PreparePairSlot | None = None
    for session in sessions:
        if session.subdir != expected_subdir:
            continue
        active_agent = session.active_agent or ""
        if not session.session_id:
            continue
        native_session_id = session.native_session_id or ""
        if slot_a is None and active_agent == agents["A"]:
            slot_a = PreparePairSlot(
                lens="A", session_id=session.session_id, native_session_id=native_session_id, agent=active_agent
            )
        elif slot_b is None and active_agent == agents["B"]:
            slot_b = PreparePairSlot(
                lens="B", session_id=session.session_id, native_session_id=native_session_id, agent=active_agent
            )
        if slot_a is not None and slot_b is not None:
            break

    if slot_a is None or slot_b is None:
        return None

    writer = StateWriter(state)
    PreparePairManager(writer).set_pair(slot_a=slot_a, slot_b=slot_b)
    payload = await writer.commit(todos_db, slug)
    # Sync the validated payload back into the caller's state dict so subsequent
    # reads (including pair_writer_reviewer_slots below) observe the new pair.
    state.clear()
    state.update(payload)
    return pair_writer_reviewer_slots(state, phase, roles)


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


async def pair_slot_alive(db: Db, slot: PreparePairSlot) -> bool:
    """Return whether a stored pair slot currently maps to a live session.

    Contract: ``db.list_sessions`` is part of the Db protocol. Failures bubble
    up — silent-fail guards are not used; a DB/contract failure must not be
    confused with "slot is alive" and dispatched into a stale session.
    """
    sessions = await db.list_sessions(include_closed=False)
    return any(session.session_id == slot.session_id for session in sessions)


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
    db: Db,
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
    db: Db,
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
