"""Characterization tests for slug resolution and readiness gating."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TypedDict
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine._types import DOR_READY_THRESHOLD, RoadmapEntry
from teleclaude.core.next_machine.roadmap import save_roadmap
from teleclaude.core.next_machine.slug_resolution import (
    resolve_canonical_project_root,
    resolve_first_runnable_holder_child,
    resolve_holder_children,
    resolve_slug,
)


class _DorState(TypedDict):
    score: int


class _ReadyState(TypedDict):
    phase: str
    build: str
    dor: _DorState


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def _ready_state() -> _ReadyState:
    return {"phase": "pending", "build": "pending", "dor": {"score": DOR_READY_THRESHOLD}}


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
    _write_state(tmp_path / "todos" / "dep", {"phase": "pending", "build": "pending", "dor": {"score": 0}})

    resolved = resolve_slug(str(tmp_path), None, True, {"blocked": ["dep"]})

    assert resolved == ("runnable", True, "ready item")


def test_resolve_canonical_project_root_falls_back_to_requested_cwd_on_git_error() -> None:
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["git"])):
        root = resolve_canonical_project_root("/repo/trees/slug")

    assert root == "/repo/trees/slug"
