"""Unit tests for roadmap assembly."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.core import RoadmapEntry
from teleclaude.core.roadmap import assemble_roadmap


@pytest.fixture
def mock_project(tmp_path):
    """Create a mock project structure."""
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    (todos_dir / "icebox.yaml").touch()  # Ensure icebox logic triggers

    # Roadmap items
    (todos_dir / "task-1").mkdir()
    (todos_dir / "task-1" / "state.yaml").write_text(
        json.dumps({"build": "started", "dor": {"score": 10}, "review": "pending"})
    )

    (todos_dir / "task-2").mkdir()
    (todos_dir / "task-2" / "state.yaml").write_text(
        json.dumps({"build": "pending", "review": "pending", "breakdown": {"todos": ["task-3"]}})
    )

    (todos_dir / "task-3").mkdir()
    # task-3 is a child of task-2

    # Icebox item
    (todos_dir / "icebox-item").mkdir()

    return tmp_path


def test_assemble_roadmap_basic(mock_project):
    """Test basic roadmap assembly."""
    entries = [
        RoadmapEntry(slug="task-1", description="Task 1", group="G1"),
        RoadmapEntry(slug="task-2", description="Task 2", group="G1"),
        RoadmapEntry(slug="task-3", description="Task 3", group="G1"),
    ]

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[RoadmapEntry(slug="icebox-item")]):
            todos = assemble_roadmap(str(mock_project))

    # Should contain 3 roadmap items.
    # icebox-item is skipped because include_icebox=False (default)
    assert len(todos) == 3
    assert todos[0].slug == "task-1"
    assert todos[0].status == "in_progress"
    assert todos[0].dor_score == 10

    assert todos[1].slug == "task-2"

    # task-3 should have task-2 as dependency (injected)
    assert todos[2].slug == "task-3"
    assert "task-2" in todos[2].after


def test_assemble_roadmap_include_icebox(mock_project):
    """Test including icebox items."""
    # We only put task-1 in roadmap. task-2 and task-3 are orphans.
    entries = [RoadmapEntry(slug="task-1", description="Task 1")]

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[RoadmapEntry(slug="icebox-item")]):
            todos = assemble_roadmap(str(mock_project), include_icebox=True)

    # task-1 (roadmap) + icebox-item (icebox) + task-2 (orphan) + task-3 (orphan)
    assert len(todos) == 4
    slugs = [t.slug for t in todos]
    assert "task-1" in slugs
    assert "icebox-item" in slugs
    assert "task-2" in slugs
    assert "task-3" in slugs

    icebox_todo = next(t for t in todos if t.slug == "icebox-item")
    assert icebox_todo.group is None  # No group set on the entry


def test_assemble_roadmap_icebox_only(mock_project):
    """Test showing only icebox items."""
    entries = [RoadmapEntry(slug="task-1", description="Task 1")]

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[RoadmapEntry(slug="icebox-item")]):
            todos = assemble_roadmap(str(mock_project), icebox_only=True)

    # Should only show icebox items. Orphans (task-2, task-3) and roadmap (task-1) excluded.
    assert len(todos) == 1
    assert todos[0].slug == "icebox-item"


def test_assemble_roadmap_container_reordering(mock_project):
    """Test that container is moved before its children if it appears later."""

    # We define task-3 then task-2 in roadmap.
    # task-2 is container for task-3.
    # task-1 and icebox-item are orphans (not in roadmap entries).
    entries = [
        RoadmapEntry(slug="task-3", description="Child"),
        RoadmapEntry(slug="task-2", description="Container"),  # task-2 has task-3 as child
    ]

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[RoadmapEntry(slug="icebox-item")]):
            todos = assemble_roadmap(str(mock_project))

    # task-3, task-2 (roadmap) + task-1 (orphan)
    # icebox-item skipped (default)
    assert len(todos) == 3

    # Check that task-2 comes before task-3 due to reordering logic
    slugs = [t.slug for t in todos]
    t2_idx = slugs.index("task-2")
    t3_idx = slugs.index("task-3")
    assert t2_idx < t3_idx
