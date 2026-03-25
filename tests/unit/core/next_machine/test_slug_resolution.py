"""Characterization tests for slug resolution and readiness gating."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TypedDict
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine._types import RoadmapEntry
from teleclaude.core.next_machine.roadmap import save_roadmap
from teleclaude.core.next_machine.slug_resolution import (
    get_item_phase,
    is_ready_for_work,
    resolve_canonical_project_root,
    resolve_first_runnable_holder_child,
    resolve_holder_children,
    resolve_slug,
)


class _ReadyStateV2(TypedDict):
    schema_version: int
    current: str


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def _ready_state() -> _ReadyStateV2:
    return {"schema_version": 2, "current": "prepared"}


def test_resolve_holder_children_prefers_roadmap_order_and_appends_breakdown_only_children(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="child-a", group="holder", after=[], description=None),
            RoadmapEntry(slug="child-b", group="holder", after=[], description=None),
        ],
    )
    _write_state(tmp_path / "todos" / "holder", {"breakdown": {"todos": ["child-b", "child-c"]}})

    children = resolve_holder_children(str(tmp_path), "holder")

    assert children == ["child-a", "child-b", "child-c"]


def test_resolve_first_runnable_holder_child_returns_first_ready_child_with_satisfied_dependencies(
    tmp_path: Path,
) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="child-a", group="holder", after=[], description=None),
            RoadmapEntry(slug="child-b", group="holder", after=[], description=None),
        ],
    )
    _write_state(tmp_path / "todos" / "child-a", _ready_state())
    _write_state(tmp_path / "todos" / "child-b", _ready_state())

    child, reason = resolve_first_runnable_holder_child(str(tmp_path), "holder", {"child-a": [], "child-b": []})

    assert (child, reason) == ("child-a", "ok")


def test_resolve_first_runnable_holder_child_reports_children_not_in_roadmap(tmp_path: Path) -> None:
    _write_state(tmp_path / "todos" / "holder", {"breakdown": {"todos": ["child-x"]}})

    child, reason = resolve_first_runnable_holder_child(str(tmp_path), "holder", {})

    assert (child, reason) == (None, "children_not_in_roadmap")


def test_resolve_slug_ready_only_skips_ready_items_with_unsatisfied_dependencies(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="blocked", group=None, after=["dep"], description="blocked item"),
            RoadmapEntry(slug="runnable", group=None, after=[], description="ready item"),
            RoadmapEntry(slug="dep", group=None, after=[], description="dependency"),
        ],
    )
    _write_state(tmp_path / "todos" / "blocked", _ready_state())
    _write_state(tmp_path / "todos" / "runnable", _ready_state())
    _write_state(tmp_path / "todos" / "dep", {"schema_version": 2, "current": "input_assessment"})

    resolved = resolve_slug(str(tmp_path), None, True, {"blocked": ["dep"]})

    assert resolved == ("runnable", True, "ready item")


def test_is_ready_for_work_accepts_pending_item_with_completed_build(tmp_path: Path) -> None:
    _write_state(tmp_path / "todos" / "from-main-slug", {"schema_version": 2, "current": "prepared"})

    assert is_ready_for_work(str(tmp_path), "from-main-slug") is True


def test_resolve_canonical_project_root_falls_back_to_requested_cwd_on_git_error() -> None:
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["git"])):
        root = resolve_canonical_project_root("/repo/trees/slug")

    assert root == "/repo/trees/slug"


def _write_delivered(tmp_path: Path, slug: str) -> None:
    """Write a minimal delivered.yaml with the given slug."""
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir(parents=True, exist_ok=True)
    (todos_dir / "delivered.yaml").write_text(yaml.dump([{"slug": slug, "date": "2026-03-20"}]), encoding="utf-8")


def test_get_item_phase_returns_done_for_delivered_slug_with_no_state_yaml(tmp_path: Path) -> None:
    """Delivered slugs with cleaned-up state.yaml must return 'done', not 'pending'."""
    slug = "my-delivered-slug"
    _write_delivered(tmp_path, slug)
    # state.yaml deliberately absent — simulates post-delivery cleanup
    assert not (tmp_path / "todos" / slug / "state.yaml").exists()

    phase = get_item_phase(str(tmp_path), slug)

    assert phase == "done"


def test_get_item_phase_raises_on_slug_in_both_delivered_and_roadmap(tmp_path: Path) -> None:
    """A slug in both delivered.yaml and roadmap.yaml is a data integrity error."""
    import pytest

    slug = "ambiguous-slug"
    _write_delivered(tmp_path, slug)
    save_roadmap(str(tmp_path), [RoadmapEntry(slug=slug, group=None, after=[], description=None)])

    with pytest.raises(ValueError, match="data integrity"):
        get_item_phase(str(tmp_path), slug)
