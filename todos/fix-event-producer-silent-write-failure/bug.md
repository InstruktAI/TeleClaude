# Bug: EventProducer emit logging invisible — misleading silent failure diagnosis

## Symptom

After finalize handoff, no integrator session spawned. Investigation found `redis-cli XLEN teleclaude:events` returned only 7 old `content.dumped` entries with 0 consumer groups, suggesting events were never written. EventProducer.emit() had zero logging, making it impossible to observe whether xadd succeeded or failed.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-11

## Investigation

1. `redis-cli XLEN teleclaude:events` (localhost:6379) → 7 entries, all `content.dumped` from Mar 2-4
2. Added logging to `EventProducer.emit()` — logs appeared to be silenced even with `instrukt_ai_logging.get_logger`
3. Traced logging config: `configure_logging("teleclaude")` sets `teleclaude.*` loggers to INFO but `teleclaude_events.*` (separate top-level package) inherits root level WARNING
4. Fixed logging level in `teleclaude/logging_config.py` — `teleclaude_events` logs now visible
5. xadd confirmed successful: `entry_id=1773234935204-0`
6. Entry not found on localhost because daemon connects to **remote** Redis (`rediss://redis.srv.instrukt.ai:6478`)
7. Remote Redis has **701 entries**, 1 consumer group (`event-processor`), 0 lag — pipeline fully operational

## Root Cause

Two compounding issues created a false diagnosis:

1. **Logging visibility**: `teleclaude_events` is a separate Python package from `teleclaude`. The logging config only set `teleclaude` loggers to INFO; `teleclaude_events.*` loggers inherited root WARNING level, silencing all INFO/DEBUG output from the entire events package (producer, processor, cartridges).

2. **Wrong Redis instance**: `redis-cli` defaults to localhost:6379. The daemon uses `rediss://redis.srv.instrukt.ai:6478`. The 7 `content.dumped` entries in local Redis were written by an old code path. All domain events have been writing to the remote Redis correctly.

The event pipeline was never broken. The integrator spawn failure for `split-children-deps` had a different cause (likely timing or session state).

## Fix Applied

- `teleclaude_events/producer.py`: Added `instrukt_ai_logging.get_logger` and emit logging (before/after xadd, exception on failure, error when _producer is None)
- `teleclaude/logging_config.py`: After `configure_logging("teleclaude")`, explicitly sets `teleclaude_events` logger to the same level as `teleclaude` logger — fixes silent log suppression for the entire events package
