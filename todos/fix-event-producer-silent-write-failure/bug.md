# Bug: EventProducer.emit() silently fails to write domain events (deployment.started, branch.pushed, review.approved) to Redis stream teleclaude:events. Stream has 0 consumer groups and only 7 old content.dumped entries written via direct xadd. The EventProducer xadd path returns without exception but writes nothing. IntegrationTriggerCartridge never fires, breaking finalize-to-integrator spawn chain. Root cause likely broken Redis client ref in EventProducer or silent xadd failure. Immediate fix: add logging to EventProducer.emit and emit_event, then trace why xadd succeeds but data is absent.

## Symptom

EventProducer.emit() silently fails to write domain events (deployment.started, branch.pushed, review.approved) to Redis stream teleclaude:events. Stream has 0 consumer groups and only 7 old content.dumped entries written via direct xadd. The EventProducer xadd path returns without exception but writes nothing. IntegrationTriggerCartridge never fires, breaking finalize-to-integrator spawn chain. Root cause likely broken Redis client ref in EventProducer or silent xadd failure. Immediate fix: add logging to EventProducer.emit and emit_event, then trace why xadd succeeds but data is absent.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-11

## Investigation

- `redis-cli XLEN teleclaude:events` → 7 entries, all `content.dumped` from Mar 2-4
- `redis-cli XINFO STREAM teleclaude:events` → `groups: 0`, `entries-added: 7`
- Zero `deployment.started`, `branch.pushed`, or `review.approved` events ever written
- `EventProducer` configured at daemon startup (confirmed via logs)
- `emit_deployment_started` called from `next_machine/core.py:3939` inside daemon API handler
- State machine logged `finalize_handoff_emitted` (success), meaning emit didn't throw
- `EventProducer.emit()` had zero logging — no way to observe xadd success/failure
- `emit_event()` had zero logging — no way to observe if producer was None

## Root Cause

Zero observability in the event emission path. `EventProducer.emit()` and `emit_event()` had no logging at all. The xadd may be silently failing (wrong Redis client, wrong DB, mock connection) or succeeding to a different stream — but without logging we cannot distinguish. The immediate observability gap is confirmed; the underlying write failure root cause requires the logging to be deployed first, then reproduced.

## Fix Applied

- Added `logging` import and logger to `teleclaude_events/producer.py`
- `EventProducer.emit()`: logs event type + entity before xadd, logs entry_id after success, logs exception on failure
- `emit_event()`: logs error when `_producer is None` before raising
- After daemon restart, the next finalize handoff will show exactly where the chain breaks
