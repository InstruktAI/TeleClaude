"""The consumer that completes pending workflow effects on every tick of the schedule clock."""

from __future__ import annotations

from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.local_checkouts import local_checkout_paths
from teleclaude.core.shutdown_drain import get_shutdown_drain
from teleclaude.core.workflow_machine.effects import reconcile_project
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.schemas.sdlc import SchedulerTickMinute
from teleclaude.events.type_pattern import TypePattern

logger = get_logger(__name__)

EFFECT_RECONCILER_CONSUMER: Final = "workflow-effect-reconciler"
RECONCILE_PAUSED_LOG: Final = "workflow effect reconciliation paused while draining"


async def _on_tick(_event: ReceivedEvent) -> None:
    """Reconcile every local checkout; a failing item is contained and logged inside the reconciler."""
    if not get_shutdown_drain().is_open:
        logger.debug(RECONCILE_PAUSED_LOG)
        return
    for project_root in await local_checkout_paths():
        await reconcile_project(project_root)


def build_effect_reconciler_consumer() -> Consumer:
    """The consumer that runs pending workflow effects to completion on this computer."""
    return Consumer(
        name=EFFECT_RECONCILER_CONSUMER,
        interest=Interest(types=(TypePattern(SchedulerTickMinute.type_name()),), own_computer_only=True),
        handler=_on_tick,
    )
