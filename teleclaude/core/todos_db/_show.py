"""Assemble the ``telec todo show`` payload from DB state."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from teleclaude.core.next_machine._types import PreparePhase, StateValue
from teleclaude.core.next_machine.work_lifecycle import LIFECYCLE_STATES

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

# Phase grouping boundaries — indices into LIFECYCLE_STATES.
# Prepare: input_assessment .. prepared (indices 0..10)
# Work:    build_started .. finalize_handed_off (indices 11..17)
_PREPARE_STATES = {s.value for s in PreparePhase if s != PreparePhase.BLOCKED}

# Map `current` values to the human-readable phase name used in `current.phase`.
_PHASE_LABEL: dict[str, str] = {
    "input_assessment": "input_assessment",
    "triangulation": "triangulation",
    "requirements_review": "requirements_review",
    "test_spec_build": "test_spec_build",
    "test_spec_review": "test_spec_review",
    "plan_drafting": "plan_drafting",
    "plan_review": "plan_review",
    "gate": "gate",
    "grounding_check": "grounding_check",
    "re_grounding": "re_grounding",
    "prepared": "prepared",
    "build_started": "build",
    "build_complete": "build",
    "review_pending": "review",
    "review_changes_requested": "review",
    "review_approved": "review",
    "finalize_ready": "finalize",
    "finalize_handed_off": "finalize",
}


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


def _derive_stage(current: str, *, delivered: bool) -> str:
    """Derive stage from current lifecycle state."""
    if delivered:
        return "delivered"
    if current in _PREPARE_STATES:
        return "prepare"
    if current.startswith("integration"):
        return "integrate"
    return "work"


def _is_phase_done(  # pylint: disable=too-many-return-statements
    current: str, state: dict[str, StateValue]
) -> bool:
    """Determine whether the current phase has a completion marker."""
    if current in ("requirements_review", "test_spec_review", "plan_review"):
        section = state.get(current)
        return isinstance(section, dict) and bool(section.get("verdict"))

    if current == "build_complete":
        return True
    if current == "build_started":
        return False
    if current == "review_approved":
        return True
    if current in ("review_pending", "review_changes_requested"):
        return False
    if current == "finalize_handed_off":
        return True
    if current == "finalize_ready":
        return False
    if current == "prepared":
        return True
    if current in ("gate", "grounding_check", "re_grounding"):
        dor = state.get("dor")
        return isinstance(dor, dict) and bool(dor.get("status"))

    return False


def _derive_current_block(current: str, state: dict[str, StateValue]) -> CurrentBlock:
    """Build the ``current`` block for the payload."""
    phase = _PHASE_LABEL.get(current, current)
    done = _is_phase_done(current, state)

    block = CurrentBlock(phase=phase, state="done" if done else "in_progress")

    if current == "review_approved":
        block["status"] = "approved"
    elif current == "review_changes_requested":
        block["status"] = "changes_requested"
    elif current == "review_pending":
        block["status"] = "pending"

    review_round = state.get("review_round")
    if isinstance(review_round, int) and review_round > 0:
        block["round"] = review_round

    return block


def _derive_previous(current: str) -> str | None:
    """Return the previous phase name, or None if at the start."""
    try:
        idx = LIFECYCLE_STATES.index(current)
    except ValueError:
        return None
    if idx == 0:
        return None
    prev_state = LIFECYCLE_STATES[idx - 1]
    return _PHASE_LABEL.get(prev_state, prev_state)


def _derive_next(current: str, state: dict[str, StateValue]) -> str | None:
    """Return the next phase name, or None if not done or at the end."""
    if not _is_phase_done(current, state):
        return None
    try:
        idx = LIFECYCLE_STATES.index(current)
    except ValueError:
        return None
    if idx >= len(LIFECYCLE_STATES) - 1:
        return None
    next_state = LIFECYCLE_STATES[idx + 1]
    return _PHASE_LABEL.get(next_state, next_state)


def _build_blocked_by(
    slug: str,
    deps: dict[str, list[str]],
    delivered_slugs: set[str],
    all_states: dict[str, dict[str, StateValue]],
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
        if dep_state:
            dep_current = str(dep_state.get("current", "input_assessment"))
            blocker["stage"] = _derive_stage(dep_current, delivered=False)
            blocker["current"] = dep_current

        if dep_slug not in visited:
            nested = _build_blocked_by(dep_slug, deps, delivered_slugs, all_states, visited=visited)
            if nested:
                blocker["blocked_by"] = nested

        blockers.append(blocker)

    return blockers if blockers else None


# ── Main assembler ──────────────────────────────────────────────────────────


async def assemble_show_payload(  # pylint: disable=too-many-locals,too-many-branches
    todos_db: TodosDb,
    slug: str,
) -> ShowPayload | None:
    """Assemble the full show payload for a slug. Returns None if not found."""
    state = await todos_db.read_state(slug)
    if state is None:
        return None

    current = str(state.get("current", "input_assessment"))

    delivered_slugs = await todos_db.delivered_slugs()
    is_delivered = slug in delivered_slugs

    roadmap_entries = await todos_db.list_roadmap(include_icebox=True, include_delivered=True)
    description: str | None = None
    for entry in roadmap_entries:
        if entry["slug"] == slug:
            description = entry.get("description")
            break

    payload = ShowPayload(slug=slug, stage=_derive_stage(current, delivered=is_delivered))

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

        blocked_by = _build_blocked_by(slug, deps, delivered_slugs, all_states)
        if blocked_by:
            payload["blocked_by"] = blocked_by

    previous = _derive_previous(current)
    if previous:
        payload["previous"] = previous

    payload["current"] = _derive_current_block(current, state)

    next_phase = _derive_next(current, state)
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
