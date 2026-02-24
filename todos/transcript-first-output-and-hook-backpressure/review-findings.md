REVIEW COMPLETE: transcript-first-output-and-hook-backpressure

Critical:

- None.

Important:

- Queue bounding is violated for critical-only backlogs, so the hook pipeline is not strictly bounded as required by `R3`. In [daemon.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/transcript-first-output-and-hook-backpressure/teleclaude/daemon.py:1101), the critical path only evicts bursty rows; if the queue is already full of critical rows, the loop exits and still appends another critical item at [daemon.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/transcript-first-output-and-hook-backpressure/teleclaude/daemon.py:1106), allowing queue growth past `HOOK_OUTBOX_SESSION_MAX_PENDING`. Concrete trace (verified): with `HOOK_OUTBOX_SESSION_MAX_PENDING=2`, enqueueing `session_start`, `user_prompt_submit`, then `agent_stop` yields queue length `3`.
- The synthetic lag acceptance test is effectively vacuous for AC4. In [test_daemon.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/transcript-first-output-and-hook-backpressure/tests/unit/test_daemon.py:341), 200 bursty rows are enqueued, but coalescing leaves one pending item; only that single row is processed at [test_daemon.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/transcript-first-output-and-hook-backpressure/tests/unit/test_daemon.py:351) before asserting `p95/p99` at [test_daemon.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/transcript-first-output-and-hook-backpressure/tests/unit/test_daemon.py:353). Lag samples are recorded only in `_process_outbox_item` ([daemon.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/transcript-first-output-and-hook-backpressure/teleclaude/daemon.py:1192)), so the percentile check is computed from one sample (verified: `lag_samples=1`).

Suggestions:

- Add a regression test for critical-only saturation that asserts queue depth never exceeds `HOOK_OUTBOX_SESSION_MAX_PENDING` and leaves overflow pressure in DB/unclaimed rows rather than in-memory queue growth.
- Replace the synthetic lag assertion with a test that drains a realistic burst through worker dispatch and asserts percentiles over multiple lag samples.

Paradigm-Fit Assessment:

- Data flow: output progression is polling-driven and hook handlers are now control-plane for `tool_use`/`tool_done`, which matches the boundary direction required by this todo.
- Component reuse: changes extend existing daemon outbox and polling coordinator paths rather than introducing an alternate pipeline.
- Pattern consistency: event routing, typed payload usage, and summary-logging style are consistent with adjacent runtime code; no copy-paste component forks found.

Manual Verification Evidence:

- Ran `telec todo demo run transcript-first-output-and-hook-backpressure` in this worktree; all 3 demo blocks passed, including focused output/control-plane and daemon/hook test slices.
- Ran targeted unit verification for touched runtime surfaces: `pytest tests/unit/test_daemon.py tests/unit/test_threaded_output_updates.py tests/unit/test_output_poller.py tests/unit/test_polling_coordinator.py tests/unit/test_agent_coordinator.py tests/unit/test_diagram_extractors.py -q` (`127 passed`).

Verdict: REQUEST CHANGES

Fixes Applied:

- Issue: Queue bounding violated for critical-only backlogs (`R3`).
  Fix: Updated `_enqueue_session_outbox_item` to requeue claimed critical rows via `mark_hook_outbox_failed` when the per-session queue is full of critical rows, preserving strict in-memory bounds and critical-event durability; added regression coverage for critical-only saturation and bursty-over-critical capacity behavior.
  Commit: `0f68ea49`
- Issue: Synthetic lag AC4 test was vacuous due to single-sample coalescing.
  Fix: Reworked `test_hook_outbox_synthetic_burst_lag_targets` to enqueue and drain a 200-row burst through `_run_session_outbox_worker`, assert multi-sample lag percentile checks, and verify delivered count over the full sample set.
  Commit: `ccc06c40`
