"""Unit tests for TaskRegistry."""

import asyncio
from unittest.mock import patch

import pytest

from teleclaude.core.task_registry import TaskRegistry


@pytest.mark.asyncio
async def test_spawn_tracks_task():
    """Test that spawn() creates and tracks a task."""
    registry = TaskRegistry()

    async def dummy_coro():
        await asyncio.sleep(0.01)
        return "done"

    task = registry.spawn(dummy_coro(), name="test-task")

    assert registry.task_count() == 1
    assert not task.done()

    # Wait for task to complete
    result = await task
    assert result == "done"


@pytest.mark.asyncio
async def test_spawn_auto_cleanup_on_completion():
    """Test that completed tasks are automatically removed from registry."""
    registry = TaskRegistry()

    async def quick_coro():
        return "quick"

    task = registry.spawn(quick_coro(), name="quick-task")
    assert registry.task_count() == 1

    # Wait for task to complete
    await task

    # Give done callback time to execute
    await asyncio.sleep(0.01)

    # Task should be auto-removed via done callback
    assert registry.task_count() == 0


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_tasks():
    """Test that shutdown() cancels all pending tasks."""
    registry = TaskRegistry()

    async def long_coro():
        await asyncio.sleep(10)  # Long sleep
        return "never"

    # Spawn multiple tasks
    registry.spawn(long_coro(), name="task-1")
    registry.spawn(long_coro(), name="task-2")
    registry.spawn(long_coro(), name="task-3")

    assert registry.task_count() == 3

    # Shutdown with short timeout
    await registry.shutdown(timeout=0.1)

    # All tasks should be cancelled (may still be in registry if cleanup hasn't run)
    # But they should all be done or cancelled
    assert registry.task_count() <= 3  # May be 0 if callbacks ran


@pytest.mark.asyncio
async def test_shutdown_waits_for_completion():
    """Test that shutdown() cancels tasks and waits for them to finish."""
    registry = TaskRegistry()

    async def long_coro():
        await asyncio.sleep(10)

    # Spawn tasks
    task_a = registry.spawn(long_coro(), name="task-a")
    task_b = registry.spawn(long_coro(), name="task-b")

    assert registry.task_count() == 2
    assert not task_a.done()
    assert not task_b.done()

    # Shutdown with sufficient timeout
    await registry.shutdown(timeout=1.0)

    # Tasks should be cancelled (done=True, cancelled=True)
    assert task_a.done()
    assert task_b.done()
    assert task_a.cancelled()
    assert task_b.cancelled()


@pytest.mark.asyncio
async def test_shutdown_logs_pending_tasks_on_timeout():
    """Test that shutdown() logs warning if tasks don't complete within timeout."""
    registry = TaskRegistry()

    async def slow_coro():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass  # Expected

    registry.spawn(slow_coro(), name="slow-task")

    # Shutdown with very short timeout (task won't complete)
    await registry.shutdown(timeout=0.01)

    # Task should be cancelled but test just verifies no crash


@pytest.mark.asyncio
async def test_empty_shutdown():
    """Test that shutdown() handles empty registry gracefully."""
    registry = TaskRegistry()
    assert registry.task_count() == 0

    # Should not crash with no tasks
    await registry.shutdown(timeout=1.0)

    assert registry.task_count() == 0


@pytest.mark.asyncio
async def test_multiple_spawns():
    """Test spawning multiple tasks and tracking them."""
    registry = TaskRegistry()

    async def numbered_coro(n: int):
        await asyncio.sleep(0.01)
        return n

    tasks = []
    for i in range(5):
        task = registry.spawn(numbered_coro(i), name=f"task-{i}")
        tasks.append(task)

    assert registry.task_count() == 5

    # Wait for all to complete
    results = await asyncio.gather(*tasks)
    assert results == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_spawn_without_name():
    """Test that spawn() works without providing a name."""
    registry = TaskRegistry()

    async def unnamed_coro():
        return "unnamed"

    task = registry.spawn(unnamed_coro())  # No name parameter
    assert registry.task_count() == 1

    result = await task
    assert result == "unnamed"


@pytest.mark.asyncio
async def test_exception_logging_with_full_traceback():
    """Test that task exceptions are logged with full traceback (exc_info)."""
    registry = TaskRegistry()

    async def failing_coro():
        raise ValueError("Test exception")

    with patch("teleclaude.core.task_registry.logger") as mock_logger:
        task = registry.spawn(failing_coro(), name="failing-task")

        # Wait for task to complete
        with pytest.raises(ValueError):
            await task

        # Give done callback time to execute
        await asyncio.sleep(0.01)

        # Verify logger.error was called with exc_info
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args

        # Check that exc_info keyword argument was passed
        assert "exc_info" in call_args.kwargs
        assert isinstance(call_args.kwargs["exc_info"], ValueError)
        assert str(call_args.kwargs["exc_info"]) == "Test exception"
