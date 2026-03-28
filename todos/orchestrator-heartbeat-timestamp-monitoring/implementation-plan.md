# Implementation Plan: orchestrator-heartbeat-timestamp-monitoring

## Overview

Replace the agent-conditional STEP 3 section in `format_tool_call()` with a
single, agent-agnostic timestamp comparison rule. Adjust notification wording
in `notify_stop()` to frame the event as a heartbeat trigger. Remove the two
prose-lock test assertions identified during grounding. Add behavioral tests
for the new assessment rule.

The approach modifies the existing orchestration instruction template in place —
no new modules, helpers, or abstractions. The `last_activity` and
`last_output_summary_at` fields are already available in
`SessionSnapshotTimestampFields` and serialized in `SessionSnapshot.to_dict()`.

## Task 1: Replace agent-conditional STEP 3 with timestamp comparison rule

**File(s):** `teleclaude/core/next_machine/output_formatting.py`

**What:** Rewrite the STEP 3 section of `format_tool_call()` (currently lines
309–360) to remove:

- The `=== IF YOU SELECTED CODEX AS THE AGENT ===` block (STEP 3a observation
  heartbeat, STEP 3b action heartbeat, the two-heartbeat protocol)
- The `=== IF YOU SELECTED CLAUDE OR GEMINI AS THE AGENT ===` block
  (notification-trust model with separate A/B event handling)

Replace both with a single unified block that instructs the orchestrator to:

1. On any heartbeat trigger (notification, timer, or manual check), run
   `telec sessions list` and read the worker session's `last_activity` and
   `last_output_summary_at`.
2. If `last_activity > last_output_summary_at` → worker is active. Reset
   timer and wait.
3. If `last_activity == last_output_summary_at` → worker is idle/settled.
   Proceed to post-completion steps.

The tailing discipline section (lines 314–316) is preserved for content
inspection but is no longer the progress-assessment mechanism. STEP 1
(dispatch) and STEP 2 (timer + marker initialization) remain unchanged.
Section C (feedback/help), section D (no-op suppression), the post-completion
block, and the orchestration principle footer all remain unchanged.

**Why:** The current agent-branching logic has two problems: (1) Codex's
two-heartbeat protocol adds unnecessary latency and complexity for a problem
that timestamp comparison solves deterministically, and (2) the
Claude/Gemini notification-trust model treats notifications as near-proof of
completion, which they aren't — sessions can emit turn-complete signals for
internal sub-agent completions regardless of agent type. A single timestamp
comparison rule is deterministic, agent-agnostic, and uses data already
available in the sessions list.

**Verification:**

- `test_format_tool_call_contains_timestamp_comparison_rule` passes (spec test)
- `test_format_tool_call_has_no_agent_type_conditionals` passes (spec test)
- `test_format_tool_call_preserves_tailing_discipline` passes (spec test)
- No occurrences of "observation heartbeat", "action heartbeat",
  "two-heartbeat", "IF YOU SELECTED CODEX", or "IF YOU SELECTED CLAUDE" in
  the output of `format_tool_call()`
- All existing `test_output_formatting.py` tests still pass (they assert on
  post-completion markers and dispatch structure, not STEP 3)

## Task 2: Adjust notification wording in notify_stop

**File(s):** `teleclaude/core/session_listeners.py`

**What:** In `notify_stop()` (line 413), change the notification body from:

```
"Session {id}{location}{title} finished its turn. Use telec sessions tail {id} to inspect."
```

to wording that frames the event as a heartbeat trigger — an event that prompts
assessment, not a conclusion. The tail instruction remains.

**Why:** "Finished its turn" implies the worker completed its task, which
reinforces the old model where notifications were treated as completion signals.
The new model (R2) explicitly states that no trigger type is treated as a direct
completion signal — all triggers prompt the same timestamp assessment. The
wording must match this mental model so the orchestrator doesn't short-circuit
the assessment.

**Verification:**

- `test_notify_stop_wording_does_not_imply_completion` passes (spec test)
- The notification message does not contain "finished its turn", "completed",
  "done", or other completion-implying language
- The tail instruction (`telec sessions tail`) remains present

## Task 3: Remove prose-lock test assertions

**File(s):**

- `tests/unit/core/next_machine/test_work.py`
- `tests/unit/core/next_machine/test_build_gates.py`

**What:** Two specific assertions are actual prose-locks (asserting on
human-facing text that could be reworded without changing behavior):

1. `test_work.py` line 183: `assert "Review iteration: round 1/3." in result`
   — Replace with a behavioral assertion that verifies the round count data
   is present (e.g., assert on the dispatch state or the format call
   arguments that produce the round text).

2. `test_build_gates.py` line 67:
   `assert "retry passed after 1 flaky failure(s)" in output`
   — Replace with a behavioral assertion: assert `passed is True` (already
   present on line 66) is sufficient since the retry path is verified by the
   `run.call_args_list[1]` assertion on line 68. The prose assertion adds no
   behavioral value. Remove it.

All other string assertions in the 7 test files were evaluated during
grounding and are execution-significant: command tokens (`telec sessions run`,
`telec todo mark-phase`), protocol markers (`ERROR: STASH_DEBT`, `BLOCKED:`,
`BUILD GATES FAILED:`), and structural markers (`STEP 0 - BEFORE DISPATCHING:`,
`ADDITIONAL CONTEXT FOR WORKER:`). These are allowed per testing policy.

**Why:** Testing policy forbids exact-string assertions on human-facing output.
However, per the output text assertion guardrail, execution-significant text
(protocol markers, command tokens) is explicitly allowed. The input estimated
49 test functions with string assertions needing removal, but careful per-test
evaluation shows only 2 actual prose-locks. The rest are execution-significant.
Removing tests that assert on protocol markers would reduce behavioral coverage,
which contradicts R6's success criteria ("behavioral assertions are preserved").

**Verification:**

- No test asserts on `"Review iteration: round 1/3."` (exact rendered text)
- No test asserts on `"retry passed after 1 flaky failure(s)"` (exact prose)
- All behavioral assertions in both files are preserved
- Pre-commit hooks pass

## Task 4: Add behavioral tests for the new timestamp comparison rule

**File(s):** `tests/unit/core/next_machine/test_output_formatting.py`

**What:** Add tests that verify the behavioral contracts of the new STEP 3
section:

1. `test_format_tool_call_contains_timestamp_comparison_rule` — The output
   contains the `last_activity` and `last_output_summary_at` field references
   and the comparison semantics (these are execution-significant: the
   orchestrator parses and acts on them).

2. `test_format_tool_call_has_no_agent_type_conditionals` — The output does
   not contain agent-type conditional markers (no "IF YOU SELECTED CODEX",
   no "IF YOU SELECTED CLAUDE OR GEMINI", no "=== END AGENT-SPECIFIC").

3. `test_format_tool_call_preserves_tailing_discipline` — The tailing
   discipline section remains present for content inspection.

**Why:** The existing test_output_formatting.py tests cover post-completion
block formatting and dispatch structure, but none cover the STEP 3 wait/monitor
section. Without these tests, a regression that re-introduces agent branching
or removes the timestamp rule would go undetected.

**Verification:**

- All new tests are initially marked as expected failures (xfail)
- Tests assert on execution-significant content (field names, protocol markers),
  not prose
- Pre-commit hooks pass with xfail markers

## Task 5: Add behavioral test for notification wording

**File(s):** `tests/unit/core/next_machine/test_output_formatting.py` (or
`tests/unit/core/test_session_listeners.py` if it exists; discover location
from existing test structure)

**What:** Add a test that verifies:

1. `notify_stop()` output does not contain completion-implying language
   ("finished its turn", "completed", "done")
2. `notify_stop()` output contains the tail instruction

**Why:** The notification wording change (Task 2) must be verified to prevent
regression to the old completion-implying language.

**Verification:**

- Test is initially marked as expected failure (xfail)
- Test asserts on absence of specific completion-implying tokens and presence
  of the tail command — both execution-significant
- Pre-commit hooks pass

## Referenced file paths

Production:

- `teleclaude/core/next_machine/output_formatting.py`
- `teleclaude/core/session_listeners.py`

Tests:

- `tests/unit/core/next_machine/test_output_formatting.py`
- `tests/unit/core/next_machine/test_work.py`
- `tests/unit/core/next_machine/test_build_gates.py`

Verified (no changes needed):

- `teleclaude/session_fields.py` — confirms `last_activity` and `last_output_summary_at` fields exist
- `teleclaude/core/models/_snapshot.py` — confirms both fields serialized in `to_dict()`
