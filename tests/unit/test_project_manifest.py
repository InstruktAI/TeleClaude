from __future__ import annotations

from pathlib import Path

import yaml

from teleclaude.project_manifest import load_manifest, register_project


def test_register_project_round_trip(tmp_path: Path) -> None:
    manifest_path = tmp_path / "projects.yaml"
    project_root = tmp_path / "teleclaude"
    index_path = project_root / "docs" / "project" / "index.yaml"
    project_root.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("snippets: []\n", encoding="utf-8")

    register_project(
        path=manifest_path,
        project_root=project_root,
        project_name="TeleClaude",
        description="Core project",
        index_path=index_path,
    )

    entries = load_manifest(manifest_path)
    assert len(entries) == 1
    assert entries[0].name == "TeleClaude"
    assert entries[0].description == "Core project"
    assert entries[0].project_root == str(project_root.resolve())
    assert entries[0].index_path == str(index_path.resolve())


def test_load_manifest_skips_stale_index_entries(tmp_path: Path) -> None:
    manifest_path = tmp_path / "projects.yaml"
    valid_root = tmp_path / "valid"
    valid_index = valid_root / "docs" / "project" / "index.yaml"
    valid_index.parent.mkdir(parents=True, exist_ok=True)
    valid_index.write_text("snippets: []\n", encoding="utf-8")

    payload = {
        "projects": [
            {
                "name": "Valid",
                "description": "ok",
                "index_path": str(valid_index),
                "project_root": str(valid_root),
            },
            {
                "name": "Stale",
                "description": "skip",
                "index_path": str(tmp_path / "missing" / "index.yaml"),
                "project_root": str(tmp_path / "missing"),
            },
        ]
    }
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    entries = load_manifest(manifest_path)
    assert [entry.name for entry in entries] == ["Valid"]
