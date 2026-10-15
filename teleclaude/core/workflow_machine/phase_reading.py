"""The one reader of an item's phase: a stored lifecycle phase read as a phase of the item vocabulary.

Every consumer that needs an item's phase reads it here. The mapping is the reading table of
``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``. It is total over the stored
lifecycle phases, so no item is left in a phase that nothing drives.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import FinalizeStatus, TodoState
from teleclaude.types.workflow_record import Phase

PREPARATION_STORED_PHASES: frozenset[LifecyclePhase] = frozenset(
    {
        LifecyclePhase.DRAFT,
        LifecyclePhase.PRD_DRAFTING,
        LifecyclePhase.PRD_REVIEW,
        LifecyclePhase.PRD_HUMAN_APPROVAL,
        LifecyclePhase.ARCHITECTURE_DRAFTING,
        LifecyclePhase.ARCHITECTURE_REVIEW,
        LifecyclePhase.DIAGNOSE,
        LifecyclePhase.PLAN_DRAFTING,
        LifecyclePhase.PLAN_REVIEW,
        LifecyclePhase.BLOCKED,
        LifecyclePhase.BUILD_STARTED,
        LifecyclePhase.BUILD_COMPLETE,
        LifecyclePhase.REVIEW_CHANGES_REQUESTED,
        LifecyclePhase.PREPARATION,
    }
)

TASK_LANE_STORED_PHASES: frozenset[LifecyclePhase] = frozenset(
    {LifecyclePhase.TASK_PLAN_DRAFTING, LifecyclePhase.TASK_RUNNING}
)


@dataclass(frozen=True)
class PhaseReading:
    """An item's phase, and the commit it is ready at when that phase is ``ready``.

    A todo of kind task has no phase in the item vocabulary whatever its stored phase: the task procedures drive it,
    including while its plan awaits authorization, when the stored phase is the shared ``prepared``.
    """

    phase: Phase | None
    ready_sha: str = ""
    ready_at: str = ""

    @property
    def task_lane(self) -> bool:
        """Whether the task lane drives the item (it has no phase in the item vocabulary)."""
        return self.phase is None


CREATIVE_STATE_KEY: Final = "creative"


def creative_snapshot(state: Mapping[str, StateValue]) -> str:
    """The creative section of the stored state, as read when the lane was resolved, for a fence at the write."""
    return json.dumps(state.get(CREATIVE_STATE_KEY), sort_keys=True, default=str)


def read_phase(state: TodoState, *, integration_head: str, creative_incomplete: bool) -> PhaseReading:
    """Read the item's phase.

    ``integration_head`` is the commit the integration ref carries now, or empty when it is unknown. A stamp
    whose commit is no longer the head is stale: the item reads as work again, and a stamp at the new head
    is required (``local/projects/teleclaude/spec/feature/workflow/work-review-cycle``).
    ``creative_incomplete`` is the creative lane's answer for an item it has not finished.
    """
    stored = state.lifecycle_phase
    if stored in TASK_LANE_STORED_PHASES or state.kind == KIND_TASK:
        return PhaseReading(phase=None)
    if stored is LifecyclePhase.DELIVERED:
        return PhaseReading(phase=Phase.DELIVERED)
    if creative_incomplete:
        return PhaseReading(phase=Phase.DESIGN)
    if stored is LifecyclePhase.READY:
        stamp = state.workflow.stamp
        if stamp is not None and integration_head and stamp.sha != integration_head:
            return PhaseReading(phase=Phase.WORK)
        return PhaseReading(
            phase=Phase.READY,
            ready_sha=stamp.sha if stamp else "",
            ready_at=stamp.ready_at if stamp else "",
        )
    if stored is LifecyclePhase.FINALIZE_READY:
        return _finalize_ready(state)
    if stored is LifecyclePhase.REVIEW_APPROVED:
        return _review_approved(state, integration_head)
    if stored is LifecyclePhase.PREPARED:
        return PhaseReading(phase=Phase.PREPARED if state.workflow.prepared else Phase.PREPARATION)
    if stored is LifecyclePhase.WAITING:
        return PhaseReading(phase=Phase.WAITING)
    if stored is LifecyclePhase.WORK:
        return PhaseReading(phase=Phase.WORK)
    return PhaseReading(phase=Phase.PREPARATION)


def _finalize_ready(state: TodoState) -> PhaseReading:
    """A carried finalize handoff is a stamp at its commit; without a ready handoff it is preparation."""
    finalize = state.finalize
    if finalize.status is not FinalizeStatus.READY or not finalize.sha:
        return PhaseReading(phase=Phase.PREPARATION)
    return PhaseReading(phase=Phase.READY, ready_sha=finalize.sha, ready_at=finalize.ready_at)


def _review_approved(state: TodoState, integration_head: str) -> PhaseReading:
    """A carried approval is a stamp at the commit it reviewed, valid only while that is the integration head."""
    reviewed = state.build_review.reviewed_target_digest
    if not reviewed or reviewed != integration_head:
        return PhaseReading(phase=Phase.PREPARATION)
    return PhaseReading(phase=Phase.READY, ready_sha=reviewed, ready_at=state.build_review.reviewed_at)
