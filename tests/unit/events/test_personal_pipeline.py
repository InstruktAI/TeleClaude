"""Characterization tests for teleclaude.events.personal_pipeline."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from teleclaude.events.cartridge_loader import LoadedCartridge
from teleclaude.events.cartridge_manifest import CartridgeManifest
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.personal_pipeline import PersonalPipeline, load_personal_pipeline
from teleclaude.events.pipeline import PipelineContext


def _make_envelope() -> EventEnvelope:
    return EventEnvelope(event="test.event", source="test", level=EventLevel.OPERATIONAL)


def _make_context() -> PipelineContext:
    return PipelineContext(catalog=MagicMock(), db=MagicMock())


def _make_personal_cartridge(cid: str = "pc1") -> LoadedCartridge:
    async def process(_event: EventEnvelope, _ctx: PipelineContext) -> None:
        return None

    return LoadedCartridge(
        manifest=CartridgeManifest(id=cid, description="personal cart", personal=True),
        module_path=Path("."),
        process=process,
    )


class TestPersonalPipeline:
    def test_member_id_stored(self) -> None:
        pipeline = PersonalPipeline("user@example.com", [])
        assert pipeline.member_id == "user@example.com"

    def test_cartridges_stored(self) -> None:
        c = _make_personal_cartridge()
        pipeline = PersonalPipeline("user@example.com", [c])
        assert len(pipeline.cartridges) == 1

    @pytest.mark.asyncio
    async def test_run_calls_all_cartridges(self) -> None:
        event = _make_envelope()
        mock1 = AsyncMock(return_value=None)
        mock2 = AsyncMock(return_value=None)
        c1 = LoadedCartridge(
            manifest=CartridgeManifest(id="c1", description="d", personal=True),
            module_path=Path("."),
            process=mock1,
        )
        c2 = LoadedCartridge(
            manifest=CartridgeManifest(id="c2", description="d", personal=True),
            module_path=Path("."),
            process=mock2,
        )
        pipeline = PersonalPipeline("user@example.com", [c1, c2])
        await pipeline.run(event, _make_context())
        mock1.assert_called_once()
        mock2.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_continues_after_cartridge_exception(self) -> None:
        event = _make_envelope()
        mock_ok = AsyncMock(return_value=None)
        c1 = LoadedCartridge(
            manifest=CartridgeManifest(id="c1", description="d", personal=True),
            module_path=Path("."),
            process=AsyncMock(side_effect=RuntimeError("fail")),
        )
        c2 = LoadedCartridge(
            manifest=CartridgeManifest(id="c2", description="d", personal=True),
            module_path=Path("."),
            process=mock_ok,
        )
        pipeline = PersonalPipeline("user@example.com", [c1, c2])
        # Should not raise; should run c2 despite c1 failing
        await pipeline.run(event, _make_context())
        mock_ok.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_returns_none(self) -> None:
        pipeline = PersonalPipeline("user@example.com", [])
        result = await pipeline.run(_make_envelope(), _make_context())
        assert result is None


class TestLoadPersonalPipeline:
    def test_rejects_non_personal_cartridges(self, tmp_path: Path) -> None:
        cdir = tmp_path / "not-personal"
        cdir.mkdir()
        (cdir / "manifest.yaml").write_text(yaml.dump({"id": "not-personal", "description": "d", "personal": False}))
        (cdir / "cartridge.py").write_text(dedent("async def process(event, ctx): return event"))
        pipeline = load_personal_pipeline("user@example.com", tmp_path)
        assert len(pipeline.cartridges) == 0

    def test_rejects_cartridges_with_depends_on(self, tmp_path: Path) -> None:
        cdir = tmp_path / "has-deps"
        cdir.mkdir()
        (cdir / "manifest.yaml").write_text(
            yaml.dump({"id": "has-deps", "description": "d", "personal": True, "depends_on": ["other"]})
        )
        (cdir / "cartridge.py").write_text(dedent("async def process(event, ctx): return event"))
        pipeline = load_personal_pipeline("user@example.com", tmp_path)
        assert len(pipeline.cartridges) == 0

    def test_returns_personal_pipeline_with_member_id(self, tmp_path: Path) -> None:
        pipeline = load_personal_pipeline("member@example.com", tmp_path / "missing")
        assert pipeline.member_id == "member@example.com"

    def test_empty_path_returns_empty_pipeline(self, tmp_path: Path) -> None:
        pipeline = load_personal_pipeline("user@example.com", tmp_path / "nonexistent")
        assert pipeline.cartridges == []
