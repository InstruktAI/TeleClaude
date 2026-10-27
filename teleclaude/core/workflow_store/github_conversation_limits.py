"""Tell the fleet master of every limit response this computer receives.

The transport reports each limit response to one observer on the GitHub I/O thread. Here it becomes a durable
notice on this computer's main loop and is delivered to the master, which pauses every conversation request until
the time the response names. A computer that cannot reach the master keeps the notice and delivers it once the
relay answers, unless the time it names has passed by then. On the master the same delivery runs locally.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger

from teleclaude.core.workflow_store.github_conversation_budget_store import ConversationBudgetStore
from teleclaude.core.workflow_store.github_conversation_master import ConversationMasterLink, MasterUnreachable
from teleclaude.core.workflow_store.github_conversation_wire import LimitNoticeRequest
from teleclaude.core.workflow_store.github_io_transport import RateLimitSignal, set_rate_limit_hook

logger = get_logger(__name__)

_RECORDED_EVENT = "github_rate_limit_noticed"
_DELIVERED_EVENT = "github_rate_limit_notice_delivered"
_HELD_EVENT = "github_rate_limit_notice_held"


class LimitNoticeCourier:
    """Record limit responses durably and deliver them to the master."""

    def __init__(
        self, store: ConversationBudgetStore, link: ConversationMasterLink, loop: asyncio.AbstractEventLoop
    ) -> None:
        self._store = store
        self._link = link
        self._loop = loop
        self._delivery = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    def install(self) -> None:
        """Become the transport's observer of limit responses."""
        set_rate_limit_hook(self.on_signal)

    def uninstall(self) -> None:
        """Stop observing limit responses."""
        set_rate_limit_hook(None)

    def on_signal(self, signal: RateLimitSignal) -> None:
        """Called on the GitHub I/O thread: hand the signal to this computer's main loop and return."""
        self._loop.call_soon_threadsafe(self._start, signal)

    def _start(self, signal: RateLimitSignal) -> None:
        task = self._loop.create_task(self.record_and_deliver(signal))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def record_and_deliver(self, signal: RateLimitSignal) -> None:
        """Keep the limit response, then tell the master."""
        await self._store.add_notice(signal.observed_at, signal.resume_at)
        logger.info(_RECORDED_EVENT, named_resume=signal.resume_at is not None)
        await self.deliver()

    async def deliver(self) -> None:
        """Tell the master of every notice it has not yet been told of, stopping at the first it cannot reach."""
        async with self._delivery:
            for notice in await self._store.undelivered_notices(datetime.now(UTC)):
                try:
                    await self._link.report_limit(LimitNoticeRequest(resume_at=notice.resume_at))
                except MasterUnreachable:
                    logger.info(_HELD_EVENT)
                    return
                await self._store.mark_notice_delivered(notice.notice_id, datetime.now(UTC))
                logger.info(_DELIVERED_EVENT)
