"""The consumers that, on every tick of the schedule clock, read the heads of items in work and complete pending workflow effects."""

from __future__ import annotations

import asyncio
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.local_checkouts import local_checkout_paths
from teleclaude.core.shutdown_drain import get_shutdown_drain
from teleclaude.core.workflow_machine.effects import reconcile_project_supervised
from teleclaude.core.workflow_machine.heads import discover_project_heads_supervised
from teleclaude.core.workflow_machine.launch_recovery import recover_stale_launches_supervised
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.schemas.sdlc import SchedulerTickMinute
from teleclaude.events.type_pattern import TypePattern

logger = get_logger(__name__)

EFFECT_RECONCILER_CONSUMER: Final = "workflow-effect-reconciler"
HEAD_OBSERVER_CONSUMER: Final = "workflow-head-observer"
INVENTORY_TIMEOUT_SECONDS: Final = 10
INVENTORY_FAILED_LOG: Final = "the project inventory could not be read for the head observation pass"
PAUSED_LOG: Final = "workflow observation and reconciliation paused while draining"


async def observe_heads() -> None:
    """Read the integration heads of items in work in every local checkout; failures are contained per item.

    This pass is the whole of head observation on a tick. It holds nothing but the reads, so the budget the
    work-review-cycle spec states for it is true whatever the reconciliation takes.
    """
    if not get_shutdown_drain().is_open:
        logger.debug(PAUSED_LOG)
        return
    try:
        projects = await asyncio.wait_for(local_checkout_paths(), INVENTORY_TIMEOUT_SECONDS)
    except Exception:  # supervision boundary: an unreadable inventory costs this pass, not the daemon
        logger.exception(INVENTORY_FAILED_LOG)
        return
    for project_root in projects:
        await discover_project_heads_supervised(project_root)


async def reconcile_and_recover() -> None:
    """Complete the pending effects of every local checkout, then release launch reservations with terminal evidence."""
    if not get_shutdown_drain().is_open:
        logger.debug(PAUSED_LOG)
        return
    for project_root in await local_checkout_paths():
        await reconcile_project_supervised(project_root)
        await recover_stale_launches_supervised(project_root)


async def observe_and_reconcile() -> None:
    """Both passes, in order: the observation of heads first, then the reconciliation."""
    await observe_heads()
    await reconcile_and_recover()


async def _on_observe_tick(_event: ReceivedEvent) -> None:
    await observe_heads()


async def _on_reconcile_tick(_event: ReceivedEvent) -> None:
    await reconcile_and_recover()


def build_head_observer_consumer() -> Consumer:
    """The consumer that reads the integration heads of items in work on every tick, apart from reconciliation."""
    return Consumer(
        name=HEAD_OBSERVER_CONSUMER,
        interest=Interest(types=(TypePattern(SchedulerTickMinute.type_name()),), own_computer_only=True),
        handler=_on_observe_tick,
    )


def build_effect_reconciler_consumer() -> Consumer:
    """The consumer that runs pending workflow effects to completion on this computer."""
    return Consumer(
        name=EFFECT_RECONCILER_CONSUMER,
        interest=Interest(types=(TypePattern(SchedulerTickMinute.type_name()),), own_computer_only=True),
        handler=_on_reconcile_tick,
    )
