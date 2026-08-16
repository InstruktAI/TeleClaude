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

## Canonical fields

### Use cases

#### UC-SSM1: checkpoint-seen updates last-checkpoint timestamp

```gherkin
Given the receiver emitted a checkpoint-seen entry with checkpoint-at = "2026-05-19T10:00:00+00:00"
When the integration service's worker dispatches the entry
Then the session-state-mutation fork accepts the entry
And the checkpoint-seen handler updates the session record's last-checkpoint timestamp
And the entry is removed from the outbox
And NO event-bus emit happens for this transition
```

#### UC-SSM2: native-metadata-update with new transcript path archives the old

```gherkin
Given the session record has native log file = "/var/log/claude/abc.jsonl"
And a native-metadata-update arrives with native log file = "/var/log/claude/def.jsonl"
When the metadata-update handler runs
Then it loads the session record
And detects the new path differs from the stored path
And the transcript history helper reads the existing serialized transcript history
And appends "/var/log/claude/abc.jsonl" to the history (if not already present)
And serializes the chain back into the transcript history
And updates the native log file to "/var/log/claude/def.jsonl"
And persists both fields atomically via a single session update
```

#### UC-SSM3: native-metadata-update is a no-op when nothing changed

```gherkin
Given a native-metadata-update arrives with values identical to current session record state
When the metadata-update handler runs
Then no field in the update set is populated
And the session update is NOT invoked (early exit when the update set is empty)
And the entry is still removed from the outbox as successful processing
```

#### UC-SSM4: native-metadata-update on missing session is a no-op

```gherkin
Given the metadata-update handler is invoked for a session id that does not exist
When the sessions store yields nothing
Then the handler returns silently
And no error is raised
And the entry is removed as processed
```

#### UC-SSM5: native-session-refresh sets native session id directly

```gherkin
Given the receiver detected a native-session-id mismatch and emitted a native-session-refresh
When the refresh handler runs
Then it confirms the payload contains the native-session-id key
And invokes a session update for the native session id
And the entry is removed from the outbox
```

#### UC-SSM6: native-session-refresh with null clears the binding

```gherkin
Given a native-session-refresh entry with payload {"native_session_id": null}
When the refresh handler runs
Then it updates the session record's native session id to null
And the session record's native binding is cleared
```

#### UC-SSM7: agent rename on metadata update

```gherkin
Given a native-metadata-update payload includes "agent": "codex"
And the session record's active agent is "claude"
When the metadata-update handler runs
Then the active-agent field is set to "codex"
And the session record's active agent flips to "codex"
And the transcript chain rule fires separately if the transcript path also changed
```

#### UC-SSM8: Closed-session-guard bypass

```gherkin
Given the session's lifecycle status is "closed"
And a native-metadata-update entry arrives
When the dispatcher runs
Then the session-state-mutation fork runs FIRST (before the closed-session guard)
And the entry is processed even though the session is closed
And the "ignoring hook event for closed session" guard only fires for non-mutation entries
```

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
