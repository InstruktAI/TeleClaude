"""Prepare entry responses outside the item machine: explicit slugs, holders and tasks."""

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
from teleclaude.core.next_machine.commit_review_stamps import OutstandingCommit, outstanding_claim_period_commits
from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    adopt_prepare_handoff_phase,
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
from teleclaude.core.next_machine.prepare_step_support import prepare_step_prepared
from teleclaude.core.next_machine.provenance import (
    read_owned_snippet_digests,
    read_referenced_snippet_digests,
    refresh_referenced_paths,
    sync_artifact_provenance,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.session_identity import get_session_id
from teleclaude.snippet_validation import snippet_body_digest_for
from teleclaude.types.state_value import StateValue

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

from teleclaude.core.next_machine.lanes import LifecycleProcedure
from teleclaude.core.next_machine.slug_resolution import (
    HolderResolutionMode,
    HolderResolutionReason,
    resolve_runnable_holder_children_db,
)
from teleclaude.core.workflow_store.store import get_workflow_store

logger = get_logger(__name__)

_PREPARED_WITHHELD_LOG = "prepared_withheld"
_MISSING_STATE_TEMPLATE = "Contract violation: no state record for slug {slug!r}"
_ITEM_ENTRY_REQUIRED_TEMPLATE = "Item {slug!r} must enter preparation through the workflow machine"
_LIFECYCLE_PHASE_FIELD = "lifecycle_phase"
_TASK_PREPARE_CONTEXT_TEMPLATE = "next_prepare({slug})"
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
    """Load current artifact presence into state before handoff adoption."""
    for state_key, artifact_name in _ADOPTION_ARTIFACTS:
        entry = getattr(writer.state.artifacts, state_key)
        if not await todos_db.artifact_exists(slug, artifact_name):
            continue
        artifact_body = await todos_db.read_artifact(slug, artifact_name)
        snippet_digest_fn = snippet_body_digest_for(repo_root)
        if entry.digest and entry.async_provenance_complete:
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


async def _adopt_task_phase(
    todos_db: WorkflowStore,
    slug: str,
    raw_state: dict[str, StateValue],
    *,
    repo_root: str,
) -> tuple[dict[str, StateValue], list[OutstandingCommit]]:
    """Adopt only the task lane phase and retain its existing reviewed-commit handoff.

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
    derived = adopt_prepare_handoff_phase(
        writer.state,
        repo_root=repo_root,
        report_digests={},
        artifact_write_timestamps={},
        prepared_withheld=prepared_withheld,
    )
    writer.state.lifecycle_phase = derived
    payload = writer.to_dict()
    if payload != raw_state:
        payload = await writer.commit(todos_db, slug)
        return payload, outstanding
    return raw_state, outstanding


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:
    """Answer a holder, missing-slug or task request; ordinary items use the workflow entry verb."""
    _ = db

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

    state = await todos_db.read_state(resolved_slug)
    if state is None:
        raise RuntimeError(_MISSING_STATE_TEMPLATE.format(slug=resolved_slug))
    writer = StateWriter(state)
    if writer.state.kind != KIND_TASK:
        raise ValueError(_ITEM_ENTRY_REQUIRED_TEMPLATE.format(slug=resolved_slug))
    if writer.state.lifecycle_phase is LifecyclePhase.TASK_RUNNING:
        return format_error(
            _TASK_RUNNING_ERROR_CODE,
            _TASK_RUNNING_MESSAGE_TEMPLATE.format(slug=resolved_slug),
        )
    state, outstanding = await _adopt_task_phase(todos_db, resolved_slug, state, repo_root=cwd)
    if outstanding:
        logger.info(
            _PREPARED_WITHHELD_LOG,
            slug=resolved_slug,
            pending_shas=[commit.sha for commit in outstanding],
        )
        return format_prepared_withheld(resolved_slug, outstanding)
    lifecycle = require_lifecycle_phase(
        state.get(_LIFECYCLE_PHASE_FIELD), context=_TASK_PREPARE_CONTEXT_TEMPLATE.format(slug=resolved_slug)
    )
    if lifecycle is LifecyclePhase.TASK_PLAN_DRAFTING:
        return format_procedure_load(
            slug=resolved_slug,
            procedure_id=LifecycleProcedure.PREPARE_TASK.value,
            hat=_TASK_PREPARER_HAT,
            expected=_TASK_PREPARER_EXPECTED,
        )
    _, instruction = await prepare_step_prepared(db, todos_db, resolved_slug, project_root=cwd)
    return instruction


__all__ = ["next_prepare"]
