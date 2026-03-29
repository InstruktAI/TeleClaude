# guard: no-companion
"""Tests for state-driven candidate scanner and verifier.

Replaces the queue-based _try_auto_enqueue tests. The integration state machine
now scans worktree state.yaml files directly instead of reading queue.json.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from teleclaude.core.integration.step_functions import (
    ScannedCandidate,
    _scan_finalize_ready_candidates,
    _tls,
    _verify_slug_ready,
)
from teleclaude.core.todos_db import TodosDb

_SHA = "a" * 40


async def _seed_state(todos_db: TodosDb, slug: str, finalize: dict[str, object]) -> None:
    """Seed a minimal state with the given finalize section into the DB."""
    await todos_db.write_state(slug, {"finalize": finalize})


def _write_state_yaml(worktree: Path, slug: str, finalize: dict[str, str]) -> None:
    """Write a minimal state.yaml with the given finalize section (legacy, kept for worktree dir creation)."""
    state_dir = worktree / "todos" / slug
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {"finalize": finalize}
    (state_dir / "state.yaml").write_text(yaml.dump(state), encoding="utf-8")


def _mock_git_pass(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
    """Mock git where ls-remote succeeds and merge-base --is-ancestor fails (not ancestor)."""
    if args[:1] == ["ls-remote"]:
        return 0, f"{_SHA}\trefs/heads/branch", ""
    if args[:2] == ["merge-base", "--is-ancestor"]:
        return 1, "", ""  # NOT ancestor → eligible
    return 0, "", ""


def _mock_git_already_ancestor(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
    """Mock git where merge-base --is-ancestor succeeds (already integrated)."""
    if args[:1] == ["ls-remote"]:
        return 0, f"{_SHA}\trefs/heads/branch", ""
    if args[:2] == ["merge-base", "--is-ancestor"]:
        return 0, "", ""  # IS ancestor → skip
    return 0, "", ""


def _mock_git_no_remote_branch(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
    """Mock git where ls-remote fails (branch not on origin)."""
    if args[:1] == ["ls-remote"]:
        return 2, "", ""  # not found
    if args[:2] == ["merge-base", "--is-ancestor"]:
        return 1, "", ""
    return 0, "", ""


# ---------------------------------------------------------------------------
# _scan_finalize_ready_candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_scan_finds_finalize_ready_candidate(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner discovers a worktree with finalize.status == 'ready'."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "my-slug"
    trees.mkdir(parents=True)
    await _seed_state(
        todos_db,
        "my-slug",
        {
            "status": "ready",
            "branch": "my-slug",
            "sha": _SHA,
            "ready_at": "2026-03-01T00:00:00+00:00",
        },
    )

    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert len(result) == 1
    assert result[0].key.slug == "my-slug"
    assert result[0].key.sha == _SHA


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_scan_skips_pending_status(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner ignores worktrees with finalize.status == 'pending'."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "pending-slug"
    trees.mkdir(parents=True)
    await _seed_state(todos_db, "pending-slug", {"status": "pending"})

    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_scan_accepts_fresh_handed_off(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner accepts handed_off candidates unconditionally — lease prevents concurrency."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "fresh-slug"
    trees.mkdir(parents=True)
    await _seed_state(
        todos_db,
        "fresh-slug",
        {
            "status": "handed_off",
            "branch": "fresh-slug",
            "sha": _SHA,
            "ready_at": "2026-03-01T00:00:00+00:00",
            "handed_off_at": datetime.now(tz=UTC).isoformat(),  # just now
        },
    )

    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert len(result) == 1
    assert result[0].key.slug == "fresh-slug"


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_scan_accepts_stale_handed_off(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner accepts handed_off candidates regardless of handed_off_at age."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "stale-slug"
    trees.mkdir(parents=True)
    stale_time = (datetime.now(tz=UTC) - timedelta(seconds=300)).isoformat()
    await _seed_state(
        todos_db,
        "stale-slug",
        {
            "status": "handed_off",
            "branch": "stale-slug",
            "sha": _SHA,
            "ready_at": "2026-03-01T00:00:00+00:00",
            "handed_off_at": stale_time,
        },
    )

    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert len(result) == 1
    assert result[0].key.slug == "stale-slug"


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_already_ancestor)
async def test_scan_skips_already_ancestor(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner skips candidates whose SHA is already ancestor of main."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "merged-slug"
    trees.mkdir(parents=True)
    await _seed_state(
        todos_db,
        "merged-slug",
        {
            "status": "ready",
            "branch": "merged-slug",
            "sha": _SHA,
            "ready_at": "2026-03-01T00:00:00+00:00",
        },
    )

    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_no_remote_branch)
async def test_scan_skips_missing_remote_branch(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner skips candidates whose branch doesn't exist on origin."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "no-remote"
    trees.mkdir(parents=True)
    await _seed_state(
        todos_db,
        "no-remote",
        {
            "status": "ready",
            "branch": "no-remote",
            "sha": _SHA,
            "ready_at": "2026-03-01T00:00:00+00:00",
        },
    )

    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_scan_excludes_integration_directory(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner skips the _integration worktree directory."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "_integration"
    trees.mkdir(parents=True)
    await _seed_state(
        todos_db,
        "_integration",
        {
            "status": "ready",
            "branch": "_integration",
            "sha": _SHA,
            "ready_at": "2026-03-01T00:00:00+00:00",
        },
    )

    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_scan_respects_exclude_slug(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner skips the slug passed as exclude_slug."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "my-slug"
    trees.mkdir(parents=True)
    await _seed_state(
        todos_db,
        "my-slug",
        {
            "status": "ready",
            "branch": "my-slug",
            "sha": _SHA,
            "ready_at": "2026-03-01T00:00:00+00:00",
        },
    )

    result = _scan_finalize_ready_candidates(str(tmp_path), exclude_slug="my-slug")
    assert result == []


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_scan_fifo_ordering_by_ready_at(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner returns candidates sorted by (ready_at, slug) for stable FIFO."""
    _tls.loop = asyncio.get_event_loop()
    for slug, ready_at in [
        ("slug-b", "2026-03-02T00:00:00+00:00"),
        ("slug-a", "2026-03-01T00:00:00+00:00"),
        ("slug-c", "2026-03-01T00:00:00+00:00"),
    ]:
        trees = tmp_path / "trees" / slug
        trees.mkdir(parents=True)
        _write_state_yaml(
            trees,
            slug,
            {
                "status": "ready",
                "branch": slug,
                "sha": _SHA,
                "ready_at": ready_at,
            },
        )

    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert len(result) == 3
    assert [c.key.slug for c in result] == ["slug-a", "slug-c", "slug-b"]


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_scan_empty_trees_dir(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner returns empty list when trees/ has no subdirectories."""
    _tls.loop = asyncio.get_event_loop()
    (tmp_path / "trees").mkdir()
    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_scan_no_trees_dir(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Scanner returns empty list when trees/ doesn't exist."""
    _tls.loop = asyncio.get_event_loop()
    result = _scan_finalize_ready_candidates(str(tmp_path))
    assert result == []


# ---------------------------------------------------------------------------
# _verify_slug_ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_verify_ready_slug(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Verifier returns candidate for a finalize-ready slug."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "my-slug"
    trees.mkdir(parents=True)
    await _seed_state(
        todos_db,
        "my-slug",
        {
            "status": "ready",
            "branch": "my-slug",
            "sha": _SHA,
            "ready_at": "2026-03-01T00:00:00+00:00",
        },
    )

    result = _verify_slug_ready(str(tmp_path), "my-slug")
    assert result is not None
    assert isinstance(result, ScannedCandidate)
    assert result.key.slug == "my-slug"


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_verify_handed_off_slug(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Verifier accepts handed_off candidates unconditionally — mirrors scanner behavior."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "ho-slug"
    trees.mkdir(parents=True)
    await _seed_state(
        todos_db,
        "ho-slug",
        {
            "status": "handed_off",
            "branch": "ho-slug",
            "sha": _SHA,
            "ready_at": "2026-03-01T00:00:00+00:00",
            "handed_off_at": datetime.now(tz=UTC).isoformat(),
        },
    )

    result = _verify_slug_ready(str(tmp_path), "ho-slug")
    assert result is not None
    assert isinstance(result, ScannedCandidate)
    assert result.key.slug == "ho-slug"


@pytest.mark.asyncio
@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_git_pass)
async def test_verify_not_ready_slug(_mock_git: object, tmp_path: Path, todos_db: TodosDb) -> None:
    """Verifier returns None for a slug with pending finalize status."""
    _tls.loop = asyncio.get_event_loop()
    trees = tmp_path / "trees" / "my-slug"
    trees.mkdir(parents=True)
    await _seed_state(todos_db, "my-slug", {"status": "pending"})

    result = _verify_slug_ready(str(tmp_path), "my-slug")
    assert result is None


@pytest.mark.asyncio
async def test_verify_missing_worktree(tmp_path: Path, todos_db: TodosDb) -> None:
    """Verifier returns None when worktree directory doesn't exist."""
    _tls.loop = asyncio.get_event_loop()
    result = _verify_slug_ready(str(tmp_path), "nonexistent")
    assert result is None
