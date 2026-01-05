import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.db import Db
from teleclaude.core.next_machine import (
    format_tool_call,
    is_build_complete,
    is_review_approved,
    is_review_changes_requested,
    mark_phase,
    next_prepare,
    read_phase_state,
    write_phase_state,
)


@pytest.mark.asyncio
async def test_next_prepare_hitl_no_slug():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"

    with patch("teleclaude.core.next_machine.resolve_slug", return_value=(None, False, "")):
        result = await next_prepare(db, slug=None, cwd=cwd, hitl=True)
        assert "Read todos/roadmap.md" in result
        assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_missing_requirements():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    with patch("teleclaude.core.next_machine.check_file_exists", return_value=False):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"Preparing: {slug}" in result
        assert "Write todos/test-slug/requirements.md" in result
        assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_missing_impl_plan():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    def mock_check_file_exists(path_cwd, relative_path):
        if "requirements.md" in relative_path:
            return True
        return False

    with patch("teleclaude.core.next_machine.check_file_exists", side_effect=mock_check_file_exists):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"Preparing: {slug}" in result
        assert "Write todos/test-slug/implementation-plan.md" in result
        assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_both_exist():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    with patch("teleclaude.core.next_machine.check_file_exists", return_value=True):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"PREPARED: todos/{slug} is ready for work." in result


@pytest.mark.asyncio
async def test_next_prepare_autonomous_dispatch():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    # Mock agent availability
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    with patch("teleclaude.core.next_machine.check_file_exists", return_value=False):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=False)
        assert "teleclaude__run_agent_command" in result
        assert f'args="{slug}"' in result
        assert 'command="next-prepare"' in result


# =============================================================================
# State Management Tests
# =============================================================================


def test_read_phase_state_returns_default_when_no_file():
    """read_phase_state returns default state when state.json doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = read_phase_state(tmpdir, "test-slug")
        assert state == {"build": "pending", "review": "pending"}


def test_read_phase_state_reads_existing_file():
    """read_phase_state reads existing state.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text(json.dumps({"build": "complete", "review": "pending"}))

        state = read_phase_state(tmpdir, slug)
        assert state == {"build": "complete", "review": "pending"}


def test_write_phase_state_creates_file():
    """write_phase_state creates state.json and commits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state = {"build": "complete", "review": "pending"}

        with patch("teleclaude.core.next_machine.Repo"):
            write_phase_state(tmpdir, slug, state)

        state_file = Path(tmpdir) / "todos" / slug / "state.json"
        assert state_file.exists()
        content = json.loads(state_file.read_text())
        assert content == state


def test_mark_phase_updates_state():
    """mark_phase updates state and returns updated dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"

        with patch("teleclaude.core.next_machine.Repo"):
            result = mark_phase(tmpdir, slug, "build", "complete")

        assert result["build"] == "complete"
        assert result["review"] == "pending"

        # Verify file was written
        state_file = Path(tmpdir) / "todos" / slug / "state.json"
        content = json.loads(state_file.read_text())
        assert content["build"] == "complete"


def test_is_build_complete_true():
    """is_build_complete returns True when build is complete."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text(json.dumps({"build": "complete"}))

        assert is_build_complete(tmpdir, slug) is True


def test_is_build_complete_false():
    """is_build_complete returns False when build is pending."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert is_build_complete(tmpdir, "test-slug") is False


def test_is_review_approved_true():
    """is_review_approved returns True when review is approved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text(json.dumps({"review": "approved"}))

        assert is_review_approved(tmpdir, slug) is True


def test_is_review_changes_requested_true():
    """is_review_changes_requested returns True when changes requested."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text(json.dumps({"review": "changes_requested"}))

        assert is_review_changes_requested(tmpdir, slug) is True


# =============================================================================
# format_tool_call Tests
# =============================================================================


def test_format_tool_call_codex_adds_prompts_prefix():
    """format_tool_call adds /prompts: prefix for codex agent."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        agent="codex",
        thinking_mode="med",
        subfolder="trees/test-slug",
        next_call="teleclaude__next_work",
    )
    assert 'command="/prompts:next-build"' in result
    assert "execution script" in result
    assert "do not re-read" in result


def test_format_tool_call_claude_no_prefix():
    """format_tool_call does not add prefix for claude agent."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        agent="claude",
        thinking_mode="med",
        subfolder="trees/test-slug",
        next_call="teleclaude__next_work",
    )
    assert 'command="next-build"' in result
    assert "/prompts:" not in result
    assert "execution script" in result
    assert "do not re-read" in result


def test_format_tool_call_gemini_no_prefix():
    """format_tool_call does not add prefix for gemini agent."""
    result = format_tool_call(
        command="next-review",
        args="test-slug",
        project="/tmp/project",
        agent="gemini",
        thinking_mode="slow",
        subfolder="trees/test-slug",
        next_call="teleclaude__next_work",
    )
    assert 'command="next-review"' in result
    assert "/prompts:" not in result
