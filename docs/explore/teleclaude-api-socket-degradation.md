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
