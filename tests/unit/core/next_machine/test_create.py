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
    db.list_sessions = AsyncMock(return_value=[])

    with (
        patch("teleclaude.core.todos_db.get_todos_db", new_callable=AsyncMock, return_value=mock_todos_db),
        patch("teleclaude.core.next_machine.create.compose_agent_guidance", return_value="runtime guidance"),
    ):
        result = await next_create(db, "slug-a", str(tmp_path))

    mock_todos_db.write_state.assert_called_once()
    written_state = mock_todos_db.write_state.call_args[0][1]
    assert written_state.get("creative", {}).get("phase") == CreativePhase.ART_GENERATION_REQUIRED.value
    assert result


# ---------------------------------------------------------------------------
# Session lifecycle — creative machine relays iteration and owns cleanup
# ---------------------------------------------------------------------------


class _FakeSession:  # pylint: disable=too-few-public-methods
    """Minimal stand-in for a core Session DTO."""

    def __init__(self, session_id: str, title: str, subdir: str) -> None:
        self.session_id = session_id
        self.title = title
        self.subdir = subdir


def _creative_workspace(tmp_path: Path, slug: str) -> Path:
    workspace = tmp_path / "workspace" / slug
    (workspace / "art").mkdir(parents=True)
    (workspace / "html").mkdir(parents=True)
    return workspace


@pytest.mark.asyncio
async def test_art_iteration_relays_to_live_artist(tmp_path: Path) -> None:
    """ART_ITERATION_REQUIRED must send feedback to the existing artist session via
    telec sessions send, not dispatch a fresh /next-create-art. Catches the context-loss
    bug where every iteration spawned a new artist session."""
    slug = "slug-iter"
    workspace = _creative_workspace(tmp_path, slug)
    (workspace / "art" / "mood.png").write_text("img", encoding="utf-8")

    mock_todos_db = AsyncMock()
    mock_todos_db.artifact_exists = AsyncMock(side_effect=lambda _s, name: name in ("input", "design-spec"))
    mock_todos_db.read_state.return_value = {
        "creative": {
            "design_spec": {"confirmed": True},
            "art": {"approved": False, "iteration_requested": True},
        },
    }
    mock_todos_db.write_state = AsyncMock()

    artist = _FakeSession("art-live", "/next-create-art slug-iter", f"workspace/{slug}")
    db = AsyncMock()
    db.list_sessions = AsyncMock(return_value=[artist])

    with (
        patch(
            "teleclaude.core.next_machine.create._derive_creative_phase",
            return_value=CreativePhase.ART_ITERATION_REQUIRED,
        ),
        patch("teleclaude.core.todos_db.get_todos_db", new_callable=AsyncMock, return_value=mock_todos_db),
        patch("teleclaude.core.next_machine.create.compose_agent_guidance", return_value="guidance"),
    ):
        result = await next_create(db, slug, str(tmp_path))

    assert "telec sessions send art-live" in result
    assert "telec sessions run" not in result
    assert "telec sessions end" not in result  # no end commands mid-iteration


@pytest.mark.asyncio
async def test_creative_complete_ends_all_slug_sessions_and_self(tmp_path: Path) -> None:
    """CREATIVE_COMPLETE must emit end commands for every live creative worker tied to
    the slug plus `telec sessions end self`. Without this the orchestrator would leave
    stale sessions and never close itself."""
    slug = "slug-done"
    workspace = _creative_workspace(tmp_path, slug)
    (workspace / "art" / "final.png").write_text("img", encoding="utf-8")
    (workspace / "html" / "index.html").write_text("<html />", encoding="utf-8")

    mock_todos_db = AsyncMock()
    mock_todos_db.artifact_exists = AsyncMock(side_effect=lambda _s, name: name in ("input", "design-spec"))
    mock_todos_db.read_state.return_value = {
        "creative": {
            "design_spec": {"confirmed": True},
            "art": {"approved": True},
            "visuals": {"approved": True},
        },
    }
    mock_todos_db.write_state = AsyncMock()

    artist = _FakeSession("art-1", "/next-create-art slug-done", f"workspace/{slug}")
    frontender = _FakeSession("fe-1", "/next-create-html slug-done", f"workspace/{slug}")
    unrelated = _FakeSession("other", "/next-build other", "trees/other")
    db = AsyncMock()
    db.list_sessions = AsyncMock(return_value=[artist, frontender, unrelated])

    with (
        patch("teleclaude.core.todos_db.get_todos_db", new_callable=AsyncMock, return_value=mock_todos_db),
        patch("teleclaude.core.next_machine.create.compose_agent_guidance", return_value="guidance"),
    ):
        result = await next_create(db, slug, str(tmp_path))

    assert "telec sessions end art-1" in result
    assert "telec sessions end fe-1" in result
    assert "telec sessions end self" in result
    # Unrelated sessions are NOT ended by this slug's cleanup
    assert "other" not in result


@pytest.mark.asyncio
async def test_creative_blocked_keeps_sessions_alive(tmp_path: Path) -> None:
    """Creative BLOCKED must not emit end commands. Sessions stay alive as signal for
    the human — ending them would lose the blocker context."""
    slug = "slug-blk"
    workspace = _creative_workspace(tmp_path, slug)
    (workspace / "art" / "mood.png").write_text("img", encoding="utf-8")

    mock_todos_db = AsyncMock()
    mock_todos_db.artifact_exists = AsyncMock(side_effect=lambda _s, name: name in ("input", "design-spec"))
    mock_todos_db.read_state.return_value = {"creative": {"design_spec": {"confirmed": True}}}
    mock_todos_db.write_state = AsyncMock()

    artist = _FakeSession("art-blk", "/next-create-art slug-blk", f"workspace/{slug}")
    db = AsyncMock()
    db.list_sessions = AsyncMock(return_value=[artist])

    with (
        patch(
            "teleclaude.core.next_machine.create._derive_creative_phase",
            return_value=CreativePhase.BLOCKED,
        ),
        patch("teleclaude.core.todos_db.get_todos_db", new_callable=AsyncMock, return_value=mock_todos_db),
        patch("teleclaude.core.next_machine.create.compose_agent_guidance", return_value="guidance"),
    ):
        result = await next_create(db, slug, str(tmp_path))

    assert "BLOCKED" in result
    # Live session ID is referenced for human inspection
    assert "art-blk" in result
    # No end commands anywhere in the output
    assert "telec sessions end" not in result
