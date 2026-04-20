"""Assemble the ``telec todo show`` payload from DB state."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import PreparePhase, StateValue, WorkPhase
from teleclaude.core.next_machine.phase_derivation import derive_prepare_phase, derive_work_phase

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


# Map derived phase value → human-readable phase label for CurrentBlock.phase.
_PHASE_LABEL: dict[str, str] = {
    PreparePhase.INPUT_ASSESSMENT.value: "input_assessment",
    PreparePhase.TRIANGULATION.value: "triangulation",
    PreparePhase.REQUIREMENTS_REVIEW.value: "requirements_review",
    PreparePhase.TEST_SPEC_BUILD.value: "test_spec_build",
    PreparePhase.TEST_SPEC_REVIEW.value: "test_spec_review",
    PreparePhase.PLAN_DRAFTING.value: "plan_drafting",
    PreparePhase.PLAN_REVIEW.value: "plan_review",
    PreparePhase.GATE.value: "gate",
    PreparePhase.GROUNDING_CHECK.value: "grounding_check",
    PreparePhase.RE_GROUNDING.value: "re_grounding",
    PreparePhase.PREPARED.value: "prepared",
    WorkPhase.BUILD_STARTED.value: "build",
    WorkPhase.BUILD_COMPLETE.value: "build",
    WorkPhase.REVIEW_CHANGES_REQUESTED.value: "review",
    WorkPhase.REVIEW_APPROVED.value: "review",
    WorkPhase.FINALIZE_READY.value: "finalize",
    WorkPhase.HANDED_OFF.value: "finalize",
}

# Ordered list of derived phase values for previous/next navigation.
_LIFECYCLE_ORDER: list[str] = [
    PreparePhase.INPUT_ASSESSMENT.value,
    PreparePhase.REQUIREMENTS_REVIEW.value,
    PreparePhase.TEST_SPEC_BUILD.value,
    PreparePhase.TEST_SPEC_REVIEW.value,
    PreparePhase.PLAN_DRAFTING.value,
    PreparePhase.PLAN_REVIEW.value,
    PreparePhase.GATE.value,
    PreparePhase.GROUNDING_CHECK.value,
    PreparePhase.PREPARED.value,
    WorkPhase.BUILD_STARTED.value,
    WorkPhase.BUILD_COMPLETE.value,
    WorkPhase.REVIEW_CHANGES_REQUESTED.value,
    WorkPhase.REVIEW_APPROVED.value,
    WorkPhase.FINALIZE_READY.value,
    WorkPhase.HANDED_OFF.value,
]

# Derived values where the show payload reports state="done" (phase complete).
_DONE_PHASE_VALUES: frozenset[str] = frozenset(
    {
        PreparePhase.PREPARED.value,
        WorkPhase.BUILD_COMPLETE.value,
        WorkPhase.REVIEW_APPROVED.value,
        WorkPhase.HANDED_OFF.value,
    }
)

# Values belonging to the prepare lifecycle for stage classification.
_PREPARE_VALUES: frozenset[str] = frozenset(
    {
        PreparePhase.INPUT_ASSESSMENT.value,
        PreparePhase.TRIANGULATION.value,
        PreparePhase.REQUIREMENTS_REVIEW.value,
        PreparePhase.TEST_SPEC_BUILD.value,
        PreparePhase.TEST_SPEC_REVIEW.value,
        PreparePhase.PLAN_DRAFTING.value,
        PreparePhase.PLAN_REVIEW.value,
        PreparePhase.GATE.value,
        PreparePhase.GROUNDING_CHECK.value,
        PreparePhase.RE_GROUNDING.value,
        PreparePhase.BLOCKED.value,
    }
)


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


class ShowPayload(TypedDict, total=False):
    """Full show payload for ``telec todo show``."""

    slug: str
    description: str
    stage: str
    blocked_by: list[BlockerEntry]
    previous: str
    current: CurrentBlock
    next: str
    artifacts: dict[str, str]


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
    """Return the derived phase value for a slug from prepare + work primitives."""
    prep = await derive_prepare_phase(state, todos_db, slug)
    if prep != PreparePhase.PREPARED:
        return str(prep.value)
    work = derive_work_phase(state, worktree_cwd, slug)
    return str(work.value)


def _derive_stage(current_value: str, *, delivered: bool) -> str:
    """Classify current value into stage bucket (delivered/prepare/work)."""
    if delivered:
        return "delivered"
    if current_value in _PREPARE_VALUES:
        return "prepare"
    return "work"


def _derive_current_block(current_value: str, state: dict[str, StateValue]) -> CurrentBlock:
    """Build the ``current`` block for the payload."""
    phase = _PHASE_LABEL.get(current_value, current_value)
    done = current_value in _DONE_PHASE_VALUES

    block = CurrentBlock(phase=phase, state="done" if done else "in_progress")

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


# ── Draft fast-path ────────────────────────────────────────────────────────


async def _assemble_draft_payload(todos_db: TodosDb, slug: str) -> ShowPayload:
    """Build a minimal show payload for draft todos — no phase derivation."""
    payload = ShowPayload(slug=slug, stage="draft")

    roadmap_entries = await todos_db.list_roadmap(include_icebox=True, include_delivered=True)
    for entry in roadmap_entries:
        if entry["slug"] == slug:
            desc = entry.get("description")
            if desc:
                payload["description"] = desc
            break

    payload["current"] = CurrentBlock(phase="draft", state="in_progress")

    artifact_names = await todos_db.list_artifacts(slug)
    if artifact_names:
        artifacts: dict[str, str] = {}
        for name in artifact_names:
            content = await todos_db.read_artifact(slug, name)
            if content:
                artifacts[name] = content
        if artifacts:
            payload["artifacts"] = artifacts

    return payload


# ── Main assembler ──────────────────────────────────────────────────────────


async def assemble_show_payload(
    todos_db: TodosDb,
    slug: str,
) -> ShowPayload | None:
    """Assemble the full show payload for a slug. Returns None if not found."""
    state = await todos_db.read_state(slug)
    is_delivered = False
    if state is None:
        # Active/icebox lookup found nothing — try delivered path
        state = await todos_db.read_state_delivered(slug)
        if state is None:
            return None
        is_delivered = True

    # Draft todos bypass phase derivation entirely — they haven't entered any lifecycle.
    if state.get("kind") == "draft":
        return await _assemble_draft_payload(todos_db, slug)

    project_root = _project_root_from_db(todos_db)
    worktree_cwd = _worktree_cwd_for(project_root, slug)
    current_value = await _derive_phase_value(state, todos_db, slug, worktree_cwd)

    delivered_slugs = await todos_db.delivered_slugs()

    roadmap_entries = await todos_db.list_roadmap(include_icebox=True, include_delivered=True)
    description: str | None = None
    for entry in roadmap_entries:
        if entry["slug"] == slug:
            description = entry.get("description")
            break

    payload = ShowPayload(slug=slug, stage=_derive_stage(current_value, delivered=is_delivered))

    if description:
        payload["description"] = description

    deps = await todos_db.load_deps()
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

    artifact_names = await todos_db.list_artifacts(slug)
    if artifact_names:
        artifacts: dict[str, str] = {}
        for name in artifact_names:
            content = await todos_db.read_artifact(slug, name)
            if content:
                artifacts[name] = content
        if artifacts:
            payload["artifacts"] = artifacts

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
