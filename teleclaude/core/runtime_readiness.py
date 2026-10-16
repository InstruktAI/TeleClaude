"""Scoped runtime-start waiters, owned by one daemon lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from teleclaude.core.events import DeliveryNoComposerContext
from teleclaude.runtime.environment import CompactionLaunchContext

_RUN_IDENTITY_ERROR = "ordinary runtime readiness requires a run id"
_COMPACTION_IDENTITY_ERROR = "compaction runtime readiness requires attempt context"
_NO_COMPOSER_HANDLER_MISSING = "runtime readiness has no no-composer owner"


@dataclass(frozen=True)
class RuntimeReadinessKey:
    """Identity of one ordinary run or one temporary compaction launch."""

    session_id: str
    runtime_run_id: str | None = None
    compaction_attempt_id: str | None = None
    native_session_id: str | None = None

    def __post_init__(self) -> None:
        ordinary = self.runtime_run_id is not None
        compaction = self.compaction_attempt_id is not None and self.native_session_id is not None
        if ordinary == compaction or (self.compaction_attempt_id is None) != (self.native_session_id is None):
            raise ValueError(_RUN_IDENTITY_ERROR)

    @classmethod
    def ordinary(cls, session_id: str, runtime_run_id: str | None) -> RuntimeReadinessKey:
        if runtime_run_id is None:
            raise ValueError(_RUN_IDENTITY_ERROR)
        return cls(session_id=session_id, runtime_run_id=runtime_run_id)

    @classmethod
    def compaction(cls, session_id: str, context: CompactionLaunchContext | None) -> RuntimeReadinessKey:
        if context is None:
            raise ValueError(_COMPACTION_IDENTITY_ERROR)
        return cls(
            session_id=session_id,
            compaction_attempt_id=context.attempt_id,
            native_session_id=context.native_session_id,
        )


class RuntimeReadiness:
    """Match observed starts to waiters registered before their launch."""

    def __init__(self) -> None:
        self._waiters: dict[RuntimeReadinessKey, set[asyncio.Future[None]]] = {}
        self._closed = False
        self._no_composer_handler: Callable[[DeliveryNoComposerContext], Awaitable[None]] | None = None

    def set_no_composer_handler(
        self,
        handler: Callable[[DeliveryNoComposerContext], Awaitable[None]],
    ) -> None:
        """Bind the runtime owner that consumes pane evidence."""
        self._no_composer_handler = handler

    async def report_no_composer(self, context: DeliveryNoComposerContext) -> None:
        """Deliver pane evidence directly to the runtime status owner."""
        if self._no_composer_handler is None:
            raise RuntimeError(_NO_COMPOSER_HANDLER_MISSING)
        await self._no_composer_handler(context)

    def register(self, key: RuntimeReadinessKey) -> asyncio.Future[None]:
        """Register and return a future settled only by this exact launch identity."""
        if self._closed:
            future = asyncio.get_running_loop().create_future()
            future.cancel()
            return future
        future = asyncio.get_running_loop().create_future()
        self._waiters.setdefault(key, set()).add(future)
        return future

    def observe_start(self, key: RuntimeReadinessKey) -> bool:
        """Settle waiters for one observed launch and report whether any matched."""
        waiters = self._waiters.pop(key, set())
        for future in waiters:
            if not future.done():
                future.set_result(None)
        return bool(waiters)

    def release(self, key: RuntimeReadinessKey, future: asyncio.Future[None]) -> None:
        """Remove one caller's waiter on completion, timeout, cancellation, or failed launch."""
        waiters = self._waiters.get(key)
        if waiters is None:
            return
        waiters.discard(future)
        if not waiters:
            self._waiters.pop(key, None)

    def settle_session(self, session_id: str) -> None:
        """Close every outstanding readiness wait for a session being torn down."""
        keys = [key for key in self._waiters if key.session_id == session_id]
        for key in keys:
            for future in self._waiters.pop(key, set()):
                if not future.done():
                    future.cancel()

    def close(self) -> None:
        """Settle outstanding waiters when the owning runtime shuts down."""
        self._closed = True
        for key in tuple(self._waiters):
            for future in self._waiters.pop(key, set()):
                if not future.done():
                    future.cancel()
