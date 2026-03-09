"""Tests for breakdown assessment in next_prepare state machine."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from teleclaude.core.db import Db
from teleclaude.core.next_machine import next_prepare, read_breakdown_state, write_breakdown_state
from teleclaude.core.next_machine.core import PreparePhase


@pytest.mark.asyncio
async def test_next_prepare_input_md_unassessed_breakdown_dispatches_discovery():
    """next_prepare dispatches next-prepare-discovery for requirements work."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    # State: no prepare_phase set — triggers phase derivation
    # Derivation: requirements.md absent → DISCOVERY
    # DISCOVERY handler: dispatches discovery for requirements work
    state = {
        "prepare_phase": "",
        "breakdown": {"assessed": False, "todos": []},
    }

    def mock_check_file_exists(_path_cwd: str, relative_path: str) -> bool:
        return "input.md" in relative_path

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core.check_file_exists", side_effect=mock_check_file_exists),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "telec sessions run" in result
        assert '--command "/next-prepare-discovery"' in result
        assert f'--args "{slug}"' in result
        assert "requirements.md" in result


@pytest.mark.asyncio
async def test_next_prepare_assessed_breakdown_with_todos_container():
    """next_prepare returns CONTAINER when holder has split children."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-parent"

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch(
            "teleclaude.core.next_machine.core.resolve_holder_children",
            return_value=["test-parent-1", "test-parent-2"],
        ),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "CONTAINER:" in result
        assert slug in result
        assert "test-parent-1" in result
        assert "test-parent-2" in result
        assert "Work on those first" in result


@pytest.mark.asyncio
async def test_next_prepare_non_roadmap_holder_with_group_children_returns_container():
    """next_prepare treats non-roadmap holder slugs as containers when children discoverable."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "holder-item"

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=["child-1", "child-2"]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=False),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)

    assert "CONTAINER:" in result
    assert slug in result
    assert "child-1" in result
    assert "child-2" in result
    assert "Work on those first" in result


@pytest.mark.asyncio
async def test_next_prepare_assessed_breakdown_empty_todos_still_dispatches_discovery():
    """Requirements routing no longer depends on breakdown.assessed."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-simple"

    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    # input.md exists, requirements.md absent → dispatches discovery
    state = {
        "prepare_phase": "",
        "breakdown": {"assessed": True, "todos": []},
    }

    def mock_check_file_exists(_path_cwd: str, relative_path: str) -> bool:
        return "input.md" in relative_path

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core.check_file_exists", side_effect=mock_check_file_exists),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-discovery" in result
        assert "requirements.md" in result
        assert "CONTAINER" not in result


@pytest.mark.asyncio
async def test_next_prepare_input_md_unassessed_breakdown_dispatches_discovery_autonomous():
    """next_prepare dispatches discovery for requirements work in autonomous mode."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.DISCOVERY.value,
        "breakdown": {"assessed": False, "todos": []},
    }

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "telec sessions run" in result
        assert '--command "/next-prepare-discovery"' in result
        assert f'--args "{slug}"' in result
        assert "requirements.md" in result


def test_read_breakdown_state_returns_defaults_when_no_file():
    """read_breakdown_state returns default breakdown state when state.yaml doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = read_breakdown_state(tmpdir, "test-slug")
        assert state == {"assessed": False, "todos": []}


def test_read_breakdown_state_returns_breakdown_when_exists():
    """read_breakdown_state returns breakdown dict from existing state.yaml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.yaml"
        state_file.write_text(
            yaml.dump({"build": "pending", "breakdown": {"assessed": True, "todos": ["test-1", "test-2"]}})
        )

        state = read_breakdown_state(tmpdir, slug)
        assert state == {"assessed": True, "todos": ["test-1", "test-2"]}


def test_read_breakdown_state_returns_defaults_when_breakdown_missing():
    """read_breakdown_state returns defaults when state.yaml exists but has no breakdown key."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.yaml"
        state_file.write_text(yaml.dump({"build": "pending"}))

        state = read_breakdown_state(tmpdir, slug)
        assert state == {"assessed": False, "todos": []}


def test_write_breakdown_state_creates_breakdown_section():
    """write_breakdown_state creates breakdown section in state.yaml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"

        with patch("teleclaude.core.next_machine.core.Repo"):
            write_breakdown_state(tmpdir, slug, assessed=True, todos=["test-1", "test-2"])

        state_file = Path(tmpdir) / "todos" / slug / "state.yaml"
        assert state_file.exists()
        content = yaml.safe_load(state_file.read_text())
        assert content["breakdown"] == {"assessed": True, "todos": ["test-1", "test-2"]}


def test_write_breakdown_state_preserves_existing_state():
    """write_breakdown_state preserves existing build/review state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.yaml").write_text(yaml.dump({"build": "complete", "review": "pending"}))

        with patch("teleclaude.core.next_machine.core.Repo"):
            write_breakdown_state(tmpdir, slug, assessed=True, todos=[])

        content = yaml.safe_load((state_dir / "state.yaml").read_text())
        assert content["build"] == "complete"
        assert content["review"] == "pending"
        assert content["breakdown"] == {"assessed": True, "todos": []}
