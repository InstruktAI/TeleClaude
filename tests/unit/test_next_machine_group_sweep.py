"""Tests for group parent auto-delivery sweep in next_work."""

import json
import tempfile
from pathlib import Path

import yaml

from teleclaude.core.next_machine.core import DeliveredEntry, load_delivered, save_delivered, sweep_completed_groups


def _write_state(tmpdir: str, slug: str, state: dict) -> None:
    state_dir = Path(tmpdir) / "todos" / slug
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.yaml").write_text(json.dumps(state))


def _write_roadmap(tmpdir: str, entries: list[dict]) -> None:
    path = Path(tmpdir) / "todos" / "roadmap.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Priority order (first = highest).\n\n"
    body = yaml.dump(entries, default_flow_style=False, sort_keys=False)
    path.write_text(header + body)


def _write_delivered(tmpdir: str, slugs: list[str]) -> None:
    entries = [DeliveredEntry(slug=s, date="2026-02-21", title=f"Delivered {s}") for s in slugs]
    save_delivered(tmpdir, entries)


def test_sweep_delivers_group_when_all_children_delivered():
    """Group parent is auto-delivered when all children are in delivered.yaml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Group parent with 3 children
        _write_state(
            tmpdir,
            "my-group",
            {
                "build": "pending",
                "breakdown": {"assessed": True, "todos": ["child-1", "child-2", "child-3"]},
            },
        )
        # All children delivered
        _write_delivered(tmpdir, ["child-1", "child-2", "child-3"])

        swept = sweep_completed_groups(tmpdir)

        assert swept == ["my-group"]
        # Group todo dir removed
        assert not (Path(tmpdir) / "todos" / "my-group").exists()
        # Group appears in delivered.yaml with children
        delivered = load_delivered(tmpdir)
        group_entry = next(e for e in delivered if e.slug == "my-group")
        assert group_entry.children == ["child-1", "child-2", "child-3"]


def test_sweep_skips_group_with_undelivered_children():
    """Group parent is NOT swept when some children are still undelivered."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_state(
            tmpdir,
            "my-group",
            {
                "build": "pending",
                "breakdown": {"assessed": True, "todos": ["child-1", "child-2"]},
            },
        )
        # Only one child delivered
        _write_delivered(tmpdir, ["child-1"])

        swept = sweep_completed_groups(tmpdir)

        assert swept == []
        assert (Path(tmpdir) / "todos" / "my-group").exists()


def test_sweep_skips_non_group_todos():
    """Regular work items (no breakdown.todos) are not touched."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_state(
            tmpdir,
            "regular-item",
            {
                "build": "pending",
                "breakdown": {"assessed": False, "todos": []},
            },
        )
        _write_delivered(tmpdir, [])

        swept = sweep_completed_groups(tmpdir)

        assert swept == []
        assert (Path(tmpdir) / "todos" / "regular-item").exists()


def test_sweep_removes_group_from_roadmap():
    """Group in roadmap is moved to delivered via deliver_to_delivered."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_state(
            tmpdir,
            "roadmap-group",
            {
                "build": "pending",
                "breakdown": {"assessed": True, "todos": ["c1", "c2"]},
            },
        )
        _write_roadmap(
            tmpdir,
            [
                {"slug": "roadmap-group", "description": "My group description"},
                {"slug": "other-item"},
            ],
        )
        _write_delivered(tmpdir, ["c1", "c2"])

        swept = sweep_completed_groups(tmpdir)

        assert swept == ["roadmap-group"]
        # Removed from roadmap
        roadmap = yaml.safe_load((Path(tmpdir) / "todos" / "roadmap.yaml").read_text())
        roadmap_slugs = [e["slug"] for e in roadmap]
        assert "roadmap-group" not in roadmap_slugs
        assert "other-item" in roadmap_slugs
        # Added to delivered with description from roadmap
        delivered = load_delivered(tmpdir)
        group_entry = next(e for e in delivered if e.slug == "roadmap-group")
        assert group_entry.title == "My group description"
        assert group_entry.children == ["c1", "c2"]


def test_sweep_handles_group_not_in_roadmap():
    """Group NOT in roadmap is still delivered (direct add to delivered.yaml)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_state(
            tmpdir,
            "orphan-group",
            {
                "build": "pending",
                "breakdown": {"assessed": True, "todos": ["x1"]},
            },
        )
        _write_roadmap(tmpdir, [{"slug": "other-item"}])
        _write_delivered(tmpdir, ["x1"])

        swept = sweep_completed_groups(tmpdir)

        assert swept == ["orphan-group"]
        delivered = load_delivered(tmpdir)
        group_entry = next(e for e in delivered if e.slug == "orphan-group")
        assert group_entry.children == ["x1"]
