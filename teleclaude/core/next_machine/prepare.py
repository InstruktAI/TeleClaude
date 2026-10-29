"""Prepare stage — Phase A dispatcher."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
)
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _PREPARE_LOOP_LIMIT
from teleclaude.core.next_machine.commit_review_stamps import OutstandingCommit, outstanding_claim_period_commits
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    adopt_prepare_handoff_phase,
    is_work_lifecycle_phase,
    require_lifecycle_phase,
)
from teleclaude.core.next_machine.output_formatting import (
    MISSING_ACTIVE_TODO_MESSAGE_TEMPLATE,
    PREPARE_SLUG_REQUIRED_MESSAGE,
    format_blocker_resolution,
    format_error,
    format_prepared_withheld,
    format_procedure_load,
)
from teleclaude.core.next_machine.prepare_steps import _commit_writer, _prepare_dispatch
from teleclaude.core.next_machine.provenance import (
    read_owned_snippet_digests,
    read_referenced_snippet_digests,
    refresh_referenced_paths,
    sync_artifact_provenance,
)
from teleclaude.core.next_machine.review_evidence import REVIEW_EVIDENCE_ARTIFACTS
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.session_identity import get_session_id
from teleclaude.snippet_validation import snippet_body_digest_for
from teleclaude.types.state_value import StateValue

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

from teleclaude.core.next_machine._types import PreparePhase as _PP
from teleclaude.core.next_machine.lanes import LifecycleProcedure
from teleclaude.core.next_machine.slug_resolution import (
    HolderResolutionMode,
    HolderResolutionReason,
    resolve_runnable_holder_children_db,
)
from teleclaude.core.workflow_store.store import get_workflow_store

logger = get_logger(__name__)

_PREPARED_WITHHELD_LOG = "prepared_withheld"
_TASK_PREPARER_HAT = "Task preparer"
_TASK_PREPARER_EXPECTED = "a durable task-plan and a human authorization request"
_TASK_RUNNING_ERROR_CODE = "TASK_RUNNING"
_TASK_RUNNING_MESSAGE_TEMPLATE = "Task '{slug}' is running in the task lane; use its task-runner session."

_ADOPTION_ARTIFACTS: tuple[tuple[str, str], ...] = (
    (STATE_KEY_INPUT, ARTIFACT_INPUT),
    (STATE_KEY_PRD, ARTIFACT_PRD),
    (STATE_KEY_REQUIREMENTS, ARTIFACT_REQUIREMENTS),
    (STATE_KEY_ARCHITECTURE, ARTIFACT_ARCHITECTURE),
    (STATE_KEY_DIAGNOSIS, ARTIFACT_DIAGNOSIS),
    (STATE_KEY_IMPLEMENTATION_PLAN, ARTIFACT_IMPLEMENTATION_PLAN),
)


def _format_holder_prepare_instruction(
    holder_slug: str,
    children: tuple[str, ...],
    runnable: tuple[str, ...],
    reason: HolderResolutionReason,
) -> str:
    """Return the next prepare action for a holder entrypoint."""
    if runnable:
        commands = "\n".join(f"telec todo prepare {child}" for child in runnable)
        return (
            "This slug is a structural holder grouping child todos. The holder is not a prepare/work target.\n"
            "Run prepare on these direct child todos:\n"
            f"{commands}"
        )
    if reason is HolderResolutionReason.COMPLETE:
        return f"All direct children for '{holder_slug}' are delivered. No prepare work remains."
    if reason is HolderResolutionReason.ALL_PREPARED:
        return (
            f"All direct children for '{holder_slug}' are already prepared or in work. "
            f"Run `telec todo work {holder_slug}` to resolve child work."
        )
    if reason is HolderResolutionReason.DEPS_UNSATISFIED:
        return (
            f"Holder '{holder_slug}' has direct children, but none are prepare-runnable because "
            "their dependencies have not reached the PREPARED gate yet."
        )
    if reason is HolderResolutionReason.CHILDREN_NOT_IN_TODO:
        return f"Holder '{holder_slug}' has child todos, but none are active todo-list entries."
    return (
        f"Holder '{holder_slug}' has direct children, but none are currently prepare-runnable. "
        f"Children: {', '.join(children)}"
    )


async def _hydrate_artifact_presence_for_adoption(
    todos_db: WorkflowStore,
    slug: str,
    writer: StateWriter,
    *,
    repo_root: str,
) -> None:
    """Load current artifact presence into state before handoff adoption.

    Stored provenance is kept only while it describes the current stored artifact; a digest
    that differs from the stored content is re-captured in full.
    """
    for state_key, artifact_name in _ADOPTION_ARTIFACTS:
        entry = getattr(writer.state.artifacts, state_key)
        if not await todos_db.artifact_exists(slug, artifact_name):
            continue
        artifact_body = await todos_db.read_artifact(slug, artifact_name)
        snippet_digest_fn = snippet_body_digest_for(repo_root)
        current_digest = await todos_db.artifact_digest(slug, artifact_name)
        if entry.digest and entry.async_provenance_complete and entry.digest == current_digest:
            if not entry.owned_snippet_digests or not entry.referenced_snippet_digests:
                owned_snippet_digests = await read_owned_snippet_digests(
                    todos_db,
                    slug,
                    artifact_name,
                    repo_root=repo_root,
                    snippet_digest_fn=snippet_digest_fn,
                )
                referenced_snippet_digests = await read_referenced_snippet_digests(
                    todos_db,
                    slug,
                    artifact_name,
                    artifact_body,
                    repo_root=repo_root,
                    snippet_digest_fn=snippet_digest_fn,
                )
                if not entry.owned_snippet_digests and owned_snippet_digests:
                    entry.owned_snippet_digests = owned_snippet_digests
                if not entry.referenced_snippet_digests and referenced_snippet_digests:
                    entry.referenced_snippet_digests = referenced_snippet_digests
            refresh_referenced_paths(writer, state_key, artifact_body=artifact_body)
            continue
        await sync_artifact_provenance(
            todos_db,
            writer,
            slug,
            artifact_name,
            repo_root=repo_root,
            artifact_body=artifact_body,
            snippet_digest_fn=snippet_digest_fn,
        )


async def _adopt_prepare_phase(
    todos_db: WorkflowStore,
    slug: str,
    raw_state: dict[str, StateValue],
    *,
    repo_root: str,
) -> tuple[dict[str, StateValue], list[OutstandingCommit]]:
    """Adopt the derived prepare phase and report the commits that withhold ``PREPARED``.

    The second element lists the calling session's claim-period commits on main
    that lack an ``approve`` stamp; it is non-empty only when the derivation would
    have entered ``PREPARED`` and was held back, so the stored phase is unchanged.
    """
    writer = StateWriter(raw_state)
    outstanding: list[OutstandingCommit] = []

    def prepared_withheld() -> bool:
        session_id = get_session_id()
        if not session_id:
            return False
        outstanding.extend(outstanding_claim_period_commits(repo_root, session_id, writer.state.events))
        return bool(outstanding)

    await _hydrate_artifact_presence_for_adoption(todos_db, slug, writer, repo_root=repo_root)
    artifact_metadata = {metadata["name"]: metadata for metadata in await todos_db.artifact_metadata(slug)}
    artifact_names = dict(_ADOPTION_ARTIFACTS)
    for phase, artifacts in REVIEW_EVIDENCE_ARTIFACTS.items():
        if artifacts.target_artifact_key is None:
            continue
        review = writer.review(phase)
        if not review.cycle.reconciliation_pending:
            continue
        target = getattr(writer.state.artifacts, artifacts.target_artifact_key)
        target_metadata = artifact_metadata.get(artifact_names[artifacts.target_artifact_key])
        report_metadata = artifact_metadata.get(artifacts.report_artifact_name)
        target_written_at = target_metadata["updated_at"] if target_metadata is not None else target.produced_at
        report_written_at = report_metadata["updated_at"] if report_metadata is not None else ""
        has_empty_bindings = not any((review.verdict, review.reviewed_target_digest, review.review_report_digest))
        if has_empty_bindings and report_written_at and target_written_at > report_written_at:
            review.open_new_cycle()
        else:
            review.cycle.reconciliation_pending = False
    report_digests = {
        artifacts.report_artifact_name: await todos_db.artifact_digest(slug, artifacts.report_artifact_name)
        for artifacts in REVIEW_EVIDENCE_ARTIFACTS.values()
        if artifacts.target_artifact_key is not None
    }
    artifact_write_timestamps = {
        state_key: artifact_metadata[artifact_name]["updated_at"] if artifact_name in artifact_metadata else ""
        for state_key, artifact_name in _ADOPTION_ARTIFACTS
    }
    derived = adopt_prepare_handoff_phase(
        writer.state,
        repo_root=repo_root,
        report_digests=report_digests,
        artifact_write_timestamps=artifact_write_timestamps,
        prepared_withheld=prepared_withheld,
    )
    for phase, artifacts in REVIEW_EVIDENCE_ARTIFACTS.items():
        if artifacts.target_artifact_key is None:
            continue
        review = getattr(writer.state, phase)
        if not review.verdict:
            continue
        current_target_digest = getattr(writer.state.artifacts, artifacts.target_artifact_key).digest
        current_report_digest = report_digests[artifacts.report_artifact_name]
        is_current = (
            bool(review.reviewed_target_digest)
            and bool(review.review_report_digest)
            and review.reviewed_target_digest == current_target_digest
            and review.review_report_digest == current_report_digest
        )
        logger.info(
            "workflow.review_evidence_evaluated",
            slug=slug,
            phase=phase,
            outcome="current" if is_current else "stale",
            bound_target_digest=review.reviewed_target_digest,
            current_target_digest=current_target_digest,
            bound_report_digest=review.review_report_digest,
            current_report_digest=current_report_digest,
            caller_session_id=review.caller_session_id,
            reviewed_at=review.reviewed_at,
            resulting_phase=derived.value,
        )
    writer.state.lifecycle_phase = derived
    payload = writer.to_dict()
    if payload != raw_state:
        payload = await writer.commit(todos_db, slug)
        return payload, outstanding
    return raw_state, outstanding


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:
    """Dispatch the current prepare lifecycle step from authoritative state."""
    _ = _commit_writer

    cwd = str(resolve_project_root(cwd))
    todos_db = await get_workflow_store(cwd)

    if slug is None:
        return format_error("TODO_SLUG_REQUIRED", PREPARE_SLUG_REQUIRED_MESSAGE)

    resolved_slug = slug

    # Holder status resolves before the lifecycle-membership guard: a holder
    # slug never matches slug_in_todo (active/icebox only), so checking
    # membership first would reject a childless holder as not-found instead
    # of the ended-group refusal below.
    is_holder_slug = await todos_db.is_structural_group_holder(resolved_slug)

    holder_resolution = await resolve_runnable_holder_children_db(
        todos_db,
        resolved_slug,
        await todos_db.load_deps(),
        mode=HolderResolutionMode.PREPARE,
    )
    if holder_resolution.children:
        instruction = _format_holder_prepare_instruction(
            resolved_slug,
            holder_resolution.children,
            holder_resolution.runnable,
            holder_resolution.reason,
        )
        return format_blocker_resolution(
            resolved_slug,
            instruction,
            blockers=[f"structural holder has grouped children: {', '.join(holder_resolution.children)}"],
        )

    if is_holder_slug:
        return format_error(
            "HOLDER_ENDED",
            f"Holder '{resolved_slug}' has no children — its group has ended. "
            "It is outside the todo lifecycle; nothing further runs against it.",
        )

    if not await todos_db.slug_in_todo(resolved_slug):
        return format_error(
            "TODO_NOT_FOUND",
            MISSING_ACTIVE_TODO_MESSAGE_TEMPLATE.format(slug=resolved_slug),
        )

    for iteration in range(_PREPARE_LOOP_LIMIT):
        state = await todos_db.read_state(resolved_slug)
        if state is None:
            raise RuntimeError(f"Contract violation: no state record for slug {resolved_slug!r}")

        state, outstanding = await _adopt_prepare_phase(todos_db, resolved_slug, state, repo_root=cwd)
        if outstanding:
            logger.info(
                _PREPARED_WITHHELD_LOG,
                slug=resolved_slug,
                pending_shas=[commit.sha for commit in outstanding],
            )
            return format_prepared_withheld(resolved_slug, outstanding)
        writer = StateWriter(state)
        lifecycle = require_lifecycle_phase(writer.state.lifecycle_phase, context=f"next_prepare({resolved_slug})")
        if lifecycle is LifecyclePhase.TASK_PLAN_DRAFTING:
            return format_procedure_load(
                slug=resolved_slug,
                procedure_id=LifecycleProcedure.PREPARE_TASK.value,
                hat=_TASK_PREPARER_HAT,
                expected=_TASK_PREPARER_EXPECTED,
            )
        if lifecycle is LifecyclePhase.TASK_RUNNING:
            return format_error(
                _TASK_RUNNING_ERROR_CODE,
                _TASK_RUNNING_MESSAGE_TEMPLATE.format(slug=resolved_slug),
            )
        phase = (
            _PP.PREPARED
            if lifecycle == LifecyclePhase.PREPARED or is_work_lifecycle_phase(lifecycle)
            else _PP(lifecycle.value)
        )
        logger.info("NEXT_PREPARE_PHASE slug=%s phase=%s iter=%d", resolved_slug, phase.value, iteration)

        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug=resolved_slug,
            cwd=cwd,
            phase=phase,
            state=state,
        )
        if not keep_going:
            return instruction

    instruction = (
        "The prepare state machine could not converge. Inspect the todo state "
        f"via `telec todo show {resolved_slug}` and surface to the user — the lifecycle "
        "cannot self-resolve."
    )
    return format_blocker_resolution(
        resolved_slug,
        instruction,
        blockers=[f"prepare loop exceeded {_PREPARE_LOOP_LIMIT} internal transitions"],
    )


__all__ = ["next_prepare"]
