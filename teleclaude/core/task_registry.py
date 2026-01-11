"""Task registry for tracking and managing background asyncio tasks.

This module provides TaskRegistry for tracking all spawned background tasks
to prevent memory leaks from fire-and-forget asyncio.create_task() calls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TaskRegistry:
    """Registry for tracking background asyncio tasks.

    Prevents memory leaks by tracking all spawned tasks and ensuring they are
    properly cancelled during shutdown. Automatically removes completed tasks
    from the registry.

    Example:
        registry = TaskRegistry()

        # Spawn tracked task
        task = registry.spawn(some_coroutine(), name="background-worker")

        # Graceful shutdown
        await registry.shutdown(timeout=5.0)
    """

    def __init__(self) -> None:
        """Initialize empty task registry."""
        self._tasks: set[asyncio.Task[object]] = set()
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

    async def shutdown(self, timeout: float = 5.0) -> None:
        """
        Cancel all tracked tasks and wait for them to complete.

        This is a graceful shutdown that:
        1. Cancels all tracked tasks
        2. Waits up to `timeout` seconds for them to complete
        3. Logs any tasks that didn't complete in time

        Args:
            timeout: Maximum time to wait for tasks to complete (seconds)

        Example:
            await registry.shutdown(timeout=10.0)
        """
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
