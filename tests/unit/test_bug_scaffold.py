"""Unit tests for bug scaffold functionality."""

from pathlib import Path

import pytest
import yaml

from teleclaude.todo_scaffold import create_bug_skeleton


class TestCreateBugSkeleton:
    """Tests for create_bug_skeleton."""

    def test_create_bug_skeleton_creates_bug_md(self, tmp_path: Path):
        """Verify bug.md content has description, reporter, session_id."""
        project_root = tmp_path
        slug = "fix-test-bug"
        description = "Something is broken"
        reporter = "tester"
        session_id = "test-session-123"

        result = create_bug_skeleton(
            project_root,
            slug,
            description,
            reporter=reporter,
            session_id=session_id,
        )

        bug_md = result / "bug.md"
        assert bug_md.exists()

        content = bug_md.read_text()
        assert description in content
        assert reporter in content
        assert session_id in content
        assert "## Symptom" in content
        assert "## Discovery Context" in content
        assert "## Investigation" in content
        assert "## Root Cause" in content
        assert "## Fix Applied" in content

    def test_create_bug_skeleton_creates_state_yaml_at_build_phase(self, tmp_path: Path):
        """Verify state.yaml has build: pending, review: pending."""
        project_root = tmp_path
        slug = "fix-test-bug"

        result = create_bug_skeleton(
            project_root,
            slug,
            "Test bug",
        )

        state_yaml = result / "state.yaml"
        assert state_yaml.exists()

        state = yaml.safe_load(state_yaml.read_text())
        assert state["build"] == "pending"
        assert state["review"] == "pending"
        assert state["dor"] is None

    def test_create_bug_skeleton_does_not_create_requirements_or_plan(self, tmp_path: Path):
        """Verify no requirements.md, implementation-plan.md, quality-checklist.md, or input.md."""
        project_root = tmp_path
        slug = "fix-test-bug"

        result = create_bug_skeleton(
            project_root,
            slug,
            "Test bug",
        )

        assert not (result / "requirements.md").exists()
        assert not (result / "implementation-plan.md").exists()
        assert not (result / "quality-checklist.md").exists()
        assert not (result / "input.md").exists()

    def test_create_bug_skeleton_rejects_existing_dir(self, tmp_path: Path):
        """Raises FileExistsError when directory already exists."""
        project_root = tmp_path
        slug = "fix-test-bug"

        # Create once
        create_bug_skeleton(project_root, slug, "Test bug")

        # Try to create again
        with pytest.raises(FileExistsError, match="Todo already exists"):
            create_bug_skeleton(project_root, slug, "Test bug")

    def test_create_bug_skeleton_rejects_invalid_slug(self, tmp_path: Path):
        """Raises ValueError for invalid slug."""
        project_root = tmp_path

        with pytest.raises(ValueError, match="Invalid slug"):
            create_bug_skeleton(project_root, "Fix_Bug", "Test bug")

        with pytest.raises(ValueError, match="Invalid slug"):
            create_bug_skeleton(project_root, "fix bug", "Test bug")

        with pytest.raises(ValueError, match="Invalid slug"):
            create_bug_skeleton(project_root, "Fix-Bug", "Test bug")
