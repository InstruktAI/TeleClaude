"""Characterization tests for delivered manifest and cleanup behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine._types import DeliveredEntry, RoadmapEntry
from teleclaude.core.next_machine.delivery import (
    deliver_to_delivered,
    load_delivered,
    reconcile_roadmap_after_merge,
    save_delivered,
    sweep_completed_groups,
)
from teleclaude.core.next_machine.roadmap import load_roadmap, save_roadmap


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def test_load_delivered_ignores_invalid_items_and_keeps_children_lists(tmp_path: Path) -> None:
    delivered_path = tmp_path / "todos" / "delivered.yaml"
    delivered_path.parent.mkdir(parents=True)
    delivered_path.write_text(
        yaml.safe_dump(
            [
                {"slug": "done", "date": "2025-01-01", "children": ["child-a"]},
                {"date": "missing-slug"},
                {"slug": "plain", "date": "2025-01-02", "children": "not-a-list"},
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    entries = load_delivered(str(tmp_path))

    assert entries == [
        DeliveredEntry(slug="done", date="2025-01-01", commit=None, children=["child-a"]),
        DeliveredEntry(slug="plain", date="2025-01-02", commit=None, children=None),
    ]


def test_deliver_to_delivered_removes_roadmap_entry_and_prepends_manifest_entry(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="carry-on", group=None, after=[], description=None),
            RoadmapEntry(slug="target", group=None, after=[], description=None),
        ],
    )
    save_delivered(
        str(tmp_path),
        [DeliveredEntry(slug="older", date="2025-01-01", commit="aaaa1111", children=None)],
    )

    delivered = deliver_to_delivered(str(tmp_path), "target", commit="deadbeef")

    assert delivered is True
    assert [entry.slug for entry in load_roadmap(str(tmp_path))] == ["carry-on"]
    assert [(entry.slug, entry.commit) for entry in load_delivered(str(tmp_path))] == [
        ("target", "deadbeef"),
        ("older", "aaaa1111"),
    ]


def test_reconcile_roadmap_after_merge_removes_ghost_and_orphan_entries(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="ghost", group=None, after=[], description=None),
            RoadmapEntry(slug="orphan", group=None, after=[], description=None),
            RoadmapEntry(slug="keep", group=None, after=[], description=None),
        ],
    )
    save_delivered(
        str(tmp_path),
        [DeliveredEntry(slug="ghost", date="2025-01-01", commit=None, children=None)],
    )
    (tmp_path / "todos" / "keep").mkdir(parents=True)

    with patch("teleclaude.core.next_machine.delivery.clean_dependency_references") as clean_refs:
        removed = reconcile_roadmap_after_merge(str(tmp_path))

    assert removed == ["ghost", "orphan"]
    assert [entry.slug for entry in load_roadmap(str(tmp_path))] == ["keep"]
    assert [call.args[1] for call in clean_refs.call_args_list] == ["ghost", "orphan"]


def test_sweep_completed_groups_delivers_holder_with_children_metadata(tmp_path: Path) -> None:
    group_dir = tmp_path / "todos" / "group-parent"
    _write_state(group_dir, {"breakdown": {"todos": ["child-a", "child-b"]}})
    save_roadmap(
        str(tmp_path),
        [RoadmapEntry(slug="group-parent", group=None, after=[], description=None)],
    )
    save_delivered(
        str(tmp_path),
        [
            DeliveredEntry(slug="child-a", date="2025-01-01", commit=None, children=None),
            DeliveredEntry(slug="child-b", date="2025-01-01", commit=None, children=None),
        ],
    )

    with patch("teleclaude.core.next_machine.delivery.cleanup_delivered_slug") as cleanup:
        swept = sweep_completed_groups(str(tmp_path))

    assert swept == ["group-parent"]
    assert cleanup.call_args.args[1] == "group-parent"
    assert load_delivered(str(tmp_path))[0].children == ["child-a", "child-b"]
