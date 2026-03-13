"""Tests for _try_auto_enqueue — skips re-enqueue when candidate already in queue."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from teleclaude.core.integration.queue import IntegrationQueue
from teleclaude.core.integration.readiness_projection import CandidateKey
from teleclaude.core.integration.step_functions import _try_auto_enqueue

_SHA = "a" * 40


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _mock_run_git_resolve_sha(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
    """Mock git that resolves rev-parse to a fixed SHA and fails ancestry check."""
    if args[:1] == ["rev-parse"]:
        return 0, _SHA, ""
    if args[:2] == ["merge-base", "--is-ancestor"]:
        return 1, "", ""  # not ancestor (squash merge)
    return 0, "", ""


# ---------------------------------------------------------------------------
# Auto-enqueue skips candidates already in queue (any status)
# ---------------------------------------------------------------------------


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_resolve_sha)
def test_auto_enqueue_skips_in_progress_item(_mock_git: object, tmp_path: Path) -> None:
    """Auto-enqueue must skip candidates with status 'in_progress'."""
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    key = CandidateKey(slug="my-slug", branch="my-slug", sha=_SHA)
    queue.enqueue(key=key, ready_at=_now_iso())
    queue.pop_next()  # queued → in_progress

    result = _try_auto_enqueue(queue=queue, slug="my-slug", cwd=str(tmp_path))
    assert result is False


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_resolve_sha)
def test_auto_enqueue_skips_queued_item(_mock_git: object, tmp_path: Path) -> None:
    """Auto-enqueue must skip candidates with status 'queued'."""
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    key = CandidateKey(slug="my-slug", branch="my-slug", sha=_SHA)
    queue.enqueue(key=key, ready_at=_now_iso())

    result = _try_auto_enqueue(queue=queue, slug="my-slug", cwd=str(tmp_path))
    assert result is False


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_resolve_sha)
def test_auto_enqueue_skips_integrated_item(_mock_git: object, tmp_path: Path) -> None:
    """Auto-enqueue must skip candidates with status 'integrated'."""
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    key = CandidateKey(slug="my-slug", branch="my-slug", sha=_SHA)
    queue.enqueue(key=key, ready_at=_now_iso())
    queue.mark_integrated(key=key, reason="test")

    result = _try_auto_enqueue(queue=queue, slug="my-slug", cwd=str(tmp_path))
    assert result is False


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_resolve_sha)
def test_auto_enqueue_skips_blocked_item(_mock_git: object, tmp_path: Path) -> None:
    """Auto-enqueue must skip candidates with status 'blocked'."""
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    key = CandidateKey(slug="my-slug", branch="my-slug", sha=_SHA)
    queue.enqueue(key=key, ready_at=_now_iso())
    queue.pop_next()  # queued → in_progress
    queue.mark_blocked(key=key, reason="conflict")  # in_progress → blocked

    result = _try_auto_enqueue(queue=queue, slug="my-slug", cwd=str(tmp_path))
    assert result is False


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_resolve_sha)
def test_auto_enqueue_skips_superseded_item(_mock_git: object, tmp_path: Path) -> None:
    """Auto-enqueue must skip candidates with status 'superseded'."""
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    key = CandidateKey(slug="my-slug", branch="my-slug", sha=_SHA)
    queue.enqueue(key=key, ready_at=_now_iso())
    queue.pop_next()  # queued → in_progress
    queue.mark_superseded(key=key, reason="newer version")  # in_progress → superseded

    result = _try_auto_enqueue(queue=queue, slug="my-slug", cwd=str(tmp_path))
    assert result is False


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_resolve_sha)
def test_auto_enqueue_succeeds_for_unknown_candidate(_mock_git: object, tmp_path: Path) -> None:
    """Auto-enqueue must succeed for a candidate not yet in the queue."""
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")

    result = _try_auto_enqueue(queue=queue, slug="my-slug", cwd=str(tmp_path))
    assert result is True

    item = queue.get(key=CandidateKey(slug="my-slug", branch="my-slug", sha=_SHA))
    assert item is not None
    assert item.status == "queued"
