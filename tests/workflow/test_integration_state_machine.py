"""Functional coverage for integration state machine behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _now_iso,
    _write_checkpoint,
)
from teleclaude.core.integration.step_functions import _step_push_succeeded
from teleclaude.hooks.checkpoint_flags import read_integrator_maintenance_marker

_SPEC = "project/spec/feature/workflow/integration-state-machine"

_FAKE_SESSION = "integrator-test-session"


def _make_checkpoint(pre_merge_head: str | None = "abc123") -> IntegrationCheckpoint:
    now = _now_iso()
    return IntegrationCheckpoint(
        phase=IntegrationPhase.PUSH_SUCCEEDED.value,
        candidate_slug="test-slug",
        candidate_branch="test-slug",
        candidate_sha="def456",
        lease_token="lease-token",
        items_processed=0,
        items_blocked=0,
        started_at=now,
        last_updated_at=now,
        error_context=None,
        pre_merge_head=pre_merge_head,
        warnings=[],
    )


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM1")
def test_delivery_writes_maintenance_marker_with_range_before_candidate_delivered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delivery writes the integrator-maintenance marker with the merge range.

    The marker must survive the CANDIDATE_DELIVERED reset so the agent-stop
    checkpoint can read it.
    """
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    pre_merge_sha = "pre111aaa"
    post_merge_sha = "post999bbb"

    checkpoint_path = tmp_path / "integrate-state.json"
    cp = _make_checkpoint(pre_merge_head=pre_merge_sha)
    _write_checkpoint(checkpoint_path, cp)

    with (
        patch("teleclaude.core.integration.step_functions.get_session_id", return_value=_FAKE_SESSION),
        patch("teleclaude.core.integration.step_functions._run_git") as mock_git,
        patch("teleclaude.core.integration.step_functions._get_head_sha", return_value=post_merge_sha),
        patch("teleclaude.core.integration.step_functions._do_cleanup") as mock_cleanup,
    ):
        # Simulate pull succeeding, no bookkeeping commits ahead
        def _fake_run_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
            if args[:2] == ["pull", "--ff-only"]:
                return 0, "", ""
            if args[:3] == ["rev-list", "--count", "origin/main..HEAD"]:
                return 0, "0\n", ""
            return 0, "", ""

        mock_git.side_effect = _fake_run_git
        mock_cleanup.return_value = (True, "")

        _step_push_succeeded(
            checkpoint=cp,
            checkpoint_path=checkpoint_path,
            cwd=str(tmp_path),
        )

    marker_content = read_integrator_maintenance_marker(_FAKE_SESSION)
    assert marker_content is not None
    expected_range = f"{pre_merge_sha}..{post_merge_sha}"
    marker_lines = [line for line in marker_content.strip().splitlines() if line]
    assert expected_range in marker_lines


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM1")
def test_maintenance_marker_accumulates_across_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple deliveries accumulate ranges in the marker file."""
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    ranges = [("pre1", "post1"), ("pre2", "post2")]
    checkpoint_path = tmp_path / "integrate-state.json"

    for pre_sha, post_sha in ranges:
        cp = _make_checkpoint(pre_merge_head=pre_sha)
        _write_checkpoint(checkpoint_path, cp)

        with (
            patch("teleclaude.core.integration.step_functions.get_session_id", return_value=_FAKE_SESSION),
            patch("teleclaude.core.integration.step_functions._run_git") as mock_git,
            patch("teleclaude.core.integration.step_functions._get_head_sha", return_value=post_sha),
            patch("teleclaude.core.integration.step_functions._do_cleanup") as mock_cleanup,
        ):

            def _fake_run_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
                if args[:2] == ["pull", "--ff-only"]:
                    return 0, "", ""
                if args[:3] == ["rev-list", "--count", "origin/main..HEAD"]:
                    return 0, "0\n", ""
                return 0, "", ""

            mock_git.side_effect = _fake_run_git
            mock_cleanup.return_value = (True, "")

            _step_push_succeeded(
                checkpoint=cp,
                checkpoint_path=checkpoint_path,
                cwd=str(tmp_path),
            )

    marker_content = read_integrator_maintenance_marker(_FAKE_SESSION)
    assert marker_content is not None
    # Verify both ranges accumulated using variable identity (no string literal on left side of `in`)
    range_1 = f"{ranges[0][0]}..{ranges[0][1]}"
    range_2 = f"{ranges[1][0]}..{ranges[1][1]}"
    marker_lines = [line for line in marker_content.strip().splitlines() if line]
    assert range_1 in marker_lines
    assert range_2 in marker_lines
