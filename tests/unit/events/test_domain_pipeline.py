"""Characterization tests for teleclaude.events.domain_pipeline."""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.domain_config import AutonomyLevel, AutonomyMatrix, DomainConfig
from teleclaude.events.domain_handlers import DomainHandlerSpec
from teleclaude.events.domain_pipeline import DomainPipeline, DomainPipelineContext, DomainPipelineRunner
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import PipelineContext


def _make_envelope() -> EventEnvelope:
    return EventEnvelope(event="test.event", source="test", level=EventLevel.OPERATIONAL)


def _make_base_context() -> PipelineContext:
    return PipelineContext(catalog=MagicMock(), db=MagicMock())


def _make_handler(
    cid: str = "c1",
    result: EventEnvelope | None = None,
) -> DomainHandlerSpec:
    process = AsyncMock(return_value=result)
    return DomainHandlerSpec(handler_id=cid, process=process)


class TestDomainPipelineContext:
    def test_inherits_pipeline_context_fields(self) -> None:
        base_field_names = {f.name for f in fields(PipelineContext)}
        ctx_field_names = {f.name for f in fields(DomainPipelineContext)}
        assert base_field_names.issubset(ctx_field_names)

    def test_domain_name_default_empty(self) -> None:
        ctx = DomainPipelineContext(catalog=MagicMock(), db=MagicMock())
        assert ctx.domain_name == ""

    def test_has_autonomy_matrix(self) -> None:
        ctx = DomainPipelineContext(catalog=MagicMock(), db=MagicMock())
        assert isinstance(ctx.autonomy_matrix, AutonomyMatrix)


class TestDomainPipeline:
    @pytest.mark.asyncio
    async def test_run_with_no_levels_returns_event(self) -> None:
        event = _make_envelope()
        domain_cfg = DomainConfig(name="eng")
        pipeline = DomainPipeline(domain=domain_cfg, levels=[])
        result = await pipeline.run(event, _make_base_context())
        assert result is event

    @pytest.mark.asyncio
    async def test_run_calls_cartridge_process(self) -> None:
        event = _make_envelope()
        mock_process = AsyncMock(return_value=event)
        cartridge = DomainHandlerSpec(handler_id="c1", process=mock_process)
        domain_cfg = DomainConfig(name="eng")
        pipeline = DomainPipeline(domain=domain_cfg, levels=[[cartridge]])
        await pipeline.run(event, _make_base_context())
        mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_returns_cartridge_result(self) -> None:
        event = _make_envelope()
        output = _make_envelope()
        cartridge = _make_handler("c1", result=output)
        domain_cfg = DomainConfig(name="eng")
        pipeline = DomainPipeline(domain=domain_cfg, levels=[[cartridge]])
        result = await pipeline.run(event, _make_base_context())
        assert result is output

    @pytest.mark.asyncio
    async def test_run_skips_cartridge_with_manual_autonomy(self) -> None:
        event = _make_envelope()
        domain_cfg = DomainConfig(
            name="eng",
            autonomy=AutonomyMatrix(
                by_cartridge={"eng/c1": AutonomyLevel.MANUAL},
            ),
        )
        mock_process = AsyncMock(return_value=event)
        cartridge = DomainHandlerSpec(handler_id="c1", process=mock_process)
        pipeline = DomainPipeline(domain=domain_cfg, levels=[[cartridge]])
        result = await pipeline.run(event, _make_base_context())
        assert result is None
        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_propagates_cartridge_exception(self) -> None:
        event = _make_envelope()
        mock_process = AsyncMock(side_effect=RuntimeError("boom"))
        cartridge = DomainHandlerSpec(handler_id="c1", process=mock_process)
        domain_cfg = DomainConfig(name="eng")
        pipeline = DomainPipeline(domain=domain_cfg, levels=[[cartridge]])
        with pytest.raises(RuntimeError, match="boom"):
            await pipeline.run(event, _make_base_context())


class TestDomainPipelineRunner:
    def test_register_domain_pipeline(self) -> None:
        runner = DomainPipelineRunner()
        pipeline = MagicMock()
        runner.register_domain_pipeline("eng", pipeline)
        assert runner._pipelines["eng"] is pipeline

    @pytest.mark.asyncio
    async def test_run_all_empty_returns_empty_dict(self) -> None:
        runner = DomainPipelineRunner()
        result = await runner.run_all(_make_envelope(), _make_base_context())
        assert result == {}

    @pytest.mark.asyncio
    async def test_run_all_returns_results_keyed_by_domain(self) -> None:
        event = _make_envelope()
        output = _make_envelope()
        runner = DomainPipelineRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(return_value=output)
        runner.register_domain_pipeline("eng", mock_pipeline)
        results = await runner.run_all(event, _make_base_context())
        assert "eng" in results
        assert results["eng"] is output

    @pytest.mark.asyncio
    async def test_run_for_domain_returns_none_for_missing_domain(self) -> None:
        runner = DomainPipelineRunner()
        result = await runner.run_for_domain("missing", _make_envelope(), _make_base_context())
        assert result is None

    @pytest.mark.asyncio
    async def test_run_for_domain_calls_correct_pipeline(self) -> None:
        event = _make_envelope()
        output = _make_envelope()
        runner = DomainPipelineRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(return_value=output)
        runner.register_domain_pipeline("eng", mock_pipeline)
        result = await runner.run_for_domain("eng", event, _make_base_context())
        assert result is output


# ---------------------------------------------------------------------------
# Specs (xfail) for guaranteed-event-consumption
# These pin the post-implementation contract; remove pytestmark when satisfied.
# ---------------------------------------------------------------------------


class TestDomainPipelineHandlerExceptionPropagationSpecs:
    """Domain handler exceptions must surface as delivery failures, not be swallowed.

    Verbatim requirement criterion (from `requirements.md`):

    > **No silent success at named sites.** Spawn failures in
    > `IntegrationTriggerCartridge._spawn_integrator`, lane-dispatch failures
    > in `LifecycleRouterCartridge._dispatch_router_lane`, and handler
    > exceptions in `DomainPipeline._run_handler` propagate as delivery
    > failures rather than being swallowed and treated as success. Deliberate
    > skips (e.g. `AutonomyLevel.MANUAL`) remain non-failures.
    """

    @pytest.mark.asyncio
    async def test_handler_exception_propagates_through_pipeline_run(self) -> None:
        """When a domain handler raises, ``DomainPipeline.run`` must raise rather than return None.

        The complementary contract — manual-autonomy still skips without
        raising — is pinned by the existing characterization
        ``test_run_skips_cartridge_with_manual_autonomy``.
        """
        event = _make_envelope()
        mock_process = AsyncMock(side_effect=RuntimeError("handler failure"))
        cartridge = DomainHandlerSpec(handler_id="c1", process=mock_process)
        domain_cfg = DomainConfig(name="eng")
        pipeline = DomainPipeline(domain=domain_cfg, levels=[[cartridge]])

        with pytest.raises(RuntimeError, match="handler failure"):
            await pipeline.run(event, _make_base_context())


class TestDomainPipelineRunnerExceptionPropagationSpecs:
    """``run_all`` must surface domain-pipeline exceptions for the ack boundary, not swallow them.

    Verbatim requirement criterion (from `requirements.md`):

    > **Durable delivery boundary.** An event is acknowledged (and removed
    > from the pending entry list) only after every required processing step
    > for that delivery has either succeeded or deliberately skipped. For v1,
    > "required processing" comprises the synchronous system pipeline and the
    > domain pipeline fan-out. A required cartridge that raises must propagate
    > its exception so the delivery is not acknowledged. A skip (returning
    > `None` to indicate the event is not for this cartridge, or a deliberate
    > manual/skipped autonomy decision) is not a failure.
    """

    @pytest.mark.asyncio
    async def test_run_all_propagates_when_a_domain_pipeline_raises(self) -> None:
        """A domain pipeline raising must cause ``run_all`` to raise, not return a None result."""
        runner = DomainPipelineRunner()
        failing_pipeline = MagicMock()
        failing_pipeline.run = AsyncMock(side_effect=RuntimeError("domain failure"))
        runner.register_domain_pipeline("eng", failing_pipeline)

        with pytest.raises(RuntimeError, match="domain failure"):
            await runner.run_all(_make_envelope(), _make_base_context())
