# Review Findings: fix-gemini-command-injection

## Scope Verification

The implementation addresses the bug by replacing brittle inactivity-based readiness detection with event-driven prompt marker detection. This directly aligns with the requirements in `bug.md`.

## Code Review

The introduction of `_wait_for_agent_prompt_ready` and the marker dictionary is a sound architectural improvement. The fallback to inactivity detection ensures robustness.

## Paradigm-fit Assessment

The changes follow the established mixin pattern for daemon session management and reuse existing tmux interaction helpers.

## Principle Violation Hunt

- **Fail Fast**: The code correctly uses an extended timeout (20s) for known markers while retaining a fallback mechanism.
- **Silent Degradation**: Fallback to inactivity detection is justified and accompanied by a warning log.

## Security Review

No secrets or injection vulnerabilities identified. `agent_name` is used safely for dictionary lookups.

## Test Coverage Check

The builder added 4 comprehensive unit tests in `tests/unit/test_daemon_session.py` covering:

- Marker found (immediate success)
- Marker not found (fallback)
- Unknown agent (direct fallback)
- Correct marker passing

## Silent Failure Hunter

Timeouts are logged as warnings, providing visibility into potential TUI readiness issues.

## Logging Policy Check

Appropriate use of `debug` for nominal flow and `warning` for timeouts/fallbacks.

## Documentation and Config

The constants and methods are well-documented with docstrings.

## Suggestions

- **Comment Accuracy**: The comment for `AGENT_PROMPT_READY_MARKERS` mentions "(ANSI-stripped) capture-pane output", but `_pane_output_snapshot` actually returns raw output (with `-e` escape sequences from `capture_pane`). While simple substring matching works because the markers are typically not interrupted by escape sequences, the comment is technically inaccurate. Consider either stripping ANSI in `_pane_output_snapshot` or updating the comment.

## Verdict: APPROVE

Findings: 0 Critical, 0 Important, 1 Suggestion.
Why No Issues: The implementation is a targeted, well-tested improvement that fixes a specific race condition. Paradigm fit and security were verified.
