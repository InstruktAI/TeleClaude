# TeleClaude API Socket Degradation — Incident Trail

## Purpose

Keep a durable, stateful trail of incident reasoning so future AI sessions can resume without re-investigating from zero.

Use this file for case-level chronology and evolving hypotheses.
Keep stable runbook instructions in `docs/project/procedure/troubleshooting.md`.

## Entry Template

Each new entry should include:

- **Timestamp window**
- **Symptom**
- **Evidence**
- **Hypothesis + confidence**
- **Change/prototype attempted**
- **Verification result**
- **Next decision**

---

## 2026-02-14 — Restart churn dominates current failure mode

- **Timestamp window:** Last 24h snapshot (captured February 14, 2026)
- **Symptom:** API/MCP appears unstable, with repeated socket refusal windows and frequent reconnect behavior.
- **Evidence:**
  - `instrukt-ai-logs teleclaude --since 24h --grep "Received SIGTERM signal"` showed **128** events.
  - `Resource snapshot` telemetry remained bounded instead of runaway:
    - `periodic count=1360 avg_fd=112.0 max_fd=151`
    - `shutdown:SIGTERM count=128 avg_fd=107.8 max_fd=152`
    - `startup count=118 avg_fd=19.6 max_fd=28`
  - `api_task_crash_count_24h=0`, `ws_send_timeout_24h=0`, `redis_reconnect_fail_24h=0`.
- **Hypothesis + confidence:** Primary active issue is restart/SIGTERM churn from external restart triggers, not current unbounded leak growth in the daemon runtime paths. **Confidence: high**.
- **Change/prototype attempted:**
  - Tightened checkpoint file-scoping in `teleclaude/hooks/checkpoint.py` to avoid broad repo-wide false positives that can force unnecessary restart actions.
  - Added shell path extraction and changed ambiguous fallback from fail-open to fail-closed.
- **Verification result:**
  - `pytest tests/unit/test_checkpoint_builder.py -q` passed.
  - `pytest tests/unit/test_checkpoint_hook.py -q` passed.
  - `ruff check teleclaude/hooks/checkpoint.py tests/unit/test_checkpoint_builder.py` passed.
- **Next decision:** Activate and monitor (controlled restart + observation window) to confirm whether SIGTERM frequency drops.

## 2026-02-14 — Restart timeout can be a false negative while daemon is still booting

- **Timestamp window:** 10:20-10:23 local
- **Symptom:** `make restart` failed with degraded health, yet daemon became healthy shortly after.
- **Evidence:**
  - `make restart` ended with timeout/degraded status.
  - Logs showed repeated SIGTERM and connection-refused windows:
    - `2026-02-14T10:20:46.717Z Received SIGTERM signal...`
    - `2026-02-14T10:21:37.683Z Received SIGTERM signal...`
    - bursts of `Connection refused. Retrying in 5s...`
  - Logs also showed eventual successful startup:
    - `2026-02-14T10:22:14.556Z Starting TeleClaude daemon...`
    - `2026-02-14T10:22:26.266Z API server listening on /tmp/teleclaude-api.sock`
  - Follow-up `make status` returned full healthy state.
- **Hypothesis + confidence:** Restart watchdog window can be shorter than real startup under load/churn, creating false-negative restart failures and encouraging harmful restart loops. **Confidence: medium-high**.
- **Change/prototype attempted:**
  - Documented this pattern in troubleshooting runbook to require log verification before issuing another restart after a timeout.
- **Verification result:**
  - `make status` healthy after waiting for startup completion.
  - Targeted tests remained green:
    - `pytest tests/unit/test_checkpoint_builder.py -q`
    - `pytest tests/unit/test_checkpoint_hook.py -q`
- **Next decision:** Consider extending restart watchdog tolerance or adding an explicit "startup in progress" terminal state in `make restart` to avoid operator/automation restart thrash.

## 2026-02-15 — Hook outbox retry storm root cause confirmed (agent/parser mismatch)

- **Timestamp window:** 01:14-01:55 UTC
- **Symptom:** Hook outbox rows retried indefinitely with `Extra data: line 2 column 1 (char 139)`, causing persistent degradation and delayed/missing stop summaries.
- **Evidence:**
  - `hook_outbox` had 66 undelivered rows with identical `last_error` and high retry counts.
  - All failing rows belonged to TeleClaude session `7236062a...`, with payload `agent_name=claude` and Claude `.jsonl` transcript paths.
  - Session metadata for that same session was stale: `active_agent=gemini`.
  - Logs repeatedly showed:
    - `Evaluating incremental output agent=gemini is_enabled=true session=7236062a`
    - followed by `Hook outbox dispatch failed (retrying) ... Extra data...`.
  - Direct parser repro:
    - `json.load()` against the failing Claude transcript throws `Extra data...`.
    - JSONL line-by-line parse succeeds.
- **Hypothesis + confidence:** Incremental output parser selection relied on stale `session.active_agent` instead of hook payload agent identity, so Claude JSONL was parsed with Gemini JSON parser. Retry classification treated this deterministic parse mismatch as retryable, producing an outbox storm. **Confidence: high**.
- **Change/prototype attempted:**
  - `teleclaude/core/agent_coordinator.py`
    - `_maybe_send_incremental_output` now prefers `payload.raw["agent_name"]` over `session.active_agent`.
  - `teleclaude/daemon.py`
    - `_dispatch_hook_event` now refreshes `active_agent` from hook payload when valid.
    - `_is_retryable_hook_error` treats `json.JSONDecodeError` with `Extra data` as non-retryable.
  - Added regression tests:
    - `tests/unit/test_threaded_output_updates.py`
    - `tests/unit/test_daemon.py`
- **Verification result:**
  - Targeted tests passed:
    - `pytest -q tests/unit/test_threaded_output_updates.py -k "prefers_payload_agent"`
    - `pytest -q tests/unit/test_daemon.py -k "hook_outbox_extra_data_decode_error_is_not_retryable or hook_outbox_other_decode_errors_remain_retryable or dispatch_hook_event_updates_active_agent_from_payload"`
  - Runtime recovery after restart:
    - `make status` returned healthy.
    - Session `7236062a...` updated to `active_agent=claude`.
    - Outbox drained fully: `pending_extra 0`, `pending_total 0`.
- **Next decision:** Keep this guard in place and monitor for new parser mismatch signatures; if similar errors appear with different parsers, add explicit parser-format detection in transcript utilities as a secondary safety net.

## 2026-02-15 — TMUX session contract mismatch can misroute hooks to stale session rows

- **Timestamp window:** Feb 15, 2026 (post hook-outbox incident, same day window)
- **Symptom:** Hook payload for Claude native session was delivered to a Gemini-labeled TeleClaude session, causing deterministic parser mismatch and repeated decode/retry failures.
- **Evidence:**
  - Session `7236062a-31e8-483c-91bf-10cd410dfae4` started as Gemini.
  - Claude hook attachment event at `2026-02-14T23:24:32Z` showed incoming `native_session_id=<claude-session-id>` while `resolved_session_id` was Gemini session.
  - Logs showed `Evaluating incremental output agent=gemini` while payload transcript type/format was Claude JSONL.
  - Parsing failure remained `Extra data: line 2 column 1`.
- **Hypothesis + confidence:** `teleclaude_session_id` contract mapping can become stale across native sessions in tmux flow, and resolver path trusted marker identity without validating native identity compatibility. Incoming hook `native_session_id` and contract marker session were not cross-checked. **Confidence: high**.
- **Change/prototype attempted:**
  - Hardened `teleclaude/hooks/receiver.py` to validate TMUX contract candidate via session row compatibility:
    - compare marker session native identity against incoming `native_session_id`
    - reject mismatched/closed/incompatible marker rows
    - fallback to lookup by native session id when marker is stale
    - fail fast when no compatible session can be found
  - Added unit tests in `tests/unit/test_hook_receiver.py`:
    - marker mismatch falls back to native lookup
    - marker mismatch without fallback exits with error
    - TMP path fallback test coverage
- **Verification result:**
  - `pytest tests/unit/test_hook_receiver.py -q` passed.
  - `pytest tests/unit/test_hook_receiver.py` reported all cases passing (33).
  - Runbook and trail documentation updated in:
    - `docs/project/procedure/troubleshooting.md`
    - `docs/explore/teleclaude-api-socket-degradation.md`
- **Next decision:** Keep `native_session_id`/marker validation in the hot path for all receiver session resolution and monitor for recurring stale-marker telemetry before adding cleanup heuristics.
