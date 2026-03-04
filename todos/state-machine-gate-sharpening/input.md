# state-machine-gate-sharpening — Input

Sharpen the next_work state machine in teleclaude/core/next_machine/core.py to stop false-invalidation loops that burn review rounds and block finalize. Three fixes, all in core.py:

1. MERGE-AWARE STALE BASELINE GUARD (line 3002-3018): Currently compares HEAD SHA to review_baseline_commit — any SHA mismatch resets review to pending. After approval, only merges from main and orchestrator state updates land. Change the guard to: git diff --name-only {baseline}..HEAD, filter out files under todos/ and .teleclaude/ and merge commits. If nothing remains, approval holds. Only invalidate when non-merge commits touch files outside todos/ and .teleclaude/.

2. PRESERVE BUILD ON GATE FAILURE WHEN REVIEW ALREADY OCCURRED (line 3088-3091): Currently resets build to started on any gate failure, forcing full /next-build re-dispatch. When review_round > 0, keep build=complete. The builder already built everything — the orchestrator just needs a focused gate fix, not a full rebuild.

3. SINGLE RETRY FOR LOW-COUNT TEST FAILURES IN run_build_gates (line ~430): When make test fails with <=2 failures out of 2500+, re-run just the failing tests once (pytest --lf). If they pass on retry, gate passes. Catches the flaky async teardown pattern that hits ~50 percent of gate runs.
