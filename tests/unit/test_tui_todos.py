"""Unit tests for todo parsing."""

# type: ignore - test uses temp directories

from pathlib import Path

import pytest

from teleclaude.cli.tui.todos import TodoItem, parse_roadmap


def test_parse_roadmap_no_file(tmp_path):
    """Test parse_roadmap when roadmap.md doesn't exist."""
    result = parse_roadmap(str(tmp_path))
    assert result == []


def test_parse_roadmap_empty_file(tmp_path):
    """Test parse_roadmap with empty roadmap.md."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    roadmap_file.write_text("")

    result = parse_roadmap(str(tmp_path))
    assert result == []


def test_parse_roadmap_pending_status(tmp_path):
    """Test parse_roadmap with pending status [ ]."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    roadmap_file.write_text("- [ ] feature-one\n")

    result = parse_roadmap(str(tmp_path))
    assert len(result) == 1
    assert result[0].slug == "feature-one"
    assert result[0].status == "pending"
    assert result[0].description is None
    assert result[0].has_requirements is False
    assert result[0].has_impl_plan is False


def test_parse_roadmap_ready_status(tmp_path):
    """Test parse_roadmap with ready status [.]."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    roadmap_file.write_text("- [.] feature-two\n")

    result = parse_roadmap(str(tmp_path))
    assert len(result) == 1
    assert result[0].slug == "feature-two"
    assert result[0].status == "ready"


def test_parse_roadmap_in_progress_status(tmp_path):
    """Test parse_roadmap with in-progress status [>]."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    roadmap_file.write_text("- [>] feature-three\n")

    result = parse_roadmap(str(tmp_path))
    assert len(result) == 1
    assert result[0].slug == "feature-three"
    assert result[0].status == "in_progress"


def test_parse_roadmap_with_description(tmp_path):
    """Test parse_roadmap extracts indented description."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    content = """- [ ] feature-one
      This is a description
      that spans multiple lines
"""
    roadmap_file.write_text(content)

    result = parse_roadmap(str(tmp_path))
    assert len(result) == 1
    assert result[0].slug == "feature-one"
    assert result[0].description == "This is a description that spans multiple lines"


def test_parse_roadmap_checks_requirements_file(tmp_path):
    """Test parse_roadmap detects requirements.md."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    roadmap_file.write_text("- [ ] feature-one\n")

    # Create requirements.md
    feature_dir = roadmap_dir / "feature-one"
    feature_dir.mkdir()
    (feature_dir / "requirements.md").write_text("# Requirements\n")

    result = parse_roadmap(str(tmp_path))
    assert len(result) == 1
    assert result[0].has_requirements is True
    assert result[0].has_impl_plan is False


def test_parse_roadmap_checks_impl_plan_file(tmp_path):
    """Test parse_roadmap detects implementation-plan.md."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    roadmap_file.write_text("- [ ] feature-one\n")

    # Create implementation-plan.md
    feature_dir = roadmap_dir / "feature-one"
    feature_dir.mkdir()
    (feature_dir / "implementation-plan.md").write_text("# Plan\n")

    result = parse_roadmap(str(tmp_path))
    assert len(result) == 1
    assert result[0].has_requirements is False
    assert result[0].has_impl_plan is True


def test_parse_roadmap_multiple_todos(tmp_path):
    """Test parse_roadmap with multiple todos."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    content = """- [ ] feature-one
- [.] feature-two
- [>] feature-three
"""
    roadmap_file.write_text(content)

    result = parse_roadmap(str(tmp_path))
    assert len(result) == 3
    assert result[0].slug == "feature-one"
    assert result[1].slug == "feature-two"
    assert result[2].slug == "feature-three"


def test_parse_roadmap_ignores_non_todo_lines(tmp_path):
    """Test parse_roadmap ignores lines that don't match pattern."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    content = """# Roadmap

Some intro text.

- [ ] feature-one
      Description here

More text in between.

- [ ] feature-two
"""
    roadmap_file.write_text(content)

    result = parse_roadmap(str(tmp_path))
    assert len(result) == 2
    assert result[0].slug == "feature-one"
    assert result[1].slug == "feature-two"


def test_parse_roadmap_handles_blank_lines_in_description(tmp_path):
    """Test parse_roadmap continues through blank lines in description."""
    roadmap_dir = tmp_path / "todos"
    roadmap_dir.mkdir()
    roadmap_file = roadmap_dir / "roadmap.md"
    content = """- [ ] feature-one
      First line

      Second line after blank
"""
    roadmap_file.write_text(content)

    result = parse_roadmap(str(tmp_path))
    assert len(result) == 1
    # Blank lines are skipped, so description should continue
    assert "First line" in result[0].description
    assert "Second line" in result[0].description
