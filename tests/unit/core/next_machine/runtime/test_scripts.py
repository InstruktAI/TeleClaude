"""Unit tests for shared next-machine runtime script builders."""

from __future__ import annotations

from inspect import signature

from syrupy.assertion import SnapshotAssertion

from teleclaude.core.next_machine.runtime.scripts import (
    format_fix_findings_message,
    format_review_ground_shift_script,
    format_review_in_progress_script,
    format_review_needs_work_script,
)


def test_format_review_in_progress_script_reuses_live_reviewer() -> None:
    instruction = format_review_in_progress_script("slug-a", "rev-1", next_step="telec todo work slug-a")

    assert "REVIEW IN PROGRESS" in instruction
    assert "rev-1" in instruction
    assert "telec todo work slug-a" in instruction
    assert "telec sessions run" not in instruction


def test_format_review_needs_work_script_hands_findings_off_without_direct_link(
    snapshot: SnapshotAssertion,
) -> None:
    instruction = format_review_needs_work_script(
        "slug-a",
        "worker-1",
        "reviewer-1",
        "Fix the findings",
        next_step="telec todo prepare slug-a",
    )

    assert instruction == snapshot


def test_format_fix_findings_message_points_to_artifact_without_count_claim() -> None:
    assert "open_count" not in signature(format_fix_findings_message).parameters

    instruction = format_fix_findings_message(
        "slug-a",
        "requirements",
        2,
        "requirements-review-findings",
        "requirements",
    )

    assert "telec todo artifacts read slug-a requirements-review-findings" in instruction


def test_format_review_ground_shift_script_sends_scoped_follow_up() -> None:
    instruction = format_review_ground_shift_script(
        "slug-a",
        "rev-1",
        "head-old",
        "head-new",
        ["src/a.py", "src/b.py"],
        next_step="telec todo work slug-a",
    )

    assert "REVIEW GROUND SHIFTED" in instruction
    assert 'telec sessions send rev-1 "' in instruction
    assert "src/a.py, src/b.py" in instruction
    assert "telec todo work slug-a" in instruction
