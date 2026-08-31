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
from teleclaude.core.next_machine.dispatch_claims import (
    DIAGNOSIS_DISPATCH_LANE,
    DIAGNOSIS_LEASE_SECONDS,
    acquire_dispatch_claim,
)
from teleclaude.core.next_machine.git_ops import (
    DRIFT_PENDING,
    DRIFT_SUBSTANTIVE,
    ArtifactDriftStatus,
)
from teleclaude.core.next_machine.lifecycle import (
    _DRIFT_MATRIX_ARTIFACTS,
    _DRIFT_REROUTABLE_CLASSES_BY_ARTIFACT,
    collapse_drift,
    derive_lifecycle_drift,
    prepare_blockers,
)
from teleclaude.core.next_machine.output_formatting import (
    ToolCallRequest,
    format_blocker_resolution,
    format_pending_classes_for_dispatch,
    format_procedure_load,
    format_tool_call,
    format_worker_redispatch,
)
from teleclaude.core.next_machine.prepare_diff_dispatch import DispatchReason
from teleclaude.core.next_machine.runtime.sessions import find_live_prepare_worker_for_slug
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.snippet_validation import snippet_body_digest

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


logger = get_logger(__name__)

_DIAGNOSE_DRIVER_PROCEDURE_ID = "software-development/procedure/lifecycle/prepare/diagnose"
_DIAGNOSE_PRE_DISPATCH_TEMPLATE = (
    "Load the prepare driver's diagnosis procedure with `{command}` and perform its triage step for `{slug}`. "
    "If triage retires the todo, stop this script without dispatching. Otherwise continue to STEP 1; the "
    "dispatched worker will load its separate peer procedure."
)
_TELEC_DOCS_GET_TEMPLATE = "telec docs get {procedure_id}"

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


def _drift_anomaly_blockers(
    state: dict[str, StateValue],
    drift_result: dict[str, dict[str, ArtifactDriftStatus]],
) -> list[str]:
    model = StateWriter(state).state
    blockers = [
        f"substantive drift_reviewed stamp targets non-matrix artifact: {artifact}"
        for artifact, stamp in sorted(model.approvals.drift_reviewed.items())
        if stamp.verdict == DRIFT_SUBSTANTIVE and artifact not in _DRIFT_MATRIX_ARTIFACTS
    ]
    for artifact, class_statuses in sorted(drift_result.items()):
        reroutable_classes = _DRIFT_REROUTABLE_CLASSES_BY_ARTIFACT.get(artifact, frozenset())
        for class_name, status in sorted(class_statuses.items()):
            if status == DRIFT_SUBSTANTIVE and class_name not in reroutable_classes:
                blockers.append(f"substantive drift route is undefined for {artifact}/{class_name}")
    return blockers


def _drift_anomaly_halt_instruction(
    slug: str,
    blockers: list[str],
    drift: dict[str, ArtifactDriftStatus],
) -> tuple[bool, str]:
    instruction = (
        "Drift review anomaly requires operator inspection. "
        "Inspect and correct the invalid substantive drift target before advancing this todo."
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
    expected: str,
    blockers: list[str] | None = None,
    additional_context: str = "",
    pre_dispatch: str = "",
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
        return False, format_worker_redispatch(
            worker_id,
            slug=slug,
            message=message,
            advance_call=f"telec todo prepare {slug}",
        )

    # No live worker — spawn a fresh one.
    project_root = _derive_project_root(cwd, slug)
    request = ToolCallRequest(
        command=f"/{command.value}",
        args=slug,
        project=project_root,
        subfolder="",
        post_block=_dispatch_post_block(slug=slug, expected=expected),
        additional_context=additional_context,
        pre_dispatch=pre_dispatch,
    )
    return False, format_tool_call(request)


def _load_procedure(
    *,
    slug: str,
    command: SlashCommand,
    hat: str,
    expected: str,
    reason: DispatchReason | None = None,
    additional_context: str = "",
) -> tuple[bool, str]:
    """Emit a procedure-load script for a drafting phase.

    Draft phases (intake, architecture, test specs, plan) are performed by the
    same session that drives the prepare lifecycle — it reads the phase's
    procedure inline and does the work. The bug lane's interrogation step is
    the same shape: the driving session stays inline and reads the same
    diagnose procedure it loaded for dispatch. This helper produces the
    verbatim instruction for that load. Reviewer phases use ``_dispatch_worker``
    instead because the cross-model reviewer runs in a separate session.

    A re-entry drafting phase passes ``reason`` so the loaded procedure reads
    an explicit ``Dispatch reason`` header instead of defaulting to a
    fresh-from-scratch production that silently overwrites an existing plan.
    """
    return False, format_procedure_load(
        slug=slug,
        command_name=command.value,
        hat=hat,
        expected=expected,
        reason=reason,
        additional_context=additional_context,
    )


def _diagnose_interrogation_context(slug: str, peer_session_id: str) -> str:
    """Compose the additional context naming the live diagnosis peer to question.

    The interrogation is the driving session's own inline work — no new
    session is dispatched — but it must know which live peer session to
    challenge rather than re-running the investigation itself.
    """
    settle_call = f"telec todo stamp {slug} --diagnosis-settled"
    unresolved_call = f'telec todo stamp {slug} --diagnosis-unresolved --reason "<why>"'
    return (
        f"LIVE DIAGNOSIS PEER: {peer_session_id}\n"
        "Interrogate the written mechanism by messaging that session "
        f'(`telec sessions send {peer_session_id} "<challenge>"`) — do not re-run the '
        "investigation yourself; the peer keeps the pen on every revision. Settle with "
        f"`{settle_call}` once every causal transition is evidenced and the strongest "
        f"rival is eliminated, or record the unresolved outcome with `{unresolved_call}`."
    )


def _diagnose_pre_dispatch_instruction(slug: str) -> str:
    """Tell the prepare driver to triage before spending the diagnosis peer."""
    command = _TELEC_DOCS_GET_TEMPLATE.format(procedure_id=_DIAGNOSE_DRIVER_PROCEDURE_ID)
    return _DIAGNOSE_PRE_DISPATCH_TEMPLATE.format(command=command, slug=slug)


def _plan_drafting_reason(state: dict[str, StateValue]) -> DispatchReason:
    """Classify why PLAN_DRAFTING was entered, from the same state signals the
    lifecycle's ``_plan_only_phase`` routes on.

    The artifact-absent case is a genuine fresh production. The two cases that
    route a *present* plan to PLAN_DRAFTING — a ``--plan`` seed and a
    substantive-drift clear — each carry their own reason so the planner
    preserves/re-derives the existing plan instead of overwriting it. No other
    state reaches PLAN_DRAFTING with a present plan (a stale review routes to
    PLAN_REVIEW), so a present plan never falls to ``FRESH``.
    """
    model = StateWriter(state).state
    plan = model.artifacts.implementation_plan
    if not (plan.digest or plan.produced_at):
        return DispatchReason.FRESH
    if plan.seeded:
        return DispatchReason.SEEDED
    if model.plan_review.cleared_by_substantive_drift:
        return DispatchReason.SUBSTANTIVE_DRIFT
    raise ValueError(
        "PLAN_DRAFTING reached with a present implementation-plan that is "
        "neither seeded nor substantive-drift-cleared. Only an absent plan may "
        "dispatch FRESH; falling through here would silently re-derive from "
        "scratch and overwrite the existing plan — the exact failure this "
        "dispatch reason exists to prevent. The contradictory state must be "
        "resolved (or a new present-plan route given its own reason), not "
        "papered over with a produce-from-scratch dispatch."
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
    if phase == PreparePhase.PRD_REVIEW:
        return await _dispatch_worker(
            db=db,
            slug=slug,
            cwd=cwd,
            phase=phase,
            state=state,
            command=SlashCommand.NEXT_REVIEW_PRD,
            expected="a PRD review verdict and findings when needed",
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
            expected="an architecture review verdict and findings when needed",
        )
    if phase == PreparePhase.DIAGNOSE:
        diagnosis = StateWriter(state).state.artifacts.diagnosis
        peer_session_id = await find_live_prepare_worker_for_slug(db, slug, SlashCommand.NEXT_PREPARE_DIAGNOSE.value)
        if not (diagnosis.digest or diagnosis.produced_at) or peer_session_id is None:
            # An unsettled diagnosis cannot advance without an independent
            # author. Open the write lease before dispatching when no active
            # diagnosis peer owns it.
            await acquire_dispatch_claim(
                todos_db,
                slug=slug,
                lane=DIAGNOSIS_DISPATCH_LANE,
                owner=f"diagnose-handoff:{slug}",
                lease_seconds=DIAGNOSIS_LEASE_SECONDS,
            )
            return await _dispatch_worker(
                db=db,
                slug=slug,
                cwd=cwd,
                phase=phase,
                state=state,
                command=SlashCommand.NEXT_PREPARE_DIAGNOSE,
                expected="a `diagnosis` artifact or revision",
                pre_dispatch=_diagnose_pre_dispatch_instruction(slug),
            )
        return False, format_procedure_load(
            slug=slug,
            procedure_id=_DIAGNOSE_DRIVER_PROCEDURE_ID,
            hat="Skeptical Examiner",
            expected="a settled or unresolved diagnosis outcome",
            additional_context=_diagnose_interrogation_context(slug, peer_session_id),
        )
    if phase == PreparePhase.PLAN_DRAFTING:
        return _load_procedure(
            slug=slug,
            command=SlashCommand.NEXT_PREPARE_PLAN,
            hat="Planner",
            expected="an `implementation-plan` artifact or breakdown decision",
            reason=_plan_drafting_reason(state),
        )
    if phase == PreparePhase.PLAN_REVIEW:
        return await _dispatch_worker(
            db=db,
            slug=slug,
            cwd=cwd,
            phase=phase,
            state=state,
            command=SlashCommand.NEXT_REVIEW_PLAN,
            expected="a plan review verdict and findings when needed",
        )
    if phase == PreparePhase.PREPARED:
        project_root = _derive_project_root(cwd, slug)
        drift_result = await _derive_and_commit_drift(todos_db=todos_db, slug=slug, cwd=project_root, state=state)
        drift = collapse_drift(drift_result)
        drift_anomaly_blockers = _drift_anomaly_blockers(state, drift_result)
        if drift_anomaly_blockers:
            return _drift_anomaly_halt_instruction(slug, drift_anomaly_blockers, drift)
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
                expected="drift_reviewed stamps for every pending artifact",
                blockers=_blockers_from_state(state, cwd=project_root),
                additional_context=format_pending_classes_for_dispatch(drift_result),
            )
        return await _prepare_step_prepared(db, todos_db, slug, project_root=project_root)
    if phase == PreparePhase.BLOCKED:
        project_root = _derive_project_root(cwd, slug)
        drift_result = await _derive_and_commit_drift(todos_db=todos_db, slug=slug, cwd=project_root, state=state)
        drift = collapse_drift(drift_result)
        blockers = _blockers_from_state(state, cwd=project_root)
        drift_anomaly_blockers = _drift_anomaly_blockers(state, drift_result)
        if drift_anomaly_blockers:
            return _drift_anomaly_halt_instruction(slug, drift_anomaly_blockers, drift)
        if _has_status(drift, DRIFT_PENDING):
            return await _dispatch_worker(
                db=db,
                slug=slug,
                cwd=cwd,
                phase=phase,
                state=state,
                command=SlashCommand.NEXT_DRIFT_ANALYZE,
                expected="drift_reviewed stamps for every pending artifact",
                blockers=blockers,
                additional_context=format_pending_classes_for_dispatch(drift_result),
            )
        return _blocker_resolution(slug, drift=drift, blockers=blockers)
    return False, f"UNHANDLED_PHASE: No handler for prepare phase: {phase.value}"


__all__ = ["_commit_writer", "_prepare_dispatch"]
