"""Unit tests for shared next-machine runtime script builders."""

from __future__ import annotations

from teleclaude.core.next_machine.runtime.scripts import (
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


def test_format_review_needs_work_script_tells_reviewer_to_open_direct_fix_link() -> None:
    instruction = format_review_needs_work_script(
        "slug-a",
        "worker-1",
        "reviewer-1",
        "Fix the findings",
        next_step="telec todo prepare slug-a",
    )

    command_lines = [
        line.strip() for line in instruction.splitlines() if line.strip().startswith("telec sessions send")
    ]
    assert command_lines[0].startswith('telec sessions send reviewer-1 "A fixer is active at worker-1.')
    assert "telec sessions send worker-1 '<your findings summary>' --direct" in command_lines[0]
    assert not command_lines[0].endswith(" --direct")
    assert "Wait for reviewer session reviewer-1 to report idle." in instruction
    assert "telec todo prepare slug-a" in instruction


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
