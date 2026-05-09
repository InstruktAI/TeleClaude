"""Todo lifecycle stamp service.

This module is the domain boundary for ``telec todo stamp``.  It accepts a
parsed stamp intent, validates the relevant evidence, and persists the resulting
state through :class:`StateWriter`.

Database access goes through the project's memoized factories
(``get_db``, ``get_todos_db``). They are the singular location and are
free to call inline — each operation that needs a database just calls the
factory; nothing is threaded through parameters.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.db import get_session_field_sync
from teleclaude.core.next_machine.git_ops import has_build_commits_beyond_main
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.state_io import (
    _ARTIFACT_UPSTREAMS,
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
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.project_root import resolve_state_root
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import PreparePairSlot

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

_ALL_VERDICT_PHASES = (*_PREPARE_VERDICT_PHASES, _BUILD_VERDICT_PHASE)

_READINESS_ARTIFACT_KEY: dict[str, str] = {
    "requirements": "requirements",
    "implementation-plan": "implementation_plan",
    "test-specs": "test_specs",
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
) -> dict[str, StateValue]:
    """Apply one parsed todo stamp and return the updated state.

    ``build_complete`` is intentionally worker-owned: the caller must be a
    TeleClaude session whose durable ``working_slug`` matches the stamped slug.
    """
    if stamp_type == "verdict":
        _validate_verdict_stamp(phase, value)
        return await asyncio.to_thread(stamp_verdict, cwd, slug, phase or "", value)

    if stamp_type == "finalize_ready":
        return await asyncio.to_thread(stamp_finalize_ready, cwd, slug)

    todos_db = await get_todos_db(cwd)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise ValueError(f"no state found for slug '{slug}'")

    writer = StateWriter(raw_state)

    if stamp_type == "grounding":
        _apply_grounding_stamp(writer, value)
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
        await _apply_readiness_stamp(todos_db, writer, slug, "test-specs", "specs_built")
    elif stamp_type == "prepare_pair":
        await _apply_prepare_pair_stamp(writer, value)
    elif stamp_type == "build_complete":
        await _apply_build_complete_stamp(
            writer,
            cwd=cwd,
            slug=slug,
            caller_session_id=caller_session_id,
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
    """Validate artifact existence and hydrate provenance.

    Provenance hydration (digest, ``produced_at``, ``upstream_digests``) is
    the fact this stamp records. The corresponding lifecycle signal fires
    from the prepare state machine on its next dispatch when it observes
    the populated provenance.
    """
    if not await todos_db.artifact_exists(slug, artifact_name):
        raise StateMutationError(f"cannot stamp {signal}: {artifact_name} artifact missing")
    state_key = _READINESS_ARTIFACT_KEY.get(artifact_name)
    if state_key:
        digest = await todos_db.artifact_digest(slug, artifact_name)
        if digest:
            entry = getattr(writer.state.artifacts, state_key)
            entry.digest = digest
            if not entry.produced_at:
                entry.produced_at = datetime.now(UTC).isoformat()
            upstream_keys = _ARTIFACT_UPSTREAMS.get(state_key, ())
            if upstream_keys:
                entry.upstream_digests = {
                    upstream_key: getattr(writer.state.artifacts, upstream_key).digest for upstream_key in upstream_keys
                }


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


async def _apply_prepare_pair_stamp(writer: StateWriter, value: str) -> None:
    """Record the orchestrator's claimed pair slot IDs.

    Slot validation (session liveness, ``active_agent``, ``native_session_id``)
    runs in the prepare state machine on its next dispatch entry. If a slot
    fails validation there, the machine emits a fix-relay script for the
    orchestrator instead of writing garbage canonical pair fields.
    """
    sid_a, sid_b = _parse_prepare_pair_value(value)
    if not sid_a or not sid_b:
        raise StateMutationError(f"prepare_pair stamp requires both slot_a and slot_b: got {value!r}")

    PreparePairManager(writer).set_pair(
        slot_a=PreparePairSlot(lens="A", session_id=sid_a, native_session_id="", agent=""),
        slot_b=PreparePairSlot(lens="B", session_id=sid_b, native_session_id="", agent=""),
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
) -> None:
    """Record the worker's claim that the build is complete.

    Gate execution and lifecycle advancement run in the work state machine
    on its next dispatch entry. Keeping pytest out of the stamp prevents
    minute-long stamp calls and the zombie processes the previous design
    produced when the gate runner's queue thread blocked interpreter exit.
    """
    await _validate_build_complete_owner(slug=slug, caller_session_id=caller_session_id)

    current = LifecyclePhase(writer.state.lifecycle_phase)
    if current not in (LifecyclePhase.BUILD_STARTED, LifecyclePhase.REVIEW_CHANGES_REQUESTED):
        raise StateMutationError(
            f"cannot stamp build_complete from lifecycle_phase {current.value!r}; "
            "expected build_started or review_changes_requested"
        )

    worktree_cwd = str(Path(resolve_state_root(cwd)) / WORKTREE_DIR / slug)
    if not has_build_commits_beyond_main(worktree_cwd):
        raise StateMutationError(f"build_complete: missing commits beyond main in {worktree_cwd}")

    writer.state.build_gate_claim_at = datetime.now(UTC).isoformat()


async def _validate_build_complete_owner(
    *,
    slug: str,
    caller_session_id: str | None,
) -> None:
    if not caller_session_id:
        raise PermissionError(f"build_complete stamp for {slug} requires a TeleClaude worker session")
    working_slug = get_session_field_sync(str(MAIN_DB_PATH), caller_session_id, "working_slug")
    if working_slug is None:
        raise PermissionError(f"build_complete stamp for {slug} requires a known TeleClaude session")
    if working_slug != slug:
        raise PermissionError(
            f"build_complete stamp for {slug} requires caller session {caller_session_id} to own working_slug={slug}"
        )
