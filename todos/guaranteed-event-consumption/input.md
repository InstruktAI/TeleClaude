# Input: guaranteed-event-consumption

## Problem Statement

The TeleClaude event platform is fire-and-forget. Events emitted to Redis Streams are
consumed without acknowledgment — if a cartridge callback throws or the daemon crashes
mid-processing, the event silently vanishes. There is no retry, no dead-letter queue,
and no way to detect that an event was lost.

This is a platform-wide concern. Every cartridge in the pipeline (integration trigger,
enrichment, correlation, classification, etc.) suffers from the same gap. An event that
fails to process disappears without trace.

## Current Behavior

- Daemon reads from Redis Streams directly, no consumer group
- Cartridge callbacks are wrapped in try/except that logs and drops
- No XACK — events are read and forgotten regardless of processing outcome
- No PEL (Pending Entry List) tracking — crashed events vanish
- No dead-letter — repeated failures are invisible
- No idempotency contract across cartridges (some are idempotent by accident, not by design)
- If Redis is unavailable at startup, the event platform silently exits — no events processed

## Design Direction

### Consumer groups per cartridge
Each cartridge gets its own consumer group on the Redis Stream. Redis tracks what each
group has and hasn't acknowledged independently.

### Explicit XACK after successful processing
The pipeline framework (not individual cartridges) calls XACK only after the cartridge
callback returns successfully. If the callback throws, no ACK — the event stays pending.

### PEL sweep for unacknowledged events
A periodic sweep (and on daemon restart) uses XAUTOCLAIM/XCLAIM to reclaim pending
entries older than a configurable threshold and redeliver them to the cartridge.

### Dead-letter after N retries
If an event fails repeatedly (configurable, e.g. 3 attempts), move it to a dead-letter
stream and emit an observable signal (log, metric, notification). The event is never
silently lost.

### Idempotent consumer contract
All cartridges must handle redelivery safely. This becomes a formal contract of the
cartridge interface — process successfully or throw, the framework handles retry and
dead-letter. Cartridges that aren't idempotent today must be made so.

### Observability
- Count of pending (unacked) events per consumer group
- Count of dead-lettered events
- Alert/signal when dead-letter queue grows

## Key Files
- `teleclaude/daemon_event_platform.py` — pipeline dispatch, cartridge wiring
- `teleclaude/events/pipeline.py` — pipeline framework
- `teleclaude/events/cartridges/` — all cartridge implementations
- `teleclaude/events/domain_pipeline.py` — domain event routing
