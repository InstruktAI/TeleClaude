"""Characterization tests for teleclaude.core.task_registry."""

from __future__ import annotations

import asyncio

import pytest

from teleclaude.core.task_registry import TaskRegistry


class TestTaskRegistry:
    @pytest.mark.unit
    async def test_initial_task_count_is_zero(self):
        registry = TaskRegistry()
        assert registry.task_count() == 0

    @pytest.mark.unit
    async def test_spawn_increments_task_count(self):
        registry = TaskRegistry()

        async def noop():
            pass

        registry.spawn(noop())
        assert registry.task_count() == 1
        await asyncio.sleep(0.01)

    @pytest.mark.unit
    async def test_completed_task_removed_from_registry(self):
        registry = TaskRegistry()

        async def quick():
            pass

        task = registry.spawn(quick())
        await task
        assert registry.task_count() == 0

    @pytest.mark.unit
    async def test_spawn_with_name_returns_task(self):
        registry = TaskRegistry()

        async def named_task():
            await asyncio.sleep(0.001)

        task = registry.spawn(named_task(), name="my-task")
        assert task.get_name() == "my-task"
        await task

    @pytest.mark.unit
    async def test_shutdown_cancels_running_tasks(self):
        registry = TaskRegistry()

        async def long_running():
            await asyncio.sleep(60)

        registry.spawn(long_running())
        await registry.shutdown(timeout=0.1)
        assert registry.task_count() == 0

    @pytest.mark.unit
    async def test_shutdown_with_no_tasks_does_nothing(self):
        registry = TaskRegistry()
        count_before = registry.task_count()
        await registry.shutdown()  # Contract: does not raise with no tasks
        assert registry.task_count() == count_before
