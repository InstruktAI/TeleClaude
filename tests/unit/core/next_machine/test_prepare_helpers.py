"""Tests for Task 2: prepare_helpers module — artifact lifecycle helpers."""
# pylint: disable=import-outside-toplevel,duplicate-code

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_roadmap_db(cwd: str, slug: str) -> None:
    """Insert a roadmap entry in the DB so write_phase_state succeeds."""
    import uuid  # pylint: disable=import-outside-toplevel

    from teleclaude.core.next_machine.state_io import _get_todos_db_sync  # pylint: disable=import-outside-toplevel

    db = _get_todos_db_sync(cwd)
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        conn.execute(
            "INSERT OR IGNORE INTO roadmap (id, slug, position, status, created_at, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, 0, 'active', '', '')",
            (str(uuid.uuid4()), slug),
        )
        conn.commit()
    finally:
        conn.close()


def _make_todo(tmp_path: Path, slug: str = "test-slug") -> tuple[str, str]:
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    cwd = str(tmp_path)
    _ensure_roadmap_db(cwd, slug)
    return cwd, slug


def _write_artifact_to_db(cwd: str, slug: str, name: str, content: str) -> None:
    """Write an artifact directly to todos.db for test setup."""
    import uuid  # pylint: disable=import-outside-toplevel

    from teleclaude.core.next_machine.state_io import _get_todos_db_sync  # pylint: disable=import-outside-toplevel

    db = _get_todos_db_sync(cwd)
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        row = conn.execute("SELECT id FROM roadmap WHERE slug=? LIMIT 1", (slug,)).fetchone()  # guard: raw-sql
        row_id = row[0] if row else str(uuid.uuid4())
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT OR REPLACE INTO todo_artifacts "  # guard: raw-sql
            "(id, slug, name, content, digest, updated_by, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, '')",
            (row_id, slug, name, content, digest, None),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# artifact_digest
# ---------------------------------------------------------------------------


def test_artifact_digest_returns_sha256_for_existing_file(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import artifact_digest

    cwd, slug = _make_todo(tmp_path)
    _write_artifact_to_db(cwd, slug, "input", "hello")

    result = artifact_digest(cwd, slug, "input.md")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert result == expected


def test_artifact_digest_returns_empty_for_missing_file(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import artifact_digest

    cwd, slug = _make_todo(tmp_path)
    assert artifact_digest(cwd, slug, "nonexistent.md") == ""


# ---------------------------------------------------------------------------
# record_artifact_produced
# ---------------------------------------------------------------------------


def test_record_artifact_produced_writes_digest_and_produced_at(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.artifacts import record_artifact_produced
    from teleclaude.core.next_machine.state_io import read_phase_state

    cwd, slug = _make_todo(tmp_path)
    _write_artifact_to_db(cwd, slug, "input", "my input")
    expected_digest = hashlib.sha256(b"my input").hexdigest()

    with patch("teleclaude.core.next_machine.artifacts._emit_prepare_event"):
        record_artifact_produced(cwd, slug, "input.md")

    state = read_phase_state(cwd, slug)
    artifacts = state.get("artifacts", {})
    assert artifacts["input"]["digest"] == expected_digest  # type: ignore[index]
    assert artifacts["input"]["produced_at"] != ""  # type: ignore[index]


# ---------------------------------------------------------------------------
# check_artifact_staleness
# ---------------------------------------------------------------------------


def test_check_artifact_staleness_no_changes_returns_empty(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.artifacts import record_artifact_produced
    from teleclaude.core.next_machine.prepare_helpers import check_artifact_staleness

    cwd, slug = _make_todo(tmp_path)
    _write_artifact_to_db(cwd, slug, "input", "hello")

    with patch("teleclaude.core.next_machine.artifacts._emit_prepare_event"):
        record_artifact_produced(cwd, slug, "input.md")

    result = check_artifact_staleness(cwd, slug)
    assert result == []


def test_check_artifact_staleness_detects_changed_input(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.artifacts import record_artifact_produced
    from teleclaude.core.next_machine.prepare_helpers import check_artifact_staleness

    cwd, slug = _make_todo(tmp_path)
    _write_artifact_to_db(cwd, slug, "input", "original")
    _write_artifact_to_db(cwd, slug, "requirements", "reqs")

    with patch("teleclaude.core.next_machine.artifacts._emit_prepare_event"):
        record_artifact_produced(cwd, slug, "input.md")
        record_artifact_produced(cwd, slug, "requirements.md")

    # Update DB artifact to simulate changed input
    _write_artifact_to_db(cwd, slug, "input", "changed content")

    result = check_artifact_staleness(cwd, slug)
    # Input and all downstream (requirements, implementation_plan) should be stale
    assert "input" in result
    assert "requirements" in result


def test_check_artifact_staleness_only_requirements_stale(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.artifacts import record_artifact_produced
    from teleclaude.core.next_machine.prepare_helpers import check_artifact_staleness

    cwd, slug = _make_todo(tmp_path)
    _write_artifact_to_db(cwd, slug, "input", "stable input")
    _write_artifact_to_db(cwd, slug, "requirements", "original reqs")
    _write_artifact_to_db(cwd, slug, "implementation-plan", "plan")

    with patch("teleclaude.core.next_machine.artifacts._emit_prepare_event"):
        record_artifact_produced(cwd, slug, "input.md")
        record_artifact_produced(cwd, slug, "requirements.md")
        record_artifact_produced(cwd, slug, "implementation-plan.md")

    # Update DB artifact to simulate changed requirements
    _write_artifact_to_db(cwd, slug, "requirements", "changed reqs")

    result = check_artifact_staleness(cwd, slug)
    assert "input" not in result
    assert "requirements" in result
    assert "implementation_plan" in result


# ---------------------------------------------------------------------------
# compute_artifact_diff
# ---------------------------------------------------------------------------


def test_compute_artifact_diff_returns_empty_when_base_sha_empty(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import compute_artifact_diff

    cwd, slug = _make_todo(tmp_path)
    result = compute_artifact_diff(cwd, slug, "todos/test-slug/requirements.md", "")
    assert result == ""


def test_compute_artifact_diff_returns_diff_output(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import compute_artifact_diff

    cwd, slug = _make_todo(tmp_path)

    with patch("teleclaude.core.next_machine.prepare_helpers.run_git_command") as mock_git:
        mock_git.return_value = (0, "diff content", "")
        result = compute_artifact_diff(cwd, slug, "todos/test-slug/requirements.md", "abc123")

    assert result == "diff content"


def test_compute_todo_folder_diff_returns_folder_diff(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import compute_todo_folder_diff

    cwd, slug = _make_todo(tmp_path)

    with patch("teleclaude.core.next_machine.prepare_helpers.run_git_command") as mock_git:
        mock_git.return_value = (0, "folder diff", "")
        result = compute_todo_folder_diff(cwd, slug, "abc123")

    assert result == "folder diff"
    call_args = mock_git.call_args[0][0]
    assert f"todos/{slug}/" in " ".join(call_args)
