"""Unit tests for roadmap assembly."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from teleclaude.core.next_machine.core import RoadmapEntry, _icebox_path
from teleclaude.core.roadmap import assemble_roadmap


@pytest.fixture
def mock_project(tmp_path):
    """Create a mock project structure."""
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    icebox_sub = todos_dir / "_icebox"
    icebox_sub.mkdir()
    (icebox_sub / "icebox.yaml").touch()  # Ensure icebox logic triggers (new path)

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

    # Icebox item in new location
    (icebox_sub / "icebox-item").mkdir()

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


def test_worktree_state_takes_precedence(tmp_path):
    """Worktree state.yaml overrides main todos/ state when present."""
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    (todos_dir / "_icebox").mkdir(exist_ok=True)
    (todos_dir / "_icebox" / "icebox.yaml").touch()

    # Main state: dor score 3
    (todos_dir / "task-1").mkdir()
    (todos_dir / "task-1" / "state.yaml").write_text(
        json.dumps({"build": "pending", "dor": {"score": 3}, "review": "pending"})
    )

    # Worktree state: dor score 8 (active work in progress)
    worktree_state_dir = tmp_path / "trees" / "task-1" / "todos" / "task-1"
    worktree_state_dir.mkdir(parents=True)
    (worktree_state_dir / "state.yaml").write_text(
        json.dumps({"build": "started", "dor": {"score": 8}, "review": "pending"})
    )

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos = assemble_roadmap(str(tmp_path))

    assert len(todos) == 1
    assert todos[0].slug == "task-1"
    assert todos[0].dor_score == 8  # Worktree value, not main
    assert todos[0].status == "in_progress"  # build: started


def test_phase_in_progress_shows_active(tmp_path):
    """phase: in_progress (set by state machine on claim) derives in_progress status."""
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    (todos_dir / "_icebox").mkdir(exist_ok=True)
    (todos_dir / "_icebox" / "icebox.yaml").touch()

    (todos_dir / "task-1").mkdir()
    (todos_dir / "task-1" / "state.yaml").write_text(
        json.dumps({"phase": "in_progress", "build": "pending", "dor": {"score": 9}, "review": "pending"})
    )

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos = assemble_roadmap(str(tmp_path))

    assert len(todos) == 1
    assert todos[0].status == "in_progress"  # phase: in_progress takes precedence over build: pending


def test_phase_done_shows_active(tmp_path):
    """phase: done derives in_progress status (still visible until delivered)."""
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    (todos_dir / "_icebox").mkdir(exist_ok=True)
    (todos_dir / "_icebox" / "icebox.yaml").touch()

    (todos_dir / "task-1").mkdir()
    (todos_dir / "task-1" / "state.yaml").write_text(
        json.dumps({"phase": "done", "build": "complete", "dor": {"score": 9}, "review": "approved"})
    )

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos = assemble_roadmap(str(tmp_path))

    assert len(todos) == 1
    assert todos[0].status == "in_progress"


def test_phase_pending_defers_to_build_and_dor(tmp_path):
    """phase: pending (or absent) falls through to build/dor derivation."""
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    (todos_dir / "_icebox").mkdir(exist_ok=True)
    (todos_dir / "_icebox" / "icebox.yaml").touch()

    # phase pending + build pending + high DOR → ready
    (todos_dir / "task-1").mkdir()
    (todos_dir / "task-1" / "state.yaml").write_text(
        json.dumps({"phase": "pending", "build": "pending", "dor": {"score": 9}, "review": "pending"})
    )

    # no phase + build pending + low DOR → pending
    (todos_dir / "task-2").mkdir()
    (todos_dir / "task-2" / "state.yaml").write_text(
        json.dumps({"build": "pending", "dor": {"score": 3}, "review": "pending"})
    )

    entries = [
        RoadmapEntry(slug="task-1", description="Task 1"),
        RoadmapEntry(slug="task-2", description="Task 2"),
    ]

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos = assemble_roadmap(str(tmp_path))

    assert todos[0].status == "ready"
    assert todos[1].status == "pending"


def test_worktree_state_fallback_to_main(tmp_path):
    """Without a worktree, main todos/ state.yaml is used."""
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    (todos_dir / "_icebox").mkdir(exist_ok=True)
    (todos_dir / "_icebox" / "icebox.yaml").touch()

    (todos_dir / "task-1").mkdir()
    (todos_dir / "task-1" / "state.yaml").write_text(
        json.dumps({"build": "pending", "dor": {"score": 5}, "review": "pending"})
    )

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos = assemble_roadmap(str(tmp_path))

    assert len(todos) == 1
    assert todos[0].dor_score == 5  # Main value used


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


# ── New _icebox/ layout tests ──────────────────────────────────────────────────


def test_icebox_path_returns_new_location(tmp_path: Path) -> None:
    """_icebox_path() must return todos/_icebox/icebox.yaml."""
    result = _icebox_path(str(tmp_path))
    assert result == tmp_path / "todos" / "_icebox" / "icebox.yaml"


def test_assemble_roadmap_reads_icebox_metadata_from_subfolder(tmp_path: Path) -> None:
    """Icebox items read state from todos/_icebox/{slug}/ after folder move."""
    todos = tmp_path / "todos"
    todos.mkdir()
    icebox_dir = todos / "_icebox"
    icebox_dir.mkdir()

    # Write icebox manifest at new location
    (icebox_dir / "icebox.yaml").write_text(yaml.dump([{"slug": "frozen-item"}]))

    # Write icebox item state under _icebox/
    item_dir = icebox_dir / "frozen-item"
    item_dir.mkdir()
    (item_dir / "state.yaml").write_text(yaml.dump({"build": "complete", "review": "pending"}))
    (item_dir / "requirements.md").write_text("# Req")

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=[]):
        todos_obj = assemble_roadmap(str(tmp_path), include_icebox=True)

    assert len(todos_obj) == 1
    assert todos_obj[0].slug == "frozen-item"
    assert todos_obj[0].build_status == "complete"
    assert todos_obj[0].has_requirements is True


def test_orphan_scan_skips_icebox_dir(tmp_path: Path) -> None:
    """_icebox directory must not appear as an orphan in roadmap listing."""
    todos = tmp_path / "todos"
    todos.mkdir()
    icebox_dir = todos / "_icebox"
    icebox_dir.mkdir()
    (icebox_dir / "icebox.yaml").write_text(yaml.dump([]))

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=[]):
        result = assemble_roadmap(str(tmp_path))

    slugs = [t.slug for t in result]
    assert "_icebox" not in slugs


def test_orphan_scan_does_not_skip_other_underscore_dirs(tmp_path: Path) -> None:
    """Only _icebox is excluded — other underscore directories are still listed."""
    todos = tmp_path / "todos"
    todos.mkdir()
    icebox_dir = todos / "_icebox"
    icebox_dir.mkdir()
    (icebox_dir / "icebox.yaml").write_text(yaml.dump([]))
    (todos / "_other-dir").mkdir()

    with patch("teleclaude.core.roadmap.load_roadmap", return_value=[]):
        result = assemble_roadmap(str(tmp_path))

    slugs = [t.slug for t in result]
    assert "_other-dir" in slugs
    assert "_icebox" not in slugs


# ── Phase field pipeline tests ──────────────────────────────────────────────


def test_read_todo_metadata_prepare_phase(tmp_path: Path) -> None:
    """prepare_phase is read from state.yaml and flows through to TodoInfo."""
    todos = tmp_path / "todos"
    todos.mkdir()
    (todos / "_icebox").mkdir()
    (todos / "_icebox" / "icebox.yaml").touch()
    (todos / "task-1").mkdir()
    (todos / "task-1" / "state.yaml").write_text(
        yaml.dump({"build": "pending", "prepare_phase": "plan_drafting"})
    )

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos_obj = assemble_roadmap(str(tmp_path))

    assert len(todos_obj) == 1
    assert todos_obj[0].prepare_phase == "plan_drafting"


def test_read_todo_metadata_integration_phase(tmp_path: Path) -> None:
    """integration_phase is read from state.yaml and flows through to TodoInfo."""
    todos = tmp_path / "todos"
    todos.mkdir()
    (todos / "_icebox").mkdir()
    (todos / "_icebox" / "icebox.yaml").touch()
    (todos / "task-1").mkdir()
    (todos / "task-1" / "state.yaml").write_text(
        yaml.dump({"build": "pending", "integration_phase": "merge_clean"})
    )

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos_obj = assemble_roadmap(str(tmp_path))

    assert len(todos_obj) == 1
    assert todos_obj[0].integration_phase == "merge_clean"


def test_read_todo_metadata_finalize_status(tmp_path: Path) -> None:
    """finalize_status is read from state.yaml finalize.status and flows through."""
    todos = tmp_path / "todos"
    todos.mkdir()
    (todos / "_icebox").mkdir()
    (todos / "_icebox" / "icebox.yaml").touch()
    (todos / "task-1").mkdir()
    (todos / "task-1" / "state.yaml").write_text(
        yaml.dump({"build": "pending", "finalize": {"status": "handed_off"}})
    )

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos_obj = assemble_roadmap(str(tmp_path))

    assert len(todos_obj) == 1
    assert todos_obj[0].finalize_status == "handed_off"


def test_read_todo_metadata_missing_phase_fields_are_none(tmp_path: Path) -> None:
    """Missing phase fields in state.yaml default to None (backward compat)."""
    todos = tmp_path / "todos"
    todos.mkdir()
    (todos / "_icebox").mkdir()
    (todos / "_icebox" / "icebox.yaml").touch()
    (todos / "task-1").mkdir()
    (todos / "task-1" / "state.yaml").write_text(yaml.dump({"build": "pending"}))

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos_obj = assemble_roadmap(str(tmp_path))

    assert todos_obj[0].prepare_phase is None
    assert todos_obj[0].integration_phase is None
    assert todos_obj[0].finalize_status is None


def test_read_todo_metadata_empty_prepare_phase_coerced_to_none(tmp_path: Path) -> None:
    """Empty string prepare_phase is coerced to None."""
    todos = tmp_path / "todos"
    todos.mkdir()
    (todos / "_icebox").mkdir()
    (todos / "_icebox" / "icebox.yaml").touch()
    (todos / "task-1").mkdir()
    (todos / "task-1" / "state.yaml").write_text(yaml.dump({"build": "pending", "prepare_phase": ""}))

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos_obj = assemble_roadmap(str(tmp_path))

    assert todos_obj[0].prepare_phase is None


def test_read_todo_metadata_unknown_finalize_status_coerced_to_none(tmp_path: Path) -> None:
    """Unknown finalize status is coerced to None."""
    todos = tmp_path / "todos"
    todos.mkdir()
    (todos / "_icebox").mkdir()
    (todos / "_icebox" / "icebox.yaml").touch()
    (todos / "task-1").mkdir()
    (todos / "task-1" / "state.yaml").write_text(
        yaml.dump({"build": "pending", "finalize": {"status": "unknown_status"}})
    )

    entries = [RoadmapEntry(slug="task-1", description="Task 1")]
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=entries):
        with patch("teleclaude.core.roadmap.load_icebox", return_value=[]):
            todos_obj = assemble_roadmap(str(tmp_path))

    assert todos_obj[0].finalize_status is None
