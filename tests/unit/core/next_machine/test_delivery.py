"""Characterization tests for delivered manifest and cleanup behavior."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from teleclaude.core.next_machine._types import DeliveredEntry, RoadmapEntry
from teleclaude.core.next_machine.delivery import (
    _archive_binary_artifacts,
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


class TestArchiveBinaryArtifacts:
    """Tests for _archive_binary_artifacts — moves art/html/input dirs to permanent storage."""

    @pytest.fixture()
    def storage_root(self, tmp_path: Path) -> Path:
        return tmp_path / "storage"

    @pytest.fixture(autouse=True)
    def _patch_storage_and_date(self, storage_root: Path) -> Iterator[None]:
        fake_date = type(
            "FakeDate", (), {"today": staticmethod(lambda: type("D", (), {"isoformat": lambda self: "2026-01-15"})())}
        )
        with (
            patch("teleclaude.core.next_machine.delivery._STORAGE_ROOT", storage_root),
            patch("teleclaude.core.next_machine.delivery.date", fake_date),
        ):
            yield

    @staticmethod
    def _make_worktree(tmp_path: Path, slug: str, dirs: dict[str, list[str]]) -> Path:
        """Create a fake worktree with the given artifact dirs and files."""
        worktree = tmp_path / "trees" / slug
        for dirname, files in dirs.items():
            artifact_dir = worktree / "todos" / slug / dirname
            artifact_dir.mkdir(parents=True, exist_ok=True)
            for fname in files:
                (artifact_dir / fname).write_bytes(b"binary data")
        return worktree

    @pytest.mark.unit
    def test_archive_moves_art_dir_to_storage(self, tmp_path: Path, storage_root: Path) -> None:
        worktree = self._make_worktree(tmp_path, "my-slug", {"art": ["mood.png", "logo.svg"]})

        _archive_binary_artifacts(worktree, "my-slug")

        art_dest = storage_root / "2026-01-15" / "my-slug" / "art"
        assert art_dest.is_dir()
        assert {f.name for f in art_dest.iterdir()} == {"mood.png", "logo.svg"}
        assert not (worktree / "todos" / "my-slug" / "art").exists()

    @pytest.mark.unit
    def test_archive_moves_html_dir_to_storage(self, tmp_path: Path, storage_root: Path) -> None:
        worktree = self._make_worktree(tmp_path, "my-slug", {"html": ["index.html"]})

        _archive_binary_artifacts(worktree, "my-slug")

        html_dest = storage_root / "2026-01-15" / "my-slug" / "html"
        assert html_dest.is_dir()
        assert (html_dest / "index.html").exists()

    @pytest.mark.unit
    def test_archive_skips_missing_worktree(self, tmp_path: Path, storage_root: Path) -> None:
        nonexistent = tmp_path / "trees" / "gone"

        _archive_binary_artifacts(nonexistent, "gone")

        assert not storage_root.exists()

    @pytest.mark.unit
    def test_archive_skips_empty_dirs(self, tmp_path: Path, storage_root: Path) -> None:
        worktree = tmp_path / "trees" / "my-slug"
        (worktree / "todos" / "my-slug" / "art").mkdir(parents=True)

        _archive_binary_artifacts(worktree, "my-slug")

        assert not storage_root.exists()

    @pytest.mark.unit
    def test_archive_noop_when_no_binary_dirs(self, tmp_path: Path, storage_root: Path) -> None:
        worktree = tmp_path / "trees" / "my-slug"
        (worktree / "todos" / "my-slug" / "src").mkdir(parents=True)
        (worktree / "todos" / "my-slug" / "src" / "main.py").write_text("code")

        _archive_binary_artifacts(worktree, "my-slug")

        assert not storage_root.exists()
