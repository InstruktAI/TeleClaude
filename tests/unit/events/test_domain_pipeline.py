"""Characterization tests for teleclaude.events.domain_pipeline."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.cartridge_loader import LoadedCartridge
from teleclaude.events.cartridge_manifest import CartridgeManifest
from teleclaude.events.domain_config import AutonomyLevel, AutonomyMatrix, DomainConfig
from teleclaude.events.domain_pipeline import (
    DomainPipeline,
    DomainPipelineContext,
    DomainPipelineRunner,
)
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import PipelineContext


def _make_envelope() -> EventEnvelope:
    return EventEnvelope(event="test.event", source="test", level=EventLevel.OPERATIONAL)


def _make_base_context() -> PipelineContext:
    return PipelineContext(catalog=MagicMock(), db=MagicMock())


def _make_loaded_cartridge(
    cid: str = "c1",
    result: EventEnvelope | None = None,
    domain_affinity: list[str] | None = None,
) -> LoadedCartridge:
    process = AsyncMock(return_value=result)
    manifest = CartridgeManifest(
        id=cid,
        description="test",
        domain_affinity=domain_affinity or [],
    )
    return LoadedCartridge(manifest=manifest, module_path=Path("."), process=process)


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
        manifest = CartridgeManifest(id="c1", description="test")
        cartridge = LoadedCartridge(manifest=manifest, module_path=Path("."), process=mock_process)
        domain_cfg = DomainConfig(name="eng")
        pipeline = DomainPipeline(domain=domain_cfg, levels=[[cartridge]])
        await pipeline.run(event, _make_base_context())
        mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_returns_cartridge_result(self) -> None:
        event = _make_envelope()
        output = _make_envelope()
        cartridge = _make_loaded_cartridge("c1", result=output)
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
                by_cartridge={"eng/c1": AutonomyLevel.manual},
            ),
        )
        mock_process = AsyncMock(return_value=event)
        manifest = CartridgeManifest(id="c1", description="test")
        cartridge = LoadedCartridge(manifest=manifest, module_path=Path("."), process=mock_process)
        pipeline = DomainPipeline(domain=domain_cfg, levels=[[cartridge]])
        result = await pipeline.run(event, _make_base_context())
        assert result is None
        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_handles_cartridge_exception(self) -> None:
        event = _make_envelope()
        mock_process = AsyncMock(side_effect=RuntimeError("boom"))
        manifest = CartridgeManifest(id="c1", description="test")
        cartridge = LoadedCartridge(manifest=manifest, module_path=Path("."), process=mock_process)
        domain_cfg = DomainConfig(name="eng")
        pipeline = DomainPipeline(domain=domain_cfg, levels=[[cartridge]])
        result = await pipeline.run(event, _make_base_context())
        assert result is None


class TestDomainPipelineRunner:
    def test_register_domain_pipeline(self) -> None:
        runner = DomainPipelineRunner()
        pipeline = MagicMock()
        runner.register_domain_pipeline("eng", pipeline)
        assert runner._pipelines["eng"] is pipeline

    def test_register_personal_pipeline(self) -> None:
        runner = DomainPipelineRunner()
        personal = MagicMock()
        runner.register_personal_pipeline("user@example.com", personal)
        assert runner._personal_pipelines["user@example.com"] is personal

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
