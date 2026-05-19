---
id: 'project/spec/feature/session_mirrors/session-end-mirror-fanout'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Event-driven mirror creation/refresh. AGENT_STOP and SESSION_CLOSED dispatch through a processor registry that calls the mirror generator for the affected session. Processors run concurrently and failures are isolated.'
---

# Session-End Mirror Fanout — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/agent_runtime.md

## What it is

Mirrors get their freshest content at session end. Two events trigger the
fanout: `AGENT_STOP` (the agent CLI announced the turn is over and the
transcript file may have advanced) and `SESSION_CLOSED` (the session record
just became closed). The mirror module exposes two handler entry points —
`handle_agent_stop` and `handle_session_closed` — that wrap each event in a
`MirrorEvent` and dispatch it to every registered processor. A single
default processor, `process_mirror_event`, is registered at daemon boot; it
resolves session context, validates that the transcript belongs to a
canonical per-agent session root, and invokes `generate_mirror`.

The dispatcher runs all processors in parallel via `asyncio.gather(...,
return_exceptions=True)` and logs each processor's exception independently
so one failing processor cannot block the others.

## Canonical fields

### Behavioral contract

#### AGENT_STOP carries transcript_path

```
Given an AGENT_STOP AgentEventContext arrives at the daemon
And its payload exposes a transcript_path attribute
When the daemon invokes handle_agent_stop(context)
Then a MirrorEvent(session_id=context.session_id, transcript_path=payload.transcript_path) is built
And all registered processors are dispatched in parallel
```

#### SESSION_CLOSED omits transcript_path

```
Given a SESSION_CLOSED SessionLifecycleContext arrives at the daemon's observer
When the daemon invokes handle_mirror_session_closed(context)
Then a MirrorEvent(session_id=context.session_id, transcript_path=None) is built
And the default processor must look up transcript_path from the main DB session row
```

#### Default processor session-context resolution

```
Given a MirrorEvent with session_id S and possibly None transcript_path
When process_mirror_event runs
Then get_session_context(session_id=S, transcript_path=event.transcript_path) is called against the main DB
And if no row is returned the processor logs debug and returns without calling the generator
And the transcript_path is taken from the event, falling back to the context's transcript_path
```

#### Guard: canonical transcript paths only

```
Given the resolved transcript_path is not under one of the per-agent session roots (in_session_root returns False)
When process_mirror_event runs
Then the processor logs debug "Mirror processor skipped non-canonical transcript"
And the generator is NOT invoked
```

#### Guard: missing or unknown agent

```
Given context.agent is empty / unset
Then the processor logs debug "Mirror processor skipped: agent missing"

Given context.agent does not parse to an AgentName enum value
Then the processor logs warning "Mirror processor skipped unknown agent <value> for <session_id>"

In both cases the generator is NOT invoked
```

#### Generator invocation enrichment

```
Given the guards pass
When process_mirror_event invokes generate_mirror
Then session_id = extract_session_id(transcript_path, agent_name)  # native session id from the file
And source_identity = build_source_identity(transcript_path, agent_name)
And computer = context.computer or config.computer.name
And project = context.project or ""
And human_email = context.human_email
And visibility = context.visibility or "private"
And last_input_origin = context.last_input_origin
And channel_identifiers = _extract_channel_identifiers(...)  # see mirror-identity-enrichment
```

#### Parallel dispatch and failure isolation

```
Given multiple processors are registered
When _dispatch(event) runs
Then asyncio.gather(*(p(event) for p in processors), return_exceptions=True) is awaited
And each result that is an Exception logs "Mirror processor failed: <exc>" with traceback
And other processors run to completion regardless of one processor's exception
```

#### Processor registry idempotency

```
Given register_processor(p) is called twice with the same processor object
When the second call runs
Then it is a no-op (the processor is not added a second time)
```

### V1 implementation pointers

- `teleclaude/mirrors/event_handlers.py:handle_agent_stop` — AGENT_STOP wrapper that builds the MirrorEvent and dispatches.
- `teleclaude/mirrors/event_handlers.py:handle_session_closed` — SESSION_CLOSED wrapper.
- `teleclaude/mirrors/event_handlers.py:_dispatch` — parallel gather with per-processor error logging.
- `teleclaude/mirrors/processors.py:MirrorEvent` — normalized event payload dataclass.
- `teleclaude/mirrors/processors.py:register_processor` / `get_processors` — registry surface.
- `teleclaude/mirrors/processors.py:process_mirror_event` — default processor.
- `teleclaude/mirrors/processors.py:register_default_processors` — called once at daemon boot.
- `teleclaude/daemon_session.py:_handle_agent_event_direct` — AGENT_STOP fan-out call site (`if context.event_type != AgentHookEvents.AGENT_STOP: return`).
- `teleclaude/daemon_session.py:_handle_session_closed` — SESSION_CLOSED observer that invokes the mirror handler.
- `teleclaude/daemon.py:333` — `register_default_processors()` call at daemon construction.

## Known caveats

- The AGENT_STOP path runs AFTER `agent_coordinator.handle_event(context)`
  returns. A long-running coordinator step delays the mirror refresh.
- The SESSION_CLOSED handler is observer-only; if the close path itself
  failed mid-flight the mirror handler still runs against whatever state
  the DB has.
- AGENT_STOP payloads from older hook formats may not expose
  `transcript_path`. `getattr(payload, "transcript_path", None)` swallows
  the absence and the processor falls back to the DB lookup.
- Subagent contexts are not filtered here. Whether a context corresponds to
  a subagent (and whether the resulting mirror should be excluded from
  search) is determined by the upstream pipeline that decides what arrives
  at this fanout, not by the mirror processor itself.
- The default processor calls `generate_mirror` with `db=None`, which
  resolves to the canonical `MIRRORS_DB_PATH`. The processor cannot be
  pointed at an alternate database without re-registering.
