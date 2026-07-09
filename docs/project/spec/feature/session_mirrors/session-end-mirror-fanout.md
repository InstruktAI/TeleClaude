---
description: 'Event-driven mirror creation/refresh. The agent-stop and session-closed lifecycle signals dispatch through a processor registry that calls the mirror extractor for the affected session. Processors run concurrently and failures are isolated.'
visibility: 'public'
---

# Session-End Mirror Fanout — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/agent_runtime.md

## What it is

Mirrors get their freshest content at session end. Two lifecycle signals
from the agent_runtime bounded context trigger the fanout: the agent-stop
signal (the agent CLI announced the turn is over and the transcript file
may have advanced) and the session-closed signal (the session record just
became closed). The session_mirrors service exposes two handler entry
points — one per signal — that wrap each event in a normalized event
payload and dispatch it to every registered processor. A single default
processor is registered at service boot; it resolves session context,
validates that the transcript belongs to a canonical per-agent session
root, and invokes mirror generation.

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

<!-- planned-change:revert-per-turn-local-mirror-wiring -->

#### UC-SEMF-1: Local agent-stop reaches the fanout

```
Given an agent-stop hook event for a locally-running session is delivered through the daemon's outbox dispatch
When the daemon completes the coordinator handling for that event
Then the agent-stop mirror handler is dispatched for that session
And the mirror event carries the session_id and the payload's transcript_path
```

<!-- change:revert-per-turn-local-mirror-wiring -->
<!-- /planned-change:revert-per-turn-local-mirror-wiring -->

<!-- planned:revert-per-turn-local-mirror-wiring -->

#### UC-SEMF-3: Local agent-stop is dispatched coordinator-only, not to the fanout

```
Given an agent-stop hook event for a locally-running (non-cluster) session is delivered through the daemon's outbox dispatch
When the daemon dispatches that event
Then the coordinator handles the event
And no mirror processor is dispatched for that session
```

<!-- /planned:revert-per-turn-local-mirror-wiring -->

#### Session-closed signal omits transcript_path

```
Given a session-closed signal arrives at the session_mirrors service
When the session-closed handler runs
Then a mirror event with session_id and no transcript_path is built
And the default processor must look up the transcript_path from the upstream session record
```

#### Default processor session-context resolution

```
Given a mirror event with session_id S and possibly no transcript_path
When the default processor runs
Then session context is resolved by session_id (and by transcript_path when present)
And if no session record is found the processor logs at debug level and returns without invoking mirror generation
And the effective transcript_path is taken from the event, falling back to the context's transcript_path
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
Then session_id is the native session id extracted from the transcript path for the resolved agent
And source_identity is the canonical identity derived from the transcript path and agent
And computer = context.computer OR the local computer name
And project = context.project OR ""
And human_email = context.human_email
And visibility = context.visibility OR "private"
And last_input_origin = context.last_input_origin
And channel_identifiers are derived per `mirror-identity-enrichment`
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

## Known caveats

- The agent-stop path runs AFTER the agent_runtime coordinator's per-event
  handling returns. A long-running coordinator step delays the mirror
  refresh.
- The session-closed handler is observer-only; if the close flow itself
  failed mid-flight the mirror handler still runs against whatever state
  the upstream store has.
- Older agent-stop payloads may not carry a `transcript_path`. The
  default processor tolerates the absence and falls back to the upstream
  session-record lookup.
- Subagent contexts are not filtered here. Whether a context corresponds
  to a subagent (and whether the resulting mirror should be excluded from
  search) is determined by the upstream pipeline that decides what
  arrives at this fanout, not by the mirror processor itself.
- The default processor invokes mirror generation against the canonical
  mirror store and cannot be pointed at an alternate store without
  re-registering.
