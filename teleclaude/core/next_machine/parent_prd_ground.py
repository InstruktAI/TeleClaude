"""Parent PRD-ground provenance for dependency drift detection."""

from __future__ import annotations

from typing import Protocol

from teleclaude.constants import STATE_KEY_ARCHITECTURE, STATE_KEY_IMPLEMENTATION_PLAN
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import DependencyEntry, ParentPrdGroundEntry, TodoState


class ParentPrdGroundReader(Protocol):
    """Boundary needed to read direct dependency ground for a todo."""

    async def get_deps_with_status(self, slug: str) -> list[DependencyEntry]:
        """Return immediate dependency slugs with todo status."""
        ...

    async def read_state(self, slug: str) -> dict[str, StateValue] | None:
        """Return persisted todo state for a dependency slug."""
        ...


async def read_parent_prd_ground(
    todos_db: ParentPrdGroundReader,
    slug: str,
) -> list[ParentPrdGroundEntry]:
    """Read PRD-approved direct dependency ground for a dependent todo."""
    entries: list[ParentPrdGroundEntry] = []
    for dependency in await todos_db.get_deps_with_status(slug):
        if dependency.roadmap_status == "delivered":
            continue
        raw_state = await todos_db.read_state(dependency.dep_slug)
        if raw_state is None:
            entries.append(ParentPrdGroundEntry(dep_slug=dependency.dep_slug))
            continue
        parent_state = TodoState.model_validate(raw_state)
        approval = parent_state.approvals.prd_approved
        if not approval.approved:
            continue
        entries.append(
            ParentPrdGroundEntry(
                dep_slug=dependency.dep_slug,
                prd_digest=approval.approved_digest or parent_state.artifacts.prd.digest,
                prd_approved_at=approval.approved_at,
                prd_approved_by_session_id=approval.caller_session_id,
                architecture_digest=getattr(parent_state.artifacts, STATE_KEY_ARCHITECTURE).digest,
                implementation_plan_digest=getattr(parent_state.artifacts, STATE_KEY_IMPLEMENTATION_PLAN).digest,
            )
        )
    return sorted(entries, key=lambda entry: entry.dep_slug)


def sorted_parent_prd_ground(entries: list[ParentPrdGroundEntry]) -> list[ParentPrdGroundEntry]:
    """Return parent PRD-ground evidence in deterministic order."""
    return sorted(entries, key=lambda entry: entry.dep_slug)
