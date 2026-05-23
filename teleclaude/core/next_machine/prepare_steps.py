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
from teleclaude.core.next_machine.git_ops import (
    DRIFT_PENDING,
    DRIFT_SUBSTANTIVE,
    ArtifactDriftStatus,
    compose_agent_guidance,
)
from teleclaude.core.next_machine.lifecycle import collapse_drift, derive_lifecycle_drift, prepare_blockers
from teleclaude.core.next_machine.output_formatting import (
    ToolCallRequest,
    format_blocker_resolution,
    format_pending_classes_for_dispatch,
    format_procedure_load,
    format_tool_call,
)
from teleclaude.core.next_machine.runtime.sessions import find_live_prepare_worker_for_slug
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.snippet_validation import snippet_body_digest

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


logger = get_logger(__name__)

_commit_writer = prepare_step_support.commit_writer
_derive_project_root = prepare_step_support.derive_project_root
_prepare_step_prepared = prepare_step_support.prepare_step_prepared


def _blockers_from_state(state: dict[str, StateValue], *, cwd: str) -> list[str]:
    return prepare_blockers(StateWriter(state).state, repo_root=cwd)


def _drift_context(drift: dict[str, ArtifactDriftStatus]) -> str:
    if not drift:
        return ""
    lines = ["DRIFT STATUS:"]
    for name, status in sorted(drift.items()):
        lines.append(f"- {name}: {status}")
    return "\n".join(lines)


def _has_status(drift: dict[str, ArtifactDriftStatus], status: ArtifactDriftStatus) -> bool:
    return any(value == status for value in drift.values())


def _drift_reprepare_instruction(slug: str, drift: dict[str, ArtifactDriftStatus]) -> tuple[bool, str]:
    blockers = [
        f"{artifact} drift is {status}; re-run prepare to re-derive" for artifact, status in sorted(drift.items())
    ]
    instruction = (
        "Substantive drift has already invalidated the affected prepared artifact path. "
        f"Call `telec todo prepare {slug}` to re-derive the next prepare phase."
    )
    return False, format_blocker_resolution(slug, instruction, blockers=blockers, context=_drift_context(drift))


async def _derive_and_commit_drift(
    *,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> dict[str, dict[str, ArtifactDriftStatus]]:
    writer = StateWriter(state)
    drift_result = await derive_lifecycle_drift(
        slug,
        writer.state,
        repo_root=cwd,
        todos_db=todos_db,
        snippet_digest_fn=snippet_body_digest,
        writer=writer,
    )
    await _commit_writer(writer, todos_db, slug, state)
    return drift_result


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
    additional_context: str = "",
    recommended_mode: str = "",
) -> tuple[bool, str]:
    _ = state, blockers  # not surfaced in verbatim dispatch script
    # Reuse-or-spawn: prefer an existing live prepare worker for this
    # slug+command and emit `telec sessions send` instead of spawning a
    # fresh one. Prepare workers persist with subdir=None (no worktree on
    # repo root); the matcher requires the title to equal "/cmd slug" or
    # be followed by a word boundary so a longer slug that starts with
    # this slug as a prefix cannot match. The re-run prompt is plain text
    # — no backticks — because the orchestrator executes the emitted
    # `telec sessions send ...` line in a shell and backticks inside
    # double quotes trigger command substitution.
    worker_id = await find_live_prepare_worker_for_slug(db, slug, command.value)
    if worker_id is not None:
        base_message = (
            f"Re-run your task for {slug}. The relevant artifact(s) have been "
            f"updated since your prior pass. If a review-findings artifact "
            f"exists, read it first: telec todo artifacts read {slug} "
            f"review-findings. Then re-execute your loaded procedure on the new "
            f"content. Reviewers: re-stamp via telec todo stamp {slug} --verdict "
            f"approve|needs_work --phase {phase.value}. Drift analyzers: stamp "
            f"drift_reviewed for each re-assessed artifact."
        )
        message = f"{additional_context} {base_message}" if additional_context else base_message
        escaped = message.replace('"', '\\"')
        return False, (
            f"WORKER RE-DISPATCH (reuse): {slug}\n\n"
            f"Execute in order:\n\n"
            f'telec sessions send {worker_id} "{escaped}"\n\n'
            f"Cancel the old heartbeat timer via KillShell(shell_id=<task_id>).\n"
            f"Start a new non-blocking heartbeat timer via "
            f'Bash(command="sleep 300", run_in_background=true) and save the new task_id.\n'
            f"When the worker reports idle, call telec todo prepare {slug}."
        )

    # No live worker — spawn a fresh one.
    guidance = await compose_agent_guidance(db)
    project_root = _derive_project_root(cwd, slug)
    request = ToolCallRequest(
        command=f"/{command.value}",
        args=slug,
        project=project_root,
        guidance=guidance,
        subfolder="",
        post_block=_dispatch_post_block(slug=slug, expected=expected),
        additional_context=additional_context,
        note=f"Required reading for this worker: agents/commands/{loader_name}.md",
        recommended_mode=recommended_mode,
    )
    return False, format_tool_call(request)


def _load_procedure(
    *,
    slug: str,
    command: SlashCommand,
    hat: str,
    expected: str,
) -> tuple[bool, str]:
    """Emit a procedure-load script for a drafting phase.

    Draft phases (intake, architecture, test specs, plan) are performed by the
    same session that drives the prepare lifecycle — it reads the phase's
    procedure inline and does the work. This helper produces the verbatim
    instruction for that load. Reviewer phases use ``_dispatch_worker``
    instead because the cross-model reviewer runs in a separate session.
    """
    return False, format_procedure_load(
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
    drift: dict[str, ArtifactDriftStatus],
    blockers: list[str],
) -> tuple[bool, str]:
    drift_context = _drift_context(drift)
    instruction = (
        f"Each blocker above names a concrete gap. Resolve it by:\n"
        f"- writing the missing artifact, or\n"
        f"- re-loading the responsible procedure (intake, architecture, test specs, plan) "
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
    if phase in (PreparePhase.DRAFT, PreparePhase.PRD_DRAFTING):
        return _load_procedure(
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
        return _load_procedure(
            slug=slug,
            command=SlashCommand.NEXT_PREPARE_ARCHITECTURE,
            hat="Architect",
            expected=(
                "doc-snippet updates (domain spec / architecture-v2 design docs) "
                "plus a thin `architecture` index artifact, or an "
                "`architecture_skipped` stamp recommendation"
            ),
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
    if phase == PreparePhase.PLAN_DRAFTING:
        return _load_procedure(
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
        project_root = _derive_project_root(cwd, slug)
        drift_result = await _derive_and_commit_drift(todos_db=todos_db, slug=slug, cwd=project_root, state=state)
        drift = collapse_drift(drift_result)
        if _has_status(drift, DRIFT_SUBSTANTIVE):
            return _drift_reprepare_instruction(slug, drift)
        if _has_status(drift, DRIFT_PENDING):
            return await _dispatch_worker(
                db=db,
                slug=slug,
                cwd=cwd,
                phase=PreparePhase.BLOCKED,
                state=state,
                command=SlashCommand.NEXT_DRIFT_ANALYZE,
                loader_name="next-drift-analyze",
                expected="drift_reviewed stamps for every pending artifact",
                blockers=_blockers_from_state(state, cwd=project_root),
                additional_context=format_pending_classes_for_dispatch(drift_result),
                recommended_mode="fast",
            )
        return await _prepare_step_prepared(db, slug)
    if phase == PreparePhase.BLOCKED:
        project_root = _derive_project_root(cwd, slug)
        drift_result = await _derive_and_commit_drift(todos_db=todos_db, slug=slug, cwd=project_root, state=state)
        drift = collapse_drift(drift_result)
        blockers = _blockers_from_state(state, cwd=project_root)
        if _has_status(drift, DRIFT_SUBSTANTIVE):
            return _drift_reprepare_instruction(slug, drift)
        if _has_status(drift, DRIFT_PENDING):
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
                additional_context=format_pending_classes_for_dispatch(drift_result),
                recommended_mode="fast",
            )
        return _blocker_resolution(slug, drift=drift, blockers=blockers)
    return False, f"UNHANDLED_PHASE: No handler for prepare phase: {phase.value}"


__all__ = ["_commit_writer", "_prepare_dispatch"]
