---
description: 'Per-session outbox between the receiver subprocess and the integration service, providing durable, coalesced, retry-safe transport for agent CLI hook events.'
visibility: 'public'
---

# Hook Event Outbox — Spec

## What it is

The durable, locally persisted write-ahead queue that decouples
short-lived receiver subprocesses from the long-running integration
service. The receiver writes one entry per accepted hook event; the
integration service's hook outbox worker (see `hook-outbox-dispatcher`)
claims, dispatches, and removes those entries. The outbox is the only
durable contract point between the agent CLI process tree and the
integration service — both sides survive across service restarts and
across long-running agent sessions. The store lives in the TeleClaude home;
each receiver subprocess opens it locally and needs no integration-service
connection to enqueue an event.

The receiver-side writer carries one extra responsibility: a per-
(session id, event type) **latest-wins coalesce window**. Within the
window, a new emit for the same key overwrites the prior unclaimed
entry in place (payload + timestamp updated, attempt count reset, last
error cleared) instead of inserting. Claimed entries are never replaced.

An accepted event is committed before its receiver subprocess exits. When a
matching entry is already claimed, the new emit creates a separate entry so the
in-flight event and the newer event remain separately represented; both entries
follow the dispatcher's retry/drop contract. The current coalesce
windows are one second for `agent-stop` and `native-metadata-update`, widened to
ten seconds for Codex `agent-stop`. Tool-call start and end events remain
separate entries and are not coalesced. The dispatcher applies its retry/drop
policy, so a failed entry may be deferred or dropped while later entries
proceed. Other event types have no coalesce window in v1 and retain one entry
per emit.

For a receiver contract violation, an `error` event is stored when its
TeleClaude session resolves; its payload carries the message,
`source="hook_receiver"`, code, `severity="error"`, `retryable=false`, and
agent and event-type details. If no session resolves, the receiver logs the
unknown-session error and records no outbox entry.

For the canonical aggregate shape, see `local/projects/teleclaude/spec/domain/integration.md`.

## Canonical fields

### Use cases

#### UC-OB1: Plain enqueue (no coalesce)

#### UC-OB2: Coalesce overwrites prior unclaimed entry

#### UC-OB3: Coalesce skipped when prior entry is claimed

#### UC-OB4: Codex agent_stop uses a wider 10s coalesce window

#### UC-OB5: native-metadata-update coalesces at 1s baseline

#### UC-OB6: Outbox store path resolution

#### UC-OB7: Error payload requires resolvable session id

#### UC-OB8: Every tool call's start and end are delivered

### Cross-context references

- Producer side belongs (in v2) to `agent_runtime` along with the
  receiver.
- Consumer side is `hook-outbox-dispatcher` (this context).
- The outbox pattern itself echoes the v2 transactional outbox aggregate
  in `docs/local/spec/domain/integration.md` (Outbox Entry); v1 uses
  a local store and a per-process writer (not a shared producer API).

## Known caveats

- The outbox is locally persisted; concurrent receivers may experience
  contention during high-frequency tool-use bursts. Coalescing the
  remaining bursty events within their configured windows reduces
  contention.
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
