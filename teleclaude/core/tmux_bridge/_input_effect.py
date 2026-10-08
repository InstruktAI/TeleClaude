"""Context-scoped hook at the first act that places input in a pane, and the unit that finishes it.

Text reaches a pane only through the paste pipeline's `paste-buffer` command.
A caller that must record progress before that effect installs a scope naming the
pane and an async hook. The pipeline awaits `before_input_effect` immediately
before the command, so everything earlier on the path (session read, pane check,
mode probe, buffer load, readiness observation, holds) places no input and
stays resumable.

A scope is bound to the installing task and to its target pane. Tasks started
inside the scope copy the context but are not the installing task, and writes
into any other pane are not the target's input, so both find the hook inert.
Outside a scope the call does nothing.

Once the hook has returned the effect has begun: `settle_begun_effect` runs the
rest of the paste, submission and buffer cleanup to completion even when its
caller is cancelled, so a begun effect is never left half-delivered.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

InputEffectHook = Callable[[], Awaitable[None]]


@dataclass
class _InputEffectBinding:
    """The hook, the pane it guards, the task that installed it, and whether it ran."""

    pane_name: str
    task: asyncio.Task[object] | None
    hook: InputEffectHook
    spent: bool = False


_binding: ContextVar[_InputEffectBinding | None] = ContextVar("tmux_input_effect_binding", default=None)


@contextmanager
def input_effect_scope(pane_name: str, hook: InputEffectHook) -> Iterator[None]:
    """Run `hook` once, just before the installing task first places input in `pane_name`."""
    token = _binding.set(_InputEffectBinding(pane_name=pane_name, task=asyncio.current_task(), hook=hook))
    try:
        yield
    finally:
        _binding.reset(token)


async def before_input_effect(pane_name: str) -> None:
    """Await the scope's hook if this write is the guarded pane's first input from the installing task."""
    binding = _binding.get()
    if binding is None or binding.spent:
        return
    if binding.pane_name != pane_name or binding.task is not asyncio.current_task():
        return
    binding.spent = True
    await binding.hook()


async def settle_begun_effect[T](effect: Coroutine[object, object, T]) -> T:
    """Run an effect that has begun to completion, awaiting it through any cancellation of the caller.

    Each tmux call inside the effect carries its own timeout, so the wait is bounded.
    """
    task = asyncio.ensure_future(effect)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                continue
        failure = None if task.cancelled() else task.exception()
        if failure is not None:
            logger.warning("Begun input effect failed after its caller was cancelled", error=str(failure))
        raise
