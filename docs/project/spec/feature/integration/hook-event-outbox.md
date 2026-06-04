---
id: 'project/spec/feature/integration/hook-event-outbox'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Per-session outbox between the receiver subprocess and the integration service, providing durable, coalesced, retry-safe transport for agent CLI hook events.'
---

# Hook Event Outbox — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The durable, locally persisted write-ahead queue that decouples
short-lived receiver subprocesses from the long-running integration
service. The receiver writes one entry per accepted hook event; the
integration service's hook outbox worker (see `hook-outbox-dispatcher`)
claims, dispatches, and removes those entries. The outbox is the only
durable contract point between the agent CLI process tree and the
integration service — both sides survive across service restarts and
across long-running agent sessions.

The receiver-side writer carries one extra responsibility: a per-
(session id, event type) **latest-wins coalesce window**. Within the
window, a new emit for the same key overwrites the prior unclaimed
entry in place (payload + timestamp updated, attempt count reset, last
error cleared) instead of inserting. Claimed entries are never replaced.

For the canonical aggregate shape, see `project/spec/domain/integration.md`.

## Canonical fields

### Use cases

#### UC-OB1: Plain enqueue (no coalesce)

```gherkin
Given the receiver has resolved a TeleClaude session id
And the event type has no coalesce window
When the receiver enqueues a hook event with session id, event type, payload
Then a new outbox entry is recorded with creation timestamp = next-attempt-at = now, attempt count = 0, no claim lock
And the entry is committed before the subprocess exits
```

#### UC-OB2: Coalesce overwrites prior unclaimed entry

```gherkin
Given an unclaimed outbox entry exists for (session id, tool-use) with creation timestamp within 1.0 second
When the receiver enqueues for the same key with a 1.0s latest-wins window
Then a guarded read inside the same transaction finds the prior entry
And the existing entry's payload is overwritten with the new payload
And creation timestamp and next-attempt-at are set to now
And attempt count is reset to 0, last error to none
And no new entry is recorded
And no second entry is created
```

#### UC-OB3: Coalesce skipped when prior entry is claimed

```gherkin
Given an in-flight outbox entry exists for (session id, event type) with a claim lock
When the receiver enqueues with a coalesce window
Then the "unclaimed only" filter excludes the in-flight entry
And a NEW entry is recorded alongside the in-flight one
And both will be processed by the integration service's worker
```

#### UC-OB4: Codex agent_stop uses a wider 10s coalesce window

```gherkin
Given the agent is Codex and event type is agent-stop
When the receiver computes the coalesce window
Then the window is widened to 10 seconds — overriding the 1.0s baseline
And the wider window absorbs the burst of stop events Codex emits per turn
```

#### UC-OB5: native-metadata-update coalesces at 1s baseline

```gherkin
Given the receiver writes a native-metadata-update on every hook that carries a native session id or native log file
When two updates land in the same second
Then the second overwrites the first
And only one entry is dispatched to the integration service for that window
```

#### UC-OB6: Outbox store path resolution

```gherkin
Given the receiver needs an outbox store
When the default outbox path is resolved
Then it derives the canonical store path under the TeleClaude home
And the subprocess opens its own client against that store (no service connection required)
```

#### UC-OB7: Error payload requires resolvable session id

```gherkin
Given the receiver encounters a contract violation that calls the best-effort error helper
When the helper tries to resolve a session id via cached and native-id lookups
Then if neither lookup yields a session id:
    - the helper logs "receiver error with unknown session" at error level
    - NO outbox entry is recorded
And if a session id IS resolved:
    - an outbox entry with event type "error" is recorded
    - the payload contains message, source="hook_receiver", code, severity="error", retryable=false
    - details include agent, event_type, code
And the receiver's parse-failure paths do NOT pass payload data,
    so unknown-session parse failures always take the log-only branch above
```

### Cross-context references

- Producer side belongs (in v2) to `agent_runtime` along with the
  receiver.
- Consumer side is `hook-outbox-dispatcher` (this context).
- The outbox pattern itself echoes the v2 transactional outbox aggregate
  in `docs/project/spec/domain/integration.md` (Outbox Entry); v1 uses
  a local store and a per-process writer (not a shared producer API).

## Known caveats

- The outbox is locally persisted; concurrent receivers may experience
  contention during high-frequency tool-use bursts. Coalescing the
  bursty events into 1-second windows reduces contention.
- The latest-wins window is enforced via a guarded read-then-write
  inside one transaction; there is a narrow race where two receivers
  running in parallel both see no prior entry and both insert. This is
  observable as occasional duplicate near-simultaneous entries — the
  integration service's worker tolerates duplicates by event-type
  semantics.
- Coalesce candidates require an attempt count of zero implicitly —
  entries that already failed once (attempt count above zero, last
  error set) also coalesce because the filter only checks for absence
  of a claim lock; the incoming emit effectively retries the prior
  failure under the new payload. This is intentional but undocumented
  in v1.
- The outbox is local to each integration service host; cross-host hook
  delivery is not supported in v1.
- The serializer helper accepts pre-encoded strings for test ergonomics;
  production callers always pass structured payloads.
