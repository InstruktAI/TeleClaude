# guard: no-companion
"""Tests for state-driven candidate scanner and verifier.

The integration state machine scans todo state from todos.db to find
finalize-ready candidates. Tests mock get_todos_db_sync (via the
step_functions module local) to inject a test-scoped TodosDb instance.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.integration.step_functions import _scan_finalize_ready_candidates, _verify_slug_ready
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.todos_db import TodosDb

_SHA = "a" * 40
_STEP = "teleclaude.core.integration.step_functions"


@pytest.fixture
def todos_db(tmp_path: Path) -> TodosDb:
    """Sync TodosDb fixture for integration scanner tests."""
    db = TodosDb(str(tmp_path / "todos.db"))
    db.initialize_sync()
    return db


def _ensure_roadmap(todos_db: TodosDb, slug: str) -> None:
    """Insert a roadmap entry via raw SQL (write_state requires it)."""
    conn = todos_db._sync_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO roadmap (id, slug, position, status, created_at, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, 0, 'active', '', '')",
            (str(uuid.uuid4()), slug),
        )
        conn.commit()
    finally:
        conn.close()


def _seed(todos_db: TodosDb, slug: str, finalize: dict[str, StateValue]) -> None:
    _ensure_roadmap(todos_db, slug)
    todos_db.write_state_sync(slug, {"finalize": finalize})


def _mock_git_pass(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
    if args[:1] == ["ls-remote"]:
        return 0, f"{_SHA}\trefs/heads/branch", ""
    if args[:2] == ["merge-base", "--is-ancestor"]:
        return 1, "", ""
    return 0, "", ""


def _mock_git_already_ancestor(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
    if args[:1] == ["ls-remote"]:
        return 0, f"{_SHA}\trefs/heads/branch", ""
    if args[:2] == ["merge-base", "--is-ancestor"]:
        return 0, "", ""
    return 0, "", ""


def _mock_git_no_remote_branch(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
    if args[:1] == ["ls-remote"]:
        return 2, "", ""
    return 0, "", ""


@patch(f"{_STEP}._run_git", side_effect=_mock_git_pass)
def test_scan_finds_finalize_ready_candidate(_mock: object, tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "my-slug").mkdir(parents=True)
    _seed(
        todos_db,
        "my-slug",
        {"status": "ready", "branch": "my-slug", "sha": _SHA, "ready_at": "2026-03-01T00:00:00+00:00"},
    )
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _scan_finalize_ready_candidates(str(tmp_path))
    assert len(result) == 1
    assert result[0].key.slug == "my-slug"


@patch(f"{_STEP}._run_git", side_effect=_mock_git_pass)
def test_scan_skips_pending(_mock: object, tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "pending").mkdir(parents=True)
    _seed(todos_db, "pending", {"status": "pending"})
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


@patch(f"{_STEP}._run_git", side_effect=_mock_git_pass)
def test_scan_accepts_handed_off(_mock: object, tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "handed").mkdir(parents=True)
    _seed(
        todos_db,
        "handed",
        {"status": "handed_off", "branch": "handed", "sha": _SHA, "ready_at": "2026-03-01T00:00:00+00:00"},
    )
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _scan_finalize_ready_candidates(str(tmp_path))
    assert len(result) == 1


@patch(f"{_STEP}._run_git", side_effect=_mock_git_already_ancestor)
def test_scan_skips_already_integrated(_mock: object, tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "old").mkdir(parents=True)
    _seed(todos_db, "old", {"status": "ready", "branch": "old", "sha": _SHA, "ready_at": "2026-03-01T00:00:00+00:00"})
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


@patch(f"{_STEP}._run_git", side_effect=_mock_git_no_remote_branch)
def test_scan_skips_missing_remote(_mock: object, tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "gone").mkdir(parents=True)
    _seed(todos_db, "gone", {"status": "ready", "branch": "gone", "sha": _SHA, "ready_at": "2026-03-01T00:00:00+00:00"})
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


def test_scan_no_trees_dir(tmp_path: Path, todos_db: TodosDb) -> None:
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


def test_scan_excludes_integration(tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "_integration").mkdir(parents=True)
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


@patch(f"{_STEP}._run_git", side_effect=_mock_git_pass)
def test_scan_skips_missing_sha(_mock: object, tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "no-sha").mkdir(parents=True)
    _seed(
        todos_db, "no-sha", {"status": "ready", "branch": "no-sha", "sha": "", "ready_at": "2026-03-01T00:00:00+00:00"}
    )
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


@patch(f"{_STEP}._run_git", side_effect=_mock_git_pass)
def test_scan_excludes_slug(_mock: object, tmp_path: Path, todos_db: TodosDb) -> None:
    for slug in ("keep", "skip"):
        (tmp_path / "trees" / slug).mkdir(parents=True)
        _seed(todos_db, slug, {"status": "ready", "branch": slug, "sha": _SHA, "ready_at": "2026-03-01T00:00:00+00:00"})
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _scan_finalize_ready_candidates(str(tmp_path), exclude_slug="skip")
    assert len(result) == 1
    assert result[0].key.slug == "keep"


# ---------------------------------------------------------------------------
# _verify_slug_ready
# ---------------------------------------------------------------------------


@patch(f"{_STEP}._run_git", side_effect=_mock_git_pass)
def test_verify_ready(_mock: object, tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "v-slug").mkdir(parents=True)
    _seed(
        todos_db,
        "v-slug",
        {"status": "ready", "branch": "v-slug", "sha": _SHA, "ready_at": "2026-03-01T00:00:00+00:00"},
    )
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _verify_slug_ready(str(tmp_path), "v-slug")
    assert result is not None
    assert result.key.slug == "v-slug"


@patch(f"{_STEP}._run_git", side_effect=_mock_git_pass)
def test_verify_handed_off(_mock: object, tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "h-slug").mkdir(parents=True)
    _seed(
        todos_db,
        "h-slug",
        {"status": "handed_off", "branch": "h-slug", "sha": _SHA, "ready_at": "2026-03-01T00:00:00+00:00"},
    )
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _verify_slug_ready(str(tmp_path), "h-slug")
    assert result is not None


def test_verify_missing_worktree(tmp_path: Path, todos_db: TodosDb) -> None:
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _verify_slug_ready(str(tmp_path), "missing")
    assert result is None


def test_verify_pending(tmp_path: Path, todos_db: TodosDb) -> None:
    (tmp_path / "trees" / "pend").mkdir(parents=True)
    _seed(todos_db, "pend", {"status": "pending"})
    with patch(f"{_STEP}.get_todos_db_sync", return_value=todos_db):
        result = _verify_slug_ready(str(tmp_path), "pend")
    assert result is None
