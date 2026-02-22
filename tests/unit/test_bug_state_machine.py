"""Unit tests for bug state machine functionality."""

from pathlib import Path

from teleclaude.core.next_machine.core import is_bug_todo


class TestIsBugTodo:
    """Tests for is_bug_todo."""

    def test_is_bug_todo_true_when_bug_md_exists(self, tmp_path: Path):
        """Returns True when bug.md exists in todos/{slug}/."""
        project_root = tmp_path
        slug = "fix-test-bug"

        # Create the bug.md file
        bug_md = project_root / "todos" / slug / "bug.md"
        bug_md.parent.mkdir(parents=True)
        bug_md.write_text("# Bug\n")

        assert is_bug_todo(str(project_root), slug) is True

    def test_is_bug_todo_false_when_no_bug_md(self, tmp_path: Path):
        """Returns False when bug.md does not exist."""
        project_root = tmp_path
        slug = "regular-todo"

        # Create a regular todo directory without bug.md
        todo_dir = project_root / "todos" / slug
        todo_dir.mkdir(parents=True)
        (todo_dir / "requirements.md").write_text("# Requirements\n")

        assert is_bug_todo(str(project_root), slug) is False

    def test_is_bug_todo_false_when_todo_dir_does_not_exist(self, tmp_path: Path):
        """Returns False when the todo directory doesn't exist."""
        project_root = tmp_path
        slug = "nonexistent"

        assert is_bug_todo(str(project_root), slug) is False
