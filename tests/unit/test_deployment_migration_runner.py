"""Tests for deployment migration discovery and execution."""

from __future__ import annotations

import json
import os
from pathlib import Path

import teleclaude.deployment.migration_runner as migration_runner
from teleclaude.deployment import parse_version


def _write_migration(version_dir: Path, name: str, source: str) -> Path:
    version_dir.mkdir(parents=True, exist_ok=True)
    path = version_dir / name
    path.write_text(source, encoding="utf-8")
    return path


def _configure_runner_paths(monkeypatch, migrations_dir: Path, state_file: Path) -> None:
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", migrations_dir)
    monkeypatch.setattr(migration_runner, "MIGRATION_STATE_FILE", state_file)


def test_parse_version_accepts_semver_with_or_without_v_prefix():
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("  v10.20.30 ") == (10, 20, 30)


def test_parse_version_rejects_invalid_values():
    for invalid in ("1.2", "1.2.3.4", "v1.a.3", "foo"):
        try:
            parse_version(invalid)
        except ValueError:
            continue
        raise AssertionError(f"Expected ValueError for {invalid!r}")


def test_discover_migrations_filters_by_version_range_and_orders_by_version_then_script(tmp_path, monkeypatch):
    migrations_dir = tmp_path / "migrations"
    state_file = tmp_path / "migration_state.json"
    _configure_runner_paths(monkeypatch, migrations_dir, state_file)

    _write_migration(
        migrations_dir / "v1.0.0", "001_pre.py", "def check():\n    return True\n\ndef migrate():\n    return True\n"
    )
    _write_migration(
        migrations_dir / "v1.1.0",
        "010_later.py",
        "def check():\n    return True\n\ndef migrate():\n    return True\n",
    )
    _write_migration(
        migrations_dir / "v1.1.0",
        "002_first.py",
        "def check():\n    return True\n\ndef migrate():\n    return True\n",
    )
    _write_migration(
        migrations_dir / "v1.2.0",
        "001_after.py",
        "def check():\n    return True\n\ndef migrate():\n    return True\n",
    )

    discovered = migration_runner.discover_migrations("1.0.0", "1.1.0")

    assert [(version, path.name) for version, path in discovered] == [
        ("1.1.0", "002_first.py"),
        ("1.1.0", "010_later.py"),
    ]


def test_run_migrations_skips_when_check_returns_true(tmp_path, monkeypatch):
    migrations_dir = tmp_path / "migrations"
    state_file = tmp_path / "migration_state.json"
    _configure_runner_paths(monkeypatch, migrations_dir, state_file)

    _write_migration(
        migrations_dir / "v1.1.0",
        "001_skip.py",
        "def check():\n    return True\n\ndef migrate():\n    raise RuntimeError('must not run')\n",
    )

    result = migration_runner.run_migrations("1.0.0", "1.1.0")

    assert result["migrations_run"] == 0
    assert result["migrations_skipped"] == 1
    assert result["error"] is None
    assert not state_file.exists()


def test_run_migrations_halts_on_failure_and_preserves_applied_state(tmp_path, monkeypatch):
    migrations_dir = tmp_path / "migrations"
    state_file = tmp_path / "migration_state.json"
    _configure_runner_paths(monkeypatch, migrations_dir, state_file)

    _write_migration(
        migrations_dir / "v1.1.0",
        "001_ok.py",
        "def check():\n    return False\n\ndef migrate():\n    return True\n",
    )
    _write_migration(
        migrations_dir / "v1.1.0",
        "002_fail.py",
        "def check():\n    return False\n\ndef migrate():\n    raise RuntimeError('boom')\n",
    )

    result = migration_runner.run_migrations("1.0.0", "1.1.0")

    assert result["migrations_run"] == 1
    assert result["migrations_skipped"] == 0
    assert result["error"] is not None
    assert "1.1.0/002_fail.py" in result["error"]

    state_payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_payload == {"applied": ["1.1.0/001_ok.py"]}


def test_state_write_is_atomic_via_temp_file_rename(tmp_path, monkeypatch):
    migrations_dir = tmp_path / "migrations"
    state_file = tmp_path / "migration_state.json"
    _configure_runner_paths(monkeypatch, migrations_dir, state_file)

    _write_migration(
        migrations_dir / "v1.1.0",
        "001_apply.py",
        "def check():\n    return False\n\ndef migrate():\n    return True\n",
    )

    calls: list[tuple[Path, Path, bool]] = []
    real_rename = os.rename

    def spy_rename(src, dst):
        src_path = Path(src)
        dst_path = Path(dst)
        calls.append((src_path, dst_path, src_path.exists()))
        real_rename(src, dst)

    monkeypatch.setattr(migration_runner.os, "rename", spy_rename)

    result = migration_runner.run_migrations("1.0.0", "1.1.0")

    assert result["error"] is None
    assert calls
    src_path, dst_path, src_exists_at_call = calls[0]
    assert src_exists_at_call
    assert src_path != state_file
    assert dst_path == state_file
    assert src_path.name.startswith(f".{state_file.name}.")


def test_dry_run_returns_plan_without_executing_or_writing_state(tmp_path, monkeypatch):
    migrations_dir = tmp_path / "migrations"
    state_file = tmp_path / "migration_state.json"
    marker = tmp_path / "marker.txt"
    _configure_runner_paths(monkeypatch, migrations_dir, state_file)

    _write_migration(
        migrations_dir / "v1.1.0",
        "001_apply.py",
        (
            "from pathlib import Path\n"
            f"MARKER = Path({str(marker)!r})\n"
            "def check():\n"
            "    return False\n\n"
            "def migrate():\n"
            "    MARKER.write_text('ran', encoding='utf-8')\n"
            "    return True\n"
        ),
    )

    result = migration_runner.run_migrations("1.0.0", "1.1.0", dry_run=True)

    assert result["error"] is None
    assert result["migrations_run"] == 0
    assert result["migrations_skipped"] == 0
    assert result["planned_migrations"] == ["1.1.0/001_apply.py"]
    assert not marker.exists()
    assert not state_file.exists()
