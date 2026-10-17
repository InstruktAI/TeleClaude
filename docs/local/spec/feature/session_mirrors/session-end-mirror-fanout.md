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

Inputs that do not resolve to a session-owned canonical transcript are skipped
before mirror generation; subagent transcripts remain excluded.

The dispatcher runs all processors in parallel with per-processor error
isolation so one failing processor cannot block the others.

## Canonical fields

### Use cases

#### UC-SEMF-3: Local agent-stop is dispatched coordinator-only, not to the fanout

#### UC-SEMF-4: An operator can read the complete conversation after session closure

```gherkin
Scenario: Read the final conversation after closure
  Given a human operator closes a session after its final exchange
  When the operator opens the session's historical conversation
  Then the conversation includes that final exchange
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
