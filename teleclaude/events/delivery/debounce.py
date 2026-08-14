"""Generic delivery-edge debounce for external notification channels.

Coalesces repeated external pushes for the same recipient/event/grouping
identity into one send after a trailing quiet window. Durable notification
rows are unaffected — this module only delays the external send, never the
row projection that happens before it.

A cancel-and-restart timer mirrors ``teleclaude.core.agent_coordinator._slow_work``,
with one deliberate divergence: a send that becomes due after a full quiet
window is never cancelled by a later arrival. Each timer removes its own key
from the pending store before invoking ``runner``, so the send phase is no
longer cancellable and a later matching ``schedule`` call opens the next quiet
window instead of aborting the in-flight one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_DEFAULT_DELIVERY_DEBOUNCE_S: float = 15.0


class DeliveryChannel(StrEnum):
    """Closed vocabulary of external notification delivery channels."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"


class DeliveryDebouncer:
    """Coalesces per-(channel, recipient, event_type, group_identity) sends into one per quiet window."""

    def __init__(self) -> None:
        self._pending: dict[tuple[DeliveryChannel, str, str, str], asyncio.Task[None]] = {}
        # Strong references for immediate (window <= 0) sends: the event loop
        # only holds a weak reference to a task, so an unretained task can be
        # garbage-collected mid-flight, silently dropping the send.
        self._immediate_tasks: set[asyncio.Task[None]] = set()

    def schedule(
        self,
        *,
        channel: DeliveryChannel,
        recipient: str,
        event_type: str,
        group_identity: str,
        debounce_s: float | None,
        runner: Callable[[], Awaitable[None]],
    ) -> None:
        """Schedule ``runner`` after ``debounce_s`` seconds of quiet for this key.

        A subsequent call for the same key while a prior timer is still
        pending cancels it and starts a fresh window (replace-and-reset). A
        window resolving to ``<= 0`` runs ``runner`` immediately with no
        timer — the per-event immediate override.
        """
        window = _DEFAULT_DELIVERY_DEBOUNCE_S if debounce_s is None else debounce_s
        key = (channel, recipient, event_type, group_identity)

        if window <= 0:
            immediate_task = asyncio.create_task(
                self._run_and_log(channel, event_type, runner),
                name=f"delivery-immediate-{channel.value}-{event_type}",
            )
            self._immediate_tasks.add(immediate_task)
            immediate_task.add_done_callback(self._immediate_tasks.discard)
            return

        existing = self._pending.pop(key, None)
        if existing is not None and not existing.done():
            existing.cancel()

        task: asyncio.Task[None]

        async def _wait_then_run() -> None:
            try:
                await asyncio.sleep(window)
            except asyncio.CancelledError:
                return
            # Pop before running: the send is now committed and must survive a
            # later arrival for this key, which will open the next window.
            current = self._pending.get(key)
            if current is task:
                self._pending.pop(key, None)
            await self._run_and_log(channel, event_type, runner)

        task = asyncio.create_task(_wait_then_run(), name=f"delivery-debounce-{channel.value}-{event_type}")
        self._pending[key] = task

    async def _run_and_log(
        self,
        channel: DeliveryChannel,
        event_type: str,
        runner: Callable[[], Awaitable[None]],
    ) -> None:
        """Run ``runner``, cancelling cleanly and logging unexpected failures."""
        try:
            await runner()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning(
                "delivery debounce runner failed",
                channel=channel.value,
                event_type=event_type,
                error=str(exc),
            )
