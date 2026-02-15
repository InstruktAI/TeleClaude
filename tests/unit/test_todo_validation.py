"""Unit tests for todo validation."""

from __future__ import annotations

import json
from pathlib import Path

from teleclaude.resource_validation import validate_todo


def test_validate_todo_pass(tmp_path: Path):
    """Verify that a complete todo passes validation."""
    todo_slug = "test-todo"
    todo_dir = tmp_path / "todos" / todo_slug
    todo_dir.mkdir(parents=True)

    state = {
        "phase": "pending",
        "dor": {"score": 10, "status": "pass"},
        "build": "pending",
        "review": "pending",
    }
    (todo_dir / "state.json").write_text(json.dumps(state))
    (todo_dir / "requirements.md").touch()
    (todo_dir / "implementation-plan.md").touch()

    errors = validate_todo(todo_slug, tmp_path)
    assert not errors


def test_validate_todo_schema_violation(tmp_path: Path):
    """Verify that schema violations are caught."""
    todo_slug = "invalid-state"
    todo_dir = tmp_path / "todos" / todo_slug
    todo_dir.mkdir(parents=True)

    # phase should be string, not int
    state = {"phase": 123}
    (todo_dir / "state.json").write_text(json.dumps(state))

    errors = validate_todo(todo_slug, tmp_path)
    assert any("state.json schema violation" in e for e in errors)


def test_validate_todo_missing_files_for_ready(tmp_path: Path):
    """Verify that missing files for Ready status (score >= 8) are caught."""
    todo_slug = "missing-files"
    todo_dir = tmp_path / "todos" / todo_slug
    todo_dir.mkdir(parents=True)

    state = {
        "phase": "pending",
        "dor": {"score": 8, "status": "pass"},
    }
    (todo_dir / "state.json").write_text(json.dumps(state))

    errors = validate_todo(todo_slug, tmp_path)
    assert any("missing requirements.md" in e for e in errors)
    assert any("missing implementation-plan.md" in e for e in errors)
