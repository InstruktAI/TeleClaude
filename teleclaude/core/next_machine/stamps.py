"""Todo lifecycle stamp service.

This module is the domain boundary for ``telec todo stamp``.  It accepts a
parsed stamp intent, validates the relevant evidence, and persists the resulting
state through :class:`StateWriter`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.db import get_db
from teleclaude.core.next_machine.build_gates import run_build_gates
from teleclaude.core.next_machine.git_ops import has_build_commits_beyond_main
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, apply_authoritative_signal
from teleclaude.core.next_machine.state_io import (
    _BUILD_VERDICT_PHASE,
    _BUILD_VERDICT_VALUES,
    _PREPARE_VERDICT_PHASES,
    _PREPARE_VERDICT_VALUES,
    stamp_finalize_ready,
    stamp_verdict,
)
from teleclaude.core.next_machine.state_mutation import (
    GroundingManager,
    PreparePairManager,
    StateMutationError,
    StateWriter,
)
from teleclaude.core.todos_db import get_todos_db
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.producer import emit_event
from teleclaude.project_root import resolve_state_root
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import PreparePairSlot

if TYPE_CHECKING:
    from teleclaude.core.db import Db
    from teleclaude.core.todos_db import TodosDb

_ALL_VERDICT_PHASES = (*_PREPARE_VERDICT_PHASES, _BUILD_VERDICT_PHASE)

_READINESS_ARTIFACT_KEY: dict[str, str] = {
    "requirements": "requirements",
    "implementation-plan": "implementation_plan",
}

_CREATIVE_GATE_STAMPS: dict[str, tuple[str, str]] = {
    "creative_design_spec_confirmed": ("design_spec", "confirmed"),
    "creative_art_approved": ("art", "approved"),
    "creative_visuals_approved": ("visuals", "approved"),
}


async def apply_todo_stamp(
    *,
    cwd: str,
    slug: str,
    stamp_type: str,
    value: str = "",
    phase: str | None = None,
    caller_session_id: str | None = None,
    session_db: Db | None = None,
) -> dict[str, StateValue]:
    """Apply one parsed todo stamp and return the updated state.

    ``build_complete`` is intentionally worker-owned: the caller must be a
    TeleClaude session whose durable ``working_slug`` matches the stamped slug.
    """
    if stamp_type == "verdict":
        _validate_verdict_stamp(phase, value)
        return await asyncio.to_thread(stamp_verdict, cwd, slug, phase or "", value)

    if stamp_type == "finalize_ready":
        state = await asyncio.to_thread(stamp_finalize_ready, cwd, slug)
        await _emit_finalize_ready(slug, state, caller_session_id=caller_session_id)
        return state

    todos_db = await get_todos_db(cwd)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise ValueError(f"no state found for slug '{slug}'")

    writer = StateWriter(raw_state)
    sessions = session_db if session_db is not None else await get_db()

    if stamp_type == "grounding":
        _apply_grounding_stamp(writer, value)
        apply_authoritative_signal(writer.state, "grounding")
    elif stamp_type == "deferrals_processed":
        writer.state.deferrals_processed = True
    elif stamp_type in _CREATIVE_GATE_STAMPS:
        section, flag = _CREATIVE_GATE_STAMPS[stamp_type]
        _apply_creative_gate_stamp(writer, section=section, flag=flag)
    elif stamp_type == "requirements_ready":
        await _apply_readiness_stamp(todos_db, writer, slug, "requirements", "requirements_ready")
    elif stamp_type == "plan_ready":
        await _apply_readiness_stamp(todos_db, writer, slug, "implementation-plan", "plan_ready")
    elif stamp_type == "specs_built":
        _apply_effective_signal(writer, "specs_built")
    elif stamp_type == "prepare_pair":
        await _apply_prepare_pair_stamp(writer, value, session_db=sessions)
    elif stamp_type == "build_complete":
        await _apply_build_complete_stamp(
            writer,
            cwd=cwd,
            slug=slug,
            caller_session_id=caller_session_id,
            session_db=sessions,
        )
    else:
        raise ValueError(f"unknown stamp type: {stamp_type}")

    return await writer.commit(todos_db, slug)


def _validate_verdict_stamp(phase: str | None, verdict: str) -> None:
    if not phase:
        raise ValueError("verdict stamp requires explicit phase")
    if phase not in _ALL_VERDICT_PHASES:
        raise ValueError(f"invalid verdict phase '{phase}': must be one of {', '.join(_ALL_VERDICT_PHASES)}")
    allowed_values = _BUILD_VERDICT_VALUES if phase == _BUILD_VERDICT_PHASE else _PREPARE_VERDICT_VALUES
    if verdict not in allowed_values:
        raise ValueError(f"invalid verdict '{verdict}' for phase '{phase}': must be one of {', '.join(allowed_values)}")


async def _apply_readiness_stamp(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    artifact_name: str,
    signal: str,
) -> None:
    """Validate artifact existence, hydrate digest, apply signal, and reject no-ops."""
    if not await todos_db.artifact_exists(slug, artifact_name):
        raise StateMutationError(f"cannot stamp {signal}: {artifact_name} artifact missing")
    state_key = _READINESS_ARTIFACT_KEY.get(artifact_name)
    if state_key:
        digest = await todos_db.artifact_digest(slug, artifact_name)
        if digest:
            getattr(writer.state.artifacts, state_key).digest = digest
    _apply_effective_signal(writer, signal)


def _apply_grounding_stamp(writer: StateWriter, value: str) -> None:
    grounding_manager = GroundingManager(writer)
    if value == "valid":
        grounding_manager.clear_invalidation()
    else:
        grounding_manager.invalidate(reason="stamped_invalid", changed_paths=[])


def _apply_creative_gate_stamp(writer: StateWriter, *, section: str, flag: str) -> None:
    creative = writer.state.creative
    if creative is None:
        creative = {}
        writer.state.creative = creative

    raw_section = creative.get(section)
    section_state: dict[str, StateValue] = dict(raw_section) if isinstance(raw_section, dict) else {}
    section_state[flag] = True
    creative[section] = section_state


async def _apply_prepare_pair_stamp(writer: StateWriter, value: str, *, session_db: Db) -> None:
    sid_a, sid_b = _parse_prepare_pair_value(value)
    if not sid_a or not sid_b:
        raise StateMutationError(f"prepare_pair stamp requires both slot_a and slot_b: got {value!r}")

    session_a = await session_db.get_session(sid_a)
    if session_a is None:
        raise StateMutationError(f"unknown session for slot_a: {sid_a}")
    session_b = await session_db.get_session(sid_b)
    if session_b is None:
        raise StateMutationError(f"unknown session for slot_b: {sid_b}")

    for lens, session_id, session in (("A", sid_a, session_a), ("B", sid_b, session_b)):
        if not session.active_agent:
            raise StateMutationError(
                f"session {session_id} for slot_{lens.lower()} has no active_agent - cannot resolve pair agent"
            )
        if not session.native_session_id:
            raise StateMutationError(
                f"session {session_id} for slot_{lens.lower()} has no native_session_id - slot would not survive TC purge"
            )

    PreparePairManager(writer).set_pair(
        slot_a=PreparePairSlot(
            lens="A",
            session_id=sid_a,
            native_session_id=session_a.native_session_id,
            agent=session_a.active_agent,
        ),
        slot_b=PreparePairSlot(
            lens="B",
            session_id=sid_b,
            native_session_id=session_b.native_session_id,
            agent=session_b.active_agent,
        ),
    )


def _parse_prepare_pair_value(value: str) -> tuple[str, str]:
    parts: dict[str, str] = {}
    for chunk in value.split(","):
        key, _, raw_value = chunk.partition(":")
        parts[key.strip()] = raw_value.strip()
    return parts.get("slot_a", ""), parts.get("slot_b", "")


async def _apply_build_complete_stamp(
    writer: StateWriter,
    *,
    cwd: str,
    slug: str,
    caller_session_id: str | None,
    session_db: Db,
) -> None:
    await _validate_build_complete_owner(slug=slug, caller_session_id=caller_session_id, session_db=session_db)

    current = LifecyclePhase(writer.state.lifecycle_phase)
    if current not in (LifecyclePhase.BUILD_STARTED, LifecyclePhase.REVIEW_CHANGES_REQUESTED):
        raise StateMutationError(
            f"cannot stamp build_complete from lifecycle_phase {current.value!r}; "
            "expected build_started or review_changes_requested"
        )

    worktree_cwd = str(Path(resolve_state_root(cwd)) / WORKTREE_DIR / slug)
    if not has_build_commits_beyond_main(worktree_cwd):
        raise StateMutationError(f"build_complete: missing commits beyond main in {worktree_cwd}")

    gates_passed, gate_output = run_build_gates(worktree_cwd, slug)
    if not gates_passed:
        raise StateMutationError(f"build_complete: build gates failed for {slug}\n\n{gate_output}")

    _apply_effective_signal(writer, "build_complete", worktree_cwd=worktree_cwd)


async def _validate_build_complete_owner(
    *,
    slug: str,
    caller_session_id: str | None,
    session_db: Db,
) -> None:
    if not caller_session_id:
        raise PermissionError(f"build_complete stamp for {slug} requires a TeleClaude worker session")
    session = await session_db.get_session(caller_session_id)
    if session is None:
        raise PermissionError(f"build_complete stamp for {slug} requires a known TeleClaude session")
    if getattr(session, "working_slug", None) != slug:
        raise PermissionError(
            f"build_complete stamp for {slug} requires caller session {caller_session_id} to own working_slug={slug}"
        )


def _apply_effective_signal(writer: StateWriter, signal: str, *, worktree_cwd: str | None = None) -> None:
    before = writer.state.lifecycle_phase
    apply_authoritative_signal(writer.state, signal, worktree_cwd=worktree_cwd)
    if writer.state.lifecycle_phase == before:
        raise StateMutationError(f"{signal} has no effect at phase {before}")


async def _emit_finalize_ready(
    slug: str,
    state: dict[str, StateValue],
    *,
    caller_session_id: str | None,
) -> None:
    finalize_raw = state.get("finalize")
    finalize: dict[str, StateValue] = finalize_raw if isinstance(finalize_raw, dict) else {}
    sha = str(finalize.get("sha", ""))
    worker_session_id = caller_session_id or ""
    await emit_event(
        event="domain.software-development.planning.todo_finalize_ready",
        source=f"finalizer/{worker_session_id or 'unknown'}",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        entity=slug,
        description=f"Finalize ready for {slug} (sha {sha[:8]})",
        payload={
            "slug": slug,
            "branch": slug,
            "sha": sha,
            "worker_session_id": worker_session_id,
        },
    )
