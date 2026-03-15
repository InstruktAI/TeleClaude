"""Characterization tests for teleclaude.events.pipeline."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import Pipeline, PipelineContext


def _make_envelope() -> EventEnvelope:
    return EventEnvelope(event="test.event", source="test", level=EventLevel.OPERATIONAL)


def _make_context() -> PipelineContext:
    return PipelineContext(
        catalog=MagicMock(),
        db=MagicMock(),
    )


def _make_cartridge(name: str = "c", result: EventEnvelope | None = None) -> MagicMock:
    cartridge = MagicMock()
    cartridge.name = name
    cartridge.process = AsyncMock(return_value=result)
    return cartridge


class TestPipeline:
    @pytest.mark.asyncio
    async def test_execute_with_no_cartridges_returns_event(self) -> None:
        pipeline = Pipeline([], _make_context())
        event = _make_envelope()
        result = await pipeline.execute(event)
        assert result == event

    @pytest.mark.asyncio
    async def test_execute_calls_cartridge_with_event(self) -> None:
        event = _make_envelope()
        cartridge = _make_cartridge(result=event)
        pipeline = Pipeline([cartridge], _make_context())
        await pipeline.execute(event)
        cartridge.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_returns_cartridge_result(self) -> None:
        original = _make_envelope()
        modified = _make_envelope()
        modified_copy = modified.model_copy(update={"domain": "changed"})
        cartridge = _make_cartridge(result=modified_copy)
        pipeline = Pipeline([cartridge], _make_context())
        result = await pipeline.execute(original)
        assert result is modified_copy

    @pytest.mark.asyncio
    async def test_execute_stops_when_cartridge_returns_none(self) -> None:
        event = _make_envelope()
        c1 = _make_cartridge("c1", result=None)
        c2 = _make_cartridge("c2", result=event)
        pipeline = Pipeline([c1, c2], _make_context())
        result = await pipeline.execute(event)
        assert result is None
        c2.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_chains_cartridges(self) -> None:
        event = _make_envelope()
        step1_result = _make_envelope()
        step2_result = _make_envelope()
        c1 = _make_cartridge("c1", result=step1_result)
        c2 = MagicMock()
        c2.name = "c2"
        c2.process = AsyncMock(return_value=step2_result)
        pipeline = Pipeline([c1, c2], _make_context())
        result = await pipeline.execute(event)
        assert result is step2_result
        # c2 received c1's output
        c2.process.assert_called_once_with(step1_result, pipeline._context)

    def test_register_appends_cartridge(self) -> None:
        pipeline = Pipeline([], _make_context())
        cartridge = _make_cartridge()
        pipeline.register(cartridge)
        assert len(pipeline._cartridges) == 1
        assert pipeline._cartridges[0] is cartridge

    @pytest.mark.asyncio
    async def test_execute_fans_out_to_domain_runner_when_result_non_none(self) -> None:
        event = _make_envelope()
        cartridge = _make_cartridge(result=event)
        domain_runner = MagicMock()
        domain_runner.run_all = AsyncMock(return_value={})
        pipeline = Pipeline([cartridge], _make_context(), domain_runner=domain_runner)
        result = await pipeline.execute(event)
        assert result is event
        # Fan-out is fire-and-forget via asyncio.create_task;
        # give the event loop a chance to run it
        await asyncio.sleep(0)
        domain_runner.run_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_does_not_fanout_when_result_is_none(self) -> None:
        event = _make_envelope()
        cartridge = _make_cartridge(result=None)
        domain_runner = MagicMock()
        domain_runner.run_all = AsyncMock(return_value={})
        pipeline = Pipeline([cartridge], _make_context(), domain_runner=domain_runner)
        await pipeline.execute(event)
        await asyncio.sleep(0)
        domain_runner.run_all.assert_not_called()
