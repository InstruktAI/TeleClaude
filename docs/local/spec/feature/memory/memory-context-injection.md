---
description: 'Render the most recent observations for a project as a Markdown block injected into agent context at session start.'
visibility: 'public'
---

# Memory Context Injection — Spec

## What it is

The memory context generator turns a project's recent observations into a Markdown block that is prepended to each new agent session's startup context. The session-start consumer in `agent_runtime` requests the block from the `memory` service for the resolved project (optionally scoped by identity) and includes the rendered string in the session's initial context. The pipeline fetches the most-recent observations for the project, orders them newest-first, and renders them as a `# Memory Context` Markdown section with a summary index table and per-observation detail blocks.

For a help-desk conversation, scope is the resolved visitor and desk. For a
human personal-assistant conversation, it is the registered person's personal
scope, including separately started PA conversations. Identity resolution and
`local/projects/teleclaude/spec/feature/memory/memory-curation` own these values.
Only current attributed memories of that identity and scope are rendered.
Retired memories, prospects and unresolved legacy observations stay outside
automatic personal and visitor context. Other session kinds retain their
existing context behavior.

## Canonical fields

### Use cases

#### UC-MCI1: A person starts work with recent memories in context

```gherkin
Scenario: Begin work with relevant recent memories
  Given a person starts a new agent session for a project
  When the session begins
  Then its context includes recent memory observations for that project and the identity it acts for, when available
  And an empty or failed memory lookup does not prevent the session from starting
```

### Cross-context references

- `agent_runtime` — the session-start consumer requests the memory context block at session start; the rendered Markdown becomes part of the agent's startup context. See `docs/local/spec/domain/agent_runtime.md`.
- `identity` — the session-start consumer resolves an identity scope for the session before requesting the memory context; see `docs/local/spec/domain/identity.md` and `identity-key-ownership`.

## Known caveats

- **Errors are swallowed.** The injection path returns the empty string on any error during read or render — a failed context generation never blocks session start.
- **No event emitted; no caching.** Each request re-queries the underlying store. There is no cache invalidation or change-notify path.
- **The 50-observation cap is fixed.** Callers cannot request more or fewer recent observations through this surface.
- **Single-project per request.** Although the consumer-facing entry accepts a project specifier, only one project's observations are rendered per call.
