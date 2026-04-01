"""Characterization tests for creative-state routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import CreativePhase
from teleclaude.core.next_machine.create import _derive_creative_phase, _find_next_creative_slug, next_create


def test_derive_creative_phase_requires_design_discovery_when_spec_is_missing(tmp_path: Path) -> None:
    """No design spec → DESIGN_DISCOVERY_REQUIRED regardless of state."""
    phase = _derive_creative_phase(tmp_path / "workspace", False, {})

    assert phase == CreativePhase.DESIGN_DISCOVERY_REQUIRED


def test_derive_creative_phase_reports_complete_when_all_artifacts_are_approved(tmp_path: Path) -> None:
    """All artifacts present and approved → CREATIVE_COMPLETE."""
    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "art").mkdir(parents=True)
    (workspace_dir / "html").mkdir(parents=True)
    (workspace_dir / "art" / "moodboard.png").write_text("img", encoding="utf-8")
    (workspace_dir / "html" / "index.html").write_text("<html />", encoding="utf-8")

    phase = _derive_creative_phase(
        workspace_dir,
        True,
        {"design_spec": {"confirmed": True}, "art": {"approved": True}, "visuals": {"approved": True}},
    )

    assert phase == CreativePhase.CREATIVE_COMPLETE


@pytest.mark.asyncio
async def test_find_next_creative_slug_skips_done_items_and_returns_first_active_creative_item() -> None:
    """Delivered items are skipped; first item with an input artifact and active phase is returned."""
    mock_db = AsyncMock()
    mock_db.list_roadmap.return_value = [
        {"slug": "done-item"},
        {"slug": "creative-item"},
    ]
    mock_db.delivered_slugs.return_value = {"done-item"}
    mock_db.artifact_exists = AsyncMock(side_effect=lambda slug, name: slug == "creative-item" and name == "input")
    mock_db.read_state.side_effect = lambda slug: (
        {"creative": {"phase": CreativePhase.ART_GENERATION_REQUIRED.value}} if slug == "creative-item" else None
    )

    result = await _find_next_creative_slug(mock_db)

    assert result == "creative-item"


@pytest.mark.asyncio
async def test_next_create_updates_creative_phase_and_dispatches_art_generation(tmp_path: Path) -> None:
    """Confirmed design spec → phase advances to ART_GENERATION_REQUIRED and state is persisted."""
    mock_todos_db = AsyncMock()
    mock_todos_db.artifact_exists = AsyncMock(side_effect=lambda _, name: name in ("input", "design-spec"))
    mock_todos_db.read_state.return_value = {"creative": {"design_spec": {"confirmed": True}}}
    db = AsyncMock()

    with (
        patch("teleclaude.core.todos_db.get_todos_db", new_callable=AsyncMock, return_value=mock_todos_db),
        patch("teleclaude.core.next_machine.create.compose_agent_guidance", return_value="runtime guidance"),
    ):
        result = await next_create(db, "slug-a", str(tmp_path))

    mock_todos_db.write_state.assert_called_once()
    written_state = mock_todos_db.write_state.call_args[0][1]
    assert written_state.get("creative", {}).get("phase") == CreativePhase.ART_GENERATION_REQUIRED.value
    assert result
