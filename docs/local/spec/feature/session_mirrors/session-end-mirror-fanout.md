---
description: 'Event-driven mirror refresh. The agent-stop lifecycle signal dispatches through a processor registry that calls the mirror extractor for the affected session. Closing a session triggers no mirror write; the reconciliation loop records its final state. Processors run concurrently and failures are isolated.'
visibility: 'public'
---

# Session-End Mirror Fanout — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md
- @docs/local/spec/domain/agent_runtime.md

## What it is

One lifecycle signal from the agent_runtime bounded context triggers the
fanout: the agent-stop signal (the agent CLI announced the turn is over and the
transcript file may have advanced). The locally dispatched agent stop does not
reach the fanout (UC-SEMF-3). The session_mirrors service exposes one handler
entry point that wraps the event in a normalized event payload and dispatches it
to every registered processor. A single default processor is registered at
service boot; it resolves session context, validates that the transcript belongs
to a canonical per-agent session root, and invokes mirror generation.

Closing a session adds no conversation, so the session-closed signal triggers no
mirror write. The reconciliation loop mirrors every transcript that changed,
including a closed session's final turn, and records the session's close
(`mirror-reconciliation-loop`, `mirror-identity-enrichment`).

The dispatcher runs all processors in parallel with per-processor error
isolation so one failing processor cannot block the others.

## Canonical fields

### Use cases

#### Agent-stop signal carries transcript_path

```
Given an agent-stop signal arrives at the session_mirrors service
And the signal payload exposes a transcript_path
When the agent-stop handler runs
Then a mirror event with session_id and transcript_path is built
And all registered processors are dispatched in parallel
```

#### UC-SEMF-3: Local agent-stop is dispatched coordinator-only, not to the fanout

```
Given an agent-stop hook event for a locally-running (non-cluster) session is delivered through the daemon's outbox dispatch
When the daemon dispatches that event
Then the coordinator handles the event
And no mirror processor is dispatched for that session
```

#### Default processor session-context resolution

```
Given a mirror event with session_id S and possibly no transcript_path
When the default processor runs
Then session context is resolved by session_id (and by transcript_path when present)
And if no session record is found the processor logs at debug level and returns without invoking mirror generation
And the effective transcript_path is taken from the event, falling back to the context's transcript_path
```

#### Guard: subagent transcripts

```
Given the resolved transcript_path is one the per-runtime subagent rule recognizes
When the default processor runs
Then the processor records the skip as a production-level decision record naming the transcript path
And mirror generation is NOT invoked
```

#### Guard: canonical transcript paths only

```
Given the resolved transcript_path is not under one of the per-agent session roots
When the default processor runs
Then the processor logs "Mirror processor skipped non-canonical transcript" at debug level
And mirror generation is NOT invoked
```

#### Guard: missing or unknown agent

```
Given context.agent is empty / unset
Then the processor logs "Mirror processor skipped: agent missing" at debug level

Given context.agent does not resolve to a known agent name
Then the processor logs "Mirror processor skipped unknown agent <value> for <session_id>" at warning level

In both cases mirror generation is NOT invoked
```

#### Mirror-generation invocation enrichment

```
Given the guards pass
When the default processor invokes mirror generation
Then native_session_id is the native session id extracted from the transcript path for the resolved agent
And source_identity is the canonical identity derived from the transcript path and agent
And the resolved session context is passed whole, so the mirror records the same identity facts and session attribution the reconciliation loop records, per `mirror-identity-enrichment`
```

#### Parallel dispatch and failure isolation

```
Given multiple processors are registered
When the dispatcher runs an event
Then all processors are invoked concurrently
And each processor that raises is logged "Mirror processor failed: <reason>" with traceback
And other processors run to completion regardless of one processor's exception
```

#### Processor registry idempotency

```
Given the same processor is registered twice
When the second registration runs
Then it is a no-op (the processor is not added a second time)
```

#### UC-SEMF-4: Closing a session writes no mirror by itself

```
Given a session closes
When the session-closed signal is published
Then no mirror is written in response to that signal
And the reconciliation loop's next pass records the session's final conversation and its close, whether or not the transcript changed after its last write
```

## Known caveats

- The agent-stop path runs AFTER the agent_runtime coordinator's per-event
  handling returns. A long-running coordinator step delays the mirror
  refresh.
- Older agent-stop payloads may not carry a `transcript_path`. The
  default processor tolerates the absence and falls back to the upstream
  session-record lookup.
- The default processor applies the same per-runtime subagent rule that
  transcript discovery applies, so a subagent transcript that reaches this
  fanout is skipped before mirror generation rather than mirrored.
- The default processor invokes mirror generation against the canonical
  mirror store and cannot be pointed at an alternate store without
  re-registering.
- A closed session's final turn and close time reach its mirror within one
  reconciliation interval, not at the moment of close.
