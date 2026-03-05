"""Tests for personal_pipeline: exception isolation, rejection logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude_events.cartridge_loader import LoadedCartridge
from teleclaude_events.cartridge_manifest import CartridgeManifest
from teleclaude_events.envelope import EventEnvelope
from teleclaude_events.personal_pipeline import PersonalPipeline, load_personal_pipeline
from teleclaude_events.pipeline import PipelineContext


def _make_loaded(
    id: str,
    personal: bool = True,
    depends_on: list[str] | None = None,
    process: AsyncMock | None = None,
) -> LoadedCartridge:
    manifest = CartridgeManifest(
        id=id,
        description=f"Test cartridge {id}",
        personal=personal,
        depends_on=depends_on or [],
    )
    return LoadedCartridge(
        manifest=manifest,
        module_path=Path("/fake"),
        process=process or AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_personal_pipeline_exception_isolation() -> None:
    """Exception in one personal cartridge does not abort others."""
    failing = _make_loaded("fail", process=AsyncMock(side_effect=RuntimeError("boom")))
    succeeding = _make_loaded("ok")

    pipeline = PersonalPipeline(member_id="alice@example.com", cartridges=[failing, succeeding])
    event = MagicMock(spec=EventEnvelope)
    context = MagicMock(spec=PipelineContext)

    # Should not raise despite the first cartridge failing
    await pipeline.run(event, context)

    succeeding.process.assert_awaited_once_with(event, context)


@pytest.mark.asyncio
async def test_personal_pipeline_runs_all_cartridges() -> None:
    """All personal cartridges are invoked when none fail."""
    c1 = _make_loaded("c1")
    c2 = _make_loaded("c2")

    pipeline = PersonalPipeline(member_id="alice@example.com", cartridges=[c1, c2])
    event = MagicMock(spec=EventEnvelope)
    context = MagicMock(spec=PipelineContext)

    await pipeline.run(event, context)

    c1.process.assert_awaited_once()
    c2.process.assert_awaited_once()


def test_load_personal_pipeline_rejects_non_personal(tmp_path: Path) -> None:
    """Cartridge with personal=False is rejected from personal pipeline."""
    from unittest.mock import patch

    domain_cartridge = _make_loaded("domain-only", personal=False)

    with patch(
        "teleclaude_events.personal_pipeline.discover_cartridges",
        return_value=[domain_cartridge],
    ):
        pipeline = load_personal_pipeline("alice@example.com", tmp_path)

    assert len(pipeline.cartridges) == 0


def test_load_personal_pipeline_rejects_depends_on(tmp_path: Path) -> None:
    """Cartridge with depends_on is rejected (leaf node required)."""
    from unittest.mock import patch

    non_leaf = _make_loaded("non-leaf", personal=True, depends_on=["other"])

    with patch(
        "teleclaude_events.personal_pipeline.discover_cartridges",
        return_value=[non_leaf],
    ):
        pipeline = load_personal_pipeline("alice@example.com", tmp_path)

    assert len(pipeline.cartridges) == 0


def test_load_personal_pipeline_accepts_valid_cartridge(tmp_path: Path) -> None:
    """Valid personal leaf cartridge is accepted."""
    from unittest.mock import patch

    valid = _make_loaded("valid", personal=True, depends_on=[])

    with patch(
        "teleclaude_events.personal_pipeline.discover_cartridges",
        return_value=[valid],
    ):
        pipeline = load_personal_pipeline("alice@example.com", tmp_path)

    assert len(pipeline.cartridges) == 1
    assert pipeline.cartridges[0].manifest.id == "valid"
