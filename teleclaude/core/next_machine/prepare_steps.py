"""Prepare state machine phase step handlers and dispatcher."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_PRD,
    ARTIFACT_TEST_SPECS,
    SlashCommand,
)
from teleclaude.core.db import Db
from teleclaude.core.next_machine import prepare_step_support
from teleclaude.core.next_machine._types import PreparePhase, StateValue
from teleclaude.core.next_machine.git_ops import DRIFT_PENDING, compose_agent_guidance
from teleclaude.core.next_machine.lifecycle import derive_prepare_drift, prepare_blockers
from teleclaude.core.next_machine.output_formatting import (
    PrepareRecommendation,
    format_prepare_recommendation,
)
from teleclaude.core.next_machine.state_mutation import StateWriter

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


logger = get_logger(__name__)

_commit_writer = prepare_step_support.commit_writer
_derive_project_root = prepare_step_support.derive_project_root
_prepare_step_prepared = prepare_step_support.prepare_step_prepared


def _kind_from_state(state: dict[str, StateValue]) -> str:
    return str(state.get("kind") or "todo")


def _drift_from_state(state: dict[str, StateValue], *, cwd: str) -> dict[str, str]:
    return {name: status for name, status in derive_prepare_drift(StateWriter(state).state, repo_root=cwd).items()}


def _blockers_from_state(state: dict[str, StateValue], *, cwd: str) -> list[str]:
    return prepare_blockers(StateWriter(state).state, repo_root=cwd)


def _recommendation(
    *,
    slug: str,
    phase: PreparePhase,
    kind: str,
    command: str,
    args: str,
    required_reads: list[str],
    drift: dict[str, str],
    blockers: list[str],
    advisory: list[str],
) -> tuple[bool, str]:
    payload: PrepareRecommendation = {
        "slug": slug,
        "lifecycle_phase": phase.value,
        "stage": "prepare",
        "kind": kind,
        "recommended_command": command,
        "recommended_args": args,
        "required_reads": required_reads,
        "drift": drift,
        "blockers": blockers,
        "advisory": advisory,
    }
    return False, format_prepare_recommendation(payload)


async def _dispatch_worker(
    *,
    db: Db,
    slug: str,
    cwd: str,
    phase: PreparePhase,
    state: dict[str, StateValue],
    command: SlashCommand,
    loader_name: str,
    expected: str,
    blockers: list[str] | None = None,
) -> tuple[bool, str]:
    guidance = await compose_agent_guidance(db)
    project_root = _derive_project_root(cwd, slug)
    return _recommendation(
        slug=slug,
        phase=phase,
        kind=_kind_from_state(state),
        command=f"/{command.value}",
        args=slug,
        required_reads=[f"agents/commands/{loader_name}.md"],
        drift=_drift_from_state(state, cwd=project_root),
        blockers=blockers or [],
        advisory=[
            f"Dispatch a worker for {expected}.",
            guidance,
            f"Re-enter with `telec todo prepare {slug}` after the worker goes idle.",
        ],
    )


def _approval_instruction(
    slug: str,
    *,
    phase: PreparePhase,
    state: dict[str, StateValue],
    cwd: str,
    artifact: str,
    stamp_flag: str,
) -> tuple[bool, str]:
    return _recommendation(
        slug=slug,
        phase=phase,
        kind=_kind_from_state(state),
        command="telec todo stamp",
        args=f"{slug} {stamp_flag}",
        required_reads=[f"telec todo artifacts read {slug} {artifact}"],
        drift=_drift_from_state(state, cwd=cwd),
        blockers=[],
        advisory=[
            "A real human must approve the artifact before this stamp is valid.",
            f"Re-enter with `telec todo prepare {slug}` after stamping.",
        ],
    )


async def _prepare_dispatch(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    phase: PreparePhase,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """Dispatch to the appropriate v2 prepare phase handler."""
    _ = todos_db
    if phase in (PreparePhase.DRAFT, PreparePhase.PRD_DRAFTING):
        return await _dispatch_worker(
            db=db,
            slug=slug,
            cwd=cwd,
            phase=phase,
            state=state,
            command=SlashCommand.NEXT_PREPARE_INTAKE,
            loader_name="next-prepare-intake",
            expected="a `prd` artifact or an explicit blocker",
        )
    if phase == PreparePhase.PRD_HUMAN_APPROVAL:
        return _approval_instruction(
            slug, phase=phase, state=state, cwd=cwd, artifact=ARTIFACT_PRD, stamp_flag="--prd-approved"
        )
    if phase == PreparePhase.ARCHITECTURE_DRAFTING:
        return await _dispatch_worker(
            db=db,
            slug=slug,
            cwd=cwd,
            phase=phase,
            state=state,
            command=SlashCommand.NEXT_PREPARE_ARCHITECTURE,
            loader_name="next-prepare-architecture",
            expected="an `architecture` artifact or an `architecture_skipped` stamp recommendation",
        )
    if phase == PreparePhase.ARCHITECTURE_REVIEW:
        return await _dispatch_worker(
            db=db,
            slug=slug,
            cwd=cwd,
            phase=phase,
            state=state,
            command=SlashCommand.NEXT_REVIEW_ARCHITECTURE,
            loader_name="next-review-architecture",
            expected="an architecture review verdict and findings when needed",
        )
    if phase == PreparePhase.ARCHITECTURE_HUMAN_APPROVAL:
        return _approval_instruction(
            slug,
            phase=phase,
            state=state,
            cwd=cwd,
            artifact=ARTIFACT_ARCHITECTURE,
            stamp_flag="--architecture-approved",
        )
    if phase == PreparePhase.TEST_SPECS_DRAFTING:
        return await _dispatch_worker(
            db=db,
            slug=slug,
            cwd=cwd,
            phase=phase,
            state=state,
            command=SlashCommand.NEXT_PREPARE_SPECS,
            loader_name="next-prepare-specs",
            expected="a prose `test-specs` artifact or a `test_specs_skipped` stamp recommendation",
        )
    if phase == PreparePhase.TEST_SPECS_REVIEW:
        return await _dispatch_worker(
            db=db,
            slug=slug,
            cwd=cwd,
            phase=phase,
            state=state,
            command=SlashCommand.NEXT_REVIEW_SPECS,
            loader_name="next-review-specs",
            expected="a test-spec review verdict and findings when needed",
        )
    if phase == PreparePhase.TEST_SPECS_HUMAN_APPROVAL:
        return _approval_instruction(
            slug,
            phase=phase,
            state=state,
            cwd=cwd,
            artifact=ARTIFACT_TEST_SPECS,
            stamp_flag="--test-specs-approved",
        )
    if phase == PreparePhase.PLAN_DRAFTING:
        return await _dispatch_worker(
            db=db,
            slug=slug,
            cwd=cwd,
            phase=phase,
            state=state,
            command=SlashCommand.NEXT_PREPARE_PLAN,
            loader_name="next-prepare-plan",
            expected="an `implementation-plan` artifact or split decision",
        )
    if phase == PreparePhase.PLAN_REVIEW:
        return await _dispatch_worker(
            db=db,
            slug=slug,
            cwd=cwd,
            phase=phase,
            state=state,
            command=SlashCommand.NEXT_REVIEW_PLAN,
            loader_name="next-review-plan",
            expected="a plan review verdict and findings when needed",
        )
    if phase == PreparePhase.PLAN_HUMAN_APPROVAL:
        return _approval_instruction(
            slug,
            phase=phase,
            state=state,
            cwd=cwd,
            artifact=ARTIFACT_IMPLEMENTATION_PLAN,
            stamp_flag="--plan-approved",
        )
    if phase == PreparePhase.PREPARED:
        return await _prepare_step_prepared(db, slug)
    if phase == PreparePhase.BLOCKED:
        project_root = _derive_project_root(cwd, slug)
        drift = _drift_from_state(state, cwd=project_root)
        blockers = _blockers_from_state(state, cwd=project_root)
        if any(status == DRIFT_PENDING for status in drift.values()):
            return await _dispatch_worker(
                db=db,
                slug=slug,
                cwd=cwd,
                phase=phase,
                state=state,
                command=SlashCommand.NEXT_DRIFT_ANALYZE,
                loader_name="next-drift-analyze",
                expected="drift_reviewed stamps for every pending artifact",
                blockers=blockers,
            )
        return _recommendation(
            slug=slug,
            phase=phase,
            kind=_kind_from_state(state),
            command="",
            args="",
            required_reads=[],
            drift=drift,
            blockers=blockers,
            advisory=[f"Resolve the blockers, then re-enter with `telec todo prepare {slug}`."],
        )
    return False, f"UNHANDLED_PHASE: No handler for prepare phase: {phase.value}"


__all__ = ["_commit_writer", "_prepare_dispatch"]
