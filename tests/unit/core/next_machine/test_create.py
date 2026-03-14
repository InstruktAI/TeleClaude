"""Characterization tests for creative-state routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from teleclaude.core.next_machine._types import CreativePhase, RoadmapEntry
from teleclaude.core.next_machine.create import _derive_creative_phase, _find_next_creative_slug, next_create
from teleclaude.core.next_machine.roadmap import save_roadmap


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def test_derive_creative_phase_requires_design_discovery_when_spec_is_missing(tmp_path: Path) -> None:
    phase = _derive_creative_phase(tmp_path / "todo", {})

    assert phase == CreativePhase.DESIGN_DISCOVERY_REQUIRED


def test_derive_creative_phase_reports_complete_when_all_artifacts_are_approved(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todo"
    (todo_dir / "art").mkdir(parents=True)
    (todo_dir / "html").mkdir(parents=True)
    (todo_dir / "design-spec.md").write_text("design", encoding="utf-8")
    (todo_dir / "art" / "moodboard.png").write_text("img", encoding="utf-8")
    (todo_dir / "html" / "index.html").write_text("<html />", encoding="utf-8")

    phase = _derive_creative_phase(
        todo_dir,
        {"design_spec": {"confirmed": True}, "art": {"approved": True}, "visuals": {"approved": True}},
    )

    assert phase == CreativePhase.CREATIVE_COMPLETE


def test_find_next_creative_slug_skips_done_items_and_returns_first_active_creative_item(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="done-item", group=None, after=[], description=None),
            RoadmapEntry(slug="creative-item", group=None, after=[], description=None),
        ],
    )
    done_dir = tmp_path / "todos" / "done-item"
    _write_state(done_dir, {"phase": "done", "creative": {"phase": CreativePhase.CREATIVE_COMPLETE.value}})
    (done_dir / "input.md").write_text("done input", encoding="utf-8")

    creative_dir = tmp_path / "todos" / "creative-item"
    _write_state(creative_dir, {"creative": {"phase": CreativePhase.ART_GENERATION_REQUIRED.value}})
    (creative_dir / "input.md").write_text("todo input", encoding="utf-8")

    assert _find_next_creative_slug(str(tmp_path)) == "creative-item"


@pytest.mark.asyncio
async def test_next_create_updates_creative_phase_and_dispatches_art_generation(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-a"
    _write_state(todo_dir, {"creative": {"design_spec": {"confirmed": True}}})
    (todo_dir / "input.md").write_text("input", encoding="utf-8")
    (todo_dir / "design-spec.md").write_text("design", encoding="utf-8")
    db = AsyncMock()

    with patch("teleclaude.core.next_machine.create.compose_agent_guidance", return_value="runtime guidance"):
        result = await next_create(db, "slug-a", str(tmp_path))

    state = yaml.safe_load((todo_dir / "state.yaml").read_text(encoding="utf-8"))
    creative = state["creative"]
    assert creative["phase"] == CreativePhase.ART_GENERATION_REQUIRED.value
    assert 'telec sessions run --command "/next-create-art" --args "slug-a"' in result
