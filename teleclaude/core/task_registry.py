"""Task registry for tracking, cancelling and supervising background asyncio tasks.

TaskRegistry tracks every spawned background task to prevent memory leaks from
fire-and-forget asyncio.create_task() calls, and supervises the long-lived tasks
the daemon depends on so none of them ends silently.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import TypeVar

from instrukt_ai_logging import get_logger

from teleclaude.core.restart_budget import RestartBudget
from teleclaude.core.shutdown_drain import ShutdownDrain

logger = get_logger(__name__)

T = TypeVar("T")

TASK_REGISTRY_SHUTDOWN_TIMEOUT_S = 5.0

# Restart allowance of one supervised task: its own sliding window, so one flapping task never spends another's.
SUPERVISED_RESTART_MAX = 5
SUPERVISED_RESTART_WINDOW_S = 300.0
SUPERVISED_RESTART_BACKOFF_S = 5.0

SupervisedStart = Callable[[], Coroutine[object, object, object]]

_SUPERVISED_END_EVENT = "Supervised task ended unexpectedly"
_SUPERVISED_RESTART_EVENT = "Restarting supervised task"
_SUPERVISED_ESCALATION_EVENT = "Supervised task will not be replaced; requesting the daemon's ordinary shutdown"
_SUPERVISED_EXPECTED_END_EVENT = "Supervised task ended while stopping or shutting down"
_SUPERVISED_STOPPING_FAILURE_EVENT = "Supervised task failed while stopping or shutting down"
_SUPERVISED_NOT_SPAWNED = "Supervised task has not been spawned"
_SUPERVISED_ESCALATION_REASON = "supervised-task-ended:{name}"


class TaskEnd(StrEnum):
    """How a supervised task's body came to an end."""

    RETURNED = "returned"
    RAISED = "raised"


class EscalationCause(StrEnum):
    """Why a supervised task's end is handed to the daemon's shutdown instead of a replacement."""

    NOT_REPLACEABLE = "not_replaceable"
    RESTART_BUDGET_EXHAUSTED = "restart_budget_exhausted"


class SupervisedTask:
    """Handle to one supervised task: the owner's way to stop it, so its end is never read as unexpected."""

    def __init__(self, name: str, start: SupervisedStart, *, restart: bool, budget: RestartBudget) -> None:
        self.name = name
        self.start = start
        self.restart = restart
        self.budget = budget
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None]:
        """The registry task that runs this supervised task and its replacements."""
        if self._task is None:
            raise RuntimeError(_SUPERVISED_NOT_SPAWNED)
        return self._task

    def attach(self, task: asyncio.Task[None]) -> None:
        """Record the registry task that runs this supervised task."""
        self._task = task

    @property
    def stopping(self) -> bool:
        """Whether the owner has stopped this task."""
        return self._stop_event.is_set()

    def done(self) -> bool:
        """Whether the supervision of this task has ended."""
        return self.task.done()

    def request_stop(self) -> None:
        """Mark the task stopped: its next end is expected and it is not replaced."""
        self._stop_event.set()

    async def sleep_unless_stopped(self, delay_s: float) -> bool:
        """Sleep `delay_s`; report False when the owner stopped the task first."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay_s)
        except TimeoutError:
            return True
        return False

    async def cancel(self) -> None:
        """Stop the task and cancel it, returning once it has ended."""
        self.request_stop()
        self.task.cancel()
        await asyncio.wait({self.task})

    async def wait(self, *, timeout: float) -> bool:
        """Stop the task and wait for it to end by itself; cancel it when `timeout` passes first.

        Returns whether the task ended on its own within the timeout.
        """
        self.request_stop()
        _, pending = await asyncio.wait({self.task}, timeout=timeout)
        if not pending:
            return True
        self.task.cancel()
        await asyncio.wait({self.task})
        return False


async def _first_task_end(tasks: tuple[asyncio.Task[object], ...]) -> None:
    """Wait for the first of `tasks` to end, re-raising how it ended."""
    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in done:
        task.result()


class TaskRegistry:
    """Registry for tracking and supervising background asyncio tasks.

    Prevents memory leaks by tracking all spawned tasks and ensuring they are
    cancelled at teardown. Automatically removes completed tasks from the
    registry. Finite accepted work holds an owned unit from the shutdown drain
    and has settled before `shutdown` runs; what `shutdown` cancels are the
    indefinite workers and any unit that outlived the preparation window.

    A task the process depends on for its lifetime runs through `supervise`: the
    registry runs it from a start callable and, when it ends while the daemon
    still admits work and its owner has not stopped it, logs the end and either
    starts it again within a bounded restart budget or escalates once to the
    daemon's ordinary shutdown, which the service manager follows with a relaunch.

    Example:
        registry = TaskRegistry(drain=get_shutdown_drain(), escalate=daemon.request_shutdown)

        # Spawn tracked task
        task = registry.spawn(some_coroutine(), name="background-worker")

        # Supervise a long-lived loop; its owner stops it through the handle
        worker = registry.supervise("long-lived-worker", loop.run, restart=True)
        await worker.cancel()

        # Teardown, after accepted work has settled
        await registry.shutdown(timeout=TASK_REGISTRY_SHUTDOWN_TIMEOUT_S)
    """

    def __init__(self, *, drain: ShutdownDrain, escalate: Callable[[str], None]) -> None:
        """Initialize an empty registry that reads admission from `drain` and escalates through `escalate`."""
        self._tasks: set[asyncio.Task[object]] = set()
        self._handles: set[SupervisedTask] = set()
        self._drain = drain
        self._escalate = escalate
        self._escalated = False
        logger.debug("TaskRegistry initialized")

    def _on_task_done(self, task: asyncio.Task[object]) -> None:
        """
        Handle task completion.

        Removes the task from the registry and logs any exceptions that occurred.

        Args:
            task: The completed task
        """
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background task %s failed: %s", task.get_name(), exc, exc_info=exc)

    def spawn(self, coro: Coroutine[object, object, T], name: str | None = None) -> asyncio.Task[T]:
        """
        Spawn a tracked background task.

        The task is automatically registered and will be cleaned up on completion
        or during shutdown. Completed tasks are automatically removed from the
        registry via done callback.

        Args:
            coro: Coroutine to execute as a background task
            name: Optional name for the task (useful for debugging)

        Returns:
            The created asyncio.Task that is being tracked

        Example:
            task = registry.spawn(process_data(), name="data-processor")
        """
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

        logger.debug(
            "Spawned tracked task: %s (total: %d)",
            name or f"<unnamed-{id(task)}>",
            len(self._tasks),
        )

        return task

    def supervise(self, name: str, start: SupervisedStart, *, restart: bool) -> SupervisedTask:
        """Run a long-lived task from `start` and keep it alive, or escalate when it cannot be.

        `start` is called for every run and must re-enter the owner's loop on the
        owner's existing state. A run that ends while the daemon admits work, and
        that the owner has not stopped through the returned handle, is logged. With
        `restart` it is then started again after a backoff until its restart budget
        is spent; without `restart`, or once the budget is spent, the registry
        requests the daemon's ordinary shutdown. Cancellation never counts as an end.
        """
        handle = SupervisedTask(
            name,
            start,
            restart=restart,
            budget=RestartBudget(
                max_restarts=SUPERVISED_RESTART_MAX,
                window_s=SUPERVISED_RESTART_WINDOW_S,
                backoff_s=SUPERVISED_RESTART_BACKOFF_S,
            ),
        )
        self._handles.add(handle)
        handle.attach(self.spawn(self._supervise(handle), name=name))
        return handle

    def observe(self, name: str, *tasks: asyncio.Task[object]) -> SupervisedTask:
        """Supervise tasks someone else runs: the first of `tasks` to end escalates the end to the daemon."""
        return self.supervise(name, lambda: _first_task_end(tasks), restart=False)

    async def _supervise(self, handle: SupervisedTask) -> None:
        """Run `handle`'s task, replacing it after each unexpected end until the owner stops it or the budget is spent."""
        try:
            while True:
                end, failure = await self._run_once(handle)
                if handle.stopping or not self._drain.is_open:
                    if failure is None:
                        logger.debug(_SUPERVISED_EXPECTED_END_EVENT, task=handle.name, outcome=end)
                    else:
                        logger.error(_SUPERVISED_STOPPING_FAILURE_EVENT, task=handle.name, exc_info=failure)
                    return
                logger.error(_SUPERVISED_END_EVENT, task=handle.name, outcome=end, exc_info=failure)
                if not handle.restart:
                    self._escalate_end(handle, EscalationCause.NOT_REPLACEABLE)
                    return
                charge = handle.budget.charge(asyncio.get_running_loop().time())
                if not charge.within_budget:
                    self._escalate_end(handle, EscalationCause.RESTART_BUDGET_EXHAUSTED, attempt=charge.attempt)
                    return
                logger.warning(
                    _SUPERVISED_RESTART_EVENT,
                    task=handle.name,
                    attempt=charge.attempt,
                    max_restarts=handle.budget.max_restarts,
                    window_s=handle.budget.window_s,
                    backoff_s=handle.budget.backoff_s,
                )
                if not await handle.sleep_unless_stopped(handle.budget.backoff_s) or not self._drain.is_open:
                    return
        finally:
            self._handles.discard(handle)

    async def _run_once(self, handle: SupervisedTask) -> tuple[TaskEnd, Exception | None]:
        """Run the task body once. This is a supervision boundary: any failure of the body is returned, not raised."""
        try:
            await handle.start()
        except Exception as exc:
            return TaskEnd.RAISED, exc
        return TaskEnd.RETURNED, None

    def _escalate_end(self, handle: SupervisedTask, cause: EscalationCause, *, attempt: int | None = None) -> None:
        """Hand the end of a task that will not be replaced to the daemon's ordinary shutdown, once."""
        logger.error(
            _SUPERVISED_ESCALATION_EVENT,
            task=handle.name,
            cause=cause,
            attempt=attempt,
            max_restarts=handle.budget.max_restarts,
            window_s=handle.budget.window_s,
        )
        if self._escalated:
            return
        self._escalated = True
        self._escalate(_SUPERVISED_ESCALATION_REASON.format(name=handle.name))

    async def shutdown(self, timeout: float = TASK_REGISTRY_SHUTDOWN_TIMEOUT_S) -> None:
        """
        Cancel all tracked tasks and wait for them to complete.

        Called at teardown, after accepted work has settled. This:
        1. Stops every supervised task still held, so no end is replaced
        2. Cancels all tracked tasks
        3. Waits up to `timeout` seconds for them to complete
        4. Logs any tasks that didn't complete in time

        Args:
            timeout: Maximum time to wait for tasks to complete (seconds)
        """
        for handle in self._handles:
            handle.request_stop()

        if not self._tasks:
            logger.debug("No tasks to shutdown")
            return

        task_count = len(self._tasks)
        logger.info("Shutting down %d tracked tasks (timeout=%.1fs)", task_count, timeout)

        # Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to complete
        if self._tasks:
            _, pending = await asyncio.wait(self._tasks, timeout=timeout)

            if pending:
                logger.warning(
                    "Shutdown timeout: %d/%d tasks still pending after %.1fs",
                    len(pending),
                    task_count,
                    timeout,
                )
                for task in pending:
                    logger.warning(
                        "Pending task: %s",
                        task.get_name() if hasattr(task, "get_name") else f"<task-{id(task)}>",
                    )
            else:
                logger.info("All %d tasks completed within timeout", task_count)

    def task_count(self) -> int:
        """
        Get the number of currently tracked tasks.

        Returns:
            Number of active tasks in the registry
        """
        return len(self._tasks)
