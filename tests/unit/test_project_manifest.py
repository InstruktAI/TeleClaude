"""Tests for teleclaude.project_manifest root-only registry."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from teleclaude import project_manifest

pytestmark = pytest.mark.unit


def test_load_roots_returns_empty_list_when_manifest_missing(tmp_path: Path) -> None:
    assert project_manifest.load_roots(tmp_path / "projects.yaml") == []


def test_load_roots_returns_normalized_absolute_paths(tmp_path: Path) -> None:
    project_a = tmp_path / "alpha"
    project_b = tmp_path / "beta"
    project_a.mkdir()
    project_b.mkdir()

    manifest_path = tmp_path / "projects.yaml"
    manifest_path.write_text(
        yaml.safe_dump({"projects": [str(project_a), str(project_b)]}),
        encoding="utf-8",
    )

    roots = project_manifest.load_roots(manifest_path)

    assert roots == [project_a.resolve(), project_b.resolve()]


def test_load_roots_dedupes_and_skips_non_existent_roots(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    dead = tmp_path / "dead"  # never created

    manifest_path = tmp_path / "projects.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    str(live),
                    str(live),  # duplicate — must collapse
                    str(dead),  # missing directory — dropped
                ]
            }
        ),
        encoding="utf-8",
    )

    assert project_manifest.load_roots(manifest_path) == [live.resolve()]


def test_load_roots_ignores_legacy_metadata_format(tmp_path: Path) -> None:
    """Legacy entries with name/description/index_path are coerced to root-only."""
    project_root = tmp_path / "legacy"
    project_root.mkdir()

    manifest_path = tmp_path / "projects.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {
                        "name": "Legacy",
                        "description": "old shape",
                        "index_path": str(project_root / "docs" / "project" / "index.yaml"),
                        "project_root": str(project_root),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert project_manifest.load_roots(manifest_path) == [project_root.resolve()]


def test_load_roots_returns_empty_on_malformed_yaml(tmp_path: Path) -> None:
    manifest_path = tmp_path / "projects.yaml"
    manifest_path.write_text("::not yaml::", encoding="utf-8")

    assert project_manifest.load_roots(manifest_path) == []


def test_register_root_writes_new_manifest_with_single_entry(tmp_path: Path) -> None:
    project_root = tmp_path / "alpha"
    project_root.mkdir()
    manifest_path = tmp_path / "state" / "projects.yaml"

    project_manifest.register_root(path=manifest_path, project_root=project_root)

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert payload == {"projects": [str(project_root.resolve())]}


def test_register_root_is_idempotent_for_repeated_calls(tmp_path: Path) -> None:
    project_root = tmp_path / "alpha"
    project_root.mkdir()
    manifest_path = tmp_path / "projects.yaml"

    project_manifest.register_root(path=manifest_path, project_root=project_root)
    project_manifest.register_root(path=manifest_path, project_root=project_root)

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert payload == {"projects": [str(project_root.resolve())]}


def test_register_root_preserves_prior_roots_and_appends_new(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    manifest_path = tmp_path / "projects.yaml"
    manifest_path.write_text(
        yaml.safe_dump({"projects": [str(existing)]}),
        encoding="utf-8",
    )

    project_manifest.register_root(path=manifest_path, project_root=fresh)

    roots = project_manifest.load_roots(manifest_path)
    assert set(roots) == {existing.resolve(), fresh.resolve()}


def test_register_root_migrates_legacy_metadata_format_to_root_only(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    manifest_path = tmp_path / "projects.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {
                        "name": "Legacy",
                        "description": "",
                        "index_path": str(legacy / "docs" / "project" / "index.yaml"),
                        "project_root": str(legacy),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    project_manifest.register_root(path=manifest_path, project_root=fresh)

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    # No nested metadata keys survived; roots are strings only.
    assert all(isinstance(entry, str) for entry in payload["projects"])
    assert set(payload["projects"]) == {str(legacy.resolve()), str(fresh.resolve())}
