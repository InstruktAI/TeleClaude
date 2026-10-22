---
description: 'Hook outbox events that mutate session-record state directly — checkpoint timestamps, native session/transcript binding, transcript history chain — without producing in-process event-bus events.'
visibility: 'public'
---

# Session State Mutation via Outbox — Spec

## What it is

A subset of hook outbox event types (checkpoint-seen,
native-metadata-update, native-session-refresh) whose only effect is to
update fields on the session record. The hook outbox dispatcher routes
these to in-process mutation handlers BEFORE the generic event-bus
dispatch path. Unlike normal hook events, they do NOT produce internal
event-bus events; they are pure state-keeping operations that ride the
outbox to gain durability and ordering across integration service
restarts.

The most behaviorally interesting handler is native-metadata-update,
which appends the previously stored native log file to a serialized
transcript history list whenever the transcript path changes. This
produces an in-order history of every transcript file the session ever
used — essential for session resume and Codex-style transcript chaining.

These state mutations emit no event-bus event, and successful processing settles
the outbox entry. `checkpoint-seen` updates only the last-checkpoint timestamp.
`native-metadata-update` changes native session and transcript fields without
changing the active agent; when the transcript path changes, the previous path
is appended once and the related fields are stored together. A
`native-session-refresh` changes the native session ID only when its key is
present, with explicit null clearing the binding; an absent key leaves it
unchanged. An unchanged metadata update or an update for a missing session is a
successful no-op.

Native metadata updates already accepted into the outbox may be applied after
session close, preserving the binding needed for revival; other hook events for
closed sessions remain ignored.

## Canonical fields

### Use cases

#### UC-SSM1: checkpoint-seen updates last-checkpoint timestamp

#### UC-SSM2: native-metadata-update with new transcript path archives the old

#### UC-SSM3: native-metadata-update is a no-op when nothing changed

#### UC-SSM4: native-metadata-update on missing session is a no-op

#### UC-SSM5: native-session-refresh sets native session id directly

#### UC-SSM6: native-session-refresh with null clears the binding

#### UC-SSM7: metadata update preserves committed runtime ownership

#### UC-SSM8: Closed-session-guard bypass

### Cross-context references

- Producer is `agent-cli-hook-reception` (the receiver emits these via
  the checkpoint-seen enqueue and native-metadata persistence).
- Carrier is `hook-event-outbox` and `hook-outbox-dispatcher`.
- Consumer is the `agent_runtime` session record (v2 destination); v1
  stores in the session record via the integration-side mutation
  contract.

## Known caveats

- The transcript history is a serialized list stored in a text field;
  the handler defensively handles null or invalid serialized values by
  treating the chain as empty.
- The handler deduplicates within the chain (appended only if the
  previous path is not already in the list) — but does NOT reorder; the
  list is append-only chronological order of replacements.
- These events deliberately bypass cluster-visibility propagation
  because they are an internal pre-event-bus state-keeping operation.
  Domain consumers who care about checkpoint timing should subscribe to
  the downstream event-bus event the next live update emits, not the
  outbox entry.
- The metadata-update handler does NOT clear stale fields; it only
  applies non-empty values from the payload.
- Idempotency comes from last-wins semantics — multiple identical
  updates converge on the same record state, so the worker's retry loop
  is safe.
