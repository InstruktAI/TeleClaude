---
description: Event-driven mirror refresh through agent lifecycle signals and reconciliation.
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

Closing a session requests readiness of its session-owned mirror for the final
conversation boundary. The existing refresh capability confirms coverage,
refreshing only when needed, and reports readiness for an unchanged mirror too.
Reconciliation remains the recovery path for a failed refresh. The existing
agent-stop path and periodic cadence remain in place.

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
And the owning session's complete transcript lineage supplies the refresh input
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
Then the owning TeleClaude session identifies the conversation mirror
And native identities and source paths remain provenance within its lineage
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

#### UC-SEMF-4:

```
Given an operator's session has closed
When closure post-processing requests its conversation mirror
Then readiness is reported only after coverage includes the closed conversation
And an already-current mirror satisfies readiness without a text rewrite
And a failed refresh remains visible and can recover through reconciliation
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
- Closure and mirror readiness are distinct outcomes. Consumers await the
  covered revision rather than assuming elapsed time proves freshness.
