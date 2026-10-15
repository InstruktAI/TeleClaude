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
from teleclaude.types.lifecycle import WORK_LIFECYCLE_PHASES, LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import FinalizeStatus, TodoState
from teleclaude.types.workflow_record import Act, Phase

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
class LaneFacts:
    """The creative lane's answer and the integration head, resolved together for one reading of an item.

    Every consumer that reads a phase obtains these from the resolver (``lane.py``) or reuses the ones a caller
    resolved before its transaction. They are never supplied as constants, so a reader added later cannot read an
    item as ordinary preparation while the creative lane drives it
    (``local/projects/teleclaude/design/architecture/workflow-machine``).
    """

    creative_incomplete: bool
    integration_head: str
    artifact_digests: tuple[tuple[str, str], ...]
    head_unreadable: bool = False

    @property
    def expected_digests(self) -> dict[str, str]:
        """The artifact revisions the creative answer was derived from, for a transaction to fence against."""
        return dict(self.artifact_digests)


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


def read_phase(state: TodoState, lane: LaneFacts) -> PhaseReading:
    """Read the item's phase.

    ``lane.integration_head`` is the commit the integration ref carries now, or empty when it is unknown. A stamp
    whose commit is no longer the head is stale: the item reads as work again, and a stamp at the new head
    is required (``local/projects/teleclaude/spec/feature/workflow/work-review-cycle``).
    ``lane.creative_incomplete`` is the creative lane's answer for an item it has not finished.
    An item the integrator admitted reads ``ready`` at the admitted commit until the integrator retires the
    admission, whatever its head, its stamp or its creative state: the integrator owns the item's posture, so no
    driver is reserved or started for it and nothing under the integrator's merge is reopened.
    """
    stored = state.lifecycle_phase
    if stored in TASK_LANE_STORED_PHASES or state.kind == KIND_TASK:
        return PhaseReading(phase=None)
    if stored is LifecyclePhase.DELIVERED:
        return PhaseReading(phase=Phase.DELIVERED)
    admitted = state.workflow.admitted
    if admitted is not None:
        return PhaseReading(phase=Phase.READY, ready_sha=admitted.sha, ready_at=admitted.at)
    if lane.creative_incomplete and _creative_overlay_applies(state, stored):
        return PhaseReading(phase=Phase.DESIGN)
    if stored is LifecyclePhase.READY:
        stamp = state.workflow.stamp
        if stamp is not None and lane.integration_head and stamp.sha != lane.integration_head:
            return PhaseReading(phase=Phase.WORK)
        return PhaseReading(
            phase=Phase.READY,
            ready_sha=stamp.sha if stamp else "",
            ready_at=stamp.ready_at if stamp else "",
        )
    held = bool(state.active_runner)
    if stored is LifecyclePhase.FINALIZE_READY:
        return _finalize_ready(state, lane.integration_head, held)
    if stored is LifecyclePhase.REVIEW_APPROVED:
        return _review_approved(state, lane.integration_head, held)
    if stored is LifecyclePhase.PREPARED:
        return PhaseReading(phase=Phase.PREPARED if state.workflow.prepared else Phase.PREPARATION)
    if stored is LifecyclePhase.WAITING:
        return PhaseReading(phase=Phase.WAITING)
    if stored is LifecyclePhase.WORK:
        return PhaseReading(phase=Phase.WORK)
    return PhaseReading(phase=Phase.PREPARATION)


def awaits_readable_head(state: TodoState, lane: LaneFacts) -> bool:
    """Whether a carried review verdict that nobody holds cannot be driven because the head could not be read.

    The verdict reads ``preparation`` while the head is unknown, but a preparation claim would not rewrite the stored
    phase, and a head that later equals the verdict would read ``ready`` under a preparation driver. No driver is
    started for it until the head is readable; an absent integration ref is a known state and is not this
    (``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``).
    """
    return (
        lane.head_unreadable
        and state.lifecycle_phase is LifecyclePhase.REVIEW_APPROVED
        and bool(state.build_review.reviewed_target_digest)
        and not state.active_runner
        and state.workflow.admitted is None
    )


def work_started(state: TodoState) -> bool:
    """Whether the build of a todo has started, whichever machine began it.

    The evidence is read from the item itself, so it holds after a kickback returned the item to preparation: work
    already begun stays begun (``local/projects/teleclaude/spec/feature/workflow/todo-management``).
    """
    if state.build_start_base_sha or state.lifecycle_phase in WORK_LIFECYCLE_PHASES:
        return True
    if state.lifecycle_phase in (LifecyclePhase.WORK, LifecyclePhase.READY):
        return True
    record = state.workflow
    if record.admitted is not None or record.stamp is not None:
        return True
    if record.observed_heads or record.publish_intents:
        return True
    return any(entry.act is Act.CLAIM and entry.bound for entry in record.ledger)


CLOSED_STORED_PHASES: Final = frozenset(
    {LifecyclePhase.PREPARATION, LifecyclePhase.WAITING, LifecyclePhase.WORK, LifecyclePhase.READY}
)
"""Phases this machine writes: a regression of the creative files never reads a record in one of them as design."""


def _creative_overlay_applies(state: TodoState, stored: LifecyclePhase) -> bool:
    """Whether the creative lane may read the item as design: only a record stored in a phase from before the item vocabulary.

    A record stored as waiting, work, ready or preparation, or prepared with its prepared record, keeps its phase
    whatever its artifacts or files do afterwards (``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``).
    """
    if stored in CLOSED_STORED_PHASES:
        return False
    return not (stored is LifecyclePhase.PREPARED and state.workflow.prepared is not None)


def _finalize_ready(state: TodoState, integration_head: str, held: bool) -> PhaseReading:
    """A carried finalize handoff is a stamp at its commit; without a ready handoff it is preparation.

    A carried stamp whose commit is no longer the known integration head returns to preparation while nobody holds the
    item, and reads work under a holder; an unknown head leaves it as it is.
    """
    finalize = state.finalize
    if finalize.status is not FinalizeStatus.READY or not finalize.sha:
        return PhaseReading(phase=Phase.PREPARATION)
    if integration_head and finalize.sha != integration_head:
        return PhaseReading(phase=Phase.WORK if held else Phase.PREPARATION)
    return PhaseReading(phase=Phase.READY, ready_sha=finalize.sha, ready_at=finalize.ready_at)


def _review_approved(state: TodoState, integration_head: str, held: bool) -> PhaseReading:
    """A carried approval is a stamp at the commit it reviewed, valid only while that is the integration head.

    Away from the head, or with the head unknown, an unheld record reads as preparation: its commit is not established
    as the head. A held record reads work when the head is known and has moved, and ready when it is not known.
    """
    reviewed = state.build_review.reviewed_target_digest
    if not reviewed:
        return PhaseReading(phase=Phase.PREPARATION)
    if integration_head and reviewed != integration_head:
        return PhaseReading(phase=Phase.WORK if held else Phase.PREPARATION)
    if not integration_head and not held:
        return PhaseReading(phase=Phase.PREPARATION)
    return PhaseReading(phase=Phase.READY, ready_sha=reviewed, ready_at=state.build_review.reviewed_at)
