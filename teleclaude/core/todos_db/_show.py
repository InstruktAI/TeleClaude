"""Assemble the ``telec todo show`` payload from DB state."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict, cast

from teleclaude.constants import WORKTREE_DIR, TodoStatus
from teleclaude.core.next_machine._types import ItemPhase, StateValue
from teleclaude.core.next_machine.artifacts import artifact_name_to_state_key
from teleclaude.core.next_machine.commit_review_stamps import (
    CommitOutcome,
    associated_commit_shas,
    outcomes_from_records,
)
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, require_lifecycle_phase
from teleclaude.core.next_machine.slug_resolution import effective_delivered_slugs_for_dependencies
from teleclaude.types.lifecycle import LIFECYCLE_PHASE_ORDER, TASK_LIFECYCLE_PHASE_ORDER
from teleclaude.types.todo_kind import TodoKind
from teleclaude.types.todos import ClaimStatus, CommitReviewDetail, HoldAuditReason, TodoEventKind, TodoState

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore
    from teleclaude.core.workflow_store.types import ArtifactMetadata, TodoDiagnosticRecord


# Map derived phase value → human-readable phase label for CurrentBlock.phase.
_PHASE_LABEL_OVERRIDES: dict[LifecyclePhase, str] = {
    LifecyclePhase.BUILD_STARTED: "build",
    LifecyclePhase.BUILD_COMPLETE: "build",
    LifecyclePhase.REVIEW_CHANGES_REQUESTED: "review",
    LifecyclePhase.REVIEW_APPROVED: "review",
    LifecyclePhase.FINALIZE_READY: "finalize",
}

_SDLC_DISPLAY_ORDER: tuple[LifecyclePhase, ...] = tuple(
    phase for phase in LIFECYCLE_PHASE_ORDER if phase is not LifecyclePhase.BLOCKED
)

# Derived values where the show payload reports state="done" (phase complete).
_DONE_PHASE_VALUES: frozenset[str] = frozenset(
    {
        LifecyclePhase.PREPARED.value,
        LifecyclePhase.BUILD_COMPLETE.value,
        LifecyclePhase.REVIEW_APPROVED.value,
        LifecyclePhase.FINALIZE_READY.value,
        LifecyclePhase.DELIVERED.value,
    }
)

# Values belonging to the prepare lifecycle for stage classification.
_PREPARE_VALUES: frozenset[str] = frozenset(
    phase.value for phase in LIFECYCLE_PHASE_ORDER[: LIFECYCLE_PHASE_ORDER.index(LifecyclePhase.PREPARED)]
) | frozenset({LifecyclePhase.TASK_PLAN_DRAFTING.value})

_EVENTS_INLINE_LIMIT = 20
_HOLDER_PHASE: Literal["holder"] = "holder"


class TodoShowStage(StrEnum):
    """Stage bucket an in-flight or delivered todo classifies into.

    The sole owner of this closed vocabulary — every stage comparison
    (`derive_active_todo_stage` callers included) references a member here
    rather than inlining one of these strings.
    """

    DELIVERED = "delivered"
    DRAFT = "draft"
    PREPARE = "prepare"
    WORK = "work"


# ── Typed payload shapes ────────────────────────────────────────────────────


class CurrentBlock(TypedDict, total=False):
    """The ``current`` block in the show payload."""

    phase: str
    state: str
    status: str
    round: int


class BlockerEntry(TypedDict, total=False):
    """A single blocker in the ``blocked_by`` list."""

    slug: str
    stage: str
    current: str
    blocked_by: list[BlockerEntry]


class ClaimBlock(TypedDict):
    """The ``claim`` block in the show payload: who holds an active todo's lifecycle claim.

    ``session_id`` names the holder and ``computer`` the computer that answered for it; ``role`` is
    present only where the caller may read the holder's session record; ``unanswered`` names the
    computers that did not answer when none did; ``reason`` says why a claim is undetermined. It is not
    ``state.active_runner``.
    """

    status: ClaimStatus
    session_id: NotRequired[str]
    computer: NotRequired[str]
    role: NotRequired[str]
    unanswered: NotRequired[list[str]]
    reason: NotRequired[str]


class TodoShowPayload(TypedDict, total=False):
    """Lifecycle-bearing todo payload for ``telec todo show``."""

    slug: str
    description: str
    stage: TodoShowStage
    blocked_by: list[BlockerEntry]
    previous: str
    current: CurrentBlock
    next: str
    roadmap: dict[str, StateValue]
    state: dict[str, StateValue]
    approvals: dict[str, StateValue]
    reviews: dict[str, StateValue]
    drift: dict[str, StateValue]
    work: dict[str, StateValue]
    artifact_state: dict[str, dict[str, StateValue]]
    audit: dict[str, StateValue]
    events: list[dict[str, StateValue]] | dict[str, StateValue]
    next_commands: dict[str, str]
    artifacts: list[str]
    artifact_content: dict[str, str]
    claim: ClaimBlock


class HolderShowPayload(TypedDict):
    """Structural holder payload for ``telec todo show``.

    Holders are grouping entries, not lifecycle-bearing todos. This shape
    deliberately has no ``current`` or lifecycle state blocks.
    """

    slug: str
    stage: Literal["holder"]
    roadmap: dict[str, StateValue]
    artifacts: list[str]
    description: NotRequired[str]
    artifact_content: NotRequired[dict[str, str]]


ShowPayload = TodoShowPayload | HolderShowPayload


# ── Derivation helpers ──────────────────────────────────────────────────────


def _project_root_from_db(todos_db: WorkflowStore) -> Path:
    """Return the canonical project root owned by the selected store."""
    return todos_db.project_root


def _worktree_cwd_for(project_root: Path, slug: str) -> str:
    """Return the worktree directory for ``slug`` under the project root."""
    return str(project_root / WORKTREE_DIR / slug)


async def _derive_phase_value(
    state: dict[str, StateValue],
    todos_db: WorkflowStore,
    slug: str,
    worktree_cwd: str,
) -> str:
    """Return the current canonical lifecycle phase value for a slug."""
    _ = todos_db, slug, worktree_cwd
    return require_lifecycle_phase(
        state.get("lifecycle_phase"),
        context=f"assemble_show_payload({slug})",
    ).value


def _derive_stage(current_value: str, *, delivered: bool) -> TodoShowStage:
    """Classify current value into stage bucket (delivered/prepare/work)."""
    if delivered:
        return TodoShowStage.DELIVERED
    if current_value == LifecyclePhase.DRAFT.value:
        return TodoShowStage.DRAFT
    if current_value in _PREPARE_VALUES:
        return TodoShowStage.PREPARE
    return TodoShowStage.WORK


def _phase_label(current_value: str) -> str:
    """Return the show label for a canonical lifecycle value."""
    lifecycle_phase = LifecyclePhase(current_value)
    return _PHASE_LABEL_OVERRIDES.get(lifecycle_phase, lifecycle_phase.value)


async def derive_active_todo_stage(todos_db: WorkflowStore, slug: str, state: dict[str, StateValue]) -> TodoShowStage:
    """Classify an in-flight (non-delivered) todo state into its stage bucket.

    Reuses the same phase/stage derivation that backs the show payload so callers
    that gate on "the prepare stage" (e.g. the prepare-artifact write guard)
    cannot drift from a second definition of the prepare value set.
    """
    project_root = _project_root_from_db(todos_db)
    worktree_cwd = _worktree_cwd_for(project_root, slug)
    current_value = await _derive_phase_value(state, todos_db, slug, worktree_cwd)
    return _derive_stage(current_value, delivered=False)


def _derive_current_block(current_value: str, state: dict[str, StateValue]) -> CurrentBlock:
    """Build the ``current`` block for the payload."""
    phase = _phase_label(current_value)
    done = current_value in _DONE_PHASE_VALUES
    if done:
        current_state = ItemPhase.DONE.value
    elif state.get("phase") == ItemPhase.PENDING.value:
        current_state = ItemPhase.PENDING.value
    else:
        current_state = ItemPhase.IN_PROGRESS.value

    block = CurrentBlock(phase=phase, state=current_state)

    if current_value == LifecyclePhase.REVIEW_APPROVED.value:
        block["status"] = "approved"
    elif current_value == LifecyclePhase.REVIEW_CHANGES_REQUESTED.value:
        block["status"] = "changes_requested"

    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    review_round = build_review.get("round", 0)
    if isinstance(review_round, int) and review_round > 0:
        block["round"] = review_round

    return block


def _derive_todo_block(
    row: TodoDiagnosticRecord | None,
    deps: dict[str, list[str]],
    slug: str,
) -> dict[str, StateValue]:
    """Project the complete persisted todo row for ``slug``, plus derived deps."""
    block: dict[str, StateValue] = {"deps": cast(StateValue, deps.get(slug, []))}
    if row is None:
        return block

    block.update(cast(dict[str, StateValue], dict(row)))
    return block


def _derive_state_block(state_model: TodoState) -> dict[str, StateValue]:
    """Project authoritative lifecycle state facts."""
    hold_audit = state_model.hold_audit.model_dump()
    if hold_audit["reason"] in {
        HoldAuditReason.LEGACY_UPDATE_COMMAND,
        HoldAuditReason.LEGACY_CREATE_COMMAND,
    }:
        hold_audit["reason"] = HoldAuditReason.UNKNOWN.value
    return {
        "schema_version": state_model.schema_version,
        "kind": state_model.kind,
        "phase": state_model.phase,
        "lifecycle_phase": state_model.lifecycle_phase,
        "integration_phase": state_model.integration_phase,
        "hold": state_model.hold,
        "hold_audit": hold_audit,
        "active_runner": state_model.active_runner,
        "deferrals_processed": state_model.deferrals_processed,
    }


def _derive_approvals_block(state_model: TodoState) -> dict[str, StateValue]:
    """Project prepare approvals, skips, and drift stamps."""
    return cast(dict[str, StateValue], state_model.approvals.model_dump())


def _derive_reviews_block(
    state_model: TodoState,
    commit_outcomes: dict[str, CommitOutcome],
) -> dict[str, StateValue]:
    """Project prepare and build review verdict state, and each commit's current review outcome."""
    return {
        "prd_review": state_model.prd_review.model_dump(),
        "requirements_review": state_model.requirements_review.model_dump(),
        "architecture_review": state_model.architecture_review.model_dump(),
        "plan_review": state_model.plan_review.model_dump(),
        "build_review": state_model.build_review.model_dump(),
        "commit_reviews": {
            sha: {
                "verdict": outcome.verdict.value,
                "stamped_by": outcome.stamped_by,
                "stamped_at": outcome.stamped_at,
                "reason": outcome.reason,
            }
            for sha, outcome in commit_outcomes.items()
        },
    }


def _derive_drift_block(state_model: TodoState) -> dict[str, StateValue]:
    """Project stored drift review stamps."""
    return {
        artifact: cast(StateValue, stamp.model_dump())
        for artifact, stamp in state_model.approvals.drift_reviewed.items()
    }


def _derive_work_block(state_model: TodoState) -> dict[str, StateValue]:
    """Project work-phase progress facts."""
    return {
        "build_start_base_sha": state_model.build_start_base_sha,
        "build_plan_digest": state_model.build_plan_digest,
        "build_completed_at": state_model.build_completed_at,
        "build_gate_claim_at": state_model.build_gate_claim_at,
        "finalize": state_model.finalize.model_dump(),
    }


def _derive_artifact_state_block(
    state_model: TodoState,
    artifact_rows: list[ArtifactMetadata],
) -> dict[str, dict[str, StateValue]]:
    """Project per-artifact provenance metadata without body content."""
    artifacts = state_model.artifacts
    block: dict[str, dict[str, StateValue]] = {}
    for artifact_row in artifact_rows:
        artifact_name = artifact_row["name"]
        state_key = artifact_name_to_state_key(artifact_name)
        entry = getattr(artifacts, state_key, None)
        metadata: dict[str, StateValue]
        if entry is not None:
            metadata = cast(dict[str, StateValue], dict(entry))
            if not metadata.get("digest"):
                metadata["digest"] = artifact_row["digest"]
            if not metadata.get("produced_at"):
                metadata["produced_at"] = artifact_row["updated_at"]
        else:
            metadata = {
                "digest": artifact_row["digest"],
                "produced_at": artifact_row["updated_at"],
                "upstream_digests": {},
                "codebase_sha_at_write": "",
                "referenced_paths": [],
                "owned_snippet_digests": {},
                "referenced_snippet_digests": {},
                "async_provenance_complete": False,
            }
        metadata["updated_by"] = artifact_row["updated_by"]
        block[artifact_name] = metadata
    return block


def _derive_audit_block(state_model: TodoState) -> dict[str, StateValue]:
    """Project bounded typed audit state."""
    return cast(dict[str, StateValue], state_model.audit.model_dump())


def _derive_events_block(state_model: TodoState) -> list[dict[str, StateValue]] | dict[str, StateValue]:
    """Project events inline when short, otherwise count plus bounded tail."""
    events = [cast(dict[str, StateValue], event.model_dump()) for event in state_model.events]
    if len(events) <= _EVENTS_INLINE_LIMIT:
        return events
    return cast(dict[str, StateValue], {"count": len(events), "tail": events[-_EVENTS_INLINE_LIMIT:]})


def _derive_next_commands_block(slug: str) -> dict[str, str]:
    """Project machine-readable follow-up command hints."""
    return {
        "read_artifact": f"telec todo artifacts read {slug} <artifact>",
        "show_with_bodies": f"telec todo show {slug} --include-artifact-content",
    }


def _navigation_order(kind: str) -> tuple[LifecyclePhase, ...]:
    """Return the canonical display progression for a kind-bearing todo."""
    if kind == TodoKind.TASK:
        return tuple(TASK_LIFECYCLE_PHASE_ORDER)
    return _SDLC_DISPLAY_ORDER


def _derive_previous(current_value: str, kind: str) -> str | None:
    """Return the label of the phase immediately before ``current_value``."""
    try:
        current_phase = LifecyclePhase(current_value)
        idx = _navigation_order(kind).index(current_phase)
    except ValueError:
        return None
    if idx == 0:
        return None
    return _phase_label(_navigation_order(kind)[idx - 1].value)


def _derive_next(current_value: str, kind: str) -> str | None:
    """Return the label of the phase immediately after ``current_value`` when done."""
    if current_value not in _DONE_PHASE_VALUES:
        return None
    try:
        current_phase = LifecyclePhase(current_value)
        order = _navigation_order(kind)
        idx = order.index(current_phase)
    except ValueError:
        return None
    if idx >= len(order) - 1:
        return None
    return _phase_label(order[idx + 1].value)


async def _build_blocked_by(
    slug: str,
    deps: dict[str, list[str]],
    delivered_slugs: set[str],
    all_states: dict[str, dict[str, StateValue]],
    todos_db: WorkflowStore,
    project_root: Path,
    *,
    visited: set[str] | None = None,
) -> list[BlockerEntry] | None:
    """Build transitive blocked_by graph for undelivered deps."""
    if visited is None:
        visited = set()
    visited.add(slug)

    direct_deps = deps.get(slug, [])
    if not direct_deps:
        return None

    blockers: list[BlockerEntry] = []
    for dep_slug in direct_deps:
        if dep_slug in delivered_slugs:
            continue

        blocker = BlockerEntry(slug=dep_slug)

        dep_state = all_states.get(dep_slug)
        if dep_state is not None:
            dep_worktree = _worktree_cwd_for(project_root, dep_slug)
            dep_current = await _derive_phase_value(dep_state, todos_db, dep_slug, dep_worktree)
            blocker["stage"] = _derive_stage(dep_current, delivered=False)
            blocker["current"] = dep_current

        if dep_slug not in visited:
            nested = await _build_blocked_by(
                dep_slug,
                deps,
                delivered_slugs,
                all_states,
                todos_db,
                project_root,
                visited=visited,
            )
            if nested:
                blocker["blocked_by"] = nested

        blockers.append(blocker)

    return blockers if blockers else None


async def _find_todo_row(todos_db: WorkflowStore, slug: str) -> TodoDiagnosticRecord | None:
    """Return the active/icebox/delivered/holder todo row that backs the show payload."""
    return await todos_db.read_todo_diagnostic_record(slug)


async def _holder_children(todos_db: WorkflowStore, holder_id: str) -> list[str]:
    """Return non-removed direct group children for a structural holder id."""
    entries = await todos_db.list_todo(include_icebox=True, include_delivered=True)
    children = [
        str(entry["slug"])
        for entry in entries
        if entry.get("group_id") == holder_id and entry.get("status") != "removed"
    ]
    return sorted(children)


async def _resolve_holder_label(todos_db: WorkflowStore, group_id: str | None) -> str | None:
    """Resolve a child's ``group_id`` to its holder's current slug, or None.

    A live join at request time — never a stored copy — so a holder rename
    is reflected without touching any child row.
    """
    if not group_id:
        return None
    rows = await todos_db.list_todo(include_holders=True)
    holder = next((row for row in rows if row["id"] == group_id), None)
    return holder["slug"] if holder is not None and holder["status"] == TodoStatus.HOLDER.value else None


# ── Main assembler ──────────────────────────────────────────────────────────


async def _lookup_removed_state(todos_db: WorkflowStore, slug: str) -> tuple[dict[str, StateValue], str] | None:
    """Resolve slug to its most recently removed row and return state plus durable id."""
    removed_entries = await todos_db.list_todo(include_removed=True, removed_only=True)
    matches = [r for r in removed_entries if r["slug"] == slug]
    if matches:
        # Removed-only entries arrive newest-first by removed_at.
        todo_id = matches[0]["id"]
        state = await todos_db.read_state_by_id(todo_id)
        if state is not None:
            return state, todo_id
    return None


async def _resolve_show_state(
    todos_db: WorkflowStore,
    slug: str,
    *,
    include_removed: bool,
    initial_state: dict[str, StateValue] | None,
) -> tuple[dict[str, StateValue] | None, bool, bool, str | None]:
    """Resolve the lifecycle state backing a non-holder show payload."""
    if initial_state is not None:
        return initial_state, False, False, None

    if include_removed:
        removed = await _lookup_removed_state(todos_db, slug)
        if removed is not None:
            removed_state, removed_id = removed
            return removed_state, False, True, removed_id

    delivered_state = await todos_db.read_state_delivered(slug)
    if delivered_state is not None:
        return delivered_state, True, False, None

    return None, False, False, None


async def _assemble_holder_payload(
    todos_db: WorkflowStore,
    slug: str,
    *,
    todo_row: TodoDiagnosticRecord,
    holder_children: list[str],
    include_artifact_content: bool,
) -> HolderShowPayload:
    """Assemble a structural payload for a holder that intentionally has no state."""
    deps = await todos_db.load_deps()
    todo_block = _derive_todo_block(todo_row, deps, slug)
    todo_block["children"] = cast(StateValue, holder_children)
    artifact_rows = await todos_db.artifact_metadata(slug)
    artifact_names = [row["name"] for row in artifact_rows]
    payload = HolderShowPayload(
        slug=slug,
        stage=_HOLDER_PHASE,
        roadmap=todo_block,
        artifacts=list(artifact_names),
    )
    description = todo_row.get("description")
    if description:
        payload["description"] = description
    if include_artifact_content:
        artifact_content: dict[str, str] = {}
        for name in artifact_names:
            artifact_content[name] = await todos_db.read_artifact(slug, name)
        payload["artifact_content"] = artifact_content
    return payload


def payload_is_active_todo(payload: ShowPayload) -> bool:
    """Whether the payload shows a live lifecycle todo, the only kind a driver start is admitted for."""
    if payload.get("stage") == _HOLDER_PHASE:
        return False
    return payload.get("roadmap", {}).get("status") == TodoStatus.ACTIVE.value


async def assemble_show_payload(
    todos_db: WorkflowStore,
    slug: str,
    include_removed: bool = False,
    *,
    include_artifact_content: bool = False,
) -> ShowPayload | None:
    """Assemble the full show payload for a slug. Returns None if not found."""
    todo_row = await _find_todo_row(todos_db, slug)
    if todo_row is not None and todo_row["status"] == TodoStatus.HOLDER.value:
        holder_children = await _holder_children(todos_db, todo_row["id"])
        if not holder_children:
            # A childless holder is genuinely outside the todo surface — the
            # show/update-404 scenario this model exists to make unrepresentable
            # is precisely this row answering as if it were still a todo.
            return None
        return await _assemble_holder_payload(
            todos_db,
            slug,
            todo_row=todo_row,
            holder_children=holder_children,
            include_artifact_content=include_artifact_content,
        )

    state = await todos_db.read_state(slug)
    state, is_delivered, is_removed, removed_id = await _resolve_show_state(
        todos_db,
        slug,
        include_removed=include_removed,
        initial_state=state,
    )
    if state is None:
        return None

    state_model = TodoState.model_validate(state)
    project_root = _project_root_from_db(todos_db)
    worktree_cwd = _worktree_cwd_for(project_root, slug)
    current_value = await _derive_phase_value(state, todos_db, slug, worktree_cwd)

    delivered_slugs = await effective_delivered_slugs_for_dependencies(todos_db)

    todo_entries = await todos_db.list_todo(
        include_icebox=True, include_delivered=True, include_removed=include_removed
    )
    description: str | None = None
    for entry in todo_entries:
        if entry["slug"] == slug:
            if is_removed and entry["status"] != "removed":
                continue
            description = entry.get("description")
            break

    payload = TodoShowPayload(slug=slug, stage=_derive_stage(current_value, delivered=is_delivered))

    if description:
        payload["description"] = description

    deps = await todos_db.load_deps()
    todo_block = _derive_todo_block(todo_row, deps, slug)
    if todo_row is not None:
        # Joined from the holder's row at request time — never a stored copy
        # on the child — so a holder rename needs no child-side update.
        todo_block["group_slug"] = cast(StateValue, await _resolve_holder_label(todos_db, todo_row["group_id"]))
    payload["roadmap"] = todo_block
    payload["state"] = _derive_state_block(state_model)
    payload["approvals"] = _derive_approvals_block(state_model)
    event_shas = tuple(
        str(event.details[CommitReviewDetail.SHA])
        for event in state_model.events
        if event.kind == TodoEventKind.COMMIT_REVIEW_STAMP
        and isinstance(event.details.get(CommitReviewDetail.SHA), str)
    )
    stamped_shas = tuple(dict.fromkeys((*event_shas, *associated_commit_shas(str(project_root), slug))))
    commit_outcomes = outcomes_from_records(await todos_db.commit_review_records(stamped_shas))
    payload["reviews"] = _derive_reviews_block(state_model, commit_outcomes)
    payload["drift"] = _derive_drift_block(state_model)
    payload["work"] = _derive_work_block(state_model)
    payload["audit"] = _derive_audit_block(state_model)
    payload["events"] = _derive_events_block(state_model)
    payload["next_commands"] = _derive_next_commands_block(slug)

    if deps.get(slug):
        all_dep_slugs: set[str] = set()
        _collect_dep_slugs(slug, deps, all_dep_slugs)
        all_states: dict[str, dict[str, StateValue]] = {}
        for dep_slug in all_dep_slugs:
            dep_state = await todos_db.read_state(dep_slug)
            if dep_state:
                all_states[dep_slug] = dep_state

        blocked_by = await _build_blocked_by(
            slug,
            deps,
            delivered_slugs,
            all_states,
            todos_db,
            project_root,
        )
        if blocked_by:
            payload["blocked_by"] = blocked_by

    previous = _derive_previous(current_value, state_model.kind)
    if previous:
        payload["previous"] = previous

    payload["current"] = _derive_current_block(current_value, state)

    next_phase = _derive_next(current_value, state_model.kind)
    if next_phase:
        payload["next"] = next_phase

    artifact_rows = (
        await todos_db.artifact_metadata_by_id(removed_id)
        if is_removed and removed_id is not None
        else await todos_db.artifact_metadata(slug)
    )
    artifact_names = [row["name"] for row in artifact_rows]
    payload["artifacts"] = list(artifact_names)
    payload["artifact_state"] = _derive_artifact_state_block(state_model, artifact_rows)
    if include_artifact_content:
        artifact_content: dict[str, str] = {}
        for name in artifact_names:
            artifact_content[name] = (
                await todos_db.read_artifact_by_id(removed_id, name)
                if is_removed and removed_id is not None
                else await todos_db.read_artifact(slug, name)
            )
        payload["artifact_content"] = artifact_content

    return payload


def _collect_dep_slugs(
    slug: str,
    deps: dict[str, list[str]],
    result: set[str],
) -> None:
    """Recursively collect all dependency slugs."""
    for dep in deps.get(slug, []):
        if dep not in result:
            result.add(dep)
            _collect_dep_slugs(dep, deps, result)
