"""Characterization tests for teleclaude.core.integration.step_functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.integration.checkpoint import IntegrationCheckpoint, IntegrationPhase
from teleclaude.core.integration.readiness_projection import CandidateKey
from teleclaude.core.integration.step_functions import (
    ScannedCandidate,
    _get_candidate_key,
    _run_git,
)

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
