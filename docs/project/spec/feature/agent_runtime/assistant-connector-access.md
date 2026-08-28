---
description: 'Every route the platform provides for reaching a mail or calendar connector leads to the mediated boundary that binds and gates the invocation, and none leads to the raw tool.'
delivered_by:
  - personal-mail-tool-launcher
---

# Assistant Connector Access — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

What an agent session may execute when it reaches for a mail or calendar
connector. Every route the platform provides leads to the mediated boundary and
to nothing else: naming the tool reaches it, and the session's own tooling
offers no alternative. What that boundary then does — binding the invocation to
a declared account, directing the person's state, applying the personal-assistant
prohibitions — is the invocation contract's, not this one's.

This is what the platform provides, not what a process can physically do. A
session carries the person's own operating-system authority, and a process with
that authority can execute a connector binary directly whatever the platform
publishes. Making that impossible requires the session to hold less authority
than the person, which is process isolation the platform does not impose.

**Business value:** every guarantee the invocation boundary makes is worth
exactly as much as the routes that lead to it. Publishing no alternative is what
makes reaching around it a deliberate act rather than an ordinary one.

## Canonical fields

### Use cases

#### UC-ACA-6: Every route the platform provides leads to the boundary

```gherkin
Given an agent session
When the session reaches for a mail or calendar connector through any route the platform provides it
Then the invocation reaches the connector through the mediated boundary
And the gates that boundary enforces apply to it
```

## Known caveats

- A session holding the person's own operating-system authority can execute a
  connector binary outside every route named here. That is not closed by
  publishing fewer routes; it is closed by the session holding less authority
  than the person, which is process isolation this contract does not assume.

## See Also

- docs/project/spec/feature/integration/assistant-connector-invocation.md — what the mediated boundary does once an invocation reaches it.
- docs/project/spec/feature/agent_runtime/sealed-commit.md — the sibling contract governing what an agent session may execute against another external tool.
