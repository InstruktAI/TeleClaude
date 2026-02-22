"""Tests for breakdown assessment in next_prepare."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from teleclaude.core.db import Db
from teleclaude.core.next_machine import next_prepare, read_breakdown_state, write_breakdown_state


@pytest.mark.asyncio
async def test_next_prepare_hitl_input_md_unassessed_breakdown():
    """next_prepare detects input.md with unassessed breakdown and returns guidance."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    # Mock: slug in roadmap, input.md exists, no breakdown state yet
    def mock_check_file_exists(_path_cwd: str, relative_path: str) -> bool:
        return "input.md" in relative_path

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.check_file_exists", side_effect=mock_check_file_exists),
        patch("teleclaude.core.next_machine.core.read_breakdown_state", return_value=None),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"Preparing: {slug}" in result
        assert "Read todos/test-slug/input.md and assess Definition of Ready" in result
        assert "split into smaller todos" in result
        assert "update state.yaml and create breakdown.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_assessed_breakdown_with_todos_container():
    """next_prepare detects assessed breakdown with split todos and returns CONTAINER message."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-parent"

    # Mock: breakdown assessed with dependent todos
    breakdown_state = {"assessed": True, "todos": ["test-parent-1", "test-parent-2"]}

    def mock_check_file_exists(_path_cwd: str, relative_path: str) -> bool:
        return "input.md" in relative_path

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.check_file_exists", side_effect=mock_check_file_exists),
        patch("teleclaude.core.next_machine.core.read_breakdown_state", return_value=breakdown_state),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert "CONTAINER:" in result
        assert slug in result
        assert "test-parent-1" in result
        assert "test-parent-2" in result
        assert "Work on those first" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_assessed_breakdown_empty_todos_proceeds():
    """next_prepare with assessed breakdown and empty todos proceeds to requirements."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-simple"

    # Mock: breakdown assessed, no split (empty todos list)
    breakdown_state = {"assessed": True, "todos": []}

    def mock_check_file_exists(_path_cwd: str, relative_path: str) -> bool:
        # input.md exists, requirements.md does not
        if "input.md" in relative_path:
            return True
        return False

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.check_file_exists", side_effect=mock_check_file_exists),
        patch("teleclaude.core.next_machine.core.read_breakdown_state", return_value=breakdown_state),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        # Should skip breakdown and proceed to requirements creation
        assert f"Preparing: {slug}" in result
        assert "Write todos/test-simple/requirements.md" in result
        assert "CONTAINER" not in result


@pytest.mark.asyncio
async def test_next_prepare_autonomous_input_md_unassessed_breakdown():
    """next_prepare in autonomous mode dispatches architect for breakdown assessment."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    def mock_check_file_exists(_path_cwd: str, relative_path: str) -> bool:
        return "input.md" in relative_path

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.check_file_exists", side_effect=mock_check_file_exists),
        patch("teleclaude.core.next_machine.core.read_breakdown_state", return_value=None),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=False)
        assert "teleclaude__run_agent_command" in result
        assert 'command="/next-prepare-draft"' in result
        assert f'args="{slug}"' in result
        assert "Assess todos/test-slug/input.md for complexity" in result


def test_read_breakdown_state_returns_defaults_when_no_file():
    """read_breakdown_state returns default breakdown state when state.yaml doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = read_breakdown_state(tmpdir, "test-slug")
        # Returns defaults from DEFAULT_STATE (via read_phase_state)
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
        # Returns defaults merged from DEFAULT_STATE
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
