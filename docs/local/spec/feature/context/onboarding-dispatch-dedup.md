---
visibility: public
description: Onboarding holds no dispatch subject; whether an analysis or assessment session already runs for a root is decided by the caller that starts one.
---

# Onboarding Dispatch Dedup — Spec

## What it is

Project and company onboarding start no worker session, so no onboarding step
resolves whether an analysis or assessment session already holds a root
(`local/projects/teleclaude/spec/feature/agent_runtime/explicit-session-dispatch`). The caller
that starts such a session through the sessions surface decides whether one is
already running, from the session list it can read.

## Canonical fields

### Use cases

#### UC-ODD6: Onboarding resolves no dispatch holder

## Known caveats

- Use-case identifiers 1 through 5 are not in use in this contract and are not
  reused.
- Two explicit starts of the same analysis command for one root start two
  sessions; the sessions surface applies no per-procedure deduplication.

## See Also

- docs/local/spec/feature/agent_runtime/explicit-session-dispatch.md
