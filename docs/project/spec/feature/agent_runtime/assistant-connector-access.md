---
description: 'An agent session cannot reach a mail or calendar connector except through the mediated boundary that binds and gates the invocation.'
delivered_by:
  - personal-mail-tool-launcher
---

# Assistant Connector Access — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

What an agent session may execute when it reaches for a mail or calendar
connector. It reaches the mediated boundary and nothing else: not by naming the
tool, and not by any other route the session has. What that boundary then does —
binding the invocation to a declared account, directing the person's state,
applying the personal-assistant prohibitions — is the invocation contract's, not
this one's.

Precedence on the tool path is not exclusivity. A wrapper that merely wins name
resolution leaves the tool reachable beside it, and a gate that can be stepped
around by naming a path is not a gate.

**Business value:** every guarantee the invocation boundary makes is worth
exactly as much as the session's inability to go around it. This is the contract
that makes the others load-bearing.

## Canonical fields

### Use cases

#### UC-ACA-6: No route from an agent session reaches a connector outside the boundary

```gherkin
Given an agent session
When the session attempts to reach a mail or calendar connector by any route available to it
Then the invocation reaches the connector only through the mediated boundary
And the gates that boundary enforces apply to it
```

## See Also

- docs/project/spec/feature/integration/assistant-connector-invocation.md — what the mediated boundary does once an invocation reaches it.
- docs/project/spec/feature/agent_runtime/sealed-commit.md — the sibling contract governing what an agent session may execute against another external tool.
