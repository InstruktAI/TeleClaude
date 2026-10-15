"""The acts only the previous machine knew, refused for an item this machine drives.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (UC-IL12) is the contract: a verb that applies an approval, return or handoff
act that only the previous machine knew is refused, naming the item's phase and the act that replaces it, and no phase moves. The creative gate
stamps and the task stamps belong to lanes that stay, and a todo of kind task or a delivered item is not driven by this machine.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from teleclaude.core.workflow_machine.lane import resolve_lane
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Act, Phase


class PreviousStamp(StrEnum):
    """The stamp types the previous machine owned and this machine replaces by an act."""

    VERDICT = "verdict"
    FINALIZE_READY = "finalize_ready"
    DEFERRALS_PROCESSED = "deferrals_processed"
    REQUIREMENTS_READY = "requirements_ready"
    PLAN_READY = "plan_ready"
    PRD_APPROVED = "prd_approved"
    DIAGNOSIS_SETTLED = "diagnosis_settled"
    DIAGNOSIS_UNRESOLVED = "diagnosis_unresolved"
    ARCHITECTURE_SKIPPED = "architecture_skipped"
    DRIFT_REVIEWED = "drift_reviewed"
    BUILD_COMPLETE = "build_complete"
    KICKBACK = "kickback"


RETURN_TO_WORK: Final = "return_to_work"
CREATE_CAPABILITY: Final = "create"

_REPLACING_ACT: Final[dict[str, str]] = {
    PreviousStamp.VERDICT: Act.FINDING.value,
    PreviousStamp.FINALIZE_READY: Act.STAMP.value,
    PreviousStamp.DEFERRALS_PROCESSED: CREATE_CAPABILITY,
    PreviousStamp.REQUIREMENTS_READY: Act.PREPARED.value,
    PreviousStamp.PLAN_READY: Act.PREPARED.value,
    PreviousStamp.PRD_APPROVED: Act.DECISION.value,
    PreviousStamp.DIAGNOSIS_SETTLED: Act.PREPARED.value,
    PreviousStamp.DIAGNOSIS_UNRESOLVED: Act.WAITING.value,
    PreviousStamp.ARCHITECTURE_SKIPPED: Act.PREPARED.value,
    PreviousStamp.DRIFT_REVIEWED: Act.PREPARED.value,
    PreviousStamp.BUILD_COMPLETE: Act.STAMP.value,
    PreviousStamp.KICKBACK: Act.KICKBACK.value,
    RETURN_TO_WORK: Act.KICKBACK.value,
}
REFUSAL_TEMPLATE: Final = (
    "{verb}: {item} is in {phase}, which the workflow machine drives; the act that replaces it is {act}, "
    "performed with `telec todo act {item} {act}` by the session that holds the item"
)
NOT_DRIVEN_PHASES: Final = frozenset({Phase.DELIVERED})


class PreviousActRefused(Exception):
    """A verb that only the previous machine knew was refused for an item this machine drives; nothing was written."""


async def refuse_previous_machine_act(project_root: str, slug: str, verb: str) -> None:
    """Raise ``PreviousActRefused`` when ``verb`` is an act of the previous machine and the item is one this machine reads.

    Any other verb, an item of the task lane, a delivered item and an item with no stored state pass through unchanged.
    """
    replacing = _REPLACING_ACT.get(verb)
    if replacing is None:
        return
    store = await get_workflow_store(project_root)
    raw = await store.read_state(slug)
    if raw is None:
        return
    state = TodoState.model_validate(raw)
    reading = read_phase(state, await resolve_lane(store, project_root, slug, raw, state))
    if reading.phase is None or reading.phase in NOT_DRIVEN_PHASES:
        return
    raise PreviousActRefused(REFUSAL_TEMPLATE.format(verb=verb, item=slug, phase=reading.phase.value, act=replacing))
