"""Characterization tests for roadmap ordering and dependency behavior."""

from __future__ import annotations

from pathlib import Path

import yaml

from teleclaude.core.next_machine._types import PhaseStatus, RoadmapEntry
from teleclaude.core.next_machine.roadmap import (
    add_to_roadmap,
    check_dependencies_satisfied,
    detect_circular_dependency,
    load_roadmap,
    move_in_roadmap,
    save_roadmap,
)


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def test_load_roadmap_skips_invalid_items_and_normalizes_after_lists(tmp_path: Path) -> None:
    roadmap_path = tmp_path / "todos" / "roadmap.yaml"
    roadmap_path.parent.mkdir(parents=True)
    roadmap_path.write_text(
        yaml.safe_dump(
            [
                {"slug": "alpha", "after": ["base"], "description": "first"},
                {"description": "missing slug"},
                {"slug": "beta", "after": "alpha"},
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    entries = load_roadmap(str(tmp_path))

    assert entries == [
        RoadmapEntry(slug="alpha", group=None, after=["base"], description="first"),
        RoadmapEntry(slug="beta", group=None, after=[], description=None),
    ]


def test_add_to_roadmap_inserts_before_target_and_rejects_duplicates(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="first", group=None, after=[], description=None),
            RoadmapEntry(slug="third", group=None, after=[], description=None),
        ],
    )

    inserted = add_to_roadmap(str(tmp_path), "second", before="third")
    duplicate = add_to_roadmap(str(tmp_path), "second")

    assert inserted is True
    assert duplicate is False
    assert [entry.slug for entry in load_roadmap(str(tmp_path))] == ["first", "second", "third"]


def test_move_in_roadmap_restores_original_position_when_target_is_missing(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="first", group=None, after=[], description=None),
            RoadmapEntry(slug="second", group=None, after=[], description=None),
            RoadmapEntry(slug="third", group=None, after=[], description=None),
        ],
    )

    moved = move_in_roadmap(str(tmp_path), "second", before="missing")

    assert moved is False
    assert [entry.slug for entry in load_roadmap(str(tmp_path))] == ["first", "second", "third"]


def test_check_dependencies_satisfied_accepts_approved_and_removed_deps(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="dep-a", group=None, after=[], description=None),
            RoadmapEntry(slug="task", group=None, after=["dep-a", "dep-b"], description=None),
        ],
    )
    _write_state(
        tmp_path / "todos" / "dep-a",
        {"phase": "pending", "review": PhaseStatus.APPROVED.value},
    )

    assert check_dependencies_satisfied(
        str(tmp_path),
        "task",
        {"task": ["dep-a", "dep-b"]},
    )


def test_detect_circular_dependency_returns_existing_cycle_path_shape() -> None:
    cycle = detect_circular_dependency({"b": ["a"], "c": ["b"]}, "a", ["c"])

    assert cycle == ["a", "a", "c", "b", "a"]
