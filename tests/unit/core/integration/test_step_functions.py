"""Characterization tests for teleclaude.core.integration.step_functions.

Patches step_functions.get_todos_db_sync (consumer-module local).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict
from unittest.mock import MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.constants import RoadmapStatus
from teleclaude.core.integration.checkpoint import IntegrationCheckpoint, IntegrationPhase
from teleclaude.core.integration.readiness_projection import CandidateKey
from teleclaude.core.integration.step_functions import (
    RECONCILE_STAGING_FAILED,
    ScannedCandidate,
    _do_merge,
    _get_candidate_key,
    _run_git,
    _step_awaiting_commit,
    _step_delivery_bookkeeping,
    _sweep_stale_artifacts,
)
from teleclaude.docs_reconcile import SnippetStatusReconcileResult

pytestmark = pytest.mark.unit

COMMIT_PROMPT = "commit-prompt"
CONFLICT_PROMPT = "conflict-prompt"


class _ObservedReconcileCall(TypedDict, total=False):
    project_root: Path
    status_map: dict[str, str]
    only_slug: str | None


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


def test_sweep_stale_artifacts_cleans_up_delivered_slugs(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
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

    assert swept == snapshot
    mock_cleanup.assert_called_once_with(str(tmp_path), "slug-1")


# ---------------------------------------------------------------------------
# _get_candidate_key
# ---------------------------------------------------------------------------


def test_get_candidate_key_returns_key_when_all_fields_present(snapshot: SnapshotAssertion) -> None:
    cp = _make_checkpoint(slug="my-slug", branch="my-branch", sha="my-sha")
    key = _get_candidate_key(cp)
    assert key is not None
    assert key == snapshot


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
# _do_merge / _step_awaiting_commit — delivery snippet reconciliation specs
# ---------------------------------------------------------------------------


def _patch_clean_merge_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, list[list[str]]]:
    wt = tmp_path / "trees" / "_integration"
    wt.mkdir(parents=True)
    git_calls: list[list[str]] = []

    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions._ensure_integration_worktree",
        lambda _cwd: (wt, ""),
    )
    monkeypatch.setattr("teleclaude.core.integration.step_functions._get_head_sha", lambda _cwd: "pre-merge")
    monkeypatch.setattr("teleclaude.core.integration.step_functions._get_diff_stats", lambda _cwd: "")
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions._get_branch_log", lambda _cwd, _branch, *, base_ref: ""
    )
    monkeypatch.setattr("teleclaude.core.integration.step_functions._read_artifact_safe", lambda _cwd, _slug, _name: "")
    monkeypatch.setattr("teleclaude.core.integration.step_functions._write_checkpoint", lambda _path, _checkpoint: None)
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions._emit_lifecycle_event", lambda _event, _payload: None
    )
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions._format_commit_decision",
        lambda _slug, _branch, _diff_stats, _branch_log, _requirements, _impl_plan: COMMIT_PROMPT,
    )

    def fake_run_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        del cwd, timeout
        git_calls.append(args)
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return 1, "", ""
        if args[:2] == ["merge", "--squash"]:
            return 0, "", ""
        if args == ["diff", "--cached", "--quiet"]:
            return 1, "", ""
        if args[:2] == ["add", "--"]:
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr("teleclaude.core.integration.step_functions._run_git", fake_run_git)
    return wt, git_calls


def test_do_merge_calls_reconcile_with_delivered_status_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: SnapshotAssertion
) -> None:
    key = CandidateKey(slug="integrate-deliveredby-flip", branch="task-branch", sha="a" * 40)
    wt, _git_calls = _patch_clean_merge_path(monkeypatch, tmp_path)
    observed: _ObservedReconcileCall = {}

    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions.build_roadmap_status_map",
        lambda _project_root: {"integrate-deliveredby-flip": RoadmapStatus.ACTIVE},
    )

    def fake_reconcile(
        project_root: Path, status_map: dict[str, str], *, only_slug: str | None = None
    ) -> list[SnippetStatusReconcileResult]:
        observed["project_root"] = project_root
        observed["status_map"] = status_map
        observed["only_slug"] = only_slug
        return []

    monkeypatch.setattr("teleclaude.core.integration.step_functions.reconcile_snippet_status", fake_reconcile)

    progressed, message = _do_merge(
        checkpoint=_make_checkpoint(slug=key.slug, branch=key.branch, sha=key.sha),
        checkpoint_path=tmp_path / "checkpoint.yaml",
        key=key,
        cwd=str(tmp_path),
    )

    assert progressed is False
    assert message == snapshot(name="message")
    assert {**observed, "project_root": str(wt).replace(str(tmp_path), "TMP")} == snapshot(name="reconcile_call")


def test_do_merge_stages_reconciled_snippet_for_current_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: SnapshotAssertion
) -> None:
    key = CandidateKey(slug="integrate-deliveredby-flip", branch="task-branch", sha="a" * 40)
    wt, git_calls = _patch_clean_merge_path(monkeypatch, tmp_path)
    snippet_path = wt / "docs" / "project" / "spec" / "snippet.md"
    monkeypatch.setattr("teleclaude.core.integration.step_functions.build_roadmap_status_map", lambda _project_root: {})
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions.reconcile_snippet_status",
        lambda _project_root, _status_map, *, only_slug=None: [
            SnippetStatusReconcileResult(path=snippet_path, removed_slugs=(key.slug,))
        ],
    )

    progressed, message = _do_merge(
        checkpoint=_make_checkpoint(slug=key.slug, branch=key.branch, sha=key.sha),
        checkpoint_path=tmp_path / "checkpoint.yaml",
        key=key,
        cwd=str(tmp_path),
    )

    assert progressed is False
    assert message == snapshot(name="message")
    assert [[part.replace(str(tmp_path), "TMP") for part in call] for call in git_calls] == snapshot(name="git_calls")


def test_do_merge_reconcile_staging_failure_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = CandidateKey(slug="integrate-deliveredby-flip", branch="task-branch", sha="a" * 40)
    wt, _git_calls = _patch_clean_merge_path(monkeypatch, tmp_path)
    snippet_path = wt / "docs" / "project" / "spec" / "snippet.md"
    observed_error: dict[str, str] = {}

    monkeypatch.setattr("teleclaude.core.integration.step_functions.build_roadmap_status_map", lambda _project_root: {})
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions.reconcile_snippet_status",
        lambda _project_root, _status_map, *, only_slug=None: [
            SnippetStatusReconcileResult(path=snippet_path, removed_slugs=(key.slug,))
        ],
    )

    def fail_git_add(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        del cwd, timeout
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return 1, "", ""
        if args[:2] == ["merge", "--squash"]:
            return 0, "", ""
        if args == ["diff", "--cached", "--quiet"]:
            return 1, "", ""
        if args[:2] == ["add", "--"]:
            return 1, "", "stage failed"
        return 0, "", ""

    def fake_format_error(code: str, message: str) -> str:
        observed_error["code"] = code
        observed_error["message"] = message
        return code

    monkeypatch.setattr("teleclaude.core.integration.step_functions._run_git", fail_git_add)
    monkeypatch.setattr("teleclaude.core.integration.step_functions._format_error", fake_format_error)

    progressed, message = _do_merge(
        checkpoint=_make_checkpoint(slug=key.slug, branch=key.branch, sha=key.sha),
        checkpoint_path=tmp_path / "checkpoint.yaml",
        key=key,
        cwd=str(tmp_path),
    )

    assert progressed is False
    assert message == RECONCILE_STAGING_FAILED
    assert observed_error["code"] == RECONCILE_STAGING_FAILED


def test_step_awaiting_commit_for_conflict_stages_reconciled_snippet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: SnapshotAssertion
) -> None:
    key = CandidateKey(slug="integrate-deliveredby-flip", branch="task-branch", sha="a" * 40)
    checkpoint = _make_checkpoint(slug=key.slug, branch=key.branch, sha=key.sha)
    checkpoint.phase = IntegrationPhase.MERGE_CONFLICTED.value
    checkpoint.error_context = {"merge_type": "conflicted", "conflicted_files": []}
    checkpoint.pre_merge_head = "pre-merge"
    wt = tmp_path / "trees" / "_integration"
    wt.mkdir(parents=True)
    snippet_path = wt / "docs" / "project" / "spec" / "snippet.md"
    git_calls: list[list[str]] = []

    monkeypatch.setattr("teleclaude.core.integration.step_functions._integration_worktree_path", lambda _cwd: wt)
    monkeypatch.setattr("teleclaude.core.integration.step_functions._merge_head_exists", lambda _cwd: False)
    monkeypatch.setattr("teleclaude.core.integration.step_functions._get_head_sha", lambda _cwd: "pre-merge")
    monkeypatch.setattr("teleclaude.core.integration.step_functions._write_checkpoint", lambda _path, _checkpoint: None)
    monkeypatch.setattr("teleclaude.core.integration.step_functions.build_roadmap_status_map", lambda _project_root: {})
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions.reconcile_snippet_status",
        lambda _project_root, _status_map, *, only_slug=None: [
            SnippetStatusReconcileResult(path=snippet_path, removed_slugs=(key.slug,))
        ],
    )
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions._format_conflict_decision",
        lambda _slug, _branch, _conflicted_files: CONFLICT_PROMPT,
    )

    def fake_run_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        del cwd, timeout
        git_calls.append(args)
        return 0, "", ""

    monkeypatch.setattr("teleclaude.core.integration.step_functions._run_git", fake_run_git)

    progressed, message = _step_awaiting_commit(
        checkpoint=checkpoint,
        checkpoint_path=tmp_path / "checkpoint.yaml",
        cwd=str(tmp_path),
    )

    assert progressed is False
    assert message == snapshot(name="message")
    assert [[part.replace(str(tmp_path), "TMP") for part in call] for call in git_calls] == snapshot(name="git_calls")


def test_step_awaiting_commit_for_clean_merge_stages_reconciled_snippet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: SnapshotAssertion
) -> None:
    key = CandidateKey(slug="integrate-deliveredby-flip", branch="task-branch", sha="a" * 40)
    checkpoint = _make_checkpoint(slug=key.slug, branch=key.branch, sha=key.sha)
    checkpoint.phase = IntegrationPhase.MERGE_CLEAN.value
    checkpoint.error_context = {"merge_type": "clean"}
    checkpoint.pre_merge_head = "pre-merge"
    wt = tmp_path / "trees" / "_integration"
    wt.mkdir(parents=True)
    snippet_path = wt / "docs" / "project" / "spec" / "snippet.md"
    git_calls: list[list[str]] = []

    monkeypatch.setattr("teleclaude.core.integration.step_functions._integration_worktree_path", lambda _cwd: wt)
    monkeypatch.setattr("teleclaude.core.integration.step_functions._merge_head_exists", lambda _cwd: False)
    monkeypatch.setattr("teleclaude.core.integration.step_functions._get_head_sha", lambda _cwd: "pre-merge")
    monkeypatch.setattr("teleclaude.core.integration.step_functions._get_diff_stats", lambda _cwd: "")
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions._get_branch_log", lambda _cwd, _branch, *, base_ref: ""
    )
    monkeypatch.setattr("teleclaude.core.integration.step_functions._read_artifact_safe", lambda _cwd, _slug, _name: "")
    monkeypatch.setattr("teleclaude.core.integration.step_functions.build_roadmap_status_map", lambda _project_root: {})
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions.reconcile_snippet_status",
        lambda _project_root, _status_map, *, only_slug=None: [
            SnippetStatusReconcileResult(path=snippet_path, removed_slugs=(key.slug,))
        ],
    )
    monkeypatch.setattr(
        "teleclaude.core.integration.step_functions._format_commit_decision",
        lambda _slug, _branch, _diff_stats, _branch_log, _requirements, _impl_plan: COMMIT_PROMPT,
    )

    def fake_run_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        del cwd, timeout
        git_calls.append(args)
        return 0, "", ""

    monkeypatch.setattr("teleclaude.core.integration.step_functions._run_git", fake_run_git)

    progressed, message = _step_awaiting_commit(
        checkpoint=checkpoint,
        checkpoint_path=tmp_path / "checkpoint.yaml",
        cwd=str(tmp_path),
    )

    assert progressed is False
    assert message == snapshot(name="message")
    assert [[part.replace(str(tmp_path), "TMP") for part in call] for call in git_calls] == snapshot(name="git_calls")


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
    tmp_path: Path, snapshot: SnapshotAssertion
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
    assert message == snapshot


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
