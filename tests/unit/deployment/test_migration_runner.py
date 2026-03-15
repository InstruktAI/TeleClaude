"""Characterization tests for teleclaude.deployment.migration_runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import teleclaude.deployment.migration_runner as migration_runner


def _write_migration(path: Path, *, check: str = "False", migrate: str = "True") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "def check() -> bool:",
                f"    return {check}",
                "",
                "def migrate() -> bool:",
                f"    return {migrate}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_discover_migrations_filters_invalid_entries_and_sorts_by_version_then_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_migration(migrations_dir / "v1.1.0" / "020_second.py")
    _write_migration(migrations_dir / "v1.1.0" / "010_first.py")
    _write_migration(migrations_dir / "v1.2.0" / "005_upgrade.py")
    _write_migration(migrations_dir / "v2.0.0" / "001_out_of_range.py")
    _write_migration(migrations_dir / "not-a-version" / "001_ignore.py")
    (migrations_dir / "v1.2.0" / "notes.txt").write_text("ignore", encoding="utf-8")
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", migrations_dir)

    discovered = migration_runner.discover_migrations("1.0.0", "1.2.0")

    assert [(version, path.name) for version, path in discovered] == [
        ("1.1.0", "010_first.py"),
        ("1.1.0", "020_second.py"),
        ("1.2.0", "005_upgrade.py"),
    ]


def test_run_migrations_dry_run_reports_planned_migrations_without_writing_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    state_path = tmp_path / "state.json"
    _write_migration(migrations_dir / "v1.0.0" / "001_bootstrap.py")
    _write_migration(migrations_dir / "v1.0.1" / "010_followup.py")
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", migrations_dir)
    monkeypatch.setattr(migration_runner, "MIGRATION_STATE_FILE", state_path)

    result = migration_runner.run_migrations("0.9.0", "1.0.1", dry_run=True)

    assert result == {
        "migrations_run": 0,
        "migrations_skipped": 0,
        "error": None,
        "planned_migrations": ["1.0.0/001_bootstrap.py", "1.0.1/010_followup.py"],
    }
    assert not state_path.exists()


def test_run_migrations_executes_unapplied_scripts_and_persists_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    state_path = tmp_path / "state.json"
    _write_migration(migrations_dir / "v1.0.0" / "001_bootstrap.py")
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", migrations_dir)
    monkeypatch.setattr(migration_runner, "MIGRATION_STATE_FILE", state_path)

    result = migration_runner.run_migrations("0.9.0", "1.0.0")

    assert result["migrations_run"] == 1
    assert result["migrations_skipped"] == 0
    assert result["error"] is None
    assert json.loads(state_path.read_text(encoding="utf-8")) == {"applied": ["1.0.0/001_bootstrap.py"]}


def test_run_migrations_skips_state_marked_migrations_without_loading_module(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    state_path = tmp_path / "state.json"
    migration_path = migrations_dir / "v1.0.0" / "001_bootstrap.py"
    _write_migration(migration_path)
    state_path.write_text(json.dumps({"applied": ["1.0.0/001_bootstrap.py"]}), encoding="utf-8")
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", migrations_dir)
    monkeypatch.setattr(migration_runner, "MIGRATION_STATE_FILE", state_path)

    def fail_if_loaded(_path: Path) -> migration_runner.MigrationModuleContract:
        raise AssertionError("applied migrations should not be reloaded")

    monkeypatch.setattr(migration_runner, "_load_migration_module", fail_if_loaded)

    result = migration_runner.run_migrations("0.9.0", "1.0.0")

    assert result["migrations_run"] == 0
    assert result["migrations_skipped"] == 1
    assert result["error"] is None
