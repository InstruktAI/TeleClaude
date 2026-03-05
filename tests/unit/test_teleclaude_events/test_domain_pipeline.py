"""Tests for domain pipeline runtime: parallel execution, exception isolation, autonomy."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from teleclaude_events.cartridge_loader import LoadedCartridge
from teleclaude_events.cartridge_manifest import CartridgeManifest
from teleclaude_events.domain_config import (
    AutonomyLevel,
    AutonomyMatrix,
    DomainConfig,
    DomainGuardianConfig,
)
from teleclaude_events.domain_pipeline import DomainPipeline, DomainPipelineRunner
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import PipelineContext


def _make_event(domain: str = "software") -> EventEnvelope:
    return EventEnvelope(
        event="task.created",
        source="daemon",
        level=EventLevel.WORKFLOW,
        domain=domain,
    )


def _make_context() -> PipelineContext:
    return PipelineContext(
        catalog=MagicMock(),
        db=MagicMock(),
    )


def _make_cartridge(id: str, process_fn: Any = None) -> LoadedCartridge:
    if process_fn is None:
        async def _passthrough(event: Any, context: Any) -> Any:
            return event
        process_fn = _passthrough

    manifest = CartridgeManifest(id=id, description=f"Test {id}")
    return LoadedCartridge(manifest=manifest, module_path=Path("/fake"), process=process_fn)


def _make_domain_config(
    name: str = "software",
    autonomy: AutonomyMatrix | None = None,
) -> DomainConfig:
    return DomainConfig(
        name=name,
        autonomy=autonomy or AutonomyMatrix(),
    )


class TestDomainPipeline:
    @pytest.mark.asyncio
    async def test_single_cartridge_runs_and_returns_event(self) -> None:
        cartridge = _make_cartridge("c1")
        domain = _make_domain_config()
        pipeline = DomainPipeline(domain=domain, levels=[[cartridge]])
        event = _make_event()
        result = await pipeline.run(event, _make_context())
        assert result is not None

    @pytest.mark.asyncio
    async def test_exception_in_cartridge_does_not_abort(self) -> None:
        async def _raise(event: Any, context: Any) -> Any:
            raise RuntimeError("cartridge exploded")

        bad_cartridge = _make_cartridge("bad", _raise)
        domain = _make_domain_config()
        pipeline = DomainPipeline(domain=domain, levels=[[bad_cartridge]])
        event = _make_event()
        # Should not raise; result may be None since the only cartridge failed
        result = await pipeline.run(event, _make_context())
        assert result is None

    @pytest.mark.asyncio
    async def test_parallel_level_runs_all_cartridges(self) -> None:
        called: list[str] = []

        def _make_recording_fn(cid: str) -> Any:
            async def _fn(event: Any, context: Any) -> Any:
                called.append(cid)
                return event
            return _fn

        c1 = _make_cartridge("c1", _make_recording_fn("c1"))
        c2 = _make_cartridge("c2", _make_recording_fn("c2"))
        domain = _make_domain_config()
        pipeline = DomainPipeline(domain=domain, levels=[[c1, c2]])
        await pipeline.run(_make_event(), _make_context())
        assert set(called) == {"c1", "c2"}

    @pytest.mark.asyncio
    async def test_manual_autonomy_skips_cartridge(self) -> None:
        called: list[str] = []

        async def _track(event: Any, context: Any) -> Any:
            called.append("ran")
            return event

        cartridge = _make_cartridge("my-c", _track)
        matrix = AutonomyMatrix(by_cartridge={"software/my-c": AutonomyLevel.manual})
        domain = _make_domain_config(autonomy=matrix)
        pipeline = DomainPipeline(domain=domain, levels=[[cartridge]])
        await pipeline.run(_make_event(), _make_context())
        assert called == []

    @pytest.mark.asyncio
    async def test_autonomous_autonomy_runs_cartridge_silently(self) -> None:
        called: list[str] = []

        async def _track(event: Any, context: Any) -> Any:
            called.append("ran")
            return event

        cartridge = _make_cartridge("my-c", _track)
        matrix = AutonomyMatrix(by_cartridge={"software/my-c": AutonomyLevel.autonomous})
        domain = _make_domain_config(autonomy=matrix)
        pipeline = DomainPipeline(domain=domain, levels=[[cartridge]])
        result = await pipeline.run(_make_event(), _make_context())
        assert called == ["ran"]
        assert result is not None

    @pytest.mark.asyncio
    async def test_guardian_config_defaults_when_absent(self) -> None:
        """DomainPipelineContext carries default guardian config when none is set."""
        captured_ctx: list[Any] = []

        async def _capture_ctx(event: Any, context: Any) -> Any:
            captured_ctx.append(context)
            return event

        cartridge = _make_cartridge("c", _capture_ctx)
        domain = DomainConfig(name="software")  # no guardian set
        pipeline = DomainPipeline(domain=domain, levels=[[cartridge]])
        await pipeline.run(_make_event(), _make_context())
        assert len(captured_ctx) == 1
        ctx = captured_ctx[0]
        assert ctx.guardian_config.agent == "claude"
        assert ctx.guardian_config.enabled is True

    @pytest.mark.asyncio
    async def test_guardian_config_passed_from_domain(self) -> None:
        captured_ctx: list[Any] = []

        async def _capture_ctx(event: Any, context: Any) -> Any:
            captured_ctx.append(context)
            return event

        cartridge = _make_cartridge("c", _capture_ctx)
        guardian = DomainGuardianConfig(agent="opus", mode="deep", enabled=False)
        domain = DomainConfig(name="software", guardian=guardian)
        pipeline = DomainPipeline(domain=domain, levels=[[cartridge]])
        await pipeline.run(_make_event(), _make_context())
        ctx = captured_ctx[0]
        assert ctx.guardian_config.agent == "opus"
        assert ctx.guardian_config.enabled is False


class TestDomainPipelineRunner:
    @pytest.mark.asyncio
    async def test_empty_runner_returns_empty_dict(self) -> None:
        runner = DomainPipelineRunner()
        results = await runner.run_all(_make_event(), _make_context())
        assert results == {}

    @pytest.mark.asyncio
    async def test_multiple_domains_run_in_parallel(self) -> None:
        call_order: list[str] = []

        def _make_fn(name: str) -> Any:
            async def _fn(event: Any, context: Any) -> Any:
                call_order.append(name)
                return event
            return _fn

        runner = DomainPipelineRunner()
        for name in ["software", "ops", "support"]:
            c = _make_cartridge(f"c-{name}", _make_fn(name))
            domain = _make_domain_config(name=name)
            p = DomainPipeline(domain=domain, levels=[[c]])
            runner.register_domain_pipeline(name, p)

        results = await runner.run_all(_make_event(), _make_context())
        assert set(results.keys()) == {"software", "ops", "support"}
        assert set(call_order) == {"software", "ops", "support"}

    @pytest.mark.asyncio
    async def test_domain_error_does_not_abort_others(self) -> None:
        async def _ok(event: Any, context: Any) -> Any:
            return event

        async def _fail(event: Any, context: Any) -> Any:
            raise RuntimeError("domain exploded")

        runner = DomainPipelineRunner()
        good_c = _make_cartridge("good", _ok)
        bad_c = _make_cartridge("bad", _fail)

        good_domain = _make_domain_config(name="good")
        bad_domain = _make_domain_config(name="bad")
        runner.register_domain_pipeline("good", DomainPipeline(domain=good_domain, levels=[[good_c]]))
        runner.register_domain_pipeline("bad", DomainPipeline(domain=bad_domain, levels=[[bad_c]]))

        results = await runner.run_all(_make_event(), _make_context())
        assert results["good"] is not None
        assert results["bad"] is None

    @pytest.mark.asyncio
    async def test_system_pipeline_unaffected_by_domain_error(self) -> None:
        """System pipeline result is unaffected even if domain pipeline raises."""
        from teleclaude_events.pipeline import Pipeline

        class _PassCartridge:
            name = "pass"

            async def process(self, event: Any, context: Any) -> Any:
                return event

        async def _domain_fail(event: Any, context: Any) -> Any:
            raise RuntimeError("domain error")

        runner = DomainPipelineRunner()
        bad_c = _make_cartridge("bad", _domain_fail)
        bad_domain = _make_domain_config(name="bad")
        runner.register_domain_pipeline("bad", DomainPipeline(domain=bad_domain, levels=[[bad_c]]))

        ctx = _make_context()
        pipeline = Pipeline([_PassCartridge()], ctx, domain_runner=runner)
        event = _make_event()
        result = await pipeline.execute(event)
        # System pipeline result must not be None
        assert result is not None

        # Wait a moment for background task to complete
        import asyncio
        await asyncio.sleep(0.05)
