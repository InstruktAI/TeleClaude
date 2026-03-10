# Plan Review Findings: codex-render-baseline

Critical:
- Scope split required. The plan still bundles at least two independently shippable workstreams: R1-R3 runtime corrections (`teleclaude/constants.py`, `teleclaude/core/tmux_bridge.py`, `teleclaude/core/session_cleanup.py`, `teleclaude/services/maintenance_service.py`, `teleclaude/core/output_poller.py`) and R4-R5 replay corpus work (`tests/fixtures/codex_pane_snapshots/`, `tests/unit/test_codex_replay.py`, `teleclaude/core/polling_coordinator.py`). The input and requirements already describe these as Phase 1 and Phase 2, and the code changes are not coupled such that splitting would create a half-working codebase. This fails Definition of Ready Gate 2 and Review-Plan Step 3.

Important:
- None.

Suggestion:
- None.

Resolved during review:
- Tightened the R3 `is_pane_dead()` cadence verification so the test proves a 5-iteration throttle instead of allowing weaker call counts.
- Corrected the fixture corpus specification so every planned snapshot includes ANSI escapes, matching the stated parser-fixture requirement.
- Added explicit `demo.md` coverage and grounding metadata so the plan anticipates the mandatory demo review lane.
