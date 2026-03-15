"""Characterization tests for teleclaude.project_manifest."""

from __future__ import annotations

from pathlib import Path

import yaml

import teleclaude.project_manifest as project_manifest


def test_entry_from_raw_normalizes_strings_and_resolves_paths(tmp_path: Path) -> None:
    index_path = tmp_path / "docs" / "project" / "index.yaml"
    project_root = tmp_path / "repo"

    entry = project_manifest._entry_from_raw(
        {
            "name": " Alpha ",
            "description": 7,
            "index_path": str(index_path),
            "project_root": str(project_root),
        }
    )

    assert entry == project_manifest.ProjectManifestEntry(
        name="Alpha",
        description="",
        index_path=str(index_path.resolve()),
        project_root=str(project_root.resolve()),
    )


def test_load_manifest_filters_out_entries_with_missing_index_files(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    live_index = live_root / "index.yaml"
    live_index.write_text("snippets: []\n", encoding="utf-8")

    dead_root = tmp_path / "dead"
    dead_root.mkdir()

    manifest_path = tmp_path / "projects.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {
                        "name": "Live",
                        "description": "kept",
                        "index_path": str(live_index),
                        "project_root": str(live_root),
                    },
                    {
                        "name": "Dead",
                        "description": "dropped",
                        "index_path": str(dead_root / "index.yaml"),
                        "project_root": str(dead_root),
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    entries = project_manifest.load_manifest(manifest_path)

    assert entries == [
        project_manifest.ProjectManifestEntry(
            name="Live",
            description="kept",
            index_path=str(live_index.resolve()),
            project_root=str(live_root.resolve()),
        )
    ]


def test_register_project_updates_existing_entry_and_sorts_by_name(tmp_path: Path) -> None:
    manifest_path = tmp_path / "state" / "projects.yaml"
    alpha_root = tmp_path / "alpha"
    zeta_root = tmp_path / "zeta"
    alpha_root.mkdir()
    zeta_root.mkdir()
    alpha_index = alpha_root / "index.yaml"
    zeta_index = zeta_root / "index.yaml"
    alpha_index.write_text("snippets: []\n", encoding="utf-8")
    zeta_index.write_text("snippets: []\n", encoding="utf-8")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {
                        "name": "Zeta",
                        "description": "existing",
                        "index_path": str(zeta_index),
                        "project_root": str(zeta_root),
                    },
                    {
                        "name": "Old Alpha",
                        "description": "stale",
                        "index_path": str(alpha_index),
                        "project_root": str(alpha_root),
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    project_manifest.register_project(
        path=manifest_path,
        project_root=alpha_root,
        project_name="Alpha",
        description="updated",
        index_path=alpha_index,
    )

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert [entry["name"] for entry in payload["projects"]] == ["Alpha", "Zeta"]
    assert payload["projects"][0]["description"] == "updated"
    assert payload["projects"][0]["project_root"] == str(alpha_root.resolve())
