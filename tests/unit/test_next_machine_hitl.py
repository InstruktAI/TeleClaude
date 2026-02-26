import asyncio
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

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
    sync_main_to_worktree,
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
        patch(
            "teleclaude.core.next_machine.core.read_phase_state", return_value={"build": "pending", "dor": {"score": 8}}
        ),
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
        assert "telec sessions run" in result
        assert f'--args "{slug}"' in result
        assert '--command "/next-prepare-draft"' in result


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
        assert "not in todos/roadmap.yaml" in result
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
        assert "telec sessions run" in result
        assert f'--args "{slug}"' in result
        assert "not in todos/roadmap.yaml" in result


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
        assert "not in todos/roadmap.yaml" in result
        assert "add it to the roadmap" in result


# =============================================================================
# State Management Tests
# =============================================================================


def test_read_phase_state_returns_default_when_no_file():
    """read_phase_state returns default state when state.yaml doesn't exist."""
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
    """read_phase_state reads existing state.yaml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.yaml"
        state_file.write_text(yaml.dump({"build": "complete", "review": "pending"}))

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
    """write_phase_state creates state.yaml and commits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state = {"build": "complete", "review": "pending"}

        with patch("teleclaude.core.next_machine.core.Repo"):
            write_phase_state(tmpdir, slug, state)

        state_file = Path(tmpdir) / "todos" / slug / "state.yaml"
        assert state_file.exists()
        content = yaml.safe_load(state_file.read_text())
        assert content == state


def test_mark_phase_updates_state():
    """mark_phase updates state and returns updated dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "implementation-plan.md").write_text("- [x] Task 1\n- [x] Task 2\n")

        with patch("teleclaude.core.next_machine.core.Repo"):
            result = mark_phase(tmpdir, slug, "build", "complete")

        assert result["build"] == "complete"
        assert result["review"] == "pending"

        # Verify file was written
        state_file = Path(tmpdir) / "todos" / slug / "state.yaml"
        content = yaml.safe_load(state_file.read_text())
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
        repo_mock.git.status.return_value = " M todos/roadmap.yaml\n?? .teleclaude/\n"

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
        (main_todo / "state.yaml").write_text("{}", encoding="utf-8")

        sync_slug_todo_from_main_to_worktree(tmpdir, slug)

        assert (worktree_root / "todos" / slug / "requirements.md").exists()
        assert (worktree_root / "todos" / slug / "implementation-plan.md").exists()
        assert (worktree_root / "todos" / slug / "state.yaml").exists()


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


def test_sync_slug_todo_from_main_to_worktree_preserves_worktree_state():
    """Worktree owns build/review progress — main sync must not clobber existing state.yaml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_todo = Path(tmpdir) / "todos" / slug
        worktree_todo = Path(tmpdir) / "trees" / slug / "todos" / slug
        main_todo.mkdir(parents=True, exist_ok=True)
        worktree_todo.mkdir(parents=True, exist_ok=True)

        (main_todo / "state.yaml").write_text('{"build":"pending"}', encoding="utf-8")
        (worktree_todo / "state.yaml").write_text('{"build":"complete"}', encoding="utf-8")

        sync_slug_todo_from_main_to_worktree(tmpdir, slug)

        final_state = (worktree_todo / "state.yaml").read_text(encoding="utf-8")
        assert '"build":"complete"' in final_state


def test_sync_slug_todo_from_main_to_worktree_seeds_state_when_missing():
    """state.yaml should be copied from main when worktree has no state yet."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_todo = Path(tmpdir) / "todos" / slug
        worktree_root = Path(tmpdir) / "trees" / slug
        main_todo.mkdir(parents=True, exist_ok=True)
        worktree_root.mkdir(parents=True, exist_ok=True)

        (main_todo / "state.yaml").write_text('{"build":"pending"}', encoding="utf-8")

        sync_slug_todo_from_main_to_worktree(tmpdir, slug)

        worktree_state = worktree_root / "todos" / slug / "state.yaml"
        assert worktree_state.exists()
        assert '"build":"pending"' in worktree_state.read_text(encoding="utf-8")


def test_sync_slug_todo_from_main_to_worktree_overwrites_planning_files():
    """Planning artifacts should always sync from main, even when worktree has them."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_todo = Path(tmpdir) / "todos" / slug
        worktree_todo = Path(tmpdir) / "trees" / slug / "todos" / slug
        main_todo.mkdir(parents=True, exist_ok=True)
        worktree_todo.mkdir(parents=True, exist_ok=True)

        (main_todo / "requirements.md").write_text("# Updated requirements\n", encoding="utf-8")
        (worktree_todo / "requirements.md").write_text("# Stale requirements\n", encoding="utf-8")

        sync_slug_todo_from_main_to_worktree(tmpdir, slug)

        final = (worktree_todo / "requirements.md").read_text(encoding="utf-8")
        assert "Updated" in final


def test_sync_main_to_worktree_skips_when_inputs_unchanged():
    """Main planning sync should skip file copy when source and destination match."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_root = Path(tmpdir)
        worktree_root = main_root / "trees" / slug
        worktree_root.mkdir(parents=True, exist_ok=True)
        (main_root / "todos").mkdir(parents=True, exist_ok=True)
        (worktree_root / "todos").mkdir(parents=True, exist_ok=True)
        (main_root / "todos" / "roadmap.yaml").write_text("- slug: test-slug\n", encoding="utf-8")
        (worktree_root / "todos" / "roadmap.yaml").write_text("- slug: test-slug\n", encoding="utf-8")

        copied = sync_main_to_worktree(tmpdir, slug)

        assert copied == 0


def test_sync_main_to_worktree_copies_when_inputs_changed():
    """Main planning sync should copy roadmap when content differs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_root = Path(tmpdir)
        worktree_root = main_root / "trees" / slug
        worktree_root.mkdir(parents=True, exist_ok=True)
        (main_root / "todos").mkdir(parents=True, exist_ok=True)
        (worktree_root / "todos").mkdir(parents=True, exist_ok=True)
        (main_root / "todos" / "roadmap.yaml").write_text("- slug: changed\n", encoding="utf-8")
        (worktree_root / "todos" / "roadmap.yaml").write_text("- slug: stale\n", encoding="utf-8")

        copied = sync_main_to_worktree(tmpdir, slug)

        assert copied == 1
        assert "changed" in (worktree_root / "todos" / "roadmap.yaml").read_text(encoding="utf-8")


def test_sync_slug_todo_from_main_to_worktree_skips_when_inputs_unchanged():
    """Slug artifact sync should report zero copied files when everything is unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_todo = Path(tmpdir) / "todos" / slug
        worktree_todo = Path(tmpdir) / "trees" / slug / "todos" / slug
        main_todo.mkdir(parents=True, exist_ok=True)
        worktree_todo.mkdir(parents=True, exist_ok=True)

        for name, content in (
            ("requirements.md", "# Requirements\n"),
            ("implementation-plan.md", "# Plan\n"),
            ("quality-checklist.md", "# Checklist\n"),
        ):
            (main_todo / name).write_text(content, encoding="utf-8")
            (worktree_todo / name).write_text(content, encoding="utf-8")
        (main_todo / "state.yaml").write_text("build: pending\n", encoding="utf-8")
        (worktree_todo / "state.yaml").write_text("build: complete\n", encoding="utf-8")

        copied = sync_slug_todo_from_main_to_worktree(tmpdir, slug)

        assert copied == 0


def test_mark_phase_review_approved_clears_unresolved_findings():
    """Review approved should clear unresolved findings and carry to resolved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.yaml").write_text(
            yaml.dump(
                {
                    "build": "complete",
                    "review": "pending",
                    "unresolved_findings": ["R1-F1"],
                    "resolved_findings": [],
                    "review_round": 1,
                }
            )
        )
        (state_dir / "review-findings.md").write_text("# Findings\n- R1-F1\n")

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
        (state_dir / "state.yaml").write_text(yaml.dump({"build": "complete"}))

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
        (state_dir / "state.yaml").write_text(yaml.dump({"review": "approved"}))

        assert is_review_approved(tmpdir, slug) is True


def test_is_review_changes_requested_true():
    """is_review_changes_requested returns True when changes requested."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.yaml").write_text(yaml.dump({"review": "changes_requested"}))

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
        guidance="Mock guidance",
        subfolder="trees/test-slug",
        next_call="telec todo work",
    )
    assert '--command "/next-build"' in result
    assert "/prompts:" not in result
    assert 'telec sessions run --command "/next-build"' in result
    assert "telec sessions run --computer " not in result


def test_format_tool_call_claude_no_prefix():
    """format_tool_call does not rewrite command prefix for claude."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        guidance="Mock guidance",
        subfolder="trees/test-slug",
        next_call="telec todo work",
    )
    assert '--command "/next-build"' in result
    assert "/prompts:" not in result
    assert 'telec sessions run --command "/next-build"' in result
    assert "telec sessions run --computer " not in result


def test_format_tool_call_gemini_no_prefix():
    """format_tool_call does not add prefix for gemini agent."""
    result = format_tool_call(
        command="next-review",
        args="test-slug",
        project="/tmp/project",
        guidance="Mock guidance",
        subfolder="trees/test-slug",
        next_call="telec todo work",
    )
    assert '--command "/next-review"' in result
    assert "/prompts:" not in result


def test_format_tool_call_next_call_with_args():
    """format_tool_call preserves next_call arguments without double parentheses."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        guidance="Mock guidance",
        subfolder="trees/test-slug",
        next_call="telec todo work test-slug",
    )
    assert "Call telec todo work test-slug" in result
    assert "Call telec todo work test-slug()" not in result


# =============================================================================
# Build Gate Tests
# =============================================================================

from unittest.mock import AsyncMock

from teleclaude.core.next_machine import next_work
from teleclaude.core.next_machine.core import (
    POST_COMPLETION,
    format_build_gate_failure,
)


def _write_roadmap_yaml(tmpdir: str, slugs: list[str]) -> None:
    """Helper to write a roadmap.yaml with given slugs."""
    import yaml as _yaml

    roadmap_path = Path(tmpdir) / "todos" / "roadmap.yaml"
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"slug": s} for s in slugs]
    roadmap_path.write_text(_yaml.dump(entries, default_flow_style=False))


@pytest.mark.asyncio
async def test_next_work_runs_gates_when_build_complete():
    """next_work runs build gates when build is complete, passing gates lead to review."""
    db = MagicMock(spec=Db)
    slug = "gate-test"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Req")
        (item_dir / "implementation-plan.md").write_text("# Plan")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "GATE PASSED: all")),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="guidance"),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "next-review" in result


@pytest.mark.asyncio
async def test_next_work_gate_failure_resets_build():
    """Failing gates reset build to started and return gate-failure instruction."""
    db = MagicMock(spec=Db)
    slug = "gate-fail"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Req")
        (item_dir / "implementation-plan.md").write_text("# Plan")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        gate_output = "GATE FAILED: make test (exit 1)\nTest output..."

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(False, gate_output)),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        # Verify gate failure response
        assert "BUILD GATES FAILED" in result
        assert "GATE FAILED" in result
        assert "Test output" in result

        # Verify build was reset to started
        state = yaml.safe_load((state_dir / "state.yaml").read_text())
        assert state["build"] == "started"


@pytest.mark.asyncio
async def test_next_work_gate_failure_includes_output():
    """Gate failure response includes failure output for the builder."""
    db = MagicMock(spec=Db)
    slug = "gate-output"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Req")
        (item_dir / "implementation-plan.md").write_text("# Plan")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        gate_output = "GATE FAILED: demo validate (exit 1)\nno executable bash blocks"

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(False, gate_output)),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "demo validate" in result
        assert "no executable bash blocks" in result
        assert "Send" in result  # instructs orchestrator to send to builder


@pytest.mark.asyncio
async def test_next_work_lazy_marking_no_state_mutation():
    """next_work does NOT mutate build state when returning a new build dispatch."""
    db = MagicMock(spec=Db)
    slug = "lazy-mark"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Req")
        (item_dir / "implementation-plan.md").write_text("# Plan")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "phase": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="guidance"),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        # Should dispatch build
        assert "next-build" in result

        # Build state should NOT have been mutated to "started"
        state = yaml.safe_load((state_dir / "state.yaml").read_text())
        assert state["build"] == "pending"

        # Output should contain marking instructions
        assert "mark-phase" in result
        assert "BEFORE DISPATCHING" in result


@pytest.mark.asyncio
async def test_next_work_concurrent_same_slug_single_flight_prep():
    """Concurrent same-slug calls should run expensive prep at most once."""
    db = MagicMock(spec=Db)
    slug = "single-flight"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.com"], cwd=tmpdir, check=True, capture_output=True, text=True
        )
        subprocess.run(["git", "config", "user.name", "Tests"], cwd=tmpdir, check=True, capture_output=True, text=True)

        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = tmp_path / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Req")
        (item_dir / "implementation-plan.md").write_text("# Plan")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        subprocess.run(["git", "add", "todos"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "worktree", "add", f"trees/{slug}", "-b", slug],
            cwd=tmpdir,
            check=True,
            capture_output=True,
            text=True,
        )

        worktree_todo = tmp_path / "trees" / slug / "todos" / slug
        (worktree_todo / "state.yaml").write_text('{"build":"pending","review":"pending"}')

        prep_calls = 0

        def _slow_prepare(*_args, **_kwargs):
            nonlocal prep_calls
            prep_calls += 1
            time.sleep(0.1)

        with (
            patch("teleclaude.core.next_machine.core._prepare_worktree", side_effect=_slow_prepare),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="guidance"),
            ),
        ):
            result_a, result_b = await asyncio.gather(
                next_work(db, slug=slug, cwd=tmpdir),
                next_work(db, slug=slug, cwd=tmpdir),
            )

        assert "next-build" in result_a
        assert "next-build" in result_b
        assert prep_calls == 1
        assert (tmp_path / "trees" / slug / ".teleclaude" / "worktree-prep-state.json").exists()


@pytest.mark.asyncio
async def test_next_work_single_flight_is_scoped_to_repo_and_slug():
    """Same slug in different repos should prepare concurrently (no cross-repo lock contention)."""
    db = MagicMock(spec=Db)
    slug = "same-slug"

    def _setup_repo(repo_dir: str, repo_slug: str) -> None:
        repo_path = Path(repo_dir)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.com"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Tests"], cwd=repo_dir, check=True, capture_output=True, text=True
        )
        _write_roadmap_yaml(repo_dir, [repo_slug])

        item_dir = repo_path / "todos" / repo_slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Req")
        (item_dir / "implementation-plan.md").write_text("# Plan")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        subprocess.run(["git", "add", "todos"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "worktree", "add", f"trees/{repo_slug}", "-b", repo_slug],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
        )

        worktree_todo = repo_path / "trees" / repo_slug / "todos" / repo_slug
        (worktree_todo / "state.yaml").write_text('{"build":"pending","review":"pending"}')

    with tempfile.TemporaryDirectory() as repo_a, tempfile.TemporaryDirectory() as repo_b:
        _setup_repo(repo_a, slug)
        _setup_repo(repo_b, slug)

        active_prepares = 0
        max_active_prepares = 0
        active_lock = threading.Lock()

        def _tracked_prepare(*_args, **_kwargs):
            nonlocal active_prepares, max_active_prepares
            with active_lock:
                active_prepares += 1
                max_active_prepares = max(max_active_prepares, active_prepares)
            time.sleep(0.1)
            with active_lock:
                active_prepares -= 1

        with (
            patch("teleclaude.core.next_machine.core._prepare_worktree", side_effect=_tracked_prepare),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="guidance"),
            ),
        ):
            result_a, result_b = await asyncio.gather(
                next_work(db, slug=slug, cwd=repo_a),
                next_work(db, slug=slug, cwd=repo_b),
            )

        assert "next-build" in result_a
        assert "next-build" in result_b
        assert max_active_prepares == 2


def test_post_completion_finalize_includes_make_restart():
    """POST_COMPLETION for next-finalize includes make restart step."""
    assert "make restart" in POST_COMPLETION["next-finalize"]


def test_post_completion_finalize_requires_ready_and_apply():
    """Finalize post-completion must require FINALIZE_READY and run canonical apply."""
    instructions = POST_COMPLETION["next-finalize"]
    assert "FINALIZE_READY: {args}" in instructions
    assert "todos/.finalize-lock" in instructions
    assert "TELECLAUDE_SESSION_ID" in instructions
    assert "<session_id>" in instructions
    assert 'git -C "$MAIN_REPO" merge {args} --no-edit' in instructions
    assert "telec roadmap deliver {args}" in instructions
    assert 'git -C "$MAIN_REPO" push origin main' in instructions


def test_format_build_gate_failure_structure():
    """format_build_gate_failure produces correct instruction structure."""
    result = format_build_gate_failure("test-slug", "GATE FAILED: make test", "telec todo work")
    assert "BUILD GATES FAILED: test-slug" in result
    assert "GATE FAILED: make test" in result
    assert "Send" in result
    assert "Do NOT end" in result
    assert "mark-phase" in result
