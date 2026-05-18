"""Prepare state machine phase step handlers and dispatcher."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ARTIFACT_PRD,
    SlashCommand,
)
from teleclaude.core.db import Db
from teleclaude.core.next_machine import prepare_step_support
from teleclaude.core.next_machine._types import PreparePhase, StateValue
from teleclaude.core.next_machine.git_ops import DRIFT_PENDING, compose_agent_guidance
from teleclaude.core.next_machine.lifecycle import derive_prepare_drift, prepare_blockers
from teleclaude.core.next_machine.output_formatting import (
    ToolCallRequest,
    format_blocker_resolution,
    format_skill_load,
    format_tool_call,
)
from teleclaude.core.next_machine.state_mutation import StateWriter

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


logger = get_logger(__name__)

_commit_writer = prepare_step_support.commit_writer
_derive_project_root = prepare_step_support.derive_project_root
_prepare_step_prepared = prepare_step_support.prepare_step_prepared


def _drift_from_state(state: dict[str, StateValue], *, cwd: str) -> dict[str, str]:
    return {name: status for name, status in derive_prepare_drift(StateWriter(state).state, repo_root=cwd).items()}


def _blockers_from_state(state: dict[str, StateValue], *, cwd: str) -> list[str]:
    return prepare_blockers(StateWriter(state).state, repo_root=cwd)


def _drift_context(drift: dict[str, str]) -> str:
    if not drift:
        return ""
    lines = ["DRIFT STATUS:"]
    for name, status in sorted(drift.items()):
        lines.append(f"- {name}: {status}")
    return "\n".join(lines)


def _dispatch_post_block(*, slug: str, expected: str) -> str:
    return f"""WHEN WORKER COMPLETES:
The worker produces {expected}.
1. Tail the worker's final output to verify it succeeded.
2. Call `telec todo prepare {slug}` to advance the lifecycle to the next phase."""


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
    _ = phase, state, blockers  # not surfaced in verbatim dispatch script
    guidance = await compose_agent_guidance(db)
    project_root = _derive_project_root(cwd, slug)
    request = ToolCallRequest(
        command=f"/{command.value}",
        args=slug,
        project=project_root,
        guidance=guidance,
        subfolder="",
        post_block=_dispatch_post_block(slug=slug, expected=expected),
        note=f"Required reading for this worker: agents/commands/{loader_name}.md",
    )
    return False, format_tool_call(request)


def _load_skill(
    *,
    slug: str,
    command: SlashCommand,
    hat: str,
    expected: str,
) -> tuple[bool, str]:
    """Emit a skill-load script for a drafting phase.

    Draft phases (intake, architecture, test specs, plan) are performed by the
    same session that drives the prepare lifecycle — it loads the phase's
    skill inline and does the work. This helper produces the verbatim
    instruction for that load. Reviewer phases use ``_dispatch_worker``
    instead because the cross-model reviewer runs in a separate session.
    """
    return False, format_skill_load(
        slug=slug,
        command_name=command.value,
        hat=hat,
        expected=expected,
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
    _ = phase, state, cwd
    instruction = (
        f"1. Read the artifact:\n"
        f"   telec todo artifacts read {slug} {artifact}\n\n"
        f"2. Present the artifact to the real human and wait for confirmation.\n\n"
        f"3. When the human confirms, stamp:\n"
        f"   telec todo stamp {slug} {stamp_flag}\n\n"
        f"4. Call `telec todo prepare {slug}` to advance the lifecycle."
    )
    context = "A real human must approve the artifact before this stamp is valid."
    return False, format_blocker_resolution(slug, instruction, context=context)


def _blocker_resolution(
    slug: str,
    *,
    drift: dict[str, str],
    blockers: list[str],
) -> tuple[bool, str]:
    drift_context = _drift_context(drift)
    instruction = (
        f"Each blocker above names a concrete gap. Resolve it by:\n"
        f"- writing the missing artifact, or\n"
        f"- re-loading the responsible phase skill (intake, architecture, test specs, plan) "
        f"in this session and addressing the review findings, or\n"
        f"- surfacing a state-machine error to the user.\n\n"
        f"Then call `telec todo prepare {slug}` to re-derive the lifecycle phase."
    )
    return False, format_blocker_resolution(slug, instruction, blockers=blockers, context=drift_context)


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
        return _load_skill(
            slug=slug,
            command=SlashCommand.NEXT_PREPARE_INTAKE,
            hat="BA",
            expected="a `prd` artifact or an explicit blocker",
        )
    if phase == PreparePhase.PRD_HUMAN_APPROVAL:
        return _approval_instruction(
            slug, phase=phase, state=state, cwd=cwd, artifact=ARTIFACT_PRD, stamp_flag="--prd-approved"
        )
    if phase == PreparePhase.ARCHITECTURE_DRAFTING:
        return _load_skill(
            slug=slug,
            command=SlashCommand.NEXT_PREPARE_ARCHITECTURE,
            hat="Architect",
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
    if phase == PreparePhase.TEST_SPECS_DRAFTING:
        return _load_skill(
            slug=slug,
            command=SlashCommand.NEXT_PREPARE_SPECS,
            hat="Test Spec Author",
            expected="a `test-specs` Gherkin artifact or a `test_specs_skipped` stamp recommendation",
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
    if phase == PreparePhase.PLAN_DRAFTING:
        return _load_skill(
            slug=slug,
            command=SlashCommand.NEXT_PREPARE_PLAN,
            hat="Planner",
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
        return _blocker_resolution(slug, drift=drift, blockers=blockers)
    return False, f"UNHANDLED_PHASE: No handler for prepare phase: {phase.value}"


__all__ = ["_commit_writer", "_prepare_dispatch"]
