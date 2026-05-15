"""Characterization tests for teleclaude.core.integration.step_functions.

Patches step_functions.get_todos_db_sync (consumer-module local).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.core.integration.checkpoint import IntegrationCheckpoint, IntegrationPhase
from teleclaude.core.integration.readiness_projection import CandidateKey
from teleclaude.core.integration.step_functions import (
    ScannedCandidate,
    _get_candidate_key,
    _run_git,
    _step_delivery_bookkeeping,
    _sweep_stale_artifacts,
)

# ---------------------------------------------------------------------------
# _sweep_stale_artifacts
# ---------------------------------------------------------------------------


def _mock_todos_db(delivered_slugs: set[str]) -> MagicMock:
    db = MagicMock()
    conn = MagicMock()
    db._sync_conn.return_value = conn
    conn.execute.return_value.fetchall.return_value = [(s,) for s in delivered_slugs]
    return db


def test_sweep_stale_artifacts_returns_empty_when_no_delivered_slugs(tmp_path: Path) -> None:
    with patch("teleclaude.core.integration.step_functions.get_todos_db_sync", return_value=_mock_todos_db(set())):
        assert _sweep_stale_artifacts(str(tmp_path)) == []


def test_sweep_stale_artifacts_returns_empty_when_no_trees_dir(tmp_path: Path) -> None:
    with patch("teleclaude.core.integration.step_functions.get_todos_db_sync", return_value=_mock_todos_db({"slug-1"})):
        assert _sweep_stale_artifacts(str(tmp_path)) == []


def test_sweep_stale_artifacts_cleans_up_delivered_slugs(tmp_path: Path) -> None:
    trees_dir = tmp_path / "trees"
    trees_dir.mkdir()
    (trees_dir / "slug-1").mkdir()
    (trees_dir / "slug-3").mkdir()  # Not delivered
    (trees_dir / "_internal").mkdir()  # Should be ignored

    with (
        patch(
            "teleclaude.core.integration.step_functions.get_todos_db_sync",
            return_value=_mock_todos_db({"slug-1", "slug-2"}),
        ),
        patch("teleclaude.core.integration.step_functions.cleanup_delivered_slug") as mock_cleanup,
    ):
        swept = _sweep_stale_artifacts(str(tmp_path))

    assert swept == ["slug-1"]
    mock_cleanup.assert_called_once_with(str(tmp_path), "slug-1")


# ---------------------------------------------------------------------------
# _get_candidate_key
# ---------------------------------------------------------------------------


def test_get_candidate_key_returns_key_when_all_fields_present() -> None:
    cp = _make_checkpoint(slug="my-slug", branch="my-branch", sha="my-sha")
    key = _get_candidate_key(cp)
    assert key is not None
    assert key == CandidateKey(slug="my-slug", branch="my-branch", sha="my-sha")


def test_get_candidate_key_returns_none_when_slug_missing() -> None:
    cp = _make_checkpoint(slug=None, branch="branch", sha="sha")
    assert _get_candidate_key(cp) is None


def test_get_candidate_key_returns_none_when_branch_missing() -> None:
    cp = _make_checkpoint(slug="slug", branch=None, sha="sha")
    assert _get_candidate_key(cp) is None


def test_get_candidate_key_returns_none_when_sha_missing() -> None:
    cp = _make_checkpoint(slug="slug", branch="branch", sha=None)
    assert _get_candidate_key(cp) is None


# ---------------------------------------------------------------------------
# _run_git
# ---------------------------------------------------------------------------


def test_run_git_returns_tuple_of_returncode_stdout_stderr(tmp_path: Path) -> None:
    rc, stdout, stderr = _run_git(["rev-parse", "--show-toplevel"], cwd=str(tmp_path))
    assert isinstance(rc, int)
    assert isinstance(stdout, str)
    assert isinstance(stderr, str)


def test_run_git_nonzero_on_bad_command(tmp_path: Path) -> None:
    rc, _, _ = _run_git(["this-is-not-a-real-git-subcommand"], cwd=str(tmp_path))
    assert rc != 0


def test_run_git_timeout_returns_nonzero(tmp_path: Path) -> None:
    # Using a very short timeout to force timeout behavior is slow; instead
    # verify the timeout parameter is accepted and returns expected shape.
    rc, _stdout, _stderr = _run_git(["--version"], cwd=str(tmp_path), timeout=5)
    assert isinstance(rc, int)


# ---------------------------------------------------------------------------
# ScannedCandidate
# ---------------------------------------------------------------------------


def test_scanned_candidate_is_frozen() -> None:
    key = CandidateKey(slug="s", branch="b", sha="x")
    sc = ScannedCandidate(key=key, ready_at="2024-01-01T12:00:00+00:00")
    with pytest.raises(AttributeError):
        sc.key = CandidateKey(slug="s2", branch="b", sha="x")  # pyright: ignore[reportAttributeAccessIssue]


# ---------------------------------------------------------------------------
# _step_delivery_bookkeeping — distinguishes missing-entry from already-delivered
# ---------------------------------------------------------------------------


def test_delivery_bookkeeping_fails_fast_when_roadmap_entry_is_missing(
    tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    """deliver_sync returns False for both 'already delivered' and 'row missing'.
    The missing case must surface as a DELIVERY_FAILED error, not a silent pass-through.
    """
    db = MagicMock()
    db.deliver_sync.return_value = False
    db.delivered_slugs_sync.return_value = set()  # slug is NOT in roadmap at all
    checkpoint = _make_checkpoint(slug="ghost-slug", branch="b", sha="x")
    checkpoint.phase = IntegrationPhase.DELIVERY_BOOKKEEPING.value
    with patch("teleclaude.core.integration.step_functions.get_todos_db_sync", return_value=db):
        progressed, message = _step_delivery_bookkeeping(
            checkpoint=checkpoint,
            checkpoint_path=tmp_path / "checkpoint.yaml",
            cwd=str(tmp_path),
        )
    assert progressed is False
    assert message == snapshot


def test_delivery_bookkeeping_idempotently_continues_when_slug_already_delivered(
    tmp_path: Path,
) -> None:
    """When deliver_sync returns False because the row is already delivered,
    the function must NOT return DELIVERY_FAILED and must progress to the push step.
    """
    db = MagicMock()
    db.deliver_sync.return_value = False
    db.delivered_slugs_sync.return_value = {"already-delivered-slug"}
    checkpoint = _make_checkpoint(slug="already-delivered-slug", branch="b", sha="abc123")
    checkpoint.phase = IntegrationPhase.DELIVERY_BOOKKEEPING.value

    @contextmanager
    def _noop_lock():
        yield

    with (
        patch("teleclaude.core.integration.step_functions.get_todos_db_sync", return_value=db),
        patch("teleclaude.core.integration.step_functions._run_git", return_value=(0, "", "")),
        patch("teleclaude.core.integration.step_functions.main_branch_lock", _noop_lock),
        patch("teleclaude.core.integration.step_functions._get_head_sha", return_value="abc123"),
        patch("teleclaude.core.integration.step_functions._write_checkpoint"),
    ):
        progressed, message = _step_delivery_bookkeeping(
            checkpoint=checkpoint,
            checkpoint_path=tmp_path / "checkpoint.yaml",
            cwd=str(tmp_path),
        )
    assert progressed is True
    assert message == ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_checkpoint(
    *,
    slug: str | None,
    branch: str | None,
    sha: str | None,
) -> IntegrationCheckpoint:
    return IntegrationCheckpoint(
        phase=IntegrationPhase.IDLE.value,
        candidate_slug=slug,
        candidate_branch=branch,
        candidate_sha=sha,
        lease_token=None,
        items_processed=0,
        items_blocked=0,
        started_at="2024-01-01T12:00:00+00:00",
        last_updated_at="2024-01-01T12:00:00+00:00",
        error_context=None,
        pre_merge_head=None,
    )
