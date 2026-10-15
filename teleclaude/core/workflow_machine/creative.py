"""The object-state decision of the creative capabilities.

The design-spec write, the creative gate stamps and the creative dispatch each act on the state read inside their own
row transaction (``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``, the creative capabilities). This
module decides which of the table's rows the item is in, and returns the state with the creative episode opened, the
legacy phase converted when there is one, or the refusal that names the cause. The caller commits that state together
with its artifact, stamp or dispatch, so a refused call writes neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.workflow_machine.doors import door_for
from teleclaude.core.workflow_machine.phase_reading import (
    CLOSED_STORED_PHASES,
    TASK_LANE_STORED_PHASES,
    LaneFacts,
    read_phase,
    stored_in_legacy_phase,
)
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import LIFECYCLE_PHASE_STATE_KEY, TodoState
from teleclaude.types.workflow_record import CreativeEpisode, EpisodePath, Phase

NO_CONVERSION: Final = ""


class CreativeCapability(StrEnum):
    """The creative writes whose object state this module decides; the value names it in a refusal."""

    DESIGN_SPEC_WRITE = "the design-spec write"
    GATE_STAMP = "the creative gate stamp"
    DESIGN = "the creative dispatch"


class CreativeRefusal(StrEnum):
    """The causes a creative capability is refused with; each names the door the contract's table gives for the state."""

    DONE = "{capability} is refused: {item} is delivered, so the item is done"
    ADMITTED = "{capability} is refused: {item} is admitted by the integrator at {sha}. Door: {door}."
    CLOSED = (
        "{capability} is refused: {item} is in {phase}, and a creative write never moves a phase or its claim. "
        "Door: {door}."
    )
    HELD = "{capability} is refused: {item} is held by session {holder}. Door: {door}."
    HOLDER = (
        "{capability} is refused: {item} is held by this session in preparation; "
        "its creative handoff is `telec todo design {item}`"
    )
    UNKNOWN = "{capability} is refused: no item {item} in this project"


class CreativeRefused(Exception):
    """A creative capability was refused for one named cause; nothing was written."""


@dataclass(frozen=True)
class EpisodeOpening:
    """The state a creative capability commits: the legacy phase it converted (empty when none) and whether it opened."""

    state: dict[str, StateValue]
    converted_from: str
    opened: bool


def _refuse(refusal: CreativeRefusal, capability: CreativeCapability, item: str, **fields: str) -> CreativeRefused:
    return CreativeRefused(refusal.value.format(capability=capability.value, item=item, **fields))


def _door_refusal(
    refusal: CreativeRefusal,
    capability: CreativeCapability,
    item: str,
    state: TodoState,
    lane: LaneFacts,
    **fields: str,
) -> CreativeRefused:
    """A refusal that names the door of the first matching row of the contract's table for the state as the machine reads it.

    The phase is the reading, not the stored value: a stored ``ready`` whose stamp the integration head has moved past
    reads ``work`` and gets that row's door.
    """
    phase = read_phase(state, lane).phase or Phase.PREPARATION
    return _refuse(refusal, capability, item, phase=phase.value, door=door_for(state, phase, item), **fields)


def open_episode(
    item: str,
    current: dict[str, StateValue] | None,
    *,
    capability: CreativeCapability,
    caller_session_id: str,
    lane: LaneFacts,
) -> EpisodeOpening:
    """Decide the capability against the state read in its own transaction, or refuse naming the cause.

    ``lane`` is the lane facts the caller resolved before the transaction; the refusals that name a door read the
    item's phase through them.
    """
    if current is None:
        raise _refuse(CreativeRefusal.UNKNOWN, capability, item)
    state = TodoState.model_validate(current)
    stored = state.lifecycle_phase
    if state.kind == KIND_TASK or stored in TASK_LANE_STORED_PHASES:
        return EpisodeOpening(state=current, converted_from=NO_CONVERSION, opened=False)
    if stored is LifecyclePhase.DELIVERED:
        raise _refuse(CreativeRefusal.DONE, capability, item)
    admitted = state.workflow.admitted
    if admitted is not None:
        raise _door_refusal(CreativeRefusal.ADMITTED, capability, item, state, lane, sha=admitted.sha)
    holder = state.active_runner or ""
    if holder and holder != caller_session_id:
        raise _door_refusal(CreativeRefusal.HELD, capability, item, state, lane, holder=holder)
    if _closed_phase(state, stored):
        raise _door_refusal(CreativeRefusal.CLOSED, capability, item, state, lane)
    if holder and capability is not CreativeCapability.DESIGN:
        raise _refuse(CreativeRefusal.HOLDER, capability, item)
    if state.workflow.episode is not None:
        return EpisodeOpening(state=current, converted_from=NO_CONVERSION, opened=False)
    converted_from = stored.value if stored_in_legacy_phase(state) else NO_CONVERSION
    record = state.workflow.model_copy(deep=True)
    record.episode = CreativeEpisode(opened_at=datetime.now(UTC).isoformat(), path=EpisodePath.CAPABILITY)
    opened: dict[str, StateValue] = dict(current)
    opened[WORKFLOW_STATE_KEY] = record.to_state()
    opened[LIFECYCLE_PHASE_STATE_KEY] = LifecyclePhase.PREPARATION.value
    return EpisodeOpening(state=opened, converted_from=converted_from, opened=True)


def _closed_phase(state: TodoState, stored: LifecyclePhase) -> bool:
    """Whether the record is stored in a closed phase of the machine that a creative write never moves."""
    if stored is LifecyclePhase.PREPARATION:
        return False
    return stored in CLOSED_STORED_PHASES or (stored is LifecyclePhase.PREPARED and state.workflow.prepared is not None)
