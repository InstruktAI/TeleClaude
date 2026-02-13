import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.db import Db
from teleclaude.core.next_machine import (
    format_tool_call,
    get_stash_entries,
    has_git_stash_entries,
    has_uncommitted_changes,
    is_build_complete,
    is_review_approved,
    is_review_changes_requested,
    mark_phase,
    next_prepare,
    read_phase_state,
    sync_slug_todo_from_main_to_worktree,
    sync_slug_todo_from_worktree_to_main,
    write_phase_state,
)


@pytest.mark.asyncio
async def test_next_prepare_hitl_no_slug():
    """Test that HITL next_prepare prompts roadmap guidance when no slug resolves."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"

    with patch("teleclaude.core.next_machine.core._find_next_prepare_slug", return_value=None):
        result = await next_prepare(db, slug=None, cwd=cwd, hitl=True)
        assert "No active preparation work found." in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_missing_requirements():
    """Test that HITL next_prepare requests requirements when slug exists but file missing."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"Preparing: {slug}" in result
        assert "Write todos/test-slug/requirements.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_missing_impl_plan():
    """Test that HITL next_prepare requests implementation plan when requirements exist."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    def mock_check_file_exists(path_cwd, relative_path):
        if "requirements.md" in relative_path:
            return True
        return False

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.check_file_exists", side_effect=mock_check_file_exists),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"Preparing: {slug}" in result
        assert "Write todos/test-slug/implementation-plan.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_both_exist():
    """Test that HITL next_prepare reports PREPARED when docs are present."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    # Mock check_file_exists to return True for requirements/impl-plan, False for input.md
    def mock_check_file_exists(path: str, file: str) -> bool:
        if "input.md" in file:
            return False
        return True  # requirements.md and implementation-plan.md exist

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.check_file_exists", side_effect=mock_check_file_exists),
        patch("teleclaude.core.next_machine.core.read_breakdown_state", return_value=None),
        patch("teleclaude.core.next_machine.core.get_item_phase", return_value="pending"),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value={"dor": {"score": 8}}),
        patch("teleclaude.core.next_machine.core.sync_main_to_worktree"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"PREPARED: todos/{slug} is ready for work." in result


@pytest.mark.asyncio
async def test_next_prepare_autonomous_dispatch():
    """Test that autonomous next_prepare emits run-agent command when docs missing."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    # Mock agent availability
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=False)
        assert "teleclaude__run_agent_command" in result
        assert f'args="{slug}"' in result
        assert 'command="/next-prepare-draft"' in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_slug_missing_from_roadmap():
    """Test that HITL next_prepare explains missing roadmap entry for slug."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert "not in todos/roadmap.md" in result
        assert "add it to the roadmap" in result


@pytest.mark.asyncio
async def test_next_prepare_autonomous_slug_missing_from_roadmap():
    """Test that autonomous next_prepare still dispatches but warns about roadmap."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=False)
        assert "teleclaude__run_agent_command" in result
        assert f'args="{slug}"' in result
        assert "not in todos/roadmap.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_slug_missing_from_roadmap_when_docs_exist():
    """Test that HITL next_prepare flags roadmap omission even when docs exist."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=True),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert "not in todos/roadmap.md" in result
        assert "add it to the roadmap" in result


# =============================================================================
# State Management Tests
# =============================================================================


def test_read_phase_state_returns_default_when_no_file():
    """read_phase_state returns default state when state.json doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = read_phase_state(tmpdir, "test-slug")
        assert state["build"] == "pending"
        assert state["review"] == "pending"
        assert state["deferrals_processed"] is False
        assert state["breakdown"] == {"assessed": False, "todos": []}
        assert state["review_round"] == 0
        assert state["max_review_rounds"] == 3
        assert state["review_baseline_commit"] == ""
        assert state["unresolved_findings"] == []
        assert state["resolved_findings"] == []


def test_read_phase_state_reads_existing_file():
    """read_phase_state reads existing state.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text(json.dumps({"build": "complete", "review": "pending"}))

        state = read_phase_state(tmpdir, slug)
        # Should merge with defaults for missing keys
        assert state["build"] == "complete"
        assert state["review"] == "pending"
        assert state["deferrals_processed"] is False
        assert state["breakdown"] == {"assessed": False, "todos": []}
        assert state["review_round"] == 0
        assert state["max_review_rounds"] == 3
        assert state["review_baseline_commit"] == ""
        assert state["unresolved_findings"] == []
        assert state["resolved_findings"] == []


def test_write_phase_state_creates_file():
    """write_phase_state creates state.json and commits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state = {"build": "complete", "review": "pending"}

        with patch("teleclaude.core.next_machine.core.Repo"):
            write_phase_state(tmpdir, slug, state)

        state_file = Path(tmpdir) / "todos" / slug / "state.json"
        assert state_file.exists()
        content = json.loads(state_file.read_text())
        assert content == state


def test_mark_phase_updates_state():
    """mark_phase updates state and returns updated dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"

        with patch("teleclaude.core.next_machine.core.Repo"):
            result = mark_phase(tmpdir, slug, "build", "complete")

        assert result["build"] == "complete"
        assert result["review"] == "pending"

        # Verify file was written
        state_file = Path(tmpdir) / "todos" / slug / "state.json"
        content = json.loads(state_file.read_text())
        assert content["build"] == "complete"


def test_mark_phase_review_changes_requested_tracks_round_and_findings():
    """Review changes_requested increments round and captures finding IDs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "review-findings.md").write_text("# Findings\n- R1-F1\n- R1-F2\n")

        result = mark_phase(tmpdir, slug, "review", "changes_requested")

        assert result["review"] == "changes_requested"
        assert result["review_round"] == 1
        assert result["unresolved_findings"] == ["R1-F1", "R1-F2"]


def test_has_uncommitted_changes_ignores_orchestrator_control_files():
    """Dirty roadmap/dependencies alone should not block next_work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir) / "trees" / "test-slug"
        worktree.mkdir(parents=True, exist_ok=True)

        repo_mock = MagicMock()
        repo_mock.git.status.return_value = " M todos/roadmap.md\n M todos/dependencies.json\n"

        with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
            assert has_uncommitted_changes(tmpdir, "test-slug") is False


def test_has_uncommitted_changes_detects_non_control_file_changes():
    """Non-control dirty files must still block next_work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir) / "trees" / "test-slug"
        worktree.mkdir(parents=True, exist_ok=True)

        repo_mock = MagicMock()
        repo_mock.git.status.return_value = " M teleclaude/core/next_machine/core.py\n"

        with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
            assert has_uncommitted_changes(tmpdir, "test-slug") is True


def test_has_uncommitted_changes_ignores_slug_todo_scaffold_paths():
    """Untracked synced slug todo files should not block next_work dispatch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir) / "trees" / "test-slug"
        worktree.mkdir(parents=True, exist_ok=True)

        repo_mock = MagicMock()
        repo_mock.git.status.return_value = "?? todos/test-slug/\n?? todos/test-slug/requirements.md\n"

        with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
            assert has_uncommitted_changes(tmpdir, "test-slug") is False


def test_get_stash_entries_returns_repo_stash_list():
    """Stash entries are repository-wide and should be detected for orchestration guardrails."""
    repo_mock = MagicMock()
    repo_mock.git.stash.return_value = "stash@{0}: WIP on test\nstash@{1}: On test"

    with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
        entries = get_stash_entries("/tmp/test")

    assert entries == ["stash@{0}: WIP on test", "stash@{1}: On test"]


def test_has_git_stash_entries_true_when_stash_not_empty():
    """Non-empty stash list should block workflow progression."""
    repo_mock = MagicMock()
    repo_mock.git.stash.return_value = "stash@{0}: WIP on test"

    with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
        assert has_git_stash_entries("/tmp/test") is True


def test_sync_slug_todo_from_main_to_worktree_copies_slug_files():
    """Slug todo artifacts should be available inside worktree before build dispatch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_todo = Path(tmpdir) / "todos" / slug
        worktree_root = Path(tmpdir) / "trees" / slug
        main_todo.mkdir(parents=True, exist_ok=True)
        worktree_root.mkdir(parents=True, exist_ok=True)

        (main_todo / "requirements.md").write_text("# req\n", encoding="utf-8")
        (main_todo / "implementation-plan.md").write_text("# plan\n", encoding="utf-8")
        (main_todo / "state.json").write_text("{}", encoding="utf-8")

        sync_slug_todo_from_main_to_worktree(tmpdir, slug)

        assert (worktree_root / "todos" / slug / "requirements.md").exists()
        assert (worktree_root / "todos" / slug / "implementation-plan.md").exists()
        assert (worktree_root / "todos" / slug / "state.json").exists()


def test_sync_slug_todo_from_main_to_worktree_includes_review_findings():
    """Review findings in main should be mirrored into worktree when present."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_todo = Path(tmpdir) / "todos" / slug
        worktree_root = Path(tmpdir) / "trees" / slug
        main_todo.mkdir(parents=True, exist_ok=True)
        worktree_root.mkdir(parents=True, exist_ok=True)

        (main_todo / "review-findings.md").write_text("# Findings\n- R1-F1\n", encoding="utf-8")
        sync_slug_todo_from_main_to_worktree(tmpdir, slug)

        mirrored = worktree_root / "todos" / slug / "review-findings.md"
        assert mirrored.exists()
        assert "R1-F1" in mirrored.read_text(encoding="utf-8")


def test_sync_slug_todo_from_worktree_to_main_includes_review_findings():
    """Review findings created in worktree should sync back to main."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_root = Path(tmpdir)
        worktree_todo = main_root / "trees" / slug / "todos" / slug
        worktree_todo.mkdir(parents=True, exist_ok=True)

        (worktree_todo / "review-findings.md").write_text("# Findings\n- [x] APPROVE\n", encoding="utf-8")
        sync_slug_todo_from_worktree_to_main(tmpdir, slug)

        main_review = main_root / "todos" / slug / "review-findings.md"
        assert main_review.exists()
        assert "APPROVE" in main_review.read_text(encoding="utf-8")


def test_sync_slug_todo_from_main_to_worktree_does_not_overwrite_existing_state():
    """Main bootstrap sync must not clobber worktree state transitions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_todo = Path(tmpdir) / "todos" / slug
        worktree_todo = Path(tmpdir) / "trees" / slug / "todos" / slug
        main_todo.mkdir(parents=True, exist_ok=True)
        worktree_todo.mkdir(parents=True, exist_ok=True)

        (main_todo / "state.json").write_text('{"build":"pending"}', encoding="utf-8")
        (worktree_todo / "state.json").write_text('{"build":"complete"}', encoding="utf-8")

        sync_slug_todo_from_main_to_worktree(tmpdir, slug)

        final_state = (worktree_todo / "state.json").read_text(encoding="utf-8")
        assert '"build":"complete"' in final_state


def test_mark_phase_review_approved_clears_unresolved_findings():
    """Review approved should clear unresolved findings and carry to resolved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text(
            json.dumps(
                {
                    "build": "complete",
                    "review": "pending",
                    "unresolved_findings": ["R1-F1"],
                    "resolved_findings": [],
                    "review_round": 1,
                }
            )
        )

        result = mark_phase(tmpdir, slug, "review", "approved")

        assert result["review"] == "approved"
        assert result["review_round"] == 2
        assert result["unresolved_findings"] == []
        assert "R1-F1" in result["resolved_findings"]


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


def test_format_tool_call_codex_uses_normalized_command():
    """format_tool_call keeps transport command payload stable for codex."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        agent="codex",
        thinking_mode="med",
        subfolder="trees/test-slug",
        next_call="teleclaude__next_work",
    )
    assert 'command="/next-build"' in result
    assert "/prompts:" not in result
    assert "teleclaude__run_agent_command(" in result


def test_format_tool_call_claude_no_prefix():
    """format_tool_call does not rewrite command prefix for claude."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        agent="claude",
        thinking_mode="med",
        subfolder="trees/test-slug",
        next_call="teleclaude__next_work",
    )
    assert 'command="/next-build"' in result
    assert "/prompts:" not in result
    assert "teleclaude__run_agent_command(" in result


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
    assert 'command="/next-review"' in result
    assert "/prompts:" not in result


def test_format_tool_call_next_call_with_args():
    """format_tool_call preserves next_call arguments without double parentheses."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        agent="claude",
        thinking_mode="med",
        subfolder="trees/test-slug",
        next_call='teleclaude__next_work(slug="test-slug")',
    )
    assert 'Call teleclaude__next_work(slug="test-slug")' in result
    assert 'Call teleclaude__next_work(slug="test-slug")()' not in result
