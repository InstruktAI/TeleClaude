"""Characterization tests for orchestrator output formatting."""

from __future__ import annotations

from teleclaude.core.next_machine.output_formatting import (
    format_finalize_handoff_complete,
    format_stash_debt,
    format_tool_call,
    format_uncommitted_changes,
)


def test_format_tool_call_uses_completion_args_and_preserves_spaced_next_call() -> None:
    output = format_tool_call(
        command="next-review-build",
        args="slug-a",
        project="/repo",
        guidance="guidance block",
        subfolder="trees/slug-a",
        next_call="telec todo work slug-a",
        completion_args="override-slug",
    )

    assert 'Dispatch metadata: command="/next-review-build" args="slug-a"' in output
    assert "telec todo mark-phase override-slug --phase review --status approved" in output
    assert "Call telec todo work slug-a" in output
    assert "telec todo work slug-a()" not in output


def test_format_tool_call_includes_pre_dispatch_block_before_dispatch_step() -> None:
    output = format_tool_call(
        command="next-build",
        args="slug-b",
        project="/repo",
        guidance="guidance block",
        subfolder="trees/slug-b",
        pre_dispatch="telec todo mark-phase slug-b --phase build --status started",
    )

    assert "STEP 0 - BEFORE DISPATCHING:" in output
    assert "telec todo mark-phase slug-b --phase build --status started" in output
    assert output.index("STEP 0 - BEFORE DISPATCHING:") < output.index("STEP 1 - DISPATCH:")


def test_format_finalize_handoff_complete_lists_child_session_cleanup_commands() -> None:
    output = format_finalize_handoff_complete("slug-c", "telec todo work", ["child-1", "child-2"])

    assert "FINALIZE HANDOFF COMPLETE: slug-c" in output
    assert "telec sessions end child-1" in output
    assert "telec sessions end child-2" in output
    assert "Call telec todo work" in output


def test_format_error_helpers_include_worktree_path_and_stash_count() -> None:
    uncommitted = format_uncommitted_changes("slug-d")
    stash = format_stash_debt("slug-d", 2)

    assert "UNCOMMITTED CHANGES in trees/slug-d" in uncommitted
    assert "telec todo work slug-d" in uncommitted
    assert "ERROR: STASH_DEBT" in stash
    assert "2 git stash entries" in stash
    assert "telec todo work slug-d" in stash
