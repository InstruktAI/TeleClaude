"""Characterization tests for delivered manifest and cleanup behavior."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from teleclaude.core.next_machine._types import DeliveredEntry, RoadmapEntry
from teleclaude.core.next_machine.delivery import (
    cleanup_delivered_slug,
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


# ---------------------------------------------------------------------------
# cleanup_delivered_slug
# ---------------------------------------------------------------------------


def test_cleanup_delivered_slug_removes_todo_dir(tmp_path: Path) -> None:
    """Todo directory is physically removed after cleanup."""
    todo_dir = tmp_path / "todos" / "my-slug"
    todo_dir.mkdir(parents=True)
    (todo_dir / "state.yaml").write_text("phase: done", encoding="utf-8")

    with (
        patch("teleclaude.core.next_machine.delivery._run_git_cmd", return_value=(0, "", "")),
        patch("teleclaude.core.next_machine.delivery.clean_dependency_references"),
    ):
        cleanup_delivered_slug(str(tmp_path), "my-slug")

    assert not todo_dir.exists()


def test_cleanup_delivered_slug_falls_back_on_worktree_remove_failure(tmp_path: Path) -> None:
    """When git worktree remove fails, the directory is removed via shutil and git worktree prune runs."""
    from teleclaude.constants import WORKTREE_DIR

    worktree_dir = tmp_path / WORKTREE_DIR / "my-slug"
    worktree_dir.mkdir(parents=True)
    (worktree_dir / "marker").write_text("exists", encoding="utf-8")

    call_log: list[list[str]] = []

    def fake_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        call_log.append(args)
        if args[:2] == ["worktree", "remove"]:
            return 1, "", "worktree remove failed"
        return 0, "", ""

    with (
        patch("teleclaude.core.next_machine.delivery._run_git_cmd", side_effect=fake_git),
        patch("teleclaude.core.next_machine.delivery.clean_dependency_references"),
    ):
        cleanup_delivered_slug(str(tmp_path), "my-slug")

    assert not worktree_dir.exists(), "worktree directory should be removed by fallback"
    assert ["worktree", "prune"] in call_log, "git worktree prune should run after fallback"


def test_cleanup_delivered_slug_logs_error_on_todo_dir_removal_failure(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """OSError during todo dir removal is logged at ERROR, not swallowed."""
    todo_dir = tmp_path / "todos" / "my-slug"
    todo_dir.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.delivery._run_git_cmd", return_value=(0, "", "")),
        patch("teleclaude.core.next_machine.delivery.clean_dependency_references"),
        patch("teleclaude.core.next_machine.delivery.shutil.rmtree", side_effect=OSError("permission denied")),
        caplog.at_level(logging.ERROR),
    ):
        cleanup_delivered_slug(str(tmp_path), "my-slug")

    assert any("todo directory removal failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _sweep_stale_artifacts (via step_functions)
# ---------------------------------------------------------------------------


def test_sweep_stale_artifacts_only_removes_delivered_slugs(tmp_path: Path) -> None:
    """Sweep calls cleanup for delivered slugs only; non-delivered slugs are untouched."""
    from teleclaude.constants import WORKTREE_DIR
    from teleclaude.core.integration.step_functions import _sweep_stale_artifacts

    save_delivered(
        str(tmp_path),
        [DeliveredEntry(slug="done-slug", date="2025-01-01", commit="abc", children=None)],
    )

    for slug in ("done-slug", "active-slug"):
        (tmp_path / WORKTREE_DIR / slug).mkdir(parents=True)
        (tmp_path / "todos" / slug).mkdir(parents=True)

    cleaned_slugs: list[str] = []

    def track_cleanup(cwd: str, slug: str, **kwargs: object) -> None:
        cleaned_slugs.append(slug)

    with patch("teleclaude.core.next_machine.delivery.cleanup_delivered_slug", side_effect=track_cleanup):
        cleaned = _sweep_stale_artifacts(str(tmp_path))

    assert "done-slug" in cleaned
    assert "active-slug" not in cleaned
    assert "done-slug" in cleaned_slugs
    assert "active-slug" not in cleaned_slugs


def test_sweep_stale_artifacts_skips_underscore_dirs(tmp_path: Path) -> None:
    """Directories starting with _ (like _integration) are never swept."""
    from teleclaude.constants import WORKTREE_DIR
    from teleclaude.core.integration.step_functions import _sweep_stale_artifacts

    save_delivered(str(tmp_path), [])
    (tmp_path / WORKTREE_DIR / "_integration").mkdir(parents=True)

    cleaned = _sweep_stale_artifacts(str(tmp_path))

    assert cleaned == []
    assert (tmp_path / WORKTREE_DIR / "_integration").exists()
