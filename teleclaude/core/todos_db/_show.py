"""Assemble the ``telec todo show`` payload from DB state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict, cast

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import ItemPhase, PreparePhase, StateValue, WorkPhase
from teleclaude.core.next_machine.artifacts import artifact_name_to_state_key
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, require_lifecycle_phase
from teleclaude.core.next_machine.slug_resolution import effective_delivered_slugs_for_dependencies
from teleclaude.core.todos_db._models import TodoStateModel
from teleclaude.core.todos_db._upcycle import upcycle_state_dict
from teleclaude.types.todos import TodoState

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
    from teleclaude.core.todos_db._models import Todo
    from teleclaude.core.todos_db._rows import ArtifactMetadataRow


# Map derived phase value → human-readable phase label for CurrentBlock.phase.
_CLASSIFY_PHASE = "classify"
_PHASE_LABEL: dict[str, str] = {
    _CLASSIFY_PHASE: _CLASSIFY_PHASE,
    LifecyclePhase.DRAFT.value: "draft",
    PreparePhase.PRD_DRAFTING.value: "prd_drafting",
    PreparePhase.PRD_HUMAN_APPROVAL.value: "prd_human_approval",
    PreparePhase.ARCHITECTURE_DRAFTING.value: "architecture_drafting",
    PreparePhase.ARCHITECTURE_REVIEW.value: "architecture_review",
    PreparePhase.DIAGNOSE.value: "diagnose",
    PreparePhase.PLAN_DRAFTING.value: "plan_drafting",
    PreparePhase.PLAN_REVIEW.value: "plan_review",
    PreparePhase.PREPARED.value: "prepared",
    WorkPhase.BUILD_STARTED.value: "build",
    WorkPhase.BUILD_COMPLETE.value: "build",
    WorkPhase.REVIEW_CHANGES_REQUESTED.value: "review",
    WorkPhase.REVIEW_APPROVED.value: "review",
    WorkPhase.FINALIZE_READY.value: "finalize",
}

# Ordered list of derived phase values for previous/next navigation.
_LIFECYCLE_ORDER: list[str] = [
    _CLASSIFY_PHASE,
    LifecyclePhase.DRAFT.value,
    PreparePhase.PRD_DRAFTING.value,
    PreparePhase.PRD_HUMAN_APPROVAL.value,
    PreparePhase.ARCHITECTURE_DRAFTING.value,
    PreparePhase.ARCHITECTURE_REVIEW.value,
    PreparePhase.DIAGNOSE.value,
    PreparePhase.PLAN_DRAFTING.value,
    PreparePhase.PLAN_REVIEW.value,
    PreparePhase.PREPARED.value,
    WorkPhase.BUILD_STARTED.value,
    WorkPhase.BUILD_COMPLETE.value,
    WorkPhase.REVIEW_CHANGES_REQUESTED.value,
    WorkPhase.REVIEW_APPROVED.value,
    WorkPhase.FINALIZE_READY.value,
]

# Derived values where the show payload reports state="done" (phase complete).
_DONE_PHASE_VALUES: frozenset[str] = frozenset(
    {
        PreparePhase.PREPARED.value,
        WorkPhase.BUILD_COMPLETE.value,
        WorkPhase.REVIEW_APPROVED.value,
        WorkPhase.FINALIZE_READY.value,
    }
)

# Values belonging to the prepare lifecycle for stage classification.
_PREPARE_VALUES: frozenset[str] = frozenset(
    {
        LifecyclePhase.DRAFT.value,
        _CLASSIFY_PHASE,
        PreparePhase.PRD_DRAFTING.value,
        PreparePhase.PRD_HUMAN_APPROVAL.value,
        PreparePhase.ARCHITECTURE_DRAFTING.value,
        PreparePhase.ARCHITECTURE_REVIEW.value,
        PreparePhase.DIAGNOSE.value,
        PreparePhase.PLAN_DRAFTING.value,
        PreparePhase.PLAN_REVIEW.value,
        PreparePhase.BLOCKED.value,
    }
)

_EVENTS_INLINE_LIMIT = 20
_HOLDER_PHASE: Literal["holder"] = "holder"
TodoShowStage = Literal["delivered", "draft", "prepare", "work"]


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


def _project_root_from_db(todos_db: TodosDb) -> Path:
    """Return the project root directory inferred from a TodosDb instance."""
    db_path = todos_db._db_path
    return db_path.parent.parent if db_path.parent.name == ".teleclaude" else db_path.parent


def _worktree_cwd_for(project_root: Path, slug: str) -> str:
    """Return the worktree directory for ``slug`` under the project root."""
    return str(project_root / WORKTREE_DIR / slug)


async def _derive_phase_value(
    state: dict[str, StateValue],
    todos_db: TodosDb,
    slug: str,
    worktree_cwd: str,
) -> str:
    """Return the current canonical lifecycle phase value for a slug."""
    _ = todos_db, slug, worktree_cwd
    if state.get("kind") is None and state.get("lifecycle_phase") is None:
        return _CLASSIFY_PHASE
    return require_lifecycle_phase(
        state.get("lifecycle_phase"),
        context=f"assemble_show_payload({slug})",
    ).value


def _derive_stage(current_value: str, *, delivered: bool) -> TodoShowStage:
    """Classify current value into stage bucket (delivered/prepare/work)."""
    if delivered:
        return "delivered"
    if current_value == LifecyclePhase.DRAFT.value:
        return "draft"
    if current_value in _PREPARE_VALUES:
        return "prepare"
    return "work"


def _derive_current_block(current_value: str, state: dict[str, StateValue]) -> CurrentBlock:
    """Build the ``current`` block for the payload."""
    phase = _PHASE_LABEL.get(current_value, current_value)
    done = current_value in _DONE_PHASE_VALUES
    if done:
        current_state = ItemPhase.DONE.value
    elif state.get("phase") == ItemPhase.PENDING.value:
        current_state = ItemPhase.PENDING.value
    else:
        current_state = ItemPhase.IN_PROGRESS.value

    block = CurrentBlock(phase=phase, state=current_state)

    if current_value == WorkPhase.REVIEW_APPROVED.value:
        block["status"] = "approved"
    elif current_value == WorkPhase.REVIEW_CHANGES_REQUESTED.value:
        block["status"] = "changes_requested"

    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    review_round = build_review.get("round", 0)
    if isinstance(review_round, int) and review_round > 0:
        block["round"] = review_round

    return block


def _derive_todo_block(row: Todo | None, deps: dict[str, list[str]], slug: str) -> dict[str, StateValue]:
    """Project persisted todo facts for ``slug``."""
    block: dict[str, StateValue] = {"deps": cast(StateValue, deps.get(slug, []))}
    if row is None:
        return block

    block.update(
        {
            "status": row.status,
            "ready_since": row.ready_since,
            "group_slug": row.group_slug,
            "description": row.description,
            "delivered_at": row.delivered_at,
            "delivered_commit": row.delivered_commit,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )
    return block


def _derive_state_block(state_model: TodoState) -> dict[str, StateValue]:
    """Project authoritative lifecycle state facts."""
    return {
        "schema_version": state_model.schema_version,
        "kind": state_model.kind,
        "phase": state_model.phase,
        "lifecycle_phase": state_model.lifecycle_phase,
        "integration_phase": state_model.integration_phase,
        "hold": state_model.hold,
        "hold_audit": state_model.hold_audit.model_dump(),
        "active_runner": state_model.active_runner,
        "deferrals_processed": state_model.deferrals_processed,
    }


def _derive_approvals_block(state_model: TodoState) -> dict[str, StateValue]:
    """Project prepare approvals, skips, and drift stamps."""
    return cast(dict[str, StateValue], state_model.approvals.model_dump())


def _derive_reviews_block(state_model: TodoState) -> dict[str, StateValue]:
    """Project prepare and build review verdict state."""
    return {
        "requirements_review": state_model.requirements_review.model_dump(),
        "architecture_review": state_model.architecture_review.model_dump(),
        "plan_review": state_model.plan_review.model_dump(),
        "build_review": state_model.build_review.model_dump(),
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
        "build_completed_at": state_model.build_completed_at,
        "build_gate_claim_at": state_model.build_gate_claim_at,
        "finalize": state_model.finalize.model_dump(),
    }


def _derive_artifact_state_block(
    state_model: TodoState,
    artifact_rows: list[ArtifactMetadataRow],
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
            metadata = cast(dict[str, StateValue], entry.model_dump())
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
                "dependency_set_at_write": [],
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


def _derive_previous(current_value: str) -> str | None:
    """Return the label of the phase immediately before ``current_value``."""
    try:
        idx = _LIFECYCLE_ORDER.index(current_value)
    except ValueError:
        return None
    if idx == 0:
        return None
    prev_value = _LIFECYCLE_ORDER[idx - 1]
    return _PHASE_LABEL.get(prev_value, prev_value)


def _derive_next(current_value: str) -> str | None:
    """Return the label of the phase immediately after ``current_value`` when done."""
    if current_value not in _DONE_PHASE_VALUES:
        return None
    try:
        idx = _LIFECYCLE_ORDER.index(current_value)
    except ValueError:
        return None
    if idx >= len(_LIFECYCLE_ORDER) - 1:
        return None
    next_value = _LIFECYCLE_ORDER[idx + 1]
    return _PHASE_LABEL.get(next_value, next_value)


async def _build_blocked_by(
    slug: str,
    deps: dict[str, list[str]],
    delivered_slugs: set[str],
    all_states: dict[str, dict[str, StateValue]],
    todos_db: TodosDb,
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


async def _find_todo_row(todos_db: TodosDb, slug: str) -> Todo | None:
    """Return the active/icebox/delivered todo row that backs the show payload."""
    rows = await todos_db._list_todo_models(include_icebox=True, include_delivered=True)
    for row in rows:
        if row.slug == slug:
            return row
    return None


async def _holder_children(todos_db: TodosDb, slug: str) -> list[str]:
    """Return non-removed direct group children for a structural holder slug."""
    entries = await todos_db.list_todo(include_icebox=True, include_delivered=True)
    children = [
        str(entry["slug"])
        for entry in entries
        if entry.get("group_slug") == slug and entry.get("slug") != slug and entry.get("status") != "removed"
    ]
    return sorted(children)


# ── Main assembler ──────────────────────────────────────────────────────────


async def _lookup_removed_state(todos_db: TodosDb, slug: str) -> dict[str, StateValue] | None:
    """Resolve slug against removed rows and return state if uniquely matched."""
    removed_entries = await todos_db.list_todo(include_removed=True, removed_only=True)
    matches = [r for r in removed_entries if r["slug"] == slug]
    if len(matches) == 1:
        todo_id = matches[0]["id"]
        async with todos_db._session() as session:
            state_model = await session.get(TodoStateModel, todo_id)
            if state_model is not None:
                return upcycle_state_dict(json.loads(state_model.state))
    return None


async def _resolve_show_state(
    todos_db: TodosDb,
    slug: str,
    *,
    include_removed: bool,
    initial_state: dict[str, StateValue] | None,
) -> tuple[dict[str, StateValue] | None, bool, bool]:
    """Resolve the lifecycle state backing a non-holder show payload."""
    if initial_state is not None:
        return initial_state, False, False

    if include_removed:
        removed_state = await _lookup_removed_state(todos_db, slug)
        if removed_state is not None:
            return removed_state, False, True

    delivered_state = await todos_db.read_state_delivered(slug)
    if delivered_state is not None:
        return delivered_state, True, False

    return None, False, False


async def _assemble_holder_payload(
    todos_db: TodosDb,
    slug: str,
    *,
    todo_row: Todo,
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
    if todo_row.description:
        payload["description"] = todo_row.description
    if include_artifact_content:
        artifact_content: dict[str, str] = {}
        for name in artifact_names:
            artifact_content[name] = await todos_db.read_artifact(slug, name)
        payload["artifact_content"] = artifact_content
    return payload


async def assemble_show_payload(
    todos_db: TodosDb,
    slug: str,
    include_removed: bool = False,
    *,
    include_artifact_content: bool = False,
) -> ShowPayload | None:
    """Assemble the full show payload for a slug. Returns None if not found."""
    todo_row = await _find_todo_row(todos_db, slug)
    state = await todos_db.read_state(slug)
    if state is None and todo_row is not None:
        holder_children = await _holder_children(todos_db, slug)
        if holder_children:
            return await _assemble_holder_payload(
                todos_db,
                slug,
                todo_row=todo_row,
                holder_children=holder_children,
                include_artifact_content=include_artifact_content,
            )

    state, is_delivered, is_removed = await _resolve_show_state(
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
    payload["roadmap"] = _derive_todo_block(todo_row, deps, slug)
    payload["state"] = _derive_state_block(state_model)
    payload["approvals"] = _derive_approvals_block(state_model)
    payload["reviews"] = _derive_reviews_block(state_model)
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

    previous = _derive_previous(current_value)
    if previous:
        payload["previous"] = previous

    payload["current"] = _derive_current_block(current_value, state)

    next_phase = _derive_next(current_value)
    if next_phase:
        payload["next"] = next_phase

    artifact_rows = await todos_db.artifact_metadata(slug)
    artifact_names = [row["name"] for row in artifact_rows]
    payload["artifacts"] = list(artifact_names)
    payload["artifact_state"] = _derive_artifact_state_block(state_model, artifact_rows)
    if include_artifact_content:
        artifact_content: dict[str, str] = {}
        for name in artifact_names:
            artifact_content[name] = await todos_db.read_artifact(slug, name)
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
